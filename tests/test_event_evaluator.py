import json
from pathlib import Path

from jsonschema import Draft202012Validator

from textbook2video.research.dynamic_planner import build_event_schedule_report
from textbook2video.research.event_evaluator import evaluate_events
from textbook2video.research.semantic_binding import build_binding_report

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def _schedule() -> dict:
    script = _load("script_v2.json")
    storyboard = _load("storyboard.json")
    binding = build_binding_report(script, storyboard)
    return build_event_schedule_report(script, storyboard, _load("storyboard_timed.json"), binding)


def test_four_evidence_layers_remain_separate_and_schema_valid() -> None:
    report = evaluate_events(
        _schedule(),
        compiled_timeline=_load("compiled_timeline.json"),
        runtime_trace=_load("animation_trace.json"),
        render_evidence=_load("render_evidence.json"),
    )
    schema = json.loads(
        (ROOT / "contracts" / "event_evaluation.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(report)

    first, second = report["events"]
    assert first["planned_start_sec"] == 0.0
    assert first["compiled_start_sec"] == 0.0
    assert first["runtime_start_sec"] == 0.042
    assert first["rendered_visible_start_sec"] == 0.08
    assert second["compiled_to_runtime_delta_sec"] == 0.058
    assert report["metrics"]["planned_to_compiled_mae_sec"] == 0.0
    assert report["metrics"]["compiled_to_runtime_mae_sec"] == 0.05
    assert report["metrics"]["render_coverage"] == 1.0
    assert report["claims"] == {
        "runtime_execution_evaluated": True,
        "rendered_visibility_evaluated": True,
        "semantic_timing_evaluated": False,
    }


def test_semantic_early_late_requires_explicit_gold_window() -> None:
    schedule = _schedule()
    event_ids = [item["event_id"] for item in schedule["events"]]
    gold = {
        "events": [
            {
                "event_id": event_ids[0],
                "acceptable_start_min_sec": 0.0,
                "acceptable_start_max_sec": 0.1,
                "acceptable_visible_start_sec": 0.0,
                "acceptable_visible_end_sec": 8.0,
                "expected_target_element_ids": [schedule["events"][0]["target_element_id"]],
            },
            {
                "event_id": event_ids[1],
                "acceptable_start_min_sec": 4.2,
                "acceptable_start_max_sec": 4.3,
                "acceptable_visible_start_sec": 4.2,
                "acceptable_visible_end_sec": 8.0,
                "expected_target_element_ids": [schedule["events"][1]["target_element_id"]],
            },
        ]
    }
    report = evaluate_events(
        schedule,
        compiled_timeline=_load("compiled_timeline.json"),
        runtime_trace=_load("animation_trace.json"),
        render_evidence=_load("render_evidence.json"),
        gold_events=gold,
    )
    assert report["events"][0]["semantic_temporal_label"] == "correct"
    assert report["events"][1]["semantic_temporal_label"] == "late"
    assert report["events"][1]["onset_error_sec"] == 0.01
    assert report["metrics"]["semantic_evaluable_count"] == 2
    assert report["metrics"]["semantic_correct_rate"] == 0.5
    assert report["claims"]["semantic_timing_evaluated"] is True


def test_missing_runtime_and_render_evidence_are_explicit() -> None:
    report = evaluate_events(_schedule(), compiled_timeline=_load("compiled_timeline.json"))
    assert report["metrics"]["runtime_coverage"] == 0.0
    assert report["metrics"]["render_coverage"] == 0.0
    assert report["metrics"]["missing_runtime_count"] == 2
    assert report["metrics"]["render_unobservable_count"] == 2
    assert report["claims"]["runtime_execution_evaluated"] is False
    assert report["claims"]["rendered_visibility_evaluated"] is False


def test_wrong_runtime_target_is_not_hidden_by_execution_success() -> None:
    trace = _load("animation_trace.json")
    trace["events"][0]["target"] = "wrong-element"
    report = evaluate_events(
        _schedule(),
        compiled_timeline=_load("compiled_timeline.json"),
        runtime_trace=trace,
        render_evidence=_load("render_evidence.json"),
    )
    assert report["events"][0]["target_match"] is False
    assert "wrong_target" in report["events"][0]["outcomes"]
    assert report["metrics"]["wrong_target_count"] == 1
