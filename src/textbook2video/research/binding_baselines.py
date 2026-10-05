"""Deterministic, model-free baselines for narration-to-visual binding."""

from __future__ import annotations

import re
from typing import Any, Iterable

METHOD_NAME = "lexical_jaccard"
METHOD_VERSION = "lexical-jaccard-v0.1"
DEFAULT_THRESHOLD = 0.08
DEFAULT_TIE_MARGIN = 0.02

_TEXT_KEYS = (
    "text",
    "title",
    "label",
    "caption",
    "description",
    "name",
    "quote",
    "items",
    "steps",
    "headers",
    "rows",
    "points",
    "labels",
    "values",
    "payload",
)


def normalize_text(value: Any) -> str:
    """Normalize Chinese/Latin text without language-specific tokenization."""
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower(), flags=re.UNICODE)


def text_features(value: Any) -> set[str]:
    """Use characters and adjacent bigrams, matching the project's local baseline style."""
    text = normalize_text(value)
    if not text:
        return set()
    return set(text) | {text[index : index + 2] for index in range(max(0, len(text) - 1))}


def jaccard_similarity(left: Any, right: Any) -> float:
    first, second = text_features(left), text_features(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _collect_text(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        if text:
            yield text
        return
    if isinstance(value, list):
        for item in value:
            yield from _collect_text(item)
        return
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            if key in value:
                yield from _collect_text(value[key])


def element_text(element: dict[str, Any]) -> str:
    """Extract semantic surface text while excluding IDs and provenance metadata."""
    return " ".join(_collect_text(element)).strip()


def rank_elements(
    proposition_text: str,
    elements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a stable descending ranking; element ID breaks score ties."""
    ranked: list[dict[str, Any]] = []
    for element in elements:
        element_id = str(element.get("id") or "").strip()
        if not element_id:
            continue
        surface = element_text(element)
        ranked.append(
            {
                "element_id": element_id,
                "score": round(jaccard_similarity(proposition_text, surface), 6),
                "element_text": surface,
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["element_id"]))
    return ranked


def lexical_jaccard_bind(
    proposition_text: str,
    elements: Iterable[dict[str, Any]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    tie_margin: float = DEFAULT_TIE_MARGIN,
    max_targets: int = 1,
) -> dict[str, Any]:
    """Bind to the best lexical candidates or explicitly abstain.

    Multiple targets are returned only when callers request ``max_targets > 1``
    and their scores fall within ``tie_margin`` of the best score.  This is a
    baseline prediction, never a semantic-correctness guarantee.
    """
    threshold = min(1.0, max(0.0, float(threshold)))
    tie_margin = min(1.0, max(0.0, float(tie_margin)))
    max_targets = max(1, int(max_targets))
    ranked = rank_elements(proposition_text, elements)
    best_score = ranked[0]["score"] if ranked else 0.0
    if not ranked or best_score < threshold:
        return {
            "status": "abstained",
            "target_element_ids": [],
            "ranked_candidates": ranked,
            "confidence": round(best_score, 6),
            "binding_source": METHOD_NAME,
            "rationale": "no lexical candidate reached the configured threshold",
        }

    selected = [
        item
        for item in ranked
        if item["score"] >= threshold and best_score - item["score"] <= tie_margin
    ][:max_targets]
    return {
        "status": "bound",
        "target_element_ids": [item["element_id"] for item in selected],
        "ranked_candidates": ranked,
        "confidence": round(best_score, 6),
        "binding_source": METHOD_NAME,
        "rationale": "selected highest lexical Jaccard candidate(s) above threshold",
    }


__all__ = [
    "DEFAULT_THRESHOLD",
    "DEFAULT_TIE_MARGIN",
    "METHOD_NAME",
    "METHOD_VERSION",
    "element_text",
    "jaccard_similarity",
    "lexical_jaccard_bind",
    "normalize_text",
    "rank_elements",
    "text_features",
]
