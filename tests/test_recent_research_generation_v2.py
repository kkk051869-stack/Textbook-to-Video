import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from textbook2video.animation_gen import build_slide_timelines
from textbook2video.research.proposition_schema import (
    annotate_storyboard_v2,
    build_compiled_timeline_v2,
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


def test_storyboard_v2_deduplicates_repeated_knowledge_links() -> None:
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
                "narration": "Motion has direction. Motion has speed.",
                "elements": [{"id": "e1", "type": "diagram"}],
                "animations": [{"target": "e1", "action": "show"}],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion.")
    script = build_script_v2(
        ["Motion has direction. Motion has speed."],
        case_id="case_1",
        lesson_plan_v2=plan,
    )
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    projected = build_storyboard_v2(annotated, case_id="case_1")
    element = projected["segments"][0]["elements"][0]
    expected_kp = plan["knowledge_points"][0]["propositions"][0]["id"]
    assert element["knowledge_proposition_ids"] == [expected_kp]
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(projected)


def test_appended_storyboard_pages_get_unique_ids_and_explicit_local_links() -> None:
    legacy_plan = {
        "lesson_title": "Flows",
        "knowledge_points": [
            {"id": "kp1", "name": "Flow basics", "description": "Flows map distributions."},
            {"id": "kp2", "name": "Sampling complexity", "description": "Sampling is linear."},
            {"id": "kp3", "name": "SCF split", "description": "SCF splits channels."},
        ],
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="flows", raw_text="Source text.")
    script = build_script_v2(["Base narration."], case_id="flows", lesson_plan_v2=plan)
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "Base narration.",
                "elements": [{"id": "e1", "type": "text"}],
                "animations": [{"target": "e1", "effect": "fadeInUp", "trigger_at_sec": 0}],
            },
            {
                "id": 2,
                "pedagogical_role": "activity",
                "knowledge_point_ids": ["kp1"],
                "narration": "Think about flow basics.",
                "elements": [{"id": "e1", "type": "activity_step", "steps": ["Think."]}],
                "animations": [{"target": "e1", "effect": "fadeInUp"}],
            },
            {
                "id": 3,
                "pedagogical_role": "knowledge_check",
                "narration": "What does SCF split do?",
                "elements": [{
                    "id": "e1",
                    "type": "quiz_card",
                    "questions": [{
                        "question": "What does SCF split do?",
                        "knowledge_point_ids": ["kp3"],
                    }],
                }],
                "animations": [{"target": "e1", "effect": "fadeInUp"}],
            },
            {
                "id": 4,
                "pedagogical_role": "lesson_summary",
                "knowledge_point_ids": ["kp1", "kp2"],
                "narration": "Flow basics; Sampling complexity",
                "elements": [{
                    "id": "e1",
                    "type": "icon_group",
                    "items": ["Flow basics", "Sampling complexity"],
                }],
                "animations": [{"target": "e1", "effect": "fadeInUp"}],
            },
        ]
    }

    annotated = annotate_storyboard_v2(storyboard, script, plan)
    annotate_storyboard_v2(annotated, script, plan)  # reruns must keep stable IDs/links

    page_relations = [page["research_generation_v2"] for page in annotated["segments"]]
    page_ids = [relation["segment_id"] for relation in page_relations]
    assert page_ids == ["flows-seg-001", "flows-seg-002", "flows-seg-003", "flows-seg-004"]
    assert len(page_ids) == len(set(page_ids))
    assert page_relations[0]["narration_proposition_ids"] == [
        script["segments"][0]["narration_propositions"][0]["id"]
    ]
    assert page_relations[1]["mapping_status"] == "unmapped"
    assert page_relations[1]["mapping_basis"] == "no_item_level_knowledge_link"
    assert page_relations[2]["mapping_basis"] == "item_level"
    assert page_relations[3]["mapping_basis"] == "item_level"
    first_script_narration_id = script["segments"][0]["narration_propositions"][0]["id"]
    assert all(
        first_script_narration_id not in relation["narration_proposition_ids"]
        for relation in page_relations[1:]
    )
    assert len(script["segments"]) == 3
    assert [item["id"] for item in script["segments"]] == [page_ids[0], page_ids[2], page_ids[3]]

    projected = build_storyboard_v2(annotated, case_id="flows")
    assert [segment["legacy_segment_id"] for segment in projected["segments"]] == [1, 3, 4]
    assert annotated["metadata"]["research_generation_v2"]["projection_exclusions"] == [
        {
            "segment_id": "flows-seg-002",
            "legacy_segment_id": 2,
            "reason": "no_item_level_knowledge_link",
        }
    ]
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    validator.validate(script)
    validator.validate(projected)

    # Untimed appendix animations are valid pre-TTS metadata, but they cannot
    # be emitted as timed events with fabricated zero-second triggers.
    with pytest.raises(ValueError, match="requires post-TTS timing"):
        build_timed_storyboard_v2(annotated, case_id="flows", timing_source="measured")


def test_unmapped_reflection_page_is_explicit_and_not_linked_to_previous_script() -> None:
    legacy_plan = {
        "lesson_title": "Flows",
        "knowledge_points": [{
            "id": "kp1", "name": "Flow basics", "description": "Flows map distributions."
        }],
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="flows", raw_text="Source text.")
    script = build_script_v2(["Base narration."], case_id="flows", lesson_plan_v2=plan)
    storyboard = {
        "segments": [
            {"id": 1, "narration": "Base narration.", "elements": [{"id": "e1", "type": "text"}],
             "animations": [{"target": "e1", "effect": "fadeInUp"}]},
            {"id": 2, "pedagogical_role": "reflection_activity",
             "knowledge_point_ids": ["kp1"], "narration": "Unlinked activity.",
             "elements": [{"id": "e1", "type": "activity_step", "steps": ["Unlinked."]}],
             "animations": [{"target": "e1", "effect": "fadeInUp"}]},
        ]
    }
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    relation = annotated["segments"][1]["research_generation_v2"]
    assert relation["segment_id"] == "flows-seg-002"
    assert relation["mapping_status"] == "unmapped"
    assert relation["mapping_basis"] == "no_item_level_knowledge_link"
    assert relation["narration_proposition_ids"] == []
    assert len(script["segments"]) == 1
    projected = build_storyboard_v2(annotated, case_id="flows")
    assert [segment["legacy_segment_id"] for segment in projected["segments"]] == [1]
    assert annotated["metadata"]["research_generation_v2"]["projection_exclusions"] == [
        {
            "segment_id": "flows-seg-002",
            "legacy_segment_id": 2,
            "reason": "no_item_level_knowledge_link",
        }
    ]
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(projected)


def test_v2_events_follow_renderer_timeline_actions_and_times() -> None:
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
                "audio_duration_sec": 12.0,
                "elements": [
                    {"id": "left", "type": "text"},
                    {"id": "right", "type": "text"},
                ],
                "timeline": [
                    {
                        "target": "left,right",
                        "action": "highlight",
                        "at_sec": 1.25,
                        "stagger": True,
                    }
                ],
                "animations": [
                    {"target": "left", "effect": "fadeIn", "trigger_at_sec": 8.0},
                    {"target": "right", "effect": "pulse", "trigger_at_sec": 9.0},
                ],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="case_1", raw_text="Motion.")
    script = build_script_v2(
        ["Motion has direction."], case_id="case_1", lesson_plan_v2=plan
    )
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    projected = build_storyboard_v2(annotated, case_id="case_1")
    timed = build_timed_storyboard_v2(
        annotated, case_id="case_1", timing_source="legacy"
    )
    compiled = build_compiled_timeline_v2(annotated, case_id="case_1")
    events = projected["segments"][0]["events"]
    scheduled = timed["segments"][0]["scheduled_events"]
    compiled_events = compiled["segments"][0]["events"]

    assert [event["action"] for event in events] == ["highlight", "highlight"]
    assert [event["action"] for event in scheduled] == ["highlight", "highlight"]
    assert [event["action"] for event in compiled_events] == ["highlight", "highlight"]
    assert [event["trigger_at_sec"] for event in scheduled] == [1.25, 1.45]
    assert [event["start_ms"] for event in compiled_events] == [1250, 1450]
    assert [event["target_element_id"] for event in scheduled] == [
        event["target_element_id"] for event in compiled_events
    ]
    assert [event["event_id"] for event in scheduled] == [
        event["id"] for event in events
    ]
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    for artifact in (projected, timed, compiled):
        validator.validate(artifact)


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


def test_v2_projects_native_step_and_table_row_targets_without_changing_events() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Process", "description": "A process has stages."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "Stage two is applied.",
                "audio_duration_sec": 5.0,
                "elements": [
                    {
                        "id": "flow",
                        "type": "flow_step",
                        "steps": [
                            {"title": "Stage one", "content": "Prepare."},
                            {"title": "Stage two", "content": "Apply."},
                        ],
                    }
                ],
                "timeline": [
                    {"target": "flow--step-1", "action": "focus", "at_sec": 1.25}
                ],
            },
            {
                "id": "2",
                "narration": "This row contains the result.",
                "audio_duration_sec": 5.0,
                "elements": [
                    {
                        "id": "table",
                        "type": "table",
                        "headers": ["Stage", "Result"],
                        "rows": [["Finish", "Complete"]],
                    }
                ],
                "timeline": [
                    {"target": "table--row-0", "action": "highlight", "at_sec": 2.5}
                ],
            },
            {
                "id": "3",
                "narration": "The original image remains visible.",
                "audio_duration_sec": 5.0,
                "elements": [{"id": "image", "type": "image"}],
                "timeline": [{"target": "image", "action": "show", "at_sec": 0.5}],
            },
        ]
    }
    original_compiled = [
        build_slide_timelines([segment])[0] for segment in storyboard["segments"]
    ]
    plan = build_lesson_plan_v2(
        legacy_plan, case_id="native-targets", raw_text="A process has stages."
    )
    script = build_script_v2(
        [segment["narration"] for segment in storyboard["segments"]],
        case_id="native-targets",
        lesson_plan_v2=plan,
    )
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    projected = build_storyboard_v2(annotated, case_id="native-targets")
    timed = build_timed_storyboard_v2(
        annotated, case_id="native-targets", timing_source="legacy"
    )
    compiled = build_compiled_timeline_v2(annotated, case_id="native-targets")

    expected_targets = ["flow--step-1", "table--row-0", "image"]
    parent_legacy_ids = ["flow", "table", "image"]
    for index, legacy_target in enumerate(expected_targets):
        projected_segment = projected["segments"][index]
        event = projected_segment["events"][0]
        scheduled = timed["segments"][index]["scheduled_events"][0]
        compiled_event = compiled["segments"][index]["events"][0]
        source_event = original_compiled[index][0]
        assert source_event["target"] == legacy_target
        assert event["action"] == source_event["action"]
        assert compiled_event["action"] == source_event["action"]
        assert compiled_event["start_ms"] == source_event["start_ms"]
        assert compiled_event["duration_ms"] == source_event["duration_ms"]
        assert scheduled["trigger_at_sec"] == source_event["start_ms"] / 1000
        assert event["target_element_id"] == scheduled["target_element_id"]
        assert event["target_element_id"] == compiled_event["target_element_id"]

        parent = next(
            element
            for element in projected_segment["elements"]
            if element["legacy_id"] == parent_legacy_ids[index]
        )
        if index < 2:
            child = next(
                element
                for element in projected_segment["elements"]
                if element["legacy_id"] == legacy_target
            )
            assert child["id"] == event["target_element_id"]
            assert child["id"] != parent["id"]
            assert child["payload"]["native_target_id"] == legacy_target
            assert child["payload"]["parent_element_id"] == parent["id"]
            assert child["payload"]["parent_legacy_id"] == parent["legacy_id"]
        else:
            assert event["target_element_id"] == parent["id"]
            assert len(projected_segment["elements"]) == 1

    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "research_generation_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    for artifact in (projected, timed, compiled):
        validator.validate(artifact)


def test_v2_rejects_nonexistent_native_child_target() -> None:
    legacy_plan = {
        "lesson_title": "Test",
        "knowledge_points": [
            {"id": "kp1", "name": "Process", "description": "A process has stages."}
        ],
    }
    storyboard = {
        "segments": [
            {
                "id": "1",
                "narration": "A process has stages.",
                "audio_duration_sec": 5.0,
                "elements": [
                    {
                        "id": "flow",
                        "type": "flow_step",
                        "steps": [{"title": "Only stage", "content": "Apply."}],
                    }
                ],
                "timeline": [
                    {"target": "flow--step-2", "action": "focus", "at_sec": 1.0}
                ],
            }
        ]
    }
    plan = build_lesson_plan_v2(legacy_plan, case_id="invalid-native", raw_text="A process.")
    script = build_script_v2(
        [storyboard["segments"][0]["narration"]],
        case_id="invalid-native",
        lesson_plan_v2=plan,
    )
    annotated = annotate_storyboard_v2(storyboard, script, plan)

    with pytest.raises(ValueError, match="does not resolve"):
        build_storyboard_v2(annotated, case_id="invalid-native")
    with pytest.raises(ValueError, match="does not resolve"):
        build_timed_storyboard_v2(
            annotated, case_id="invalid-native", timing_source="measured"
        )
    with pytest.raises(ValueError, match="does not resolve"):
        build_compiled_timeline_v2(annotated, case_id="invalid-native")


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
                "research_generation_v2": {
                    "segment_id": "case-1-seg-001",
                    "narration_proposition_ids": ["case-nprop-001"],
                },
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
