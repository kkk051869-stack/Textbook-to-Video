import json
from pathlib import Path

from textbook2video.research.dynamic_planner import build_event_schedule_report
from textbook2video.research.event_evaluator import evaluate_events
from textbook2video.research.semantic_binding import build_binding_report

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def test_unresolved_target_survives_schedule_to_runtime_evaluation() -> None:
    script = _load("script_v2.json")
    storyboard = _load("storyboard.json")
    schedule = build_event_schedule_report(
        script,
        storyboard,
        _load("storyboard_timed.json"),
        build_binding_report(script, storyboard),
    )
    trace = _load("animation_trace.json")
    trace["events"][0]["target_resolved"] = False
    trace["events"][0]["executed"] = False
    trace["events"][0]["status"] = "skipped"
    trace["events"][0]["actual"] = None
    trace["events"][0]["error_code"] = "TARGET_MISSING"

    report = evaluate_events(
        schedule,
        compiled_timeline=_load("compiled_timeline.json"),
        runtime_trace=trace,
        render_evidence=_load("render_evidence.json"),
    )
    first = report["events"][0]
    assert first["target_resolved"] is False
    assert "unresolved_target" in first["outcomes"]
    assert "missing_runtime_event" in first["outcomes"]
    assert report["metrics"]["missing_runtime_count"] == 1
