import json

import pytest

from textbook2video.pipeline.artifact_integrity import verify_render_bundle


def _write_storyboard(path, durations):
    path.write_text(json.dumps({"segments": [
        {"id": index, "audio_duration_sec": value}
        for index, value in enumerate(durations, 1)
    ]}), encoding="utf-8")


def test_verify_render_bundle_accepts_matching_durations(tmp_path):
    storyboard = tmp_path / "lesson_timed_storyboard.json"
    html = tmp_path / "lesson.html"
    _write_storyboard(storyboard, [2.2, 3.1])
    html.write_text("<script>var slideDurations = [2200, 3100];</script>", encoding="utf-8")

    report = verify_render_bundle(storyboard, html)

    assert report["slide_count"] == 2
    assert report["total_duration_sec"] == 5.3


def test_verify_render_bundle_rejects_stale_html(tmp_path):
    storyboard = tmp_path / "lesson_timed_storyboard.json"
    html = tmp_path / "lesson.html"
    _write_storyboard(storyboard, [2.2, 3.1])
    html.write_text("<script>var slideDurations = [5000, 5000];</script>", encoding="utf-8")

    with pytest.raises(ValueError, match="逐页时长不一致"):
        verify_render_bundle(storyboard, html)
