"""Audio/video composition helpers.

The video recorder produces a silent MP4. This module concatenates per-segment
TTS files into one audio track, then muxes that track into the recorded video.
It can optionally attach an SRT file as a soft subtitle track.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

__all__ = [
    "find_segment_audio",
    "concat_audio",
    "mux_audio_video",
    "compose_video",
    "resolve_audio_dir",
]


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def _escape_subtitles_filter_path(path: str | Path) -> str:
    """Escape a subtitle path for ffmpeg's subtitles filter on Windows and POSIX."""
    p = Path(path).resolve()
    escaped = str(p).replace("\\", "/").replace(":", r"\:")
    return f"'{escaped}'"


def resolve_audio_dir(audio_arg: str | Path) -> Path:
    """Resolve a mux audio argument to an audio directory.

    - Directory input is returned as-is.
    - A storyboard JSON path resolves to a sibling ``<stem>_audio`` directory.
    """
    p = Path(audio_arg)
    if p.is_file() and p.suffix.lower() == ".json":
        stem = p.stem
        if stem.endswith("_storyboard"):
            stem = stem[: -len("_storyboard")]
        return p.parent / f"{stem}_audio"
    return p


def find_segment_audio(audio_dir: str | Path) -> list[Path]:
    """Return sN.* audio files sorted by their numeric segment index."""
    audio_dir = Path(audio_dir)
    if not audio_dir.is_dir():
        raise FileNotFoundError(f"Audio directory not found: {audio_dir}")

    indexed: list[tuple[int, Path]] = []
    for f in audio_dir.iterdir():
        m = re.fullmatch(r"s(\d+)", f.stem, flags=re.IGNORECASE)
        if m and f.is_file():
            indexed.append((int(m.group(1)), f))
    indexed.sort(key=lambda t: t[0])
    return [p for _, p in indexed]


def concat_audio(audio_files: list[str | Path], out_path: str | Path) -> Path:
    """Concatenate per-segment audio files into one AAC audio track."""
    files = [Path(f) for f in audio_files]
    if not files:
        raise ValueError("No audio files to concatenate")
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"Missing audio files: {', '.join(missing)}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    list_path = out_path.with_suffix(".concat.txt")
    lines = []
    for f in files:
        safe = str(f.resolve()).replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(list_path),
                "-c:a", "aac", "-b:a", "192k",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        _unlink_quiet(list_path)
    return out_path


def mux_audio_video(
    video_path: str | Path,
    audio_path: str | Path,
    out_path: str | Path,
    *,
    subtitle_path: str | Path | None = None,
) -> Path:
    """Mux audio into an MP4 video and burn subtitles if provided."""
    video_path, audio_path, out_path = Path(video_path), Path(audio_path), Path(out_path)
    for p in (video_path, audio_path):
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")
    subtitle = Path(subtitle_path) if subtitle_path else None
    if subtitle and not subtitle.exists():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
    ]
    if subtitle:
        cmd.extend([
            "-vf", f"subtitles={_escape_subtitles_filter_path(subtitle)}:charenc=UTF-8",
        ])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0",
    ])
    cmd.extend([
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ])
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def compose_video(
    video_path: str | Path,
    audio_dir: str | Path,
    out_path: str | Path,
    *,
    subtitle_path: str | Path | None = None,
) -> Path:
    """Concatenate segment audio and mux it into the video."""
    out_path = Path(out_path)
    audio_files = find_segment_audio(audio_dir)
    if not audio_files:
        raise FileNotFoundError(f"No segment audio files found in: {audio_dir}")

    track_path = out_path.parent / f".{out_path.stem}.fulltrack.m4a"
    try:
        concat_audio(audio_files, track_path)
        mux_audio_video(video_path, track_path, out_path, subtitle_path=subtitle_path)
    finally:
        _unlink_quiet(track_path)
    return out_path
