import json
from pathlib import Path

import pytest

from textbook2video.pipeline.storyboard import (
    _build_visual_briefs_section,
    _ensure_visual_brief_coverage,
    _sanitize_image_paths,
)
from textbook2video.research.p0_integration import (
    P0_PLAN_VERSION,
    apply_p0_event_schedule,
    prepare_p0_candidate,
    validate_p0_case_bundle,
    write_p0_case_manifest,
)
from textbook2video.research.p0_planner import build_local_p0_plan
from textbook2video.research.source_evidence import build_source_evidence
from textbook2video.research.visual_briefs import (
    build_visual_briefs,
    build_vlm_review_context,
)
from textbook2video.research.visual_synthesis import compile_visuals
from textbook2video.variants import pick_variant_html


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _storyboard() -> dict:
    return {
        "lesson_title": "Test lesson",
        "segments": [
            {
                "id": "seg-01",
                "narration": "先介绍概念。再解释关键机制。",
                "audio_duration_sec": 8.0,
                "elements": [
                    {"id": "existing-title", "type": "heading", "text": "概念"},
                    {"id": "existing-diagram", "type": "flow_step", "text": "关键机制"},
                ],
                "animations": [
                    {"target": "existing-title", "effect": "fadeInUp", "trigger_at_sec": 0.0}
                ],
                "timeline": [
                    {"target": "existing-title", "effect": "fadeInUp", "at_sec": 0.0},
                    {"target": "existing-diagram", "effect": "fadeInUp", "at_sec": 0.1},
                ],
            }
        ],
    }


def test_p0_candidate_preserves_baseline_and_schedules_existing_element(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    plan = tmp_path / "p0_plan.json"
    _write_json(baseline, _storyboard())
    _write_json(
        plan,
        {
            "schema_version": P0_PLAN_VERSION,
            "events": [
                {
                    "id": "p0-event-001",
                    "segment_id": "seg-01",
                    "proposition_id": "seg-01-nprop-02",
                    "target_element_id": "existing-diagram",
                    "lead_sec": 0.0,
                    "action": "focus",
                }
            ],
        },
    )

    paths = prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan)
    assert json.loads(baseline.read_text(encoding="utf-8")) == _storyboard()
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    assert candidate["metadata"]["research_p0"]["enabled"] is True
    assert candidate["segments"][0]["elements"][1]["id"] == "existing-diagram"

    sidecar = apply_p0_event_schedule(paths, sentence_cues={"segments": [{
        "segment_id": "seg-01", "cues": [
            {"sentence_id": "seg-01-sent-01", "index": 1, "text": "先介绍概念。", "start_sec": 0.0, "end_sec": 3.0},
            {"sentence_id": "seg-01-sent-02", "index": 2, "text": "再解释关键机制。", "start_sec": 3.0, "end_sec": 8.0},
        ],
    }]})
    scheduled = sidecar["events"][0]
    assert scheduled["status"] == "SCHEDULED_ON_PRODUCTION_ANIMATION"
    assert scheduled["planned_trigger_at_sec"] > 0
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    animation = next(
        item
        for item in candidate["segments"][0]["animations"]
        if item["target"] == "existing-diagram"
    )
    assert animation["research_p0"]["event_id"] == "p0-event-001"
    assert animation["action"] == "focus"
    timeline_event = next(
        item
        for item in candidate["segments"][0]["timeline"]
        if item["target"] == "existing-diagram"
    )
    assert timeline_event["action"] == "focus"
    assert timeline_event["at_sec"] == scheduled["planned_trigger_at_sec"]
    assert paths.candidate_storyboard_path.with_name("lesson_p0_timed_storyboard.json").is_file()


def test_p0_candidate_materializes_a_compiled_svg_visual(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    _write_json(baseline, _storyboard())
    manifest = compile_visuals([
        {"id": "network", "kind": "network", "title": "节点网络", "items": ["甲", "乙", "丙"]}
    ], tmp_path / "compiled")
    paths = prepare_p0_candidate(
        baseline,
        output_dir=tmp_path / "candidate",
        compiled_visual_manifest_path=manifest,
        compiled_visual_bindings=[{
            "asset_id": "network", "segment_id": "seg-01", "element_id": "generic-network",
            "proposition_id": "seg-01-nprop-02", "description": "节点网络结构",
        }],
    )
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    visual = candidate["segments"][0]["elements"][-1]
    assert visual["src"] == "network.svg"
    assert visual["research_p0"]["acquisition"] == "DETERMINISTIC_SVG"
    assert (paths.candidate_storyboard_path.parent / "images" / "network.svg").is_file()


def test_compiled_svg_can_fulfill_a_generate_visual_decision(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    plan = tmp_path / "plan.json"
    _write_json(baseline, _storyboard())
    _write_json(graph, {"narration_propositions": [{
        "id": "p-network", "segment_id": "seg-01", "text": "解释节点网络",
        "source_refs": [], "knowledge_proposition_ids": [],
    }]})
    _write_json(decisions, {"decisions": [{
        "narration_proposition_id": "p-network", "action": "generate",
    }]})
    _write_json(plan, {"schema_version": P0_PLAN_VERSION, "events": [{
        "id": "event-network", "segment_id": "seg-01", "proposition_id": "p-network",
        "target_element_id": "generic-network", "action": "show",
    }]})
    manifest = compile_visuals([
        {"id": "network", "kind": "network", "title": "节点网络", "items": ["甲", "乙"]}
    ], tmp_path / "compiled")
    paths = prepare_p0_candidate(
        baseline, output_dir=tmp_path / "candidate", plan_path=plan,
        proposition_graph_path=graph, visual_decision_path=decisions,
        compiled_visual_manifest_path=manifest,
        compiled_visual_bindings=[{
            "asset_id": "network", "segment_id": "seg-01", "element_id": "generic-network",
            "proposition_id": "p-network", "description": "节点网络结构",
        }],
    )
    sidecar = json.loads(paths.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["events"][0]["target_element_id"] == "generic-network"


def test_p0_schedule_uses_persisted_tts_sentence_cues_when_available(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    plan = tmp_path / "p0_plan.json"
    _write_json(baseline, _storyboard())
    _write_json(plan, {"schema_version": P0_PLAN_VERSION, "events": [{
        "id": "p0-event-001", "segment_id": "seg-01",
        "proposition_id": "seg-01-nprop-02", "target_element_id": "existing-diagram",
        "action": "focus", "hold_sec": 2.0,
    }]})
    paths = prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan)
    sidecar = apply_p0_event_schedule(paths, sentence_cues={"segments": [{
            "segment_id": "seg-01", "cues": [
                {"sentence_id": "seg-01-sent-01", "index": 1, "text": "先介绍概念。", "start_sec": 0.0, "end_sec": 5.1},
                {"sentence_id": "seg-01-sent-02", "index": 2, "text": "再解释关键机制。", "start_sec": 5.1, "end_sec": 8.0},
            ],
    }]})
    event = sidecar["events"][0]
    assert event["planned_trigger_at_sec"] == 5.1
    assert event["cue_timing_kind"] == "measured_sentence_cue"


def test_p0_schedule_rejects_duration_weighted_fallback(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    plan = tmp_path / "p0_plan.json"
    _write_json(baseline, _storyboard())
    _write_json(plan, {"schema_version": P0_PLAN_VERSION, "events": [{
        "id": "p0-event-001", "segment_id": "seg-01",
        "proposition_id": "seg-01-nprop-02", "target_element_id": "existing-diagram",
    }]})
    paths = prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan)

    with pytest.raises(ValueError, match="requires measured sentence cues"):
        apply_p0_event_schedule(paths)


def test_p0_schedule_maps_proposition_span_inside_measured_sentence(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    graph = tmp_path / "graph.json"
    plan = tmp_path / "p0_plan.json"
    storyboard = _storyboard()
    storyboard["segments"][0]["narration"] = "第一句很短。第二句先解释背景，然后讲关键机制。"
    _write_json(baseline, storyboard)
    proposition_text = "然后讲关键机制"
    start = storyboard["segments"][0]["narration"].index(proposition_text)
    _write_json(graph, {"narration_propositions": [{
        "id": "graph-nprop-1", "segment_id": "seg-01", "text": proposition_text,
        "span": {"start": start, "end": start + len(proposition_text)},
        "knowledge_proposition_ids": ["kp-1"], "source_refs": ["raw-unit-1"],
    }]})
    _write_json(plan, {"schema_version": P0_PLAN_VERSION, "events": [{
        "id": "p0-event-001", "segment_id": "seg-01", "proposition_id": "graph-nprop-1",
        "target_element_id": "existing-diagram", "action": "focus",
    }]})
    paths = prepare_p0_candidate(
        baseline, output_dir=tmp_path, plan_path=plan, proposition_graph_path=graph,
    )
    sidecar = apply_p0_event_schedule(paths, sentence_cues={"segments": [{
        "segment_id": "seg-01", "cues": [
            {"sentence_id": "s1", "index": 1, "text": "第一句很短。", "start_sec": 0.0, "end_sec": 2.0},
            {"sentence_id": "s2", "index": 2, "text": "第二句先解释背景，然后讲关键机制。", "start_sec": 2.0, "end_sec": 8.0},
        ],
    }]})
    event = sidecar["events"][0]
    assert event["cue_sentence_id"] == "s2"
    assert event["cue_match_kind"] == "exact_narration_span"
    assert 4.0 < event["planned_trigger_at_sec"] < 8.0

    # Re-applying the same intervention updates the event instead of duplicating it.
    apply_p0_event_schedule(paths, sentence_cues={"segments": [{
        "segment_id": "seg-01", "cues": [
            {"sentence_id": "s1", "index": 1, "text": "第一句很短。", "start_sec": 0.0, "end_sec": 2.0},
            {"sentence_id": "s2", "index": 2, "text": "第二句先解释背景，然后讲关键机制。", "start_sec": 2.0, "end_sec": 8.0},
        ],
    }]})
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    target_events = [
        item for item in candidate["segments"][0]["timeline"]
        if item.get("target") == "existing-diagram"
    ]
    assert len(target_events) == 1


def test_p0_candidate_rejects_nonexistent_production_target(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    plan = tmp_path / "p0_plan.json"
    _write_json(baseline, _storyboard())
    _write_json(
        plan,
        {
            "schema_version": P0_PLAN_VERSION,
            "events": [
                {
                    "segment_id": "seg-01",
                    "proposition_id": "seg-01-nprop-01",
                    "target_element_id": "invented-element",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="missing production element"):
        prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan)


def test_local_planner_emits_reuse_binding_and_unmatched_local_retrieval_request(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    _write_json(baseline, _storyboard())
    bootstrap = prepare_p0_candidate(baseline, output_dir=tmp_path)

    plan_path = build_local_p0_plan(bootstrap)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    decisions = {item["proposition_id"]: item for item in plan["decisions"]}
    assert decisions["seg-01-nprop-02"]["acquisition"] == "REUSE"
    assert decisions["seg-01-nprop-02"]["target_element_id"] == "existing-diagram"
    assert decisions["seg-01-nprop-01"]["acquisition"] == "RETRIEVE_REQUIRED_PRE_STORYBOARD"
    assert decisions["seg-01-nprop-01"]["retrieval_status"] == "REQUESTED_NO_POST_STORYBOARD_MATERIALIZATION"
    assert plan["events"][0]["target_element_id"] == "existing-diagram"
    assert plan["events"][0]["action"] == "show"
    assert plan["events"][1]["action"] == "focus"


def test_local_planner_exports_unmet_need_without_post_storyboard_image_injection(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    storyboard = _storyboard()
    storyboard["segments"][0]["narration"] = "展示网络拓扑关系。"
    storyboard["segments"][0]["elements"] = [
        {"id": "existing-title", "type": "heading", "text": "开场"}
    ]
    storyboard["metadata"] = {
        "available_images": [
            {"id": "fig-1", "filename": "network.png", "description": "网络拓扑关系图"}
        ]
    }
    _write_json(baseline, storyboard)
    raw = tmp_path / "lesson_raw.txt"
    raw.write_text("本节展示网络拓扑关系。", encoding="utf-8")
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "network.png").write_bytes(b"not-rendered-in-this-unit-test")

    bootstrap = prepare_p0_candidate(baseline, output_dir=tmp_path)
    evidence_path = build_source_evidence(
        raw,
        storyboard["metadata"]["available_images"],
        output_path=tmp_path / "lesson_p0_source_evidence.json",
    )
    plan_path = build_local_p0_plan(bootstrap, source_evidence_path=evidence_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["retrieved_visuals"] == []
    decision = plan["decisions"][0]
    assert decision["acquisition"] == "RETRIEVE_REQUIRED_PRE_STORYBOARD"
    assert decision["retrieval_status"] == "REQUESTED_NO_POST_STORYBOARD_MATERIALIZATION"

    paths = prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan_path)
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    images = [item for item in candidate["segments"][0]["elements"] if item["type"] == "image"]
    assert images == []
    sidecar = json.loads(paths.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["source_evidence"]["status"] == "LINKED_MACHINE_CANDIDATES"
    assert sidecar["propositions"][0]["source_refs"][0]["status"] == "MACHINE_CANDIDATE_NOT_GOLD"


def test_visual_briefs_bind_images_to_storyboard_segments_and_block_other_assets() -> None:
    prompt = _build_visual_briefs_section(
        [{
            "segment_id": "2", "source_image_id": "fig-dvc",
            "visual_summary": "运动估计流程图", "proposition": "解释光流编码",
        }],
        batch_start=0,
        batch_size=3,
    )
    assert "fig-dvc" in prompt
    assert "指定段落" in prompt

    storyboard = {"segments": [{"narration": "解释光流", "elements": [
        {"type": "image", "src": "fig-dvc"},
        {"type": "image", "src": "unverified"},
    ]}]}
    _sanitize_image_paths(
        storyboard,
        [
            {"id": "fig-dvc", "filename": "dvc.png"},
            {"id": "unverified", "filename": "photo.png"},
        ],
        allowed_image_ids={"fig-dvc"},
    )
    images = storyboard["segments"][0]["elements"]
    assert images[0]["src"] == "dvc.png"
    assert "src" not in images[1]


def test_visual_brief_asset_is_not_usable_on_a_different_segment() -> None:
    storyboard = {"segments": [
        {"id": "1", "elements": [{"type": "image", "src": "fig-dvc"}]},
        {"id": "2", "elements": [{"type": "image", "src": "fig-dvc"}]},
    ]}
    _sanitize_image_paths(
        storyboard,
        [{"id": "fig-dvc", "filename": "dvc.png"}],
        allowed_image_ids={"fig-dvc"},
        allowed_image_ids_by_segment={"2": {"fig-dvc"}},
    )
    assert storyboard["segments"][0]["elements"] == []
    assert storyboard["segments"][1]["elements"][0]["src"] == "dvc.png"


def test_visual_brief_sanitizer_keeps_resolved_filename_and_removes_unbound_image() -> None:
    storyboard = {"segments": [{"id": "2", "elements": [
        {"type": "image", "src": "dvc.png"},
        {"type": "image", "description": "LLM-invented decorative image"},
    ]}]}
    _sanitize_image_paths(
        storyboard, [{"id": "fig-dvc", "filename": "dvc.png"}],
        allowed_image_ids={"fig-dvc"},
        allowed_image_ids_by_segment={"2": {"fig-dvc"}},
    )
    assert storyboard["segments"][0]["elements"] == [{
        "type": "image", "src": "dvc.png", "source_image_id": "fig-dvc",
    }]


def test_visual_brief_coverage_injects_only_a_missing_bound_source_figure() -> None:
    storyboard = {"segments": [
        {"id": "1", "elements": []},
        {"id": "2", "elements": [{"type": "image", "src": "fig-2"}]},
    ]}
    briefs = [
        {"segment_id": "1", "source_image_id": "fig-1", "visual_summary": "Figure one",
         "figure_id": "Figure 1", "caption": "Figure 1: Original source caption."},
        {"segment_id": "2", "source_image_id": "fig-2", "visual_summary": "Figure two",
         "figure_id": "Figure 2", "caption": "Figure 2: Second source caption."},
    ]
    _ensure_visual_brief_coverage(
        storyboard, briefs,
        [{"id": "fig-1", "filename": "one.png"}, {"id": "fig-2", "filename": "two.png"}],
    )
    inserted = storyboard["segments"][0]["elements"][0]
    assert inserted["src"] == "fig-1"
    assert inserted["injected_from_visual_brief"] is True
    assert inserted["figure_id"] == "Figure 1"
    assert inserted["source_caption"] == "Figure 1: Original source caption."
    existing = storyboard["segments"][1]["elements"][0]
    assert existing["source_caption"] == "Figure 2: Second source caption."
    assert len(storyboard["segments"][1]["elements"]) == 1


def test_source_figure_renderer_prefers_original_caption_to_vlm_summary() -> None:
    html = pick_variant_html(
        "image",
        {
            "id": "figure",
            "description": "Long VLM interpretation that is not a display caption.",
            "figure_id": "Figure 4",
            "source_caption": "Figure 4: Our Motion Compensation Network.",
        },
        "4",
        "delay-1",
        {"4:figure"},
        preferred=["polaroid"],
    )
    assert "Figure 4: Our Motion Compensation Network." in html
    assert "Long VLM interpretation" not in html


def test_visual_briefs_require_explicit_vlm_accept_and_real_visual_summary() -> None:
    briefs = build_visual_briefs(
        [
            {"verdict": "REJECT", "source_image_id": "fig-1", "segment_id": "1"},
            {"verdict": "ACCEPT", "source_image_id": "fig-1", "segment_id": "1",
             "visual_summary": "真实流程图", "proposition": "解释编码流程"},
            {"verdict": "ACCEPT", "source_image_id": "unknown", "segment_id": "2",
             "visual_summary": "不存在", "proposition": "无效"},
        ],
        [{"id": "fig-1", "filename": "flow.png"}],
    )
    assert briefs == [{
        "segment_id": "1", "source_image_id": "fig-1", "filename": "flow.png",
        "visual_summary": "真实流程图", "proposition": "解释编码流程",
        "layout_hint": "主视觉 + 简短解释", "vlm_verdict": "ACCEPT", "vlm_reason": "",
    }]


def test_vlm_review_context_includes_source_caption_and_proposition() -> None:
    context = build_vlm_review_context(
        {
            "id": "fig-1", "filename": "motion.png", "page_number": 5,
            "figure_id": "Figure 3", "caption": "Figure 3. Motion compensation.",
            "caption_source_span": {"start": 100, "end": 130},
        },
        segment_id="4",
        proposition="The previous frame is warped using the motion vector.",
    )
    assert context["caption"] == "Figure 3. Motion compensation."
    assert context["proposition"].startswith("The previous frame")
    assert "INPUT_EXAMPLE" in context["review_instruction"]


def test_visual_brief_preserves_vlm_visual_role() -> None:
    briefs = build_visual_briefs(
        [{
            "verdict": "ACCEPT", "role": "EXPLANATORY_DIAGRAM",
            "source_image_id": "fig-1", "segment_id": "2",
            "visual_summary": "A codec graph.", "proposition": "The codec has an encoder.",
        }],
        [{"id": "fig-1", "filename": "codec.png"}],
    )
    assert briefs[0]["visual_role"] == "EXPLANATORY_DIAGRAM"


def test_p0_rejects_visual_decision_from_different_storyboard_revision(tmp_path: Path) -> None:
    storyboard_path = tmp_path / "storyboard.json"
    graph_path = tmp_path / "graph.json"
    decisions_path = tmp_path / "decisions.json"
    plan_path = tmp_path / "plan.json"
    storyboard = _storyboard()
    storyboard["segments"][0]["elements"][1]["source_image_id"] = "clean-figure-1"
    _write_json(storyboard_path, storyboard)
    _write_json(graph_path, {"narration_propositions": [{
        "id": "p1", "segment_id": "seg-01", "text": "鍏抽敭鏈哄埗",
        "knowledge_proposition_ids": ["k1"], "source_refs": ["u1"],
    }]})
    _write_json(decisions_path, {"decisions": [{
        "narration_proposition_id": "p1", "action": "reuse",
        "source_image_id": "stale-figure-1",
    }]})
    _write_json(plan_path, {"schema_version": P0_PLAN_VERSION, "events": [{
        "id": "event-1", "segment_id": "seg-01", "proposition_id": "p1",
        "target_element_id": "existing-diagram", "action": "show",
    }]})
    with pytest.raises(ValueError, match="mixes visual decision source"):
        prepare_p0_candidate(
            storyboard_path,
            output_dir=tmp_path / "candidate",
            plan_path=plan_path,
            proposition_graph_path=graph_path,
            visual_decision_path=decisions_path,
        )


def test_p0_case_manifest_validates_cross_artifact_hashes_and_bindings(tmp_path: Path) -> None:
    storyboard = _storyboard()
    storyboard["segments"][0]["elements"][1]["source_image_id"] = "fig-1"
    storyboard_path = tmp_path / "candidate_storyboard.json"
    graph_path = tmp_path / "graph.json"
    decisions_path = tmp_path / "decisions.json"
    plan_path = tmp_path / "plan.json"
    for path, value in [
        (storyboard_path, storyboard),
        (graph_path, {"narration_propositions": [{
            "id": "p1", "segment_id": "seg-01", "text": "鍏抽敭鏈哄埗",
            "source_refs": ["u1"],
        }]}),
        (decisions_path, {"decisions": [{
            "narration_proposition_id": "p1", "action": "reuse", "source_image_id": "fig-1",
        }]}),
        (plan_path, {"schema_version": P0_PLAN_VERSION, "bindings": [{
            "proposition_id": "p1", "segment_id": "seg-01", "target_element_id": "existing-diagram",
        }], "events": [{
            "id": "e1", "proposition_id": "p1", "segment_id": "seg-01",
            "target_element_id": "existing-diagram", "action": "show",
        }]}),
    ]:
        _write_json(path, value)
    manifest_path = write_p0_case_manifest(
        tmp_path / "case_manifest.json", case_id="case-1",
        artifacts={
            "candidate_storyboard": storyboard_path,
            "p0_plan": plan_path,
            "proposition_graph": graph_path,
            "visual_decisions": decisions_path,
        },
    )
    result = validate_p0_case_bundle(manifest_path)
    assert result["valid"] is True
    assert result["event_count"] == 1
    assert result["binding_count"] == 1
