import json

import pytest

from textbook2video.pipeline import artifact_integrity
from textbook2video.pipeline.artifact_integrity import verify_render_bundle


def _write_storyboard(path, durations):
    path.write_text(
        json.dumps(
            {
                "segments": [
                    {"id": index, "audio_duration_sec": value}
                    for index, value in enumerate(durations, 1)
                ]
            }
        ),
        encoding="utf-8",
    )


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


@pytest.mark.parametrize("measured", [(3.0, 3.0), (2.0, 4.0)])
def test_audio_pages_cannot_hide_swapped_durations_in_equal_total(tmp_path, monkeypatch, measured):
    from textbook2video.pipeline import compose

    storyboard, html = tmp_path / "board.json", tmp_path / "lesson.html"
    _write_storyboard(storyboard, [2.0, 4.0])
    html.write_text("<script>var slideDurations = [2000, 4000];</script>", encoding="utf-8")
    files = [tmp_path / "segment_001.mp3", tmp_path / "segment_002.mp3"]
    monkeypatch.setattr(compose, "find_segment_audio", lambda path: files)
    monkeypatch.setattr(
        artifact_integrity, "media_duration_seconds", lambda path: measured[files.index(path)]
    )
    if measured == (3.0, 3.0):
        with pytest.raises(ValueError, match="第 1 页音频"):
            verify_render_bundle(storyboard, html, audio_dir=tmp_path)
    else:
        report = verify_render_bundle(storyboard, html, audio_dir=tmp_path)
        assert report["audio_duration_sec_by_page"] == list(measured)
