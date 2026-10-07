import json
from pathlib import Path

from textbook2video.research.presentation_compiler import (
    compile_presentation_candidate,
    optimize_layout,
    write_presentation_candidate,
)
from textbook2video.template_renderer import render_slide

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def _visual_package() -> dict:
    return {
        "case_id": "mock_lesson_001",
        "visuals": [
            {
                "segment_id": "mock-lesson-001-seg-001",
                "narration_proposition_id": "mock-lesson-001-nprop-002",
                "event_id": "mock-lesson-001-seg-001-evt-b01",
                "element": {
                    "id": "mock-lesson-001-seg-001-el-b01",
                    "type": "highlight_box",
                    "semantic_role": "explain",
                    "acquisition": "retrieve",
                    "source_refs": ["mock-lesson-001-src-p0002"],
                    "knowledge_proposition_ids": ["mock-lesson-001-kprop-002"],
                    "payload": {"description": "??????????"},
                },
            }
        ],
    }


def test_compile_candidate_preserves_baseline_and_adds_planned_event() -> None:
    storyboard = _load("storyboard.json")
    result = compile_presentation_candidate(
        _load("script_v2.json"), storyboard, _load("storyboard_timed.json"), _visual_package()
    )

    assert len(storyboard["segments"][0]["elements"]) == 2
    candidate = result["candidate_storyboard"]["segments"][0]
    assert candidate["elements"][-1]["id"] == "mock-lesson-001-seg-001-el-b01"
    scheduled = result["candidate_timed_storyboard"]["segments"][0]["scheduled_events"][-1]
    assert scheduled["event_id"] == "mock-lesson-001-seg-001-evt-b01"
    assert scheduled["timing_source"] == "semantic"
    assert result["baseline_mutated"] is False
    assert result["time_claim"] == "planned_event_times_only_not_rendered_visibility"


def test_renderer_segments_are_consumable_by_template_renderer() -> None:
    result = compile_presentation_candidate(
        _load("script_v2.json"),
        _load("storyboard.json"),
        _load("storyboard_timed.json"),
        _visual_package(),
    )

    html = render_slide(result["renderer_segments"][0])

    assert html is not None
    assert 'data-anim-id="mock-lesson-001-seg-001-el-b01"' in html


def test_rejects_unknown_proposition_without_creating_event() -> None:
    package = _visual_package()
    package["visuals"][0]["narration_proposition_id"] = "missing"
    result = compile_presentation_candidate(
        _load("script_v2.json"), _load("storyboard.json"), _load("storyboard_timed.json"), package
    )

    assert result["failures"] == [
        {
            "type": "unknown_narration_proposition",
            "segment_id": "mock-lesson-001-seg-001",
            "narration_proposition_id": "missing",
        }
    ]
    assert len(result["candidate_storyboard"]["segments"][0]["events"]) == 2


def test_layout_is_bounded_and_has_no_loop() -> None:
    result = optimize_layout(
        [
            {"id": "one", "type": "highlight_box"},
            {"id": "two", "type": "image"},
            {"id": "three", "type": "highlight_box"},
        ],
        max_passes=2,
    )

    assert result.status == "converged"
    assert result.passes == 1
    assert result.cycle_detected is False
    assert [item["row"] for item in result.placements] == [0, 1, 2]


def test_candidate_writer_keeps_baseline_files_separate(tmp_path: Path) -> None:
    candidate = compile_presentation_candidate(
        _load("script_v2.json"),
        _load("storyboard.json"),
        _load("storyboard_timed.json"),
        _visual_package(),
    )

    output = write_presentation_candidate(candidate, tmp_path / "candidate.json")

    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["baseline_mutated"] is False
