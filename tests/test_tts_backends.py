"""Tests for the optional cloud TTS backend dispatch."""

import json
from pathlib import Path

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
