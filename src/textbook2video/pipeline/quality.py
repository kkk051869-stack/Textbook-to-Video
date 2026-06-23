"""Deterministic quality report for generated teaching videos.

This first pass deliberately avoids VLM/LLM judging. It checks artifacts that
the pipeline already knows how to reason about: storyboard structure, segment
durations, subtitle coverage, audio segment presence, layout reports, and
textbook image usage. The goal is a stable baseline report that can later grow
into TextbookEval.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__all__ = [
    "build_quality_report",
    "write_quality_report",
]

_SRT_TIME_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _score(ok: bool) -> float:
    return 1.0 if ok else 0.0


def _srt_seconds(stamp: str) -> float:
    hms, ms = stamp.split(",", 1)
    h, m, s = [int(part) for part in hms.split(":")]
    return h * 3600 + m * 60 + s + int(ms) / 1000


def _parse_srt(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "present": False,
            "cue_count": 0,
            "total_duration_sec": 0.0,
            "long_cue_warnings": [],
        }

    text = path.read_text(encoding="utf-8")
    spans = [
        (_srt_seconds(m.group("start")), _srt_seconds(m.group("end")))
        for m in _SRT_TIME_RE.finditer(text)
    ]
    long_warnings: list[str] = []
    for idx, (start, end) in enumerate(spans, 1):
        if end - start > 8:
            long_warnings.append(
                f"subtitle cue {idx} is long: {round(end - start, 1)}s"
            )
    total = spans[-1][1] - spans[0][0] if spans else 0.0
    return {
        "present": True,
        "cue_count": len(spans),
        "total_duration_sec": round(total, 3),
        "long_cue_warnings": long_warnings,
    }


def _audio_files(audio_dir: str | Path | None) -> list[Path]:
    if not audio_dir:
        return []
    p = Path(audio_dir)
    if not p.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for f in p.iterdir():
        m = re.fullmatch(r"s(\d+)", f.stem, flags=re.IGNORECASE)
        if m and f.is_file():
            out.append((int(m.group(1)), f))
    return [f for _, f in sorted(out, key=lambda t: t[0])]


def _find_layout_reports(output_dir: Path, stem: str) -> list[Path]:
    patterns = [
        f"{stem}*.layout.json",
        f"{stem}*.layout-*.json",
        f"{stem}*.layout-repair*.json",
    ]
    reports: list[Path] = []
    for pattern in patterns:
        reports.extend(output_dir.glob(pattern))
    return sorted(set(reports))


def _layout_summary(report_paths: list[Path]) -> dict[str, Any]:
    if not report_paths:
        return {
            "present": False,
            "report_count": 0,
            "pass": None,
            "failed_pages": [],
            "reports": [],
        }

    failed_pages: set[int] = set()
    pass_values: list[bool] = []
    for path in report_paths:
        try:
            data = _read_json(path)
        except Exception:  # noqa: BLE001 - report is diagnostic, do not fail produce
            continue
        if "ok" in data:
            pass_values.append(bool(data.get("ok")))
        elif "pass" in data:
            pass_values.append(bool(data.get("pass")))
        for key in ("failed_pages", "failing_pages", "failed_slide_indices"):
            val = data.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, int):
                        failed_pages.add(item)
        issues = data.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, dict):
                    idx = issue.get("slide_index")
                    if isinstance(idx, int):
                        failed_pages.add(idx)

    passed = (all(pass_values) and not failed_pages) if pass_values else not failed_pages
    return {
        "present": True,
        "report_count": len(report_paths),
        "pass": passed,
        "failed_pages": sorted(failed_pages),
        "reports": [str(p) for p in report_paths],
    }


def _textbook_image_usage(storyboard: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    img_dir = base_dir / "images"
    available = []
    if img_dir.is_dir():
        available = [
            p.name for p in img_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        ]

    used: set[str] = set()
    for seg in storyboard.get("segments", []):
        if not isinstance(seg, dict):
            continue
        for el in seg.get("elements", []) or []:
            if isinstance(el, dict) and el.get("type") == "image":
                src = el.get("src")
                if src:
                    used.add(str(src))

    available_set = set(available)
    grounded = sorted(used & available_set)
    ratio = len(grounded) / len(available_set) if available_set else None
    return {
        "available": len(available_set),
        "used": len(grounded),
        "ratio": round(ratio, 3) if ratio is not None else None,
        "used_files": grounded,
    }


def _animation_timing_warnings(storyboard: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for idx, seg in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(seg, dict):
            continue
        duration = seg.get("audio_duration_sec")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            continue
        max_trigger = 0.0
        for anim in seg.get("animations", []) or []:
            if not isinstance(anim, dict):
                continue
            trigger = anim.get("trigger_at_sec")
            if isinstance(trigger, (int, float)) and not isinstance(trigger, bool):
                max_trigger = max(max_trigger, float(trigger))
        if max_trigger and float(duration) < max_trigger + 0.5:
            warnings.append(
                f"segment[{idx}] duration {duration}s is shorter than last trigger "
                f"{max_trigger}s + 0.5s buffer"
            )
    return warnings


def build_quality_report(
    storyboard_path: str | Path,
    *,
    audio_dir: str | Path | None = None,
    subtitle_path: str | Path | None = None,
    final_video: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic quality report from local pipeline artifacts."""
    sb_path = Path(storyboard_path)
    storyboard = _read_json(sb_path)
    out_dir = Path(output_dir) if output_dir else sb_path.parent
    stem = sb_path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]

    segments = storyboard.get("segments", [])
    segment_count = len(segments) if isinstance(segments, list) else 0
    durations = [
        float(seg.get("audio_duration_sec"))
        for seg in segments
        if isinstance(seg, dict)
        and isinstance(seg.get("audio_duration_sec"), (int, float))
        and not isinstance(seg.get("audio_duration_sec"), bool)
        and seg.get("audio_duration_sec") > 0
    ] if isinstance(segments, list) else []

    audio = _audio_files(audio_dir)
    srt = _parse_srt(Path(subtitle_path)) if subtitle_path else {
        "present": False,
        "cue_count": 0,
        "total_duration_sec": 0.0,
        "long_cue_warnings": [],
    }
    expected_sec = round(sum(durations), 3)
    subtitle_coverage = None
    if expected_sec > 0 and srt["present"]:
        subtitle_coverage = round(srt["total_duration_sec"] / expected_sec, 3)

    layout = _layout_summary(_find_layout_reports(out_dir, stem))
    image_usage = _textbook_image_usage(storyboard, sb_path.parent)
    timing_warnings = _animation_timing_warnings(storyboard)

    warnings: list[str] = []
    if segment_count and len(durations) != segment_count:
        warnings.append(
            f"audio_duration_sec coverage {len(durations)}/{segment_count}"
        )
    if audio_dir and len(audio) != segment_count:
        warnings.append(f"audio segment files {len(audio)}/{segment_count}")
    if subtitle_coverage is not None and subtitle_coverage < 0.95:
        warnings.append(f"subtitle coverage is low: {subtitle_coverage}")
    warnings.extend(srt["long_cue_warnings"])
    warnings.extend(timing_warnings)
    if image_usage["ratio"] is not None and image_usage["ratio"] < 0.6:
        warnings.append(
            f"textbook image usage is low: {image_usage['used']}/"
            f"{image_usage['available']}"
        )
    if layout["pass"] is False:
        warnings.append(f"layout QA failed pages: {layout['failed_pages']}")

    scores = {
        "structure": _score(segment_count > 0 and len(durations) == segment_count),
        "audio": _score(bool(audio) and len(audio) == segment_count)
        if audio_dir else None,
        "subtitle": (
            max(0.0, min(1.0, subtitle_coverage))
            if subtitle_coverage is not None else None
        ),
        "layout": _score(layout["pass"]) if layout["pass"] is not None else None,
        "image_grounding": image_usage["ratio"],
    }
    numeric_scores = [v for v in scores.values() if isinstance(v, (int, float))]
    ok = not warnings and bool(numeric_scores)

    return {
        "ok": ok,
        "storyboard": str(sb_path),
        "final_video": str(final_video) if final_video else None,
        "summary": {
            "segments": segment_count,
            "duration_sec": expected_sec,
            "warnings": len(warnings),
        },
        "scores": scores,
        "checks": {
            "audio_files": {
                "dir": str(audio_dir) if audio_dir else None,
                "count": len(audio),
                "expected": segment_count,
            },
            "subtitles": {
                **srt,
                "coverage_ratio": subtitle_coverage,
            },
            "layout": layout,
            "textbook_images": image_usage,
            "timing_warnings": timing_warnings,
        },
        "warnings": warnings,
    }


def write_quality_report(
    storyboard_path: str | Path,
    out_path: str | Path,
    **kwargs: Any,
) -> Path:
    """Build and write a quality report JSON file."""
    report = build_quality_report(storyboard_path, **kwargs)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
