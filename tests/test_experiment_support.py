"""Common experiment tools require no P0 mode, models or video generation."""

import copy
import json

import pytest

from textbook2video.research.event_timeline import set_runtime_timeline_event
from textbook2video.research.experiment_support import (
    collect_event_evidence,
    freeze_experiment_inputs,
    index_event_records,
    sha256_file,
    validate_binding_references,
    verify_experiment_inputs,
)


@pytest.fixture
def pinned(tmp_path):
    inputs = {}
    for name in ["source", "propositions", "candidates", "method_config", "source_version"]:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"role": name}), encoding="utf-8")
        inputs[name] = path
    methods = {"rq1": {"research_condition": None},
               "rq2": {"method": "source-context-teaching-focus-v1.3"},
               "review": {"status": "USED_WITH_WARNING"}}
    manifest = freeze_experiment_inputs(
        tmp_path / "inputs.json", inputs=inputs, methods=methods,
        version={"commit": "test-commit", "dirty_source": "explicitly-pinned"},
    )
    return manifest, inputs, methods


def test_freeze_pins_inputs_and_keeps_method_and_review_identity(pinned):
    path, inputs, methods = pinned
    document = verify_experiment_inputs(path, expected_sha256=sha256_file(path))
    assert set(document["inputs"]) == set(inputs)
    assert document["methods"] == methods
    with pytest.raises(FileExistsError):
        freeze_experiment_inputs(path, inputs=inputs, methods={}, version={})


@pytest.mark.parametrize("role", ["source", "propositions", "candidates",
                                  "method_config", "source_version"])
def test_input_drift_is_rejected(pinned, role):
    manifest, inputs, _methods = pinned
    inputs[role].write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen input changed or missing"):
        verify_experiment_inputs(manifest)


def test_manifest_metadata_tampering_requires_the_pinned_manifest_hash(pinned):
    manifest, _inputs, _methods = pinned
    expected = sha256_file(manifest)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["methods"]["rq1"]["research_condition"] = "proposed"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash changed"):
        verify_experiment_inputs(manifest, expected_sha256=expected)


def test_missing_input_is_not_silently_frozen(tmp_path):
    destination = tmp_path / "manifest.json"
    with pytest.raises(FileNotFoundError):
        freeze_experiment_inputs(destination, inputs={"source": tmp_path / "absent"},
                                 methods={}, version={})
    assert not destination.exists()


def test_pinned_paths_do_not_depend_on_later_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("fixed source", encoding="utf-8")
    manifest = freeze_experiment_inputs(tmp_path / "inputs.json", inputs={"source": "source.txt"},
                                       methods={}, version={})
    monkeypatch.chdir(tmp_path.parent)
    assert verify_experiment_inputs(manifest)["inputs"]["source"]["path"] == str(source)


@pytest.mark.parametrize("fault", [None, "source", "proposition", "target"])
def test_binding_reference_checks_preserve_status_and_reject_dangling_ids(fault):
    arguments = {"source_units": [{"id": "u1"}],
                 "propositions": [{"id": "p1", "source_refs": ["u1"]}],
                 "candidates": [{"id": "v1"}, {"id": "v2"}],
                 "results": [
                     {"method": "direct_llm_vlm", "proposition_id": "p1",
                      "selected_candidate_ids": ["v1", "v2"], "status": "BOUND"},
                     {"method": "source_conditioned", "proposition_id": "p1",
                      "selected_candidate_id": None, "status": "SEMANTIC_CHECK_FAILED"},
                 ]}
    if fault == "source":
        arguments["propositions"][0]["source_refs"] = ["unknown"]
    elif fault == "proposition":
        arguments["results"][0]["proposition_id"] = "unknown"
    elif fault == "target":
        arguments["results"][0]["selected_candidate_ids"] = ["unknown"]
    before = copy.deepcopy(arguments)
    if fault:
        with pytest.raises(ValueError, match="unknown"):
            validate_binding_references(**arguments)
    else:
        validate_binding_references(**arguments)
    assert arguments == before


def test_evidence_keeps_execution_and_video_disagreement_and_unmatched_records():
    supplied = {
        "method_decisions": [{"narration_proposition_id": "p1", "research_condition": None}],
        "bindings": [{"proposition_id": "p1", "status": "BOUND_MULTIPLE"}],
        "planned": [{"id": "event-1", "proposition_id": "p1"}],
        "compiled": [{"event_id": "event-1"}],
        "runtime": [{"event_id": "event-1", "status": "executed"},
                    {"event_id": "extra-legacy", "status": "executed"},
                    {"note": "unkeyed failure"}, {"note": "second unkeyed failure"}],
        "rendered": [{"event_id": "event-1", "status": "NOT_OBSERVED_AT_MIDPOINT"}],
    }
    before = copy.deepcopy(supplied)
    evidence = collect_event_evidence(**supplied)
    first, extra = evidence["events"]
    assert first["runtime"]["status"] == "executed"
    assert first["rendered"]["status"] == "NOT_OBSERVED_AT_MIDPOINT"
    assert first["method_decisions"] == supplied["method_decisions"]
    assert first["bindings"] == supplied["bindings"]
    assert extra["event_id"] == "extra-legacy" and extra["planned"] is None
    assert len(evidence["unkeyed_records"]["runtime"]) == 2
    assert supplied == before


def test_linker_rejects_duplicate_ids_but_legacy_index_keeps_last_record():
    runtime = [{"event_id": "e1", "status": "failed"},
               {"event_id": "e1", "status": "executed"}]
    assert index_event_records(runtime)["e1"] is runtime[-1]
    with pytest.raises(ValueError, match="duplicate event ID"):
        collect_event_evidence(method_decisions=[], bindings=[], planned=[], compiled=[],
                               runtime=runtime, rendered=[])


def test_common_timeline_writer_preserves_wire_format_and_unrelated_targets():
    segment = {"elements": [{"id": "v1", "source_image_id": "figure-1"}],
               "timeline": [{"target": "figure-1,v2", "action": "show", "at_sec": 0}]}
    metadata = {"event_id": "focus-1", "proposition_id": "p1"}
    kwargs = dict(target="v1", action="focus", effect="focus", trigger=2,
                  hold_sec=1, research_metadata=metadata, preserve_legacy=True)
    set_runtime_timeline_event(segment, **kwargs)
    once = copy.deepcopy(segment)
    set_runtime_timeline_event(segment, **kwargs)
    assert segment == once
    assert segment["timeline"][0]["target"] == "figure-1,v2"
    assert segment["timeline"][1]["research_p0"] == metadata
