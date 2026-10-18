"""Tests for the optional cloud TTS backend dispatch."""

import json
from pathlib import Path
import wave

import pytest

from textbook2video.pipeline import narrator


def test_cosyvoice_backend_runs_one_batch_and_returns_wav(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, input, **kwargs):
        request = json.loads(input)
        calls.append((command, request, kwargs))
        output_dir = Path(request["output_dir"])
        for index in range(len(request["segments"])):
            (output_dir / f"s{index + 1}.wav").write_bytes(b"wav")

    monkeypatch.setattr(narrator.subprocess, "run", fake_run)
    outputs = narrator.generate_audio(
        ["CPU first", "second"], output_dir=str(tmp_path), backend="cosyvoice3"
    )

    assert [path.name for path in outputs] == ["s1.wav", "s2.wav"]
    assert len(calls) == 1
    assert calls[0][1]["segments"] == ["C P U first", "second"]


def test_megatts3_backend_runs_one_batch_and_returns_wav(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, input, **kwargs):
        request = json.loads(input)
        calls.append((command, request, kwargs))
        output_dir = Path(request["output_dir"])
        for index in range(len(request["segments"])):
            (output_dir / f"s{index + 1}.wav").write_bytes(b"wav")

    monkeypatch.setattr(narrator.subprocess, "run", fake_run)
    outputs = narrator.generate_audio(
        ["first", "second"], output_dir=str(tmp_path), backend="megatts3"
    )

    assert [path.name for path in outputs] == ["s1.wav", "s2.wav"]
    assert len(calls) == 1
    assert calls[0][1]["prompt_wav"].endswith("Chinese_prompt.wav")


def test_sapi_backend_runs_one_batch_and_returns_wav(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, *, input, **kwargs):
        request = json.loads(input)
        calls.append((command, request, kwargs))
        output_dir = Path(request["output_dir"])
        for index in range(len(request["segments"])):
            with wave.open(str(output_dir / f"s{index + 1}.wav"), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(bytes(3200))

    monkeypatch.setattr(narrator.os, "name", "nt")
    monkeypatch.setattr(narrator.shutil, "which", lambda _name: "powershell.exe")
    monkeypatch.setattr(narrator.subprocess, "run", fake_run)
    outputs = narrator.generate_audio(
        ["CPU first", "second"],
        output_dir=str(tmp_path),
        backend="sapi",
        voice="Microsoft Huihui Desktop",
        rate="+5%",
    )

    assert [path.name for path in outputs] == ["s1.wav", "s2.wav"]
    assert calls[0][1]["segments"] == ["C P U first", "second"]
    assert calls[0][1]["voice"] == "Microsoft Huihui Desktop"
    assert calls[0][1]["rate"] == 1


def test_sapi_sentence_audio_writes_measured_cues(tmp_path, monkeypatch):
    def fake_sapi(segments, output_dir, _voice, _rate):
        outputs = []
        for index, _text in enumerate(segments, start=1):
            path = output_dir / f"s{index}.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(bytes(3200 * index))
            outputs.append(path)
        return outputs

    monkeypatch.setattr(narrator, "_generate_sapi", fake_sapi)
    result = narrator.generate_sentence_audio(
        [["first", "second"]], output_dir=tmp_path, backend="sapi", segment_ids=["seg-1"]
    )

    assert result["audio_files"] == [tmp_path / "s1.wav"]
    payload = json.loads((tmp_path / "sentence_cues.json").read_text(encoding="utf-8"))
    cues = payload["segments"][0]["cues"]
    assert cues[0]["end_sec"] == pytest.approx(0.1)
    assert cues[1]["start_sec"] == pytest.approx(0.1)
    assert cues[1]["end_sec"] == pytest.approx(0.3)


def test_unknown_backend_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported TTS backend"):
        narrator.generate_audio(["text"], output_dir=str(tmp_path), backend="unknown")


def test_audio_duration_uses_ffmpeg_next_to_python(tmp_path, monkeypatch):
    python = tmp_path / "python"
    ffmpeg = tmp_path / "ffmpeg"
    python.touch()
    ffmpeg.touch()
    seen = []

    class Result:
        stderr = "Duration: 00:00:03.25, start: 0.000000, bitrate: 1 kb/s"

    def fake_run(command, **_kwargs):
        seen.append(command)
        return Result()

    monkeypatch.setattr(narrator.sys, "executable", str(python))
    monkeypatch.setattr(narrator.shutil, "which", lambda _name: None)
    monkeypatch.setattr(narrator.subprocess, "run", fake_run)

    assert narrator.get_audio_duration("audio.wav") == 3.25
    assert seen[0][0] == str(ffmpeg)


def test_audio_duration_falls_back_to_mpeg2_layer3_frames_without_ffmpeg(tmp_path, monkeypatch):
    # MPEG-2 Layer III, 48 kbps, 24 kHz: each 144-byte frame is 576 samples.
    audio = tmp_path / "audio.mp3"
    frame = bytes.fromhex("FFF364C4") + bytes(140)
    audio.write_bytes(frame * 2)
    monkeypatch.setattr(narrator.shutil, "which", lambda _name: None)
    monkeypatch.setattr(narrator.sys, "executable", str(tmp_path / "python"))

    def missing_binary(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(narrator.subprocess, "run", missing_binary)
    assert narrator.get_audio_duration(str(audio)) == pytest.approx(2 * 576 / 24000)


def test_run_tts_reuses_existing_audio_without_calling_tts(tmp_path, monkeypatch):
    from textbook2video.pipeline.orchestrator import run_tts

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    frame = bytes.fromhex("FFF364C4") + bytes(140)
    (audio_dir / "s1.mp3").write_bytes(frame * 2)
    storyboard = {"segments": [{"id": "1", "narration": "hello"}]}
    storyboard_path = tmp_path / "lesson_storyboard.json"
    monkeypatch.setattr("textbook2video.pipeline.narrator.generate_audio", lambda *_args, **_kwargs: pytest.fail("TTS should not run"))
    monkeypatch.setattr("textbook2video.pipeline.narrator.get_audio_duration", lambda _path: 2 * 576 / 24000)
    monkeypatch.setattr("textbook2video.pipeline.orchestrator.os.getenv", lambda key, default=None: "edge" if key == "T2V_TTS_BACKEND" else default)

    durations = run_tts(storyboard, storyboard_path, audio_dir, reuse_existing_audio=True)
    assert durations == [pytest.approx(2 * 576 / 24000)]


def test_edge_sentence_audio_writes_measured_cues(tmp_path, monkeypatch):
    monkeypatch.setattr(narrator, "edge_tts", object())

    async def fake_generate(text, output_path, _voice, _rate, **_kwargs):
        output_path.write_bytes(text.encode("utf-8"))
        return output_path

    def fake_duration(path):
        return 1.25 if "0001" in str(path) else 2.0

    class Result:
        returncode = 0

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"joined")
        return Result()

    monkeypatch.setattr(narrator, "_generate_single", fake_generate)
    monkeypatch.setattr(narrator, "get_audio_duration", fake_duration)
    monkeypatch.setattr(narrator.shutil, "which", lambda name: "ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(narrator.subprocess, "run", fake_run)

    result = narrator.generate_sentence_audio(
        [["第一句。", "第二句。"]], output_dir=tmp_path, backend="edge", segment_ids=["seg-1"],
    )
    assert result["audio_files"] == [tmp_path / "s1.mp3"]
    payload = json.loads((tmp_path / "sentence_cues.json").read_text(encoding="utf-8"))
    cues = payload["segments"][0]["cues"]
    assert [cue["text"] for cue in cues] == ["第一句。", "第二句。"]
    assert cues[0]["end_sec"] == 1.25
    assert cues[1]["start_sec"] == 1.25
    assert cues[1]["end_sec"] == 3.25


def test_run_tts_reuses_frozen_audio_only_with_matching_sentence_cues(tmp_path, monkeypatch):
    from textbook2video.pipeline.orchestrator import run_tts

    frozen = tmp_path / "frozen"
    frozen.mkdir()
    frame = bytes.fromhex("FFF364C4") + bytes(140)
    (frozen / "s1.mp3").write_bytes(frame * 2)
    (frozen / "sentence_cues.json").write_text(json.dumps({
        "schema_version": "sentence-cues-v1",
        "segments": [{
            "segment_id": "1", "duration_sec": 0.048,
            "cues": [{
                "sentence_id": "segment-1-sentence-1", "index": 1, "text": "hello",
                "start_sec": 0.0, "end_sec": 0.048, "duration_sec": 0.048,
            }],
        }],
    }), encoding="utf-8")
    storyboard = {"segments": [{"id": "1", "narration": "different text"}]}
    storyboard_path = tmp_path / "lesson_storyboard.json"
    monkeypatch.setattr("textbook2video.pipeline.orchestrator.os.getenv", lambda key, default=None: "edge" if key == "T2V_TTS_BACKEND" else default)

    with pytest.raises(ValueError, match="do not match frozen narration"):
        run_tts(
            storyboard,
            storyboard_path,
            tmp_path / "candidate_audio",
            frozen_audio_dir=frozen,
            timing_mode="semantic",
        )
