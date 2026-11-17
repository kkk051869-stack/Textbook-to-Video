import json

import pytest

from textbook2video.pipeline.subtitles import (
    SentenceSplitter,
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


def test_sentence_splitter_exposes_stable_sentence_boundaries():
    assert SentenceSplitter().split("第一句。第二句！") == ["第一句。", "第二句！"]


def test_build_subtitle_cues_prefers_measured_sentence_cues():
    storyboard = {
        "segments": [
            {"id": 1, "narration": "估算文本。", "audio_duration_sec": 9.0},
        ]
    }
    measured = {
        "segments": [
            {
                "segment_id": "1",
                "cues": [
                    {"text": "真实第一句。", "start_sec": 0.25, "end_sec": 1.5},
                    {"text": "真实第二句。", "start_sec": 1.5, "end_sec": 3.0},
                ],
            }
        ]
    }

    cues = build_subtitle_cues(storyboard, sentence_cues=measured)

    assert [cue.text for cue in cues] == ["真实第一句。", "真实第二句。"]
    assert cues[0].start_sec == 0.25
    assert cues[-1].end_sec == 3.0


def test_measured_cues_remain_unsplit_for_semantic_timing_by_default():
    storyboard = {
        "segments": [
            {"id": 1, "narration": "一条很慢的实测长句。", "audio_duration_sec": 17.2},
        ]
    }
    measured = [
        {
            "sentence_id": "segment-1-sentence-1",
            "text": "一条很慢的实测长句。",
            "start_sec": 0.0,
            "end_sec": 17.2,
        }
    ]

    cues = build_subtitle_cues(storyboard, sentence_cues=measured)

    assert len(cues) == 1
    assert cues[0].sentence_id == "segment-1-sentence-1"
    assert cues[0].end_sec == 17.2


def test_measured_cues_split_for_srt_without_changing_interval_or_sentence_identity():
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "区块链把数据按时间顺序连接起来，每个区块都保存前一区块的摘要。",
                "audio_duration_sec": 17.2,
            },
        ]
    }
    measured = {
        "segments": [
            {
                "segment_id": "1",
                "duration_sec": 17.2,
                "cues": [
                    {
                        "sentence_id": "segment-1-sentence-1",
                        "index": 1,
                        "text": "区块链把数据按时间顺序连接起来，每个区块都保存前一区块的摘要。",
                        "start_sec": 0.0,
                        "end_sec": 17.2,
                    }
                ],
            }
        ]
    }

    cues = build_subtitle_cues(
        storyboard,
        sentence_cues=measured,
        split_measured_cues=True,
        max_cue_sec=8.0,
    )

    assert len(cues) >= 3
    assert cues[0].start_sec == 0.0
    assert cues[-1].end_sec == 17.2
    assert all(cue.end_sec - cue.start_sec < 8.0 for cue in cues)
    assert all(cue.sentence_id == "segment-1-sentence-1" for cue in cues)
    assert "".join(cue.text for cue in cues) == measured["segments"][0]["cues"][0]["text"]


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


def test_generate_srt_splits_overlong_measured_sentence(tmp_path):
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "区块链把数据按时间顺序连接起来，每个区块都保存前一区块的摘要。",
                "audio_duration_sec": 17.2,
            }
        ]
    }
    measured = [{
        "sentence_id": "segment-1-sentence-1",
        "text": "区块链把数据按时间顺序连接起来，每个区块都保存前一区块的摘要。",
        "start_sec": 0.0,
        "end_sec": 17.2,
    }]

    out = generate_srt(
        storyboard,
        tmp_path / "lesson.srt",
        sentence_cues=measured,
    )
    timestamps = [
        line for line in out.read_text(encoding="utf-8").splitlines() if " --> " in line
    ]

    assert len(timestamps) >= 3
    assert timestamps[0].startswith("00:00:00,000 --> ")
    assert timestamps[-1].endswith("00:00:17,200")
