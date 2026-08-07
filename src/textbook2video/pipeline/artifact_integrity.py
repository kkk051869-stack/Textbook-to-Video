"""Validation and manifests for narration-driven render bundles."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = ["verify_render_bundle", "write_render_manifest", "media_duration_seconds"]

_DURATIONS = re.compile(r"var\s+slideDurations\s*=\s*(\[[^;]*\])\s*;")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _storyboard_durations(path: Path) -> list[int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError(f"storyboard 没有可用 segments: {path}")
    durations: list[int] = []
    for index, segment in enumerate(segments, 1):
        duration = segment.get("audio_duration_sec") if isinstance(segment, dict) else None
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(f"storyboard 第 {index} 页没有有效音频时长")
        durations.append(int(duration * 1000))
    return durations


def _html_durations(path: Path) -> list[int]:
    match = _DURATIONS.search(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"HTML 未嵌入 slideDurations: {path}")
    durations = json.loads(match.group(1))
    if not isinstance(durations, list) or not all(isinstance(v, int) and v > 0 for v in durations):
        raise ValueError(f"HTML slideDurations 无效: {path}")
    return durations


def media_duration_seconds(path: str | Path) -> float:
    """Read an audio/video duration with ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
            check=True, capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    if not ffmpeg:
        raise FileNotFoundError("需要 ffprobe 或 ffmpeg 才能校验媒体时长")
    result = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True, errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValueError(f"无法读取媒体时长: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def verify_render_bundle(
    storyboard_path: str | Path,
    html_path: str | Path,
    *,
    audio_dir: str | Path | None = None,
    tolerance_sec: float = 0.1,
) -> dict[str, Any]:
    """Fail closed unless storyboard, rendered HTML and optional audio agree."""
    storyboard_path, html_path = Path(storyboard_path), Path(html_path)
    expected = _storyboard_durations(storyboard_path)
    actual = _html_durations(html_path)
    if actual != expected:
        raise ValueError(
            "HTML 与 timed storyboard 的逐页时长不一致；拒绝录制。"
            f" storyboard={expected}, html={actual}"
        )
    report: dict[str, Any] = {
        "storyboard": storyboard_path.name,
        "storyboard_sha256": _sha256(storyboard_path),
        "html": html_path.name,
        "html_sha256": _sha256(html_path),
        "slide_count": len(expected),
        "slide_durations_ms": expected,
        "total_duration_sec": round(sum(expected) / 1000, 3),
    }
    if audio_dir is not None:
        from textbook2video.pipeline.compose import find_segment_audio

        files = find_segment_audio(audio_dir)
        if len(files) != len(expected):
            raise ValueError(f"音频段数 {len(files)} 与页面数 {len(expected)} 不一致；拒绝录制。")
        actual_audio = sum(media_duration_seconds(path) for path in files)
        expected_audio = sum(expected) / 1000
        if abs(actual_audio - expected_audio) > tolerance_sec:
            raise ValueError(
                f"音频总时长 {actual_audio:.3f}s 与 timed storyboard {expected_audio:.3f}s 不一致；拒绝录制。"
            )
        report["audio_files"] = [path.name for path in files]
        report["audio_total_duration_sec"] = round(actual_audio, 3)
    return report


def write_render_manifest(
    storyboard_path: str | Path,
    html_path: str | Path,
    *,
    audio_dir: str | Path | None = None,
) -> Path:
    """Validate a render bundle and write its immutable transfer manifest."""
    report = verify_render_bundle(storyboard_path, html_path, audio_dir=audio_dir)
    out_path = Path(html_path).with_name(f"{Path(html_path).stem}.manifest.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
