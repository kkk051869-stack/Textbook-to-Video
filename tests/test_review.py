import json

import pytest

from textbook2video.pipeline.review import (
    approve_storyboard,
    ensure_review_approved,
    review_path_for,
    write_review_packet,
)


def _storyboard():
    return {
        "lesson_title": "Demo",
        "segments": [
            {
                "id": 1,
                "visual_type": "definition",
                "narration": "Explain the concept.",
                "elements": [
                    {"id": "e1", "type": "heading", "text": "Concept"},
                    {"id": "e2", "type": "text", "text": "Explanation"},
                ],
                "animations": [],
            }
        ],
        "metadata": {"total_slides": 1},
    }


def test_write_review_packet_creates_markdown_and_preview(tmp_path):
    sb = tmp_path / "lesson_storyboard.json"
    sb.write_text(json.dumps(_storyboard()), encoding="utf-8")

    out = write_review_packet(sb)

    assert out == review_path_for(sb)
    text = out.read_text(encoding="utf-8")
    assert "Storyboard Review" in text
    assert "Checklist" in text
    assert "t2v review" in text
    assert (tmp_path / "lesson_preview.html").exists()


def test_approve_storyboard_marks_metadata(tmp_path):
    sb = tmp_path / "lesson_storyboard.json"
    sb.write_text(json.dumps(_storyboard()), encoding="utf-8")

    approve_storyboard(sb, reviewer="tester", note="looks good")

    data = json.loads(sb.read_text(encoding="utf-8"))
    review = data["metadata"]["human_review"]
    assert review["status"] == "approved"
    assert review["reviewer"] == "tester"
    assert review["note"] == "looks good"
    ensure_review_approved(sb)


def test_ensure_review_approved_rejects_pending_storyboard(tmp_path):
    sb = tmp_path / "lesson_storyboard.json"
    sb.write_text(json.dumps(_storyboard()), encoding="utf-8")

    with pytest.raises(RuntimeError, match="human-approved"):
        ensure_review_approved(sb)
