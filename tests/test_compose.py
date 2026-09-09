"""音画合成测试（pipeline/compose）。

find_segment_audio 是纯逻辑，完整测试；concat/mux 依赖 ffmpeg，无则 skip。
"""

import shutil
import subprocess

import pytest

from textbook2video.pipeline.compose import (
    compose_video,
    concat_audio,
    find_segment_audio,
    mux_audio_video,
    resolve_audio_dir,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
requires_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="无 ffmpeg，跳过合成测试")


def _touch(path):
    path.write_bytes(b"")
    return path


def test_find_segment_audio_sorts_numerically(tmp_path):
    # 乱序 + 字典序陷阱（s10 应排在 s9 之后，而非 s1 之后）
    for name in ["s2.mp3", "s10.mp3", "s1.mp3", "s9.mp3"]:
        _touch(tmp_path / name)
    found = find_segment_audio(tmp_path)
    assert [p.stem for p in found] == ["s1", "s2", "s9", "s10"]


def test_find_segment_audio_ignores_non_segment_files(tmp_path):
    _touch(tmp_path / "s1.mp3")
    _touch(tmp_path / "fulltrack.m4a")   # 非 sN 命名
    _touch(tmp_path / "notes.txt")
    found = find_segment_audio(tmp_path)
    assert [p.name for p in found] == ["s1.mp3"]


def test_find_segment_audio_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_segment_audio(tmp_path / "nope")


def test_resolve_audio_dir_passthrough_for_directory(tmp_path):
    d = tmp_path / "ch3_s0_audio"
    d.mkdir()
    assert resolve_audio_dir(d) == d


def test_resolve_audio_dir_from_storyboard_json(tmp_path):
    sb = tmp_path / "ch3_s0_storyboard.json"
    sb.write_text("{}", encoding="utf-8")
    assert resolve_audio_dir(sb) == tmp_path / "ch3_s0_audio"


def test_resolve_audio_dir_json_without_storyboard_suffix(tmp_path):
    sb = tmp_path / "lesson4.json"
    sb.write_text("{}", encoding="utf-8")
    assert resolve_audio_dir(sb) == tmp_path / "lesson4_audio"


def test_concat_audio_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        concat_audio([], tmp_path / "out.m4a")


def test_concat_audio_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        concat_audio([tmp_path / "ghost.mp3"], tmp_path / "out.m4a")


def _make_silence(path, seconds, sr=44100):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r={sr}:cl=mono", "-t", str(seconds),
         "-c:a", "libmp3lame", str(path)],
        check=True, capture_output=True,
    )


def _make_blank_video(path, seconds, fps=10):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=black:s=320x240:r={fps}", "-t", str(seconds),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


def _duration(path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(probe.stdout.strip())


@requires_ffmpeg
def test_concat_audio_lengths_add_up(tmp_path):
    a, b = tmp_path / "s1.mp3", tmp_path / "s2.mp3"
    _make_silence(a, 1.0)
    _make_silence(b, 2.0)
    out = concat_audio([a, b], tmp_path / "track.m4a")
    assert out.exists()
    assert abs(_duration(out) - 3.0) < 0.4   # 1s + 2s，容忍编码误差


@requires_ffmpeg
def test_compose_video_muxes_audio_track(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    _make_silence(audio_dir / "s1.mp3", 1.0)
    _make_silence(audio_dir / "s2.mp3", 1.0)
    video = tmp_path / "silent.mp4"
    _make_blank_video(video, 2.0)

    out = compose_video(video, audio_dir, tmp_path / "final.mp4")
    assert out.exists()
    # 成片应含音频流
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert "audio" in probe.stdout
    # 中间整段音轨临时文件应已清理
    assert not list(tmp_path.glob(".*.fulltrack.m4a"))


@requires_ffmpeg
def test_compose_video_muxes_soft_subtitle_track(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    _make_silence(audio_dir / "s1.mp3", 1.0)
    video = tmp_path / "silent.mp4"
    _make_blank_video(video, 1.0)
    srt = tmp_path / "captions.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n",
        encoding="utf-8",
    )

    out = compose_video(video, audio_dir, tmp_path / "final_subtitled.mp4", subtitle_path=srt)
    assert out.exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert "subtitle" in probe.stdout


@requires_ffmpeg
def test_mux_missing_inputs_raise(tmp_path):
    with pytest.raises(FileNotFoundError):
        mux_audio_video(tmp_path / "no.mp4", tmp_path / "no.m4a", tmp_path / "o.mp4")
