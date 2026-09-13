"""Deterministic narration and audio/video composition gate.

The gate deliberately checks the files that are delivered with a candidate
run.  It does not infer audio success from a renderer log or from the
existence of a silent MP4.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..runner import EvalContext
from .common import evidence_for


AUDIO_ISSUES = {
    "AUDIO_ASSET_MISSING",
    "AUDIO_DECODE_FAILED",
    "AUDIO_SEGMENT_MISSING",
    "AUDIO_DURATION_MISMATCH",
    "MP4_AUDIO_STREAM_MISSING",
    "SUBTITLE_COVERAGE_INCOMPLETE",
    "AV_DURATION_MISMATCH",
}


def _find_tool(name: str, env_name: str) -> str | None:
    configured = os.getenv(env_name, "").strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which(name)


def _parse_duration(value: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _media_info(path: Path) -> dict[str, Any]:
    """Probe a media file using ffprobe, or ffmpeg when ffprobe is absent."""
    ffprobe = _find_tool("ffprobe", "T2V_FFPROBE")
    if ffprobe:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,sample_rate,channels:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or f"ffprobe failed for {path.name}")
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams", [])
        fmt = payload.get("format", {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        return {
            "duration_sec": float(fmt["duration"]) if fmt.get("duration") else None,
            "audio_stream_count": sum(s.get("codec_type") == "audio" for s in streams),
            "video_stream_count": sum(s.get("codec_type") == "video" for s in streams),
            "audio_codec": audio.get("codec_name") if audio else None,
            "sample_rate": int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
            "channels": int(audio["channels"]) if audio and audio.get("channels") else None,
            "video_codec": video.get("codec_name") if video else None,
        }

    ffmpeg = _find_tool("ffmpeg", "T2V_FFMPEG")
    if not ffmpeg:
        raise ValueError("ffmpeg/ffprobe is not available")
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    diagnostic = result.stderr
    if result.returncode != 0 and "Stream #" not in diagnostic:
        raise ValueError(diagnostic.strip() or f"ffmpeg failed for {path.name}")
    audio_match = re.search(r"Stream #\S+.*?Audio:\s*([\w]+).*?(\d+) Hz", diagnostic)
    video_match = re.search(r"Stream #\S+.*?Video:\s*([\w]+)", diagnostic)
    return {
        "duration_sec": _parse_duration(diagnostic),
        "audio_stream_count": 1 if audio_match else 0,
        "video_stream_count": 1 if video_match else 0,
        "audio_codec": audio_match.group(1) if audio_match else None,
        "sample_rate": int(audio_match.group(2)) if audio_match else None,
        "channels": None,
        "video_codec": video_match.group(1) if video_match else None,
    }


def _timed_duration(path: Path) -> tuple[float, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("timed storyboard must contain a non-empty segments list")
    durations = []
    for index, segment in enumerate(segments, start=1):
        duration = segment.get("audio_duration_sec") if isinstance(segment, dict) else None
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(f"segment {index} has no positive audio_duration_sec")
        durations.append(float(duration))
    return sum(durations), len(durations)


def _subtitle_coverage(path: Path, expected_duration: float) -> tuple[float, int]:
    text = path.read_text(encoding="utf-8-sig")
    intervals: list[tuple[float, float]] = []
    for line in text.splitlines():
        match = re.search(
            r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", line
        )
        if not match:
            continue
        values = [int(item) for item in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        if end > start:
            intervals.append((max(0.0, start), min(expected_duration, end)))
    intervals.sort()
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    covered = sum(end - start for start, end in merged)
    return (covered / expected_duration if expected_duration else 0.0), len(intervals)


def _issue(case_id: str, issue_type: str, message: str, *, evidence_ids: list[str]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "stage": "audio",
        "evaluator": "audio_integrity",
        "type": issue_type,
        "severity": "major",
        "message": message,
        "evidence_ids": evidence_ids,
        "review_status": "unreviewed",
    }


def evaluate_audio_integrity(context: EvalContext) -> dict[str, Any]:
    name = "audio_integrity"
    timed_storyboard = context.artifact("timed_storyboard") or context.artifact("storyboard")
    audio_dir = context.artifact("audio_dir")
    audio_provenance = context.artifact("audio_provenance")
    final_video = context.artifact("final_video")
    subtitle = context.artifact("subtitle")
    evidence_ids: list[str] = []
    evidence: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    def add_evidence(path: Path | None, suffix: str, kind: str) -> None:
        if path is not None and path.exists():
            evidence_id = f"{context.case.case_id}-audio-{suffix}"
            evidence_ids.append(evidence_id)
            evidence.append(evidence_for(path, evidence_id=evidence_id, kind=kind))

    add_evidence(timed_storyboard, "timed-storyboard", "timed_storyboard")
    add_evidence(audio_dir, "asset", "audio_assets")
    add_evidence(audio_provenance, "provenance", "audio_provenance")
    add_evidence(final_video, "video", "final_video")
    add_evidence(subtitle, "subtitle", "subtitles")

    metrics: dict[str, Any] = {
        "audio_asset_exists": bool(audio_dir and audio_dir.is_dir()),
        "audio_decode": False,
        "audio_stream_present": False,
        "audio_duration_sec": None,
        "timed_storyboard_duration_sec": None,
        "video_duration_sec": None,
        "audio_video_delta_sec": None,
        "audio_storyboard_delta_sec": None,
        "segment_count_expected": None,
        "segment_count_actual": 0,
        "subtitle_coverage": None,
        "subtitle_cue_count": 0,
    }

    if timed_storyboard is None or not timed_storyboard.is_file():
        issues.append(_issue(context.case.case_id, "AUDIO_ASSET_MISSING", "timed storyboard is missing", evidence_ids=evidence_ids))
        expected_duration = None
        expected_segments = None
    else:
        try:
            expected_duration, expected_segments = _timed_duration(timed_storyboard)
            metrics["timed_storyboard_duration_sec"] = round(expected_duration, 3)
            metrics["segment_count_expected"] = expected_segments
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(_issue(context.case.case_id, "AUDIO_DECODE_FAILED", str(exc), evidence_ids=evidence_ids))
            expected_duration = None
            expected_segments = None

    audio_files: list[Path] = []
    if audio_dir is None or not audio_dir.is_dir():
        issues.append(_issue(context.case.case_id, "AUDIO_ASSET_MISSING", "audio segment directory is missing", evidence_ids=evidence_ids))
    else:
        audio_files = sorted(
            (path for path in audio_dir.iterdir() if path.is_file() and re.fullmatch(r"s\d+", path.stem, re.I)),
            key=lambda path: int(re.search(r"\d+", path.stem).group()),
        )
        metrics["segment_count_actual"] = len(audio_files)
        if expected_segments is not None:
            present = {int(re.search(r"\d+", path.stem).group()) for path in audio_files}
            missing = sorted(set(range(1, expected_segments + 1)) - present)
            if missing:
                issues.append(_issue(context.case.case_id, "AUDIO_SEGMENT_MISSING", f"missing audio segments: {missing}", evidence_ids=evidence_ids))

    segment_durations: list[float] = []
    audio_duration: float | None = None
    for audio_file in audio_files:
        try:
            info = _media_info(audio_file)
            duration = info.get("duration_sec")
            if not isinstance(duration, (int, float)) or duration <= 0:
                raise ValueError("audio duration is missing or zero")
            segment_durations.append(float(duration))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(_issue(context.case.case_id, "AUDIO_DECODE_FAILED", f"{audio_file.name}: {exc}", evidence_ids=evidence_ids))
    if segment_durations:
        audio_duration = sum(segment_durations)
        metrics["audio_duration_sec"] = round(audio_duration, 3)
        metrics["audio_decode"] = len(segment_durations) == len(audio_files)
        if expected_duration is not None:
            metrics["audio_storyboard_delta_sec"] = round(abs(audio_duration - expected_duration), 3)
            tolerance = max(0.5, expected_duration * 0.02)
            if abs(audio_duration - expected_duration) > tolerance:
                issues.append(_issue(context.case.case_id, "AUDIO_DURATION_MISMATCH", f"audio/storyboard duration delta exceeds {tolerance:.3f}s", evidence_ids=evidence_ids))

    video_info: dict[str, Any] | None = None
    if final_video is None or not final_video.is_file():
        issues.append(_issue(context.case.case_id, "MP4_AUDIO_STREAM_MISSING", "final MP4 is missing", evidence_ids=evidence_ids))
    else:
        try:
            video_info = _media_info(final_video)
            metrics["video_duration_sec"] = round(float(video_info.get("duration_sec") or 0.0), 3)
            metrics["audio_stream_present"] = video_info.get("audio_stream_count", 0) >= 1
            metrics["video_codec"] = video_info.get("video_codec")
            metrics["audio_codec"] = video_info.get("audio_codec")
            metrics["audio_sample_rate"] = video_info.get("sample_rate")
            if not metrics["audio_stream_present"]:
                issues.append(_issue(context.case.case_id, "MP4_AUDIO_STREAM_MISSING", "final MP4 contains no audio stream", evidence_ids=evidence_ids))
            if expected_duration is not None and video_info.get("duration_sec") is not None:
                metrics["storyboard_video_delta_sec"] = round(abs(float(video_info["duration_sec"]) - expected_duration), 3)
                if metrics["storyboard_video_delta_sec"] > max(0.5, expected_duration * 0.02):
                    issues.append(_issue(context.case.case_id, "AV_DURATION_MISMATCH", "video/storyboard duration delta exceeds tolerance", evidence_ids=evidence_ids))
            if audio_duration is not None and video_info.get("duration_sec") is not None:
                metrics["audio_video_delta_sec"] = round(abs(float(video_info["duration_sec"]) - audio_duration), 3)
                if metrics["audio_video_delta_sec"] > max(0.5, audio_duration * 0.02):
                    issues.append(_issue(context.case.case_id, "AV_DURATION_MISMATCH", "audio/video duration delta exceeds tolerance", evidence_ids=evidence_ids))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(_issue(context.case.case_id, "AUDIO_DECODE_FAILED", f"final MP4: {exc}", evidence_ids=evidence_ids))

    if subtitle is None or not subtitle.is_file() or expected_duration is None:
        issues.append(_issue(context.case.case_id, "SUBTITLE_COVERAGE_INCOMPLETE", "subtitle file is missing", evidence_ids=evidence_ids))
    else:
        try:
            coverage, cue_count = _subtitle_coverage(subtitle, expected_duration)
            metrics["subtitle_coverage"] = round(coverage, 6)
            metrics["subtitle_cue_count"] = cue_count
            if coverage < 0.98 or cue_count == 0:
                issues.append(_issue(context.case.case_id, "SUBTITLE_COVERAGE_INCOMPLETE", f"subtitle coverage is {coverage:.6f}", evidence_ids=evidence_ids))
        except (OSError, ValueError) as exc:
            issues.append(_issue(context.case.case_id, "SUBTITLE_COVERAGE_INCOMPLETE", str(exc), evidence_ids=evidence_ids))

    unique_issues = list({(item["type"], item["message"]): item for item in issues}.values())
    passed = not unique_issues and metrics["audio_stream_present"] and metrics["audio_decode"]
    return {
        "status": "ok" if passed else "failed",
        "passed": passed,
        "metrics": metrics,
        "details": {
            "required": True,
            "audio_dir": str(audio_dir) if audio_dir else None,
            "final_video": str(final_video) if final_video else None,
            "subtitle": str(subtitle) if subtitle else None,
            "segment_files": [path.name for path in audio_files],
            "audio_stream_count": video_info.get("audio_stream_count") if video_info else 0,
            "video_stream_count": video_info.get("video_stream_count") if video_info else 0,
            "provenance": (
                json.loads(audio_provenance.read_text(encoding="utf-8-sig"))
                if audio_provenance is not None and audio_provenance.is_file()
                else None
            ),
        },
        "issues": unique_issues,
        "evidence_ids": evidence_ids,
        "_evidence": evidence,
    }


evaluate_audio_integrity.evaluator_name = "audio_integrity"
