import json
from pathlib import Path

from jsonschema import Draft202012Validator

from textbook2video.research.proposition_schema import (
    annotate_storyboard_v2,
    build_lesson_plan_v2,
    build_script_v2,
    migrate_legacy_bundle,
    build_storyboard_v2,
    build_source_units_v2,
)
from textbook2video.research.render_evidence import write_render_evidence


def test_v2_migration_keeps_legacy_ids_and_adds_explicit_relations() -> None:
    legacy_plan = {"lesson_title": "Test", "knowledge_points": [{"id": "kp1", "name": "Motion", "description": "Motion has direction."}]}
    storyboard = {"segments": [{"id": "1", "narration": "Motion has direction.", "elements": [{"id": "e1", "type": "image"}], "animations": [{"target": "e1", "action": "show"}]}]}
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)
    assert plan["knowledge_points"][0]["propositions"][0]["source_refs"]
    assert annotated["segments"][0]["research_generation_v2"]["narration_proposition_ids"]
    assert annotated["segments"][0]["elements"][0]["id"] == "e1"
    assert annotated["segments"][0]["elements"][0]["research_generation_v2"]["binding_source"] == "deterministic_bootstrap"
    projected = build_storyboard_v2(annotated, case_id="case_1")
    assert projected["artifact_type"] == "storyboard_v2"
    schema = json.loads((Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(plan))
    assert not list(validator.iter_errors(script))
    assert not list(validator.iter_errors(projected))
    assert not list(validator.iter_errors(build_source_units_v2(case_id="case_1", raw_text="Motion has direction.")))
    migrated = migrate_legacy_bundle(lesson_plan=legacy_plan, script_segments=["Motion has direction."], storyboard=storyboard, raw_text="Motion has direction.", case_id="case_1")
    assert migrated["script_v2"]["artifact_type"] == "script_v2"


def test_render_evidence_does_not_claim_runtime_as_visibility(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not-a-real-video")
    output = write_render_evidence(
        video_path=video, case_id="case_1", output_path=tmp_path / "evidence.json",
        runtime_trace={"events": [{"event_id": "evt-1", "status": "executed", "actual_ms": 1000}]},
        planned_events=[{"id": "evt-1", "target_element_id": "el-1"}],
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["observations"][0]["status"] == "not_reviewed"
    assert value["observations"][0]["observed_visible_start_sec"] is None
