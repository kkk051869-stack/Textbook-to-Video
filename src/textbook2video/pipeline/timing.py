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
_LIST_KEYS = ("items", "steps", "headers", "rows", "points", "labels", "values", "questions")
_DEFAULT_EFFECT = "fadeInUp"
_MIN_GAP_SEC = 0.3
_DEFAULT_LEAD_SEC = 1.0


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


def _segment_cues(
    segment: dict[str, Any], sentence_cues: dict[str, Any] | list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    cues = build_subtitle_cues({"segments": [segment]}, sentence_cues=sentence_cues)
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


def _fit_monotonic(
    times: list[float],
    max_sec: float,
    provenance: list[dict[str, Any]] | None = None,
) -> list[float]:
    """Clamp trigger times while keeping semantic elements for one sentence together.

    The global minimum gap is a visual-stagger safeguard. It must not alter the
    semantic timing contract when adjacent elements are matched to the same cue.
    """
    if not times:
        return []
    if len(times) == 1:
        return [round(max(0.0, min(times[0], max_sec)), 2)]

    out: list[float] = []
    for index, value in enumerate(times):
        value = max(0.0, min(float(value), max_sec))
        previous = provenance[index - 1] if provenance and index > 0 else None
        current = provenance[index] if provenance and index < len(provenance) else None
        same_sentence = bool(
            previous
            and current
            and previous.get("trigger_source") == "text_match"
            and current.get("trigger_source") == "text_match"
            and previous.get("matched_sentence_id") == current.get("matched_sentence_id")
        )
        if out and value < out[-1] + _MIN_GAP_SEC and not same_sentence:
            value = out[-1] + _MIN_GAP_SEC
        out.append(value)

    if out[-1] > max_sec:
        return _even_times(len(times), max_sec)
    return [round(value, 2) for value in out]


def _best_cue(element_text: str, cues: list[dict[str, Any]]) -> tuple[int, float] | None:
    best_score = 0.0
    best: tuple[int, float] | None = None
    for index, cue in enumerate(cues):
        score = _similarity(element_text, cue.get("text", ""))
        if score > best_score:
            best_score = score
            best = (index, float(cue.get("start", 0.0)))
    return best if best_score >= 0.08 else None


def _fallback_trigger(element: dict[str, Any], index: int, duration: float) -> tuple[float, str]:
    """Return a conservative trigger for elements absent from the narration."""
    element_type = str(element.get("type") or element.get("visual_type") or "").lower()
    if index == 0 or element_type in {"heading", "title", "subtitle", "section_title"}:
        return 0.0, "structural_fallback"
    if element_type in {
        "image", "figure", "table", "comparison", "comparison_panel", "flow", "flow_step",
        "chart", "diagram", "formula", "code", "quote",
    }:
        return min(0.5, max(0.0, duration - 0.2)), "primary_visual_fallback"
    return min(0.8, max(0.0, duration - 0.2)), "decorative_fallback"


def build_segment_timing(
    segment: dict[str, Any], sentence_cues: dict[str, Any] | list[dict[str, Any]] | None = None,
    lead_sec: float = _DEFAULT_LEAD_SEC,
) -> list[dict[str, Any]]:
    """Build animation entries with deterministic, narration-aware trigger times.

    A text-matched element is shown ``lead_sec`` before its sentence starts. Elements
    absent from the narration receive a conservative structural/visual fallback.
    """
    duration = segment.get("audio_duration_sec")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return list(segment.get("animations", []) or [])

    elements = [
        element for element in segment.get("elements", []) or []
        if isinstance(element, dict) and str(element.get("id") or "").strip()
    ]
    if not elements:
        return list(segment.get("animations", []) or [])

    cues = _segment_cues(segment, sentence_cues)
    max_sec = _max_trigger_sec(float(duration))
    proposed: list[float] = []
    provenance: list[dict[str, Any]] = []

    for index, element in enumerate(elements):
        matched = _best_cue(_element_text(element), cues)
        if matched is not None:
            cue_index, cue_start = matched
            proposed.append(max(0.0, cue_start - max(0.0, float(lead_sec))))
            provenance.append({
                "trigger_source": "text_match",
                "matched_sentence_id": str(cues[cue_index].get("id") or f"sentence_{cue_index + 1}"),
                "lead_sec": round(max(0.0, float(lead_sec)), 2),
            })
        else:
            trigger, source = _fallback_trigger(element, index, float(duration))
            proposed.append(trigger)
            provenance.append({"trigger_source": source})

    times = _fit_monotonic(proposed, max_sec, provenance)
    effects = _existing_effects(segment)
    animations: list[dict[str, Any]] = []
    for element, trigger, details in zip(elements, times, provenance):
        target = str(element.get("id"))
        animation = {
            "target": target,
            "effect": effects.get(target, _DEFAULT_EFFECT),
            "trigger_at_sec": trigger,
        }
        animation.update(details)
        animations.append(animation)
    return animations


def apply_timing(
    storyboard: dict[str, Any],
    sentence_cues: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a timed copy of ``storyboard`` with animation trigger times."""
    timed = copy.deepcopy(storyboard)
    for segment in timed.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        segment_cues = sentence_cues
        if isinstance(sentence_cues, dict):
            segment_cues = [
                cue
                for group in sentence_cues.get("segments", []) or []
                if isinstance(group, dict) and str(group.get("segment_id")) == str(segment.get("id"))
                for cue in group.get("cues", []) or []
            ]
        animations = build_segment_timing(segment, segment_cues)
        if animations:
            segment["animations"] = animations
    metadata = timed.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["timing_source"] = (
            "sentence_cues" if sentence_cues else "deterministic_subtitle_cues"
        )
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
