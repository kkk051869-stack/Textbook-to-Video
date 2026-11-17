"""Regression checks for saved-prediction experiments; no model transport."""

import copy
import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
media = importlib.import_module("run_doc2present_local_media")
rq1 = importlib.import_module("run_rq1_doc2present_v2")
rq2 = importlib.import_module("run_rq2_binding_dev")


def fixture():
    candidates = [
        {"id": ident, "text": ident, "sha256": "abc", "source_refs": ["source"]}
        for ident in ("a", "b")
    ]
    tasks = [
        {
            "id": f"p{i}",
            "document_id": "doc",
            "proposition": {"text": text},
            "candidates": candidates,
        }
        for i, text in enumerate(("First.", "Second."))
    ]
    results = {
        f"p{i}": {"method": {"status": "BOUND", "selected_candidate_id": ident}}
        for i, ident in enumerate(("a", "b"))
    }
    audio = {
        "segment_id": "doc",
        "duration_sec": 8,
        "cues": [
            {"text": "First.", "start_sec": 0, "end_sec": 3},
            {"text": "Second.", "start_sec": 3, "end_sec": 8},
        ],
    }
    return tasks, results, audio


def test_all_conditions_share_actual_predictions_content_and_measured_audio():
    tasks, results, audio = fixture()
    before = copy.deepcopy((tasks, results, audio))
    boards, dynamic, props, predictions = media.condition_inputs(tasks, results, audio, "method")
    assert (tasks, results, audio) == before
    assert {b["segments"][0]["narration"] for b in boards.values()} == {"First. Second."}
    assert all(
        b["segments"][0]["elements"] == boards["legacy"]["segments"][0]["elements"]
        for b in boards.values()
    )
    assert [p["selected_candidate_id"] for p in predictions] == ["a", "b"]
    shows = {
        e["target_element_id"]: e["at_sec"] for e in dynamic["events"] if e["action"] == "show"
    }
    assert shows == {"a": 0, "b": 3}
    assert props[1]["start_sec"] == 3
    assert all(b["segments"][0]["audio_duration_sec"] == 8 for b in boards.values())


def test_wrong_but_existing_target_preserved_and_abstention_never_replaced():
    tasks, results, audio = fixture()
    results["p0"]["method"]["selected_candidate_id"] = "b"
    results["p1"]["method"] = {
        "status": "ABSTAINED_NO_SUPPORTED_TARGET",
        "selected_candidate_id": None,
    }
    boards, dynamic, _, predictions = media.condition_inputs(tasks, results, audio, "method")
    assert predictions[0]["selected_candidate_id"] == "b"
    assert dynamic["unbound_propositions"] == ["p1"]
    assert [e["id"] for e in boards["legacy"]["segments"][0]["elements"]] == [
        "heading",
        "narration",
        "b",
    ]


def test_missing_unknown_and_mismatched_audio_fail_before_render():
    for kind in ("missing", "unknown", "audio"):
        tasks, results, audio = fixture()
        if kind == "missing":
            del results["p1"]
        elif kind == "unknown":
            results["p0"]["method"]["selected_candidate_id"] = "invented"
        else:
            audio["cues"][0]["text"] = "Other."
        with pytest.raises(ValueError):
            media.condition_inputs(tasks, results, audio, "method")


def test_one_invalid_method_does_not_remove_other_valid_proposals():
    results = {
        "broken": {"status": "INVALID_RESPONSE", "selected_candidate_id": None},
        "bound": {"status": "BOUND", "selected_candidate_id": "a"},
        "abstain": {"status": "ABSTAINED_UNCERTAIN", "selected_candidate_id": None},
    }
    eligible = rq2.valid_results(results)
    options, mapping = rq2.groups_for(eligible)
    assert set(mapping) == {"bound", "abstain"}
    assert len(options) == 2


def test_local_use_is_exactly_document_scoped_and_default_remains_strict():
    assert rq1._require_explicit_license({}) is True
    config = {
        "scope": "DEVELOPMENT_METHOD_COMPARISON_NOT_LOCKED_TEST_NOT_FORMAL_EXPERIMENT",
        "comparison": {"source_files": [{"document_id": "doc", "sha256": "abc"}]},
        "selection": {"locked_test": False},
        "acquisition": {"require_explicit_license": False},
        "local_research_use": {
            "purpose": "LOCAL_RESEARCH_PAPER_TO_VIDEO",
            "source_sha256": {"doc": "abc"},
            "authorization_record": "user",
        },
    }
    assert rq1._require_explicit_license(config) is False
    config["local_research_use"]["source_sha256"]["doc"] = "different"
    with pytest.raises(ValueError):
        rq1._require_explicit_license(config)


def test_missing_actual_comparison_cannot_enter_public_media_adapter(tmp_path):
    with pytest.raises(FileNotFoundError):
        media.require_completed_comparison(tmp_path, "source_conditioned_context")


def test_audio_hash_and_sentence_identity_must_both_match(tmp_path):
    tasks, _, audio = fixture()
    media.write(tmp_path / "sentence_cues.json", {"segments": [audio]})
    (tmp_path / "s1.wav").write_bytes(b"ENGINEERING_AUDIO_FIXTURE")
    media.write(
        tmp_path / "manifest.json",
        {
            "files": {
                "sentence_cues.json": media.sha(tmp_path / "sentence_cues.json"),
                "s1.wav": media.sha(tmp_path / "s1.wav"),
            }
        },
    )
    assert media.verify_audio(tmp_path, tasks, "doc")["duration_sec"] == 8
    wrong = copy.deepcopy(tasks)
    wrong[0]["proposition"]["text"] = "Different sentence."
    with pytest.raises(ValueError, match="narration"):
        media.verify_audio(tmp_path, wrong, "doc")
    (tmp_path / "s1.wav").write_bytes(b"DRIFT")
    with pytest.raises(ValueError, match="hash drift"):
        media.verify_audio(tmp_path, tasks, "doc")
