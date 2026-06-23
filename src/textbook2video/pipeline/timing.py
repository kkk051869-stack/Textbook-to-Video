"""Deterministic narration-driven animation timing.

This module turns a storyboard with measured ``audio_duration_sec`` into a
timed storyboard by filling ``animations[].trigger_at_sec``. It deliberately
does not call an LLM: subtitle cues provide approximate narration timing, then
simple text matching maps page elements to the cue that mentions them.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from textbook2video.pipeline.subtitles import build_subtitle_cues

__all__ = [
    "apply_timing",
    "build_segment_timing",
    "timed_storyboard_path",
    "write_timed_storyboard",
]

_TEXT_KEYS = (
    "text",
    "title",
    "label",
    "caption",
    "description",
    "name",
    "quote",
)
_LIST_KEYS = ("items", "steps", "headers", "rows", "points", "labels", "values")
_DEFAULT_EFFECT = "fadeInUp"
_MIN_GAP_SEC = 0.3


def timed_storyboard_path(storyboard_path: str | Path) -> Path:
    """Return the sibling path used for the timed storyboard copy."""
    path = Path(storyboard_path)
    stem = path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]
    return path.with_name(f"{stem}_timed_storyboard.json")


def _normalize_text(text: Any) -> str:
    text = str(text or "").lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _features(text: Any) -> set[str]:
    text = _normalize_text(text)
    if not text:
        return set()
    chars = set(text)
    bigrams = {text[i : i + 2] for i in range(max(0, len(text) - 1))}
    return chars | bigrams


def _similarity(a: Any, b: Any) -> float:
    fa, fb = _features(a), _features(b)
    if not fa or not fb:
        return 0.0
    return len(fa & fb) / len(fa | fb)


def _collect_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_collect_text(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for key in _TEXT_KEYS:
            out.extend(_collect_text(value.get(key)))
        for key in _LIST_KEYS:
            out.extend(_collect_text(value.get(key)))
        return out
    return []


def _element_text(element: dict[str, Any]) -> str:
    return " ".join(_collect_text(element))


def _existing_effects(segment: dict[str, Any]) -> dict[str, str]:
    effects: dict[str, str] = {}
    for anim in segment.get("animations", []) or []:
        if not isinstance(anim, dict):
            continue
        target = str(anim.get("target") or "").strip()
        effect = str(anim.get("effect") or "").strip()
        if target and effect:
            effects[target] = effect
    return effects


def _segment_cues(segment: dict[str, Any]) -> list[dict[str, Any]]:
    cues = build_subtitle_cues({"segments": [segment]})
    return [
        {"start": cue.start_sec, "end": cue.end_sec, "text": cue.text}
        for cue in cues
    ]


def _max_trigger_sec(duration: float) -> float:
    if duration <= 0:
        return 0.0
    if duration <= 1.0:
        return max(0.0, duration * 0.6)
    return max(0.0, min(duration * 0.8, duration - 0.2))


def _even_times(count: int, max_sec: float) -> list[float]:
    if count <= 0:
        return []
    if count == 1 or max_sec <= 0:
        return [0.0] * count
    step = max_sec / (count - 1)
    return [round(i * step, 2) for i in range(count)]


def _fit_monotonic(times: list[float], max_sec: float) -> list[float]:
    if not times:
        return []
    if len(times) == 1:
        return [round(max(0.0, min(times[0], max_sec)), 2)]

    out: list[float] = []
    for value in times:
        value = max(0.0, min(float(value), max_sec))
        if out and value < out[-1] + _MIN_GAP_SEC:
            value = out[-1] + _MIN_GAP_SEC
        out.append(value)

    if out[-1] > max_sec:
        return _even_times(len(times), max_sec)
    return [round(value, 2) for value in out]


def _best_cue_start(element_text: str, cues: list[dict[str, Any]]) -> float | None:
    best_score = 0.0
    best_start: float | None = None
    for cue in cues:
        score = _similarity(element_text, cue.get("text", ""))
        if score > best_score:
            best_score = score
            best_start = float(cue.get("start", 0.0))
    return best_start if best_score >= 0.08 else None


def build_segment_timing(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Build animation entries with deterministic ``trigger_at_sec`` values."""
    duration = segment.get("audio_duration_sec")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return list(segment.get("animations", []) or [])

    elements = [
        element for element in segment.get("elements", []) or []
        if isinstance(element, dict) and str(element.get("id") or "").strip()
    ]
    if not elements:
        return list(segment.get("animations", []) or [])

    cues = _segment_cues(segment)
    max_sec = _max_trigger_sec(float(duration))
    fallback = _even_times(len(elements), max_sec)
    proposed: list[float] = []

    for index, element in enumerate(elements):
        if index == 0 or element.get("type") == "heading":
            proposed.append(0.0)
            continue
        matched = _best_cue_start(_element_text(element), cues)
        proposed.append(fallback[index] if matched is None else matched)

    times = _fit_monotonic(proposed, max_sec)
    effects = _existing_effects(segment)
    animations: list[dict[str, Any]] = []
    for element, trigger in zip(elements, times):
        target = str(element.get("id"))
        animations.append({
            "target": target,
            "effect": effects.get(target, _DEFAULT_EFFECT),
            "trigger_at_sec": trigger,
        })
    return animations


def apply_timing(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Return a timed copy of ``storyboard`` with animation trigger times."""
    timed = copy.deepcopy(storyboard)
    for segment in timed.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        animations = build_segment_timing(segment)
        if animations:
            segment["animations"] = animations
    metadata = timed.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["timing_source"] = "deterministic_subtitle_cues"
    return timed


def write_timed_storyboard(
    storyboard: dict[str, Any],
    storyboard_path: str | Path,
) -> Path:
    """Write the timed storyboard copy next to the original storyboard."""
    timed = apply_timing(storyboard)
    out = timed_storyboard_path(storyboard_path)
    out.write_text(json.dumps(timed, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
