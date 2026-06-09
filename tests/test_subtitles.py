import json

import pytest

from textbook2video.pipeline.subtitles import (
    build_subtitle_cues,
    format_srt_timestamp,
    generate_srt,
    split_narration,
)


def test_format_srt_timestamp():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(65.432) == "00:01:05,432"
    assert format_srt_timestamp(3661.005) == "01:01:01,005"


def test_split_narration_splits_sentences_and_long_phrases():
    chunks = split_narration(
        "同学们好。今天我们学习数字化转型，它不是简单使用工具，而是组织能力重构。",
        max_chars=12,
    )

    assert chunks[0] == "同学们好。"
    assert len(chunks) >= 3
    assert all(chunk.strip() for chunk in chunks)


def test_build_subtitle_cues_respects_segment_boundaries():
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "第一句。第二句更长。",
                "audio_duration_sec": 4.0,
            },
            {
                "id": 2,
                "narration": "第三句。",
                "audio_duration_sec": 2.0,
            },
        ]
    }

    cues = build_subtitle_cues(storyboard, max_chars=20)

    assert cues[0].start_sec == 0
    assert cues[-1].end_sec == pytest.approx(6.0)
    assert any(cue.start_sec == pytest.approx(4.0) for cue in cues)


def test_generate_srt_writes_file(tmp_path):
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "# 标题页\n欢迎学习。",
                "audio_duration_sec": 3.0,
            }
        ]
    }
    sb_path = tmp_path / "lesson_storyboard.json"
    sb_path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")

    out = generate_srt(sb_path, tmp_path / "lesson.srt")
    text = out.read_text(encoding="utf-8")

    assert "00:00:00,000 --> 00:00:03,000" in text
    assert "标题页 欢迎学习。" in text
