import json
from pathlib import Path

from textbook2video.research.dynamic_planner import build_event_schedule_report
from textbook2video.research.semantic_binding import build_binding_report

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def test_local_baselines_declare_that_no_external_model_was_used() -> None:
    script = _load("script_v2.json")
    storyboard = _load("storyboard.json")
    binding = build_binding_report(script, storyboard)
    schedule = build_event_schedule_report(
        script,
        storyboard,
        _load("storyboard_timed.json"),
        binding,
    )
    assert binding["method"]["name"] == "lexical_jaccard"
    assert binding["method"]["uses_external_model"] is False
    assert schedule["uses_external_model"] is False
