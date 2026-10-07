import json
from pathlib import Path

from textbook2video.research.presentation_compiler import compile_presentation_candidate
from textbook2video.research.presentation_render import (
    build_candidate_html,
    check_and_repair_layout,
)

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def _candidate() -> dict:
    return compile_presentation_candidate(
        _load("script_v2.json"),
        _load("storyboard.json"),
        _load("storyboard_timed.json"),
        {
            "case_id": "mock_lesson_001",
            "visuals": [
                {
                    "segment_id": "mock-lesson-001-seg-001",
                    "narration_proposition_id": "mock-lesson-001-nprop-002",
                    "event_id": "mock-lesson-001-seg-001-evt-b01",
                    "element": {
                        "id": "mock-lesson-001-seg-001-el-b01",
                        "type": "highlight_box",
                        "payload": {"description": "mock supporting visual"},
                    },
                }
            ],
        },
    )


def test_candidate_html_keeps_planned_event_in_existing_runtime() -> None:
    html = build_candidate_html(_candidate())

    assert "SlideController" in html
    assert "slideTimelines" in html
    assert "mock-lesson-001-seg-001-el-b01" in html


def test_layout_repair_stops_when_state_would_repeat(tmp_path: Path) -> None:
    html_path = tmp_path / "candidate.html"
    html_path.write_text("<html><head></head><body></body></html>", encoding="utf-8")
    calls: list[Path] = []

    def always_failing_runner(_: Path, report_path: Path) -> dict:
        calls.append(report_path)
        report = {"staticRisks": [{"kind": "overflow", "severity": "error"}]}
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report

    result = check_and_repair_layout(
        html_path, tmp_path / "layout", max_attempts=3, layout_runner=always_failing_runner
    )

    assert len(calls) == 2
    assert result[0]["repair_applied"] == "overflow_hotfix_v0.1"
    assert result[-1]["stopped_reason"] == "repair_state_repeated"
    assert "candidate-local bounded repair" in html_path.read_text(encoding="utf-8")
