import json

from textbook2video.pipeline.preview import (
    build_preview_html,
    preview_path_for,
    write_preview,
)


def _storyboard():
    return {
        "lesson_title": "Algorithm",
        "segments": [
            {
                "id": 1,
                "visual_type": "definition",
                "render_mode": "template",
                "knowledge_point_ids": ["kp1"],
                "narration": "Algorithm means clear steps.",
                "audio_duration_sec": 5.0,
                "elements": [
                    {"id": "e1", "type": "heading", "text": "Algorithm"},
                    {"id": "e2", "type": "text", "text": "clear steps"},
                ],
                "animations": [
                    {"target": "e1", "effect": "fadeIn", "trigger_at_sec": 0.0},
                    {"target": "e2", "effect": "fadeInUp", "trigger_at_sec": 1.2},
                ],
            }
        ],
        "metadata": {"total_slides": 1},
    }


def test_build_preview_html_embeds_storyboard_data():
    html = build_preview_html(_storyboard(), source_path="lesson_storyboard.json")

    assert "<!doctype html>" in html
    assert "Algorithm means clear steps." in html
    assert "trigger_at_sec" in html
    assert "lesson_storyboard.json" in html
    assert "slideList" in html


def test_write_preview_uses_default_sibling_path(tmp_path):
    sb_path = tmp_path / "lesson4_storyboard.json"
    sb_path.write_text(json.dumps(_storyboard()), encoding="utf-8")

    out = write_preview(sb_path)

    assert out == tmp_path / "lesson4_preview.html"
    assert out == preview_path_for(sb_path)
    assert "Algorithm" in out.read_text(encoding="utf-8")


def test_write_preview_rejects_non_storyboard_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"segments": "nope"}), encoding="utf-8")

    try:
        write_preview(bad)
    except ValueError as exc:
        assert "segments" in str(exc)
    else:
        raise AssertionError("write_preview should reject invalid storyboard JSON")
