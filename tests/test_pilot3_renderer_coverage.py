import json
from pathlib import Path

from textbook2video.template_renderer import render_slide


REPO_ROOT = Path(__file__).resolve().parents[1]


def _storyboard(case_id: str) -> dict:
    path = REPO_ROOT / "datasets" / "pilot3" / "artifacts" / case_id / "storyboard.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_lesson_008_and_011_are_fully_deterministic_renderable():
    for case_id in ("lesson_008", "lesson_011"):
        storyboard = _storyboard(case_id)
        assert storyboard["segments"]
        for index, segment in enumerate(storyboard["segments"]):
            available = {
                f'{segment["id"]}:{element["id"]}'
                for element in segment.get("elements", [])
                if element.get("type") == "image"
            }
            html = render_slide(segment, index, available)
            assert html is not None, f"{case_id} slide {segment['id']} fell back"


def test_closing_renderer_keeps_subheading_animation_target():
    segment = _storyboard("lesson_011")["segments"][-1]
    html = render_slide(segment, len(_storyboard("lesson_011")["segments"]) - 1, {
        f'{segment["id"]}:{element["id"]}'
        for element in segment.get("elements", [])
        if element.get("type") == "image"
    })
    assert html is not None
    assert 'data-anim-id="e2"' in html
