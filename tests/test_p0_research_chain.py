import json
from pathlib import Path

from textbook2video.research.p0_integration import prepare_p0_candidate
from textbook2video.research.p0_planner import build_local_p0_plan
from textbook2video.research.signaling_diagnostics import diagnose_signaling
from textbook2video.research.source_evidence import build_source_evidence
from textbook2video.research.visual_acquisition import (
    build_reviewed_acquisition_briefs,
    execute_visual_acquisition,
)
from textbook2video.research.visual_briefs import build_visual_briefs
from textbook2video.research.visual_decision import decide_visual_support


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _storyboard() -> dict:
    return {
        "segments": [{
            "id": "1", "narration": "DVC 使用神经网络替代传统模块。",
            "elements": [
                {"id": "figure", "type": "image", "src": "f2.png", "source_image_id": "fig-2", "description": "DVC framework"},
                {"id": "title", "type": "heading", "text": "DVC"},
            ], "animations": [], "timeline": [],
        }],
    }


def test_explicit_none_decision_blocks_event_creation(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    evidence = tmp_path / "evidence.json"
    _write(baseline, _storyboard())
    _write(graph, {"narration_propositions": [{
        "id": "lesson-seg-1-nprop-001", "segment_id": "1", "text": "DVC 使用神经网络替代传统模块。",
        "knowledge_proposition_ids": ["lesson-kprop-001"], "source_refs": ["raw-unit-0001"],
    }]})
    _write(decisions, {"decisions": [{
        "narration_proposition_id": "lesson-seg-1-nprop-001", "action": "none", "rationale": "No explanatory visual needed",
    }]})
    _write(evidence, {"source_units": [{"id": "raw-unit-0001", "text": "source"}]})
    paths = prepare_p0_candidate(baseline, output_dir=tmp_path, proposition_graph_path=graph)
    plan_path = build_local_p0_plan(paths, source_evidence_path=evidence, visual_decision_path=decisions)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["events"] == []
    assert plan["decisions"][0]["acquisition"] == "NONE"


def test_multiple_propositions_share_one_figure_without_duplicate_signal(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    storyboard = _storyboard()
    storyboard["segments"][0]["elements"][0]["source_image_id"] = "fig-2"
    _write(baseline, storyboard)
    _write(graph, {"narration_propositions": [
        {"id": "p1", "segment_id": "1", "text": "DVC 使用神经网络", "span": {"start": 0, "end": 9}, "knowledge_proposition_ids": ["k1"], "source_refs": ["u1"]},
        {"id": "p2", "segment_id": "1", "text": "替代传统模块", "span": {"start": 9, "end": 15}, "knowledge_proposition_ids": ["k2"], "source_refs": ["u2"]},
    ]})
    _write(decisions, {"decisions": [
        {"narration_proposition_id": "p1", "action": "reuse", "source_image_id": "fig-2"},
        {"narration_proposition_id": "p2", "action": "reuse", "source_image_id": "fig-2"},
    ]})
    paths = prepare_p0_candidate(
        baseline, output_dir=tmp_path, proposition_graph_path=graph,
    )
    plan_path = build_local_p0_plan(
        paths, visual_decision_path=decisions, require_visual_decisions=True,
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert len(plan["bindings"]) == 2
    assert len(plan["events"]) == 2
    assert [event["action"] for event in plan["events"]] == ["show", "focus"]


def test_retrieval_and_generation_keep_provenance_and_do_not_fabricate_assets(
    tmp_path: Path, monkeypatch
) -> None:
    decisions = tmp_path / "decisions.json"
    _write(decisions, {"decisions": [
        {"narration_proposition_id": "p1", "action": "retrieve", "retrieval_query": "neural compression framework"},
        {"narration_proposition_id": "p2", "action": "generate", "generation_prompt": "a clean neural compression diagram"},
    ]})
    monkeypatch.setattr(
        "textbook2video.research.visual_acquisition.generate_image",
        lambda *_args, **_kwargs: None,
    )
    result_path = execute_visual_acquisition(decision_path=decisions, output_dir=tmp_path / "out")
    assets = json.loads(result_path.read_text(encoding="utf-8"))["assets"]
    assert assets[0]["status"] == "RETRIEVAL_NO_ACCEPTABLE_RESULT"
    assert assets[1]["status"] == "GENERATION_FAILED"


def test_generation_can_be_explicitly_disabled(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions.json"
    _write(decisions, {"decisions": [{
        "narration_proposition_id": "p2", "action": "generate", "generation_prompt": "a diagram",
    }]})
    result_path = execute_visual_acquisition(
        decision_path=decisions, output_dir=tmp_path / "out", enable_generation=False,
    )
    asset = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert asset["status"] == "GENERATION_REQUIRES_EXPLICIT_ENABLE"


def test_retrieval_below_threshold_is_not_materialized(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    source.write_bytes(b"candidate")
    decisions = tmp_path / "decisions.json"
    catalog = tmp_path / "catalog.json"
    _write(decisions, {"decisions": [{
        "narration_proposition_id": "p1", "action": "retrieve",
        "retrieval_query": "neural compression architecture",
    }]})
    _write(catalog, {"assets": [{
        "id": "weak", "path": str(source), "license": "CC-BY",
        "title": "neural illustration",
    }]})
    result_path = execute_visual_acquisition(
        decision_path=decisions,
        output_dir=tmp_path / "out",
        retrieval_catalog_path=catalog,
        min_retrieval_score=0.8,
    )
    asset = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert asset["status"] == "RETRIEVAL_BELOW_RELEVANCE_THRESHOLD"
    assert not list((tmp_path / "out" / "images").glob("*"))


def test_source_reuse_materializes_exact_bytes_but_does_not_grant_review(tmp_path):
    import hashlib
    import pytest

    source = tmp_path / 'source.png'
    source.write_bytes(b'original figure bytes')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = tmp_path / 'evidence.json'
    decisions = tmp_path / 'decisions.json'
    _write(evidence, {'source_images': [{'id': 'fig-1', 'local_path': str(source),
                                       'sha256': digest}]})
    _write(decisions, {'decisions': [
        {'narration_proposition_id': prop, 'action': 'reuse', 'source_image_id': 'fig-1'}
        for prop in ('p1', 'p2')]})
    path = execute_visual_acquisition(decision_path=decisions, output_dir=tmp_path/'out',
                                     source_evidence_path=evidence, enable_generation=False)
    assets = json.loads(path.read_text(encoding='utf-8'))['assets']
    assert len(assets) == 2
    assert len(list((tmp_path/'out/images').iterdir())) == 1
    assert all(a['status'] == 'SOURCE_REUSED_PENDING_VLM_REVIEW' for a in assets)
    assert all(a['sha256'] == digest and 'vlm_verdict' not in a for a in assets)
    assert Path(assets[0]['local_path']).read_bytes() == source.read_bytes()
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='source image hash drift'):
        execute_visual_acquisition(decision_path=decisions, output_dir=tmp_path/'bad',
                                   source_evidence_path=evidence)


def test_retrieved_assets_with_colliding_sanitized_ids_preserve_both_candidates(tmp_path):
    first, second = tmp_path/'first.png', tmp_path/'second.png'
    first.write_bytes(b'first'); second.write_bytes(b'second')
    catalog, decisions = tmp_path/'catalog.json', tmp_path/'decisions.json'
    _write(catalog, {'assets': [
        {'id': 'same?', 'path': str(first), 'license': 'CC0', 'title': 'alpha'},
        {'id': 'same!', 'path': str(second), 'license': 'CC0', 'title': 'beta'}]})
    _write(decisions, {'decisions': [
        {'narration_proposition_id': query, 'action': 'retrieve', 'retrieval_query': query}
        for query in ('alpha', 'beta', 'unmatched')]})
    path = execute_visual_acquisition(decision_path=decisions, output_dir=tmp_path/'out',
                                     retrieval_catalog_path=catalog, enable_generation=False,
                                     content_addressed_assets=True)
    assets = json.loads(path.read_text(encoding='utf-8'))['assets']
    assert Path(assets[0]['local_path']).read_bytes() == b'first'
    assert Path(assets[1]['local_path']).read_bytes() == b'second'
    assert assets[0]['filename'] != assets[1]['filename']
    assert assets[0]['asset_id'] != assets[1]['asset_id']
    assert assets[2]['status'] == 'RETRIEVAL_NO_ACCEPTABLE_RESULT'


def test_default_retrieval_keeps_persisted_review_asset_id(tmp_path):
    source = tmp_path/'source.png'
    source.write_bytes(b'pixels')
    catalog, decisions = tmp_path/'catalog.json', tmp_path/'decisions.json'
    _write(catalog, {'assets': [{'id': 'old-asset', 'path': str(source),
                                'title': 'architecture', 'license': 'CC0'}]})
    _write(decisions, {'decisions': [{'narration_proposition_id': 'p1', 'action': 'retrieve',
                                     'retrieval_query': 'architecture'}]})
    path = execute_visual_acquisition(decision_path=decisions, output_dir=tmp_path/'out',
                                     retrieval_catalog_path=catalog, enable_generation=False)
    assert json.loads(path.read_text(encoding='utf-8'))['assets'][0]['asset_id'] == 'old-asset'


def test_source_evidence_preserves_full_figure_granularity_and_blocks_fragment(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "lesson_raw.txt"
    raw.write_text("source", encoding="utf-8")
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "figure.png").write_bytes(b"figure")
    (images_dir / "fragment.jpeg").write_bytes(b"fragment")
    available = [
        {
            "id": "fig-2", "filename": "figure.png", "figure_id": "Figure 2",
            "caption": "Figure 2: Complete architecture.",
            "asset_kind": "RENDERED_FIGURE_CROP", "source_component_ids": ["img-1"],
        },
        {
            "id": "img-1", "filename": "fragment.jpeg", "figure_id": "Figure 2",
            "caption": "Figure 2: Complete architecture.",
        },
    ]
    evidence_path = build_source_evidence(
        raw, available, output_path=tmp_path / "evidence.json",
    )
    images = {
        item["id"]: item
        for item in json.loads(evidence_path.read_text(encoding="utf-8"))["source_images"]
    }
    assert images["fig-2"]["asset_kind"] == "RENDERED_FIGURE_CROP"
    assert images["fig-2"]["caption"].startswith("Figure 2")
    assert images["fig-2"]["teaching_asset_status"].startswith("ELIGIBLE_COMPLETE_FIGURE")
    assert images["img-1"]["teaching_asset_status"] == "INELIGIBLE_ISOLATED_FIGURE_COMPONENT"

    briefs = build_visual_briefs(
        [{
            "verdict": "ACCEPT", "source_image_id": "img-1", "segment_id": "1",
            "visual_summary": "fragment", "proposition": "claim",
        }],
        list(images.values()),
    )
    assert briefs == []


def test_visual_decision_reuse_candidates_are_scoped_to_storyboard_segment(
    tmp_path: Path, monkeypatch,
) -> None:
    graph = tmp_path / "graph.json"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    _write(graph, {"narration_propositions": [
        {"id": "p1", "segment_id": "1", "text": "claim one"},
        {"id": "p2", "segment_id": "2", "text": "claim two"},
    ]})
    _write(evidence, {"source_images": [
        {"id": "fig-1", "filename": "one.png", "availability": "AVAILABLE_LOCAL", "teaching_asset_status": "ELIGIBLE_COMPLETE_FIGURE_REQUIRES_VLM"},
        {"id": "fig-2", "filename": "two.png", "availability": "AVAILABLE_LOCAL", "teaching_asset_status": "ELIGIBLE_COMPLETE_FIGURE_REQUIRES_VLM"},
    ]})
    _write(storyboard, {"segments": [
        {"id": "1", "elements": [{"type": "image", "source_image_id": "fig-1"}]},
        {"id": "2", "elements": [{"type": "image", "source_image_id": "fig-2"}]},
    ]})
    prompts = []

    def fake_chat(prompt, **_kwargs):
        request = json.loads(prompt)
        prompts.append(request)
        proposition_id = request["narration_propositions"][0]["id"]
        return json.dumps({"decisions": [{
            "narration_proposition_id": proposition_id,
            "action": "none",
            "rationale": "not needed",
        }]})

    monkeypatch.setattr(
        "textbook2video.research.visual_decision.chat_with_system", fake_chat,
    )
    decide_visual_support(
        proposition_graph_path=graph,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        output_path=tmp_path / "decisions.json",
    )
    assert [[item["id"] for item in prompt["source_images"]] for prompt in prompts] == [
        ["fig-1"], ["fig-2"],
    ]


def test_signaling_diagnostics_rejects_missing_target_and_reports_density() -> None:
    result = diagnose_signaling(
        events=[
            {"id": "e1", "segment_id": "1", "target_element_id": "missing", "proposition_id": "p1", "action": "focus", "lead_sec": 0},
            {"id": "e2", "segment_id": "1", "target_element_id": "known", "proposition_id": "p1", "action": "highlight", "lead_sec": 0},
            {"id": "e3", "segment_id": "1", "target_element_id": "known", "proposition_id": "p1", "action": "pulse", "lead_sec": 1},
        ],
        elements_by_segment={"1": {"known"}},
        propositions={"p1": {"segment_id": "1"}},
    )
    codes = {item["code"] for item in result["findings"]}
    assert result["pass"] is False
    assert "SIGNAL_TARGET_MISSING" in codes
    assert "SIGNAL_DENSITY_EXCEEDED" in codes


def test_only_vlm_accepted_acquisition_becomes_storyboard_brief(tmp_path: Path) -> None:
    image = tmp_path / "asset.png"
    image.write_bytes(b"png")
    decisions = tmp_path / "decisions.json"
    acquisition = tmp_path / "acquisition.json"
    reviews = tmp_path / "reviews.json"
    _write(decisions, {"decisions": [{"narration_proposition_id": "p1", "action": "retrieve", "rationale": "diagram"}]})
    _write(acquisition, {"assets": [{
        "asset_id": "asset-1", "proposition_id": "p1", "status": "RETRIEVED_LOCAL_RAG",
        "local_path": str(image), "filename": image.name, "license": "CC-BY",
    }]})
    _write(reviews, {"decisions": [
        {"asset_id": "asset-1", "narration_proposition_id": "p1", "segment_id": "2", "verdict": "REJECT", "visual_summary": "bad"},
        {"asset_id": "asset-1", "narration_proposition_id": "p1", "segment_id": "2", "verdict": "ACCEPT", "visual_summary": "useful diagram"},
    ]})
    output = build_reviewed_acquisition_briefs(
        decision_path=decisions, acquisition_path=acquisition,
        vlm_review_path=reviews, output_path=tmp_path / "briefs.json",
    )
    briefs = json.loads(output.read_text(encoding="utf-8"))["visual_briefs"]
    assert len(briefs) == 1
    assert briefs[0]["source_image_id"] == "asset-1"
    assert briefs[0]["vlm_verdict"] == "ACCEPT"
    assert (tmp_path / "images" / "asset.png").is_file()
    assert (tmp_path / "briefs_images.json").is_file()
