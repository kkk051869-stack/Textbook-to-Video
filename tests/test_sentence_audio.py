import io
import wave
from pathlib import Path

import pytest

from textbook2video.pipeline import narrator
from textbook2video.pipeline.sentence_audio import (
    build_sentence_cues,
    concat_wav_bytes,
    sentence_cache_key,
    wav_duration,
)
from textbook2video.pipeline.subtitles import SentenceSplitter, build_subtitle_cues
from textbook2video.pipeline.timing import build_segment_timing
from textbook2video.pipeline.timing import apply_timing


def _wav(seconds: float, rate: int = 1000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\0\0" * int(seconds * rate))
    return out.getvalue()


def test_sentence_splitter_keeps_sentence_boundaries():
    assert SentenceSplitter().split("第一句。第二句！第三句？") == [
        "第一句。",
        "第二句！",
        "第三句？",
    ]


def test_concat_wav_bytes_is_in_memory_and_preserves_duration():
    merged = concat_wav_bytes([_wav(1.0), _wav(2.0)])
    assert abs(wav_duration(merged) - 3.0) < 0.01


def test_concat_wav_rejects_mismatched_format():
    with pytest.raises(ValueError, match="parameters"):
        concat_wav_bytes([_wav(1.0, 1000), _wav(1.0, 2000)])


def test_build_sentence_cues_are_contiguous():
    cues = build_sentence_cues(4, ["一。", "二。"], [1.25, 2.5])
    assert cues[0].start_sec == 0.0
    assert cues[0].end_sec == cues[1].start_sec
    assert cues[-1].end_sec == 3.75


def test_sentence_cache_key_includes_config():
    a = sentence_cache_key("你好", backend="megatts3", config={"t": 24})
    b = sentence_cache_key("你好", backend="megatts3", config={"t": 25})
    assert a != b


def test_real_sentence_cues_drive_subtitles_and_animation_timing():
    sidecar = {
        "segments": [{
            "segment_id": 1,
            "cues": [
                {"text": "第一句。", "start_sec": 0.0, "end_sec": 1.2},
                {"text": "关键概念。", "start_sec": 1.2, "end_sec": 2.8},
            ],
        }]
    }
    storyboard = {
        "segments": [{
            "id": 1,
            "narration": "第一句。关键概念。",
            "audio_duration_sec": 2.8,
            "elements": [
                {"id": "h", "type": "heading", "text": "标题"},
                {"id": "k", "type": "text", "text": "关键概念"},
            ],
        }]
    }
    cues = build_subtitle_cues(storyboard, sentence_cues=sidecar)
    assert [(cue.start_sec, cue.end_sec) for cue in cues] == [(0.0, 1.2), (1.2, 2.8)]
    animations = build_segment_timing(storyboard["segments"][0], sidecar["segments"][0]["cues"])
    assert animations[1]["trigger_at_sec"] == 1.2
    assert apply_timing(storyboard, sidecar)["metadata"]["timing_source"] == "sentence_cues"


def test_generate_sentence_audio_keeps_only_segment_outputs(tmp_path, monkeypatch):
    def fake_batch(texts, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, _ in enumerate(texts, start=1):
            path = output_dir / f"s{index}.wav"
            path.write_bytes(_wav(0.5))
            paths.append(path)
        return paths

    monkeypatch.setattr(narrator, "_generate_megatts3", fake_batch)
    result = narrator.generate_sentence_audio(
        [["一。", "二。"], ["三。"]], output_dir=tmp_path
    )
    assert [p.name for p in result["audio_files"]] == ["s1.wav", "s2.wav"]
    assert (tmp_path / "sentence_cues.json").exists()
    assert not list(tmp_path.glob(".sentence_tts_*"))
