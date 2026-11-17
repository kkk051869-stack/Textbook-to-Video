import importlib.util
import json
from pathlib import Path

import pytest

from textbook2video.research import visual_decision

ROOT = Path(__file__).parents[1]


def _load_runner():
    path = ROOT / "scripts/run_rq1_new_corpus.py"
    spec = importlib.util.spec_from_file_location("rq1_new_corpus_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_output_manifest_detects_mutation_and_new_files(tmp_path):
    runner = _load_runner()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    protocol = {"dataset_id": "d", "run_id": "r", "budget": {"max_transport_calls": 2}}
    _write(run_dir / "protocol.json", protocol)
    _write(run_dir / "calls.json", [])
    _write(run_dir / "report.json", {"status": "saved"})
    _write(run_dir / "predictions.json", {"action": "none"})
    _write(run_dir / "output_manifest.json", runner._build_output_manifest(run_dir, protocol))

    assert runner._verify_output_manifest(run_dir, protocol)["status"] == "PASS"
    (run_dir / "predictions.json").write_text('{"action":"retrieve"}', encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        runner._verify_output_manifest(run_dir, protocol)
    (run_dir / "predictions.json").write_text('{"action":"none"}', encoding="utf-8")
    (run_dir / "untracked.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="files differ"):
        runner._verify_output_manifest(run_dir, protocol)


def test_analyze_only_recomputes_to_separate_output_without_transport(tmp_path, monkeypatch):
    runner = _load_runner()
    run_dir = tmp_path / "package" / "run-01"
    run_dir.mkdir(parents=True)
    protocol_path = run_dir / "protocol.json"
    _write(protocol_path, {"dataset_id": "d", "run_id": "r"})
    _write(run_dir / "calls.json", [])
    _write(run_dir / "report.json", {"protocol_sha256": runner._sha(protocol_path), "value": "old"})
    recompute_calls = []
    monkeypatch.setattr(runner, "_verify_protocol_and_claims", lambda *_: {})
    monkeypatch.setattr(runner, "_verify_output_manifest", lambda *_: {"status": "PASS"})

    def recompute(package_root, actual_run_dir, protocol, *, persist=True):
        recompute_calls.append({
            "package_root": package_root,
            "run_dir": actual_run_dir,
            "protocol": protocol,
            "persist": persist,
        })
        return {"value": "recomputed from prediction and judge files"}

    monkeypatch.setattr(runner, "_refresh_report", recompute)
    output = tmp_path / "analysis.json"
    result = runner.analyze_only(run_dir, output)
    assert result["status"] == "ANALYZED_FROM_SAVED_RUN_NO_MODEL_CALLS"
    assert result["new_model_calls"] == 0
    assert result["report"]["value"] == "recomputed from prediction and judge files"
    assert recompute_calls[0]["persist"] is False
    assert json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["value"] == "old"


def test_rq1_conditions_expose_only_their_frozen_inputs(tmp_path, monkeypatch):
    image = tmp_path / "source.png"
    image.write_bytes(b"fixture pixels")
    graph = tmp_path / "graph.json"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    catalog = tmp_path / "catalog.json"
    _write(graph, {"narration_propositions": [{
        "id": "p1", "segment_id": "1", "text": "A source-backed claim.", "source_refs": ["s1"]
    }]})
    _write(evidence, {
        "source_units": [{"id": "s1", "text": "A source-backed claim.", "page_number": 1}],
        "source_images": [{
            "id": "fig-1", "filename": image.name, "caption": "Original chart",
            "description": "A cited source chart", "source_locator": "p. 1",
            "page_number": 1, "availability": "AVAILABLE_LOCAL",
            "teaching_asset_status": "ELIGIBLE_COMPLETE_FIGURE_REQUIRES_VLM",
            "local_path": str(image), "sha256": "fixture-hash",
        }],
    })
    _write(storyboard, {"segments": [{"id": "1", "elements": [{
        "type": "image", "source_image_id": "fig-1"
    }]}]})
    _write(catalog, {"summary": "One fixed candidate."})

    captured = []

    def response(prompt, *args, **kwargs):
        payload = json.loads(prompt)
        captured.append((payload, bool(args)))
        return json.dumps({"decisions": [{
            "narration_proposition_id": "p1", "action": "none",
            "rationale": "The claim is adequately explained in the text.",
        }]})

    monkeypatch.setattr(visual_decision, "chat_with_system", response)
    monkeypatch.setattr(visual_decision, "chat_with_images", response)
    outputs = {}
    for condition in (
        "direct_llm", "proposed", "no_source", "without_source_sufficiency",
        "without_retrieval_suitability", "without_uncertainty_handling",
    ):
        target = tmp_path / f"{condition}.json"
        visual_decision.decide_visual_support(
            proposition_graph_path=graph,
            source_evidence_path=evidence,
            storyboard_path=storyboard,
            retrieval_catalog_path=catalog,
            output_path=target,
            research_condition=condition,
        )
        outputs[condition] = json.loads(target.read_text(encoding="utf-8"))["decisions"][0]

    prompts = {payload["research_condition"]: payload for payload, _ in captured}
    staged_rule = "First decide whether an additional visual has instructional value."
    assert staged_rule not in prompts["direct_llm"]["rules"]
    assert staged_rule in prompts["proposed"]["rules"]
    assert prompts["direct_llm"]["source_context"] == prompts["proposed"]["source_context"]
    assert captured[0][1] is True and captured[2][1] is False

    no_source = prompts["no_source"]
    assert "source_context" not in no_source
    assert no_source["source_visual_inventory"] == []
    assert no_source["source_images"] == []
    assert "source_refs" not in no_source["narration_propositions"][0]
    assert outputs["no_source"]["source_sufficiency"] == "UNKNOWN"
    without_source_schema = prompts["without_source_sufficiency"]["output_schema"][
        "decisions"
    ][0]
    assert "source_sufficiency" not in without_source_schema
    assert outputs["without_source_sufficiency"]["source_sufficiency"] == "UNKNOWN"
    without_retrieval_schema = prompts["without_retrieval_suitability"]["output_schema"][
        "decisions"
    ][0]
    assert "retrieval_suitability" not in without_retrieval_schema
    assert outputs["without_retrieval_suitability"]["retrieval_suitability"] == "UNKNOWN"
    assert outputs["without_uncertainty_handling"]["decision_state"] == "DECIDED"
    assert outputs["without_uncertainty_handling"]["abstain"] is False


def test_source_visual_context_uses_explicit_cross_page_links_not_page_co_location(tmp_path, monkeypatch):
    graph = tmp_path / "graph.json"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    catalog = tmp_path / "catalog.json"
    _write(graph, {"narration_propositions": [{
        "id": "p1", "segment_id": "1", "text": "A claim on page two.", "source_refs": ["s1"]
    }]})
    _write(evidence, {
        "source_units": [{"id": "s1", "text": "A claim on page two.", "page_number": 2}],
        "source_images": [
            {
                "id": "linked-figure", "caption": "A cross-page process figure",
                "source_locator": "Section 2, Figure 1", "page_number": 1,
                "availability": "AVAILABLE_LOCAL", "teaching_asset_status": "ELIGIBLE_COMPLETE_FIGURE",
            },
            {
                "id": "same-page-unlinked", "caption": "Unrelated photo on the claim page",
                "source_locator": "Page 2, Figure 2", "page_number": 2,
                "availability": "AVAILABLE_LOCAL", "teaching_asset_status": "ELIGIBLE_COMPLETE_FIGURE",
            },
        ],
    })
    _write(storyboard, {"segments": [{"id": "1", "elements": [{
        "type": "image", "source_image_id": "linked-figure"
    }]}]})
    _write(catalog, {"summary": "fixed empty catalog", "assets": []})
    captured = []

    def response(prompt, *args, **kwargs):
        captured.append(json.loads(prompt))
        return json.dumps({"decisions": [{
            "narration_proposition_id": "p1", "action": "none", "rationale": "No added visual."
        }]})

    monkeypatch.setattr(visual_decision, "chat_with_system", response)
    monkeypatch.setattr(visual_decision, "chat_with_images", response)
    visual_decision.decide_visual_support(
        proposition_graph_path=graph,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        retrieval_catalog_path=catalog,
        output_path=tmp_path / "out.json",
        research_condition="direct_llm",
    )

    payload = captured[0]
    inventory = payload["source_visual_inventory"]
    assert [item["id"] for item in inventory] == ["linked-figure"]
    assert inventory[0]["page_number"] == 1
    assert any("Page co-location alone" in rule for rule in payload["rules"])
