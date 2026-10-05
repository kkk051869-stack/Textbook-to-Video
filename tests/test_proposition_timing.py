import json
from pathlib import Path

from textbook2video.research.dynamic_planner import build_event_schedule_report
from textbook2video.research.semantic_binding import build_binding_report

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def test_mock_schedule_reuses_authoritative_timed_storyboard() -> None:
    script = _load("script_v2.json")
    storyboard = _load("storyboard.json")
    timed = _load("storyboard_timed.json")
    bindings = build_binding_report(script, storyboard)
    report = build_event_schedule_report(script, storyboard, timed, bindings)

    assert report["uses_external_model"] is False
    assert report["metrics"] == {
        "assignment_count": 2,
        "unique_event_count": 2,
        "timed_event_count": 2,
        "timing_coverage": 1.0,
    }
    assert [event["planned_start_sec"] for event in report["events"]] == [0.0, 4.2]
    assert all(event["schedule_authority"] == "storyboard_timed" for event in report["events"])


def test_missing_canonical_time_uses_explicit_span_ratio_fallback() -> None:
    script = _load("script_v2.json")
    storyboard = _load("storyboard.json")
    timed = _load("storyboard_timed.json")
    timed["segments"][0]["scheduled_events"] = []
    bindings = build_binding_report(script, storyboard)
    report = build_event_schedule_report(script, storyboard, timed, bindings)

    by_id = {event["event_id"]: event for event in report["events"]}
    assert by_id["mock-lesson-001-seg-001-evt-001"]["planned_start_sec"] == 0.0
    assert by_id["mock-lesson-001-seg-001-evt-002"]["planned_start_sec"] == 4.571429
    assert all(event["timing_source"] == "narration_span_ratio" for event in report["events"])


def test_binding_without_visual_event_is_a_failure_not_an_invented_event() -> None:
    script = _load("script_v2.json")
    storyboard = _load("storyboard.json")
    timed = _load("storyboard_timed.json")
    storyboard["segments"][0]["events"] = storyboard["segments"][0]["events"][:1]
    bindings = build_binding_report(script, storyboard)
    report = build_event_schedule_report(script, storyboard, timed, bindings)

    assert report["metrics"]["unique_event_count"] == 1
    assert any(item["type"] == "missing_visual_event" for item in report["failures"])
