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
    "alt",
    "name",
    "quote",
)
_LIST_KEYS = ("items", "steps", "headers", "rows", "points", "labels", "values", "questions")
_REFERENCE_KEYS = ("target", "reference", "bind_to", "parent_id")
_REFERENCE_TEXT_KEYS = ("text", "title", "label", "caption", "description", "alt")
_ALIASES = {
    "ai": "人工智能",
    "aigc": "生成式人工智能",
}
_TOKEN_STOPWORDS = {
    "一个", "一种", "这个", "这种", "我们", "能够", "可以", "通过", "以及", "不是",
    "因此", "目前", "未来", "我国", "数字", "字化", "经济", "发展", "实现", "方式", "重要",
    "转型", "企业", "全球", "竞争", "支撑", "成为",
}
_CJK_ANCHORS = {
    "芯片", "支柱", "技术", "信任", "哈希", "区块", "比特", "交易", "工厂", "自动化",
    "网络", "智能", "人工", "劳动", "人才", "生产", "传感", "平台", "金融", "点对", "对点",
}
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


def _alias_text(text: Any) -> tuple[str, bool]:
    """Apply only the small, unambiguous aliases used by the frozen cases."""
    value = str(text or "").lower()
    changed = False
    for alias, replacement in _ALIASES.items():
        updated = re.sub(
            rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
            replacement,
            value,
        )
        changed = changed or updated != value
        value = updated
    return value, changed


def _semantic_tokens(text: Any) -> set[str]:
    """Return meaningful CJK bigrams and technical/number tokens."""
    value, _ = _alias_text(text)
    tokens: set[str] = set()
    for match in re.finditer(r"\d+(?:\.\d+)?[a-z]*|[a-z]+", value):
        token = match.group(0)
        if token and token not in _TOKEN_STOPWORDS:
            tokens.add(token)
    for run in re.findall(r"[\u4e00-\u9fff]+", value):
        tokens.update(
            run[index : index + 2]
            for index in range(len(run) - 1)
            if run[index : index + 2] not in _TOKEN_STOPWORDS
        )
    return tokens


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


def _deterministic_match(
    element_text: str,
    cue_text: str,
) -> tuple[float, str] | None:
    """Return a high-confidence match before falling back to fuzzy similarity."""
    element_alias, element_changed = _alias_text(element_text)
    cue_alias, cue_changed = _alias_text(cue_text)
    element_normalized = _normalize_text(element_alias)
    cue_normalized = _normalize_text(cue_alias)
    if not element_normalized or not cue_normalized:
        return None
    if element_normalized == cue_normalized:
        return 1.0, "exact"

    shorter = min(element_normalized, cue_normalized, key=len)
    if len(shorter) >= 2 and shorter not in _TOKEN_STOPWORDS and (
        element_normalized in cue_normalized or cue_normalized in element_normalized
    ):
        method = "alias_overlap" if element_changed or cue_changed else "substring"
        return 0.96, method

    element_tokens = _semantic_tokens(element_alias)
    cue_tokens = _semantic_tokens(cue_alias)
    shared = element_tokens & cue_tokens
    if shared:
        # A single technical/number token is intentional evidence (5G, BTC, 0.5).
        # CJK bigrams are accepted when they are not generic stopwords.
        coverage = len(shared) / max(1, len(element_tokens))
        technical_shared = any(
            re.fullmatch(r"\d+(?:\.\d+)?[a-z]*|[a-z]+", token)
            for token in shared
        )
        anchor_shared = shared & _CJK_ANCHORS
        if coverage >= 0.35 or technical_shared or anchor_shared:
            method = "alias_overlap" if element_changed or cue_changed else "token_overlap"
            return round(0.88 + min(0.1, coverage * 0.1), 4), method
    return None


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


def _reference_text(element: dict[str, Any]) -> str:
    """Collect only the finite semantic fields allowed from a referenced element."""
    return " ".join(
        _collect_text({key: element.get(key) for key in _REFERENCE_TEXT_KEYS})
    )


def _element_text(
    element: dict[str, Any],
    references: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Collect own text and, for explicit relations, one referenced element's text."""
    own = " ".join(_collect_text(element))
    if not references:
        return own
    reference_id = next(
        (str(element.get(key)).strip() for key in _REFERENCE_KEYS if element.get(key)),
        None,
    )
    if not reference_id or reference_id not in references:
        return own
    parent = _reference_text(references[reference_id])
    return " ".join(value for value in (own, parent) if value)


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
    segment_cues = sentence_cues
    if isinstance(sentence_cues, dict):
        segment_cues = [
            cue
            for group in sentence_cues.get("segments", []) or []
            if isinstance(group, dict) and str(group.get("segment_id")) == str(segment.get("id"))
            for cue in group.get("cues", []) or []
            if isinstance(cue, dict)
        ]
    cues = build_subtitle_cues({"segments": [segment]}, sentence_cues=segment_cues)
    return [
        {
            "id": cue.sentence_id or f"sentence_{cue.index}",
            "sentence_id": cue.sentence_id or f"sentence_{cue.index}",
            "sentence_index": cue.sentence_index or cue.index,
            "start": cue.start_sec,
            "end": cue.end_sec,
            "start_sec": cue.start_sec,
            "end_sec": cue.end_sec,
            "text": cue.text,
        }
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
        both_structural = bool(
            previous
            and current
            and previous.get("trigger_source") == "structural_fallback"
            and current.get("trigger_source") == "structural_fallback"
        )
        if out and value < out[-1] + _MIN_GAP_SEC and not same_sentence and not both_structural:
            value = out[-1] + _MIN_GAP_SEC
        out.append(value)

    if out[-1] > max_sec:
        return _even_times(len(times), max_sec)
    return [round(value, 2) for value in out]


def _best_cue_details(
    own_text: str,
    reference_text: str,
    cues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for index, cue in enumerate(cues):
        cue_text = cue.get("text", "")
        deterministic = _deterministic_match(own_text, cue_text)
        if deterministic is not None:
            score, method = deterministic
        else:
            # Parent context is deliberately narrow: only a strong deterministic
            # match of the explicitly referenced element can rescue the child.
            if reference_text:
                parent_match = _deterministic_match(reference_text, cue_text)
                if parent_match is not None and parent_match[1] in {"exact", "substring", "alias_overlap"}:
                    score, method = parent_match[0], "parent_context"
                else:
                    score, method = _similarity(own_text, cue_text), "fuzzy"
            else:
                score, method = _similarity(own_text, cue_text), "fuzzy"
        candidate = {
            "index": index,
            "start": float(cue.get("start", cue.get("start_sec", 0.0))),
            "score": float(score),
            "method": method,
            "cue": cue,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    if best is None or best["score"] < 0.08:
        return None
    return best


def _best_cue(element_text: str, cues: list[dict[str, Any]]) -> tuple[int, float] | None:
    """Backward-compatible tuple view of the richer cue match details."""
    best = _best_cue_details(element_text, "", cues)
    if best is None:
        return None
    return int(best["index"]), float(best["start"])


def _fallback_trigger(element: dict[str, Any], index: int, duration: float) -> tuple[float, str]:
    """Return a conservative trigger for elements absent from the narration."""
    element_type = str(element.get("type") or element.get("visual_type") or "").lower()
    if index == 0 or element_type in {
        "heading", "title", "subtitle", "subheading", "section_title", "section_heading",
    }:
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
    references = {
        str(element.get("id")): element
        for element in elements
        if str(element.get("id") or "").strip()
    }
    max_sec = _max_trigger_sec(float(duration))
    proposed: list[float] = []
    provenance: list[dict[str, Any]] = []

    for index, element in enumerate(elements):
        own_text = " ".join(_collect_text(element))
        semantic_text = _element_text(element, references=references)
        reference_text = semantic_text[len(own_text) :].strip() if own_text else semantic_text
        matched = _best_cue_details(own_text, reference_text, cues)
        if matched is not None:
            cue_index = int(matched["index"])
            cue_start = float(matched["start"])
            proposed.append(max(0.0, cue_start - max(0.0, float(lead_sec))))
            provenance.append({
                "trigger_source": "text_match",
                "matched_sentence_id": str(
                    cues[cue_index].get("sentence_id")
                    or cues[cue_index].get("id")
                    or f"sentence_{cue_index + 1}"
                ),
                "matched_sentence_index": int(
                    cues[cue_index].get("sentence_index") or cue_index + 1
                ),
                "matched_sentence_text": str(cues[cue_index].get("text", "")),
                "match_score": round(float(matched["score"]), 4),
                "match_method": str(matched["method"]),
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
