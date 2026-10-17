import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from textbook2video.research.proposition_schema import (
    annotate_storyboard_v2,
    build_lesson_plan_v2,
    build_script_v2,
    build_source_units_v2,
    build_storyboard_v2,
    build_timed_storyboard_v2,
    migrate_legacy_bundle,
)
from textbook2video.research.render_evidence import write_render_evidence


def test_v2_migration_keeps_legacy_ids_and_adds_explicit_relations() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Motion", "description": "Motion has direction."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Motion has direction.",
                "elements": [{"id": "e1", "type": "image"}],
                "animations": [{"target": "e1", "action": "show"}],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)
    assert plan["knowledge_points"][0]["propositions"][0]["source_refs"]
    assert annotated["segments"][0]["research_generation_v2"]["narration_proposition_ids"]
    assert annotated["segments"][0]["elements"][0]["id"] == "e1"
    assert (
        annotated["segments"][0]["elements"][0]["research_generation_v2"]["binding_source"]
        == "deterministic_bootstrap"
    )
    projected = build_storyboard_v2(annotated, case_id="case_1")
    assert projected["artifact_type"] == "storyboard_v2"
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(plan))
    assert not list(validator.iter_errors(script))
    assert not list(validator.iter_errors(projected))
    assert not list(
        validator.iter_errors(
            build_source_units_v2(case_id="case_1", raw_text="Motion has direction.")
        )
    )
    migrated = migrate_legacy_bundle(
        lesson_plan=legacy_plan,
        script_segments=["Motion has direction."],
        storyboard=storyboard,
        raw_text="Motion has direction.",
        case_id="case_1",
    )
    assert migrated["script_v2"]["artifact_type"] == "script_v2"


def test_timed_storyboard_v2_maps_legacy_animation_target_to_v2_id() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Motion", "description": "Motion has direction."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Motion has direction.",
                "audio_duration_sec": 3.0,
                "elements": [{"id": "legacy-element", "type": "image"}],
                "animations": [
                    {
                        "target": "legacy-element",
                        "action": "show",
                        "trigger_at_sec": 1.25,
                        "duration": 0.5,
                    }
                ],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    timed = build_timed_storyboard_v2(annotated, case_id="case_1", timing_source="measured")

    expected_id = annotated["segments"][0]["elements"][0]["research_generation_v2"]["element_id"]
    assert timed["segments"][0]["scheduled_events"][0]["target_element_id"] == expected_id


def test_storyboard_v2_rejects_missing_animation_target() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Motion", "description": "Motion has direction."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Motion has direction.",
                "audio_duration_sec": 3.0,
                "elements": [{"id": "existing", "type": "image"}],
                "animations": [{"target": "missing", "action": "show"}],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    with pytest.raises(ValueError, match="does not resolve"):
        build_storyboard_v2(annotated, case_id="case_1")
    with pytest.raises(ValueError, match="does not resolve"):
        build_timed_storyboard_v2(annotated, case_id="case_1", timing_source="measured")


def test_storyboard_v2_rejects_duplicate_legacy_element_ids() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Motion", "description": "Motion has direction."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Motion has direction.",
                "audio_duration_sec": 3.0,
                "elements": [
                    {"id": "duplicate", "type": "image"},
                    {"id": "duplicate", "type": "text"},
                ],
                "animations": [{"target": "duplicate", "action": "show"}],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    with pytest.raises(ValueError, match="duplicate legacy element id"):
        build_storyboard_v2(annotated, case_id="case_1")
    with pytest.raises(ValueError, match="duplicate legacy element id"):
        build_timed_storyboard_v2(annotated, case_id="case_1", timing_source="measured")


def test_storyboard_v2_rejects_animation_without_event_id() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Motion", "description": "Motion has direction."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Motion has direction.",
                "audio_duration_sec": 3.0,
                "elements": [{"id": "element", "type": "image"}],
                "animations": [{"target": "element", "action": "show"}],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)
    del annotated["segments"][0]["animations"][0]["research_generation_v2"]["event_id"]

    with pytest.raises(ValueError, match="missing event_id"):
        build_storyboard_v2(annotated, case_id="case_1")
    with pytest.raises(ValueError, match="missing event_id"):
        build_timed_storyboard_v2(annotated, case_id="case_1", timing_source="measured")


def test_storyboard_v2_rejects_duplicate_event_ids() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Motion", "description": "Motion has direction."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Motion has direction.",
                "audio_duration_sec": 3.0,
                "elements": [{"id": "element", "type": "image"}],
                "animations": [
                    {"target": "element", "action": "show"},
                    {"target": "element", "action": "emphasize"},
                ],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion has direction.")
    script = build_script_v2(["Motion has direction."], case_id="case_1", lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)
    first_event_id = annotated["segments"][0]["animations"][0]["research_generation_v2"][
        "event_id"
    ]
    annotated["segments"][0]["animations"][1]["research_generation_v2"][
        "event_id"
    ] = first_event_id

    with pytest.raises(ValueError, match="duplicate event_id"):
        build_storyboard_v2(annotated, case_id="case_1")
    with pytest.raises(ValueError, match="duplicate event_id"):
        build_timed_storyboard_v2(annotated, case_id="case_1", timing_source="measured")


def test_storyboard_v2_rejects_non_object_animation() -> None:
    storyboard = {
        "segments": [
            {
                "id": "1",
                "research_generation_v2": {"segment_id": "case-1-seg-001"},
                "elements": [
                    {
                        "id": "element",
                        "type": "image",
                        "research_generation_v2": {"element_id": "case-1-el-101"},
                    }
                ],
                "animations": [None],
            }
        ]
    }

    with pytest.raises(ValueError, match="animation 1 must be an object"):
        build_storyboard_v2(storyboard, case_id="case_1")
    with pytest.raises(ValueError, match="animation 1 must be an object"):
        build_timed_storyboard_v2(storyboard, case_id="case_1", timing_source="measured")


def test_render_evidence_does_not_claim_runtime_as_visibility(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not-a-real-video")
    output = write_render_evidence(
        video_path=video,
        case_id="case_1",
        output_path=tmp_path / "evidence.json",
        runtime_trace={"events": [{"event_id": "evt-1", "status": "executed", "actual_ms": 1000}]},
        planned_events=[{"id": "evt-1", "target_element_id": "el-1"}],
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["observations"][0]["status"] == "not_reviewed"
    assert value["observations"][0]["observed_visible_start_sec"] is None
