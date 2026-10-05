"""Cloud-model proposition-to-element binding baseline.

This module is intentionally separate from the model-free lexical baseline.
It accepts an injected OpenAI-compatible client so local tests never contact a
model service; callers must persist the raw response and run metadata.
"""

from __future__ import annotations

from typing import Any

from .binding_baselines import element_text
from .semantic_binding import _key, _storyboard_segments

SCHEMA_VERSION = "cloud-proposition-visual-binding-v0.1"
PROMPT_VERSION = "cloud-binding-v0.1"


def _prediction(raw: Any, allowed_ids: set[str]) -> tuple[dict[str, Any], str | None]:
    if not isinstance(raw, dict):
        return _abstain("model response was not a JSON object"), "response_not_object"
    status = str(raw.get("status") or "abstained")
    selected = raw.get("target_element_ids", [])
    selected = selected if isinstance(selected, list) else []
    targets = [str(item) for item in selected if str(item) in allowed_ids]
    invalid = [str(item) for item in selected if str(item) not in allowed_ids]
    if status != "bound" or not targets:
        return _abstain(str(raw.get("rationale") or "model abstained")), (
            "invalid_target_id" if invalid else None
        )
    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "status": "bound",
        "target_element_ids": list(dict.fromkeys(targets))[:2],
        "confidence": round(confidence, 6),
        "rationale": str(raw.get("rationale") or "model selected candidate")[:1200],
    }, "invalid_target_id" if invalid else None


def _abstain(rationale: str) -> dict[str, Any]:
    return {
        "status": "abstained",
        "target_element_ids": [],
        "confidence": 0.0,
        "rationale": rationale[:1200],
    }


def _messages(proposition: str, elements: list[dict[str, Any]]) -> list[dict[str, str]]:
    candidates = [
        {"element_id": str(item["id"]), "type": item.get("type"), "text": element_text(item)[:800]}
        for item in elements
        if item.get("id")
    ]
    return [
        {
            "role": "system",
            "content": (
                "You bind one narration proposition to explanatory visual elements in an "
                "educational video. Select only supplied IDs with a direct semantic relation; "
                "otherwise abstain. Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": str(
                {
                    "proposition": proposition,
                    "candidates": candidates,
                    "output": {
                        "status": "bound|abstained",
                        "target_element_ids": ["supplied IDs only"],
                        "confidence": "0..1",
                        "rationale": "short reason",
                    },
                }
            ),
        },
    ]


def build_cloud_binding_report(
    script: dict[str, Any],
    storyboard: dict[str, Any],
    *,
    case_id: str,
    client: Any,
    model: str,
    max_tokens: int = 400,
) -> dict[str, Any]:
    """Call a cloud model once per proposition and retain every raw response."""
    by_segment = _storyboard_segments(storyboard)
    bindings, failures = [], []
    for position, segment in enumerate(script.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        segment_id = _key(segment.get("id") or segment.get("segment_id") or position)
        legacy_segment_id = _key(segment.get("legacy_segment_id"))
        visual = by_segment.get(segment_id) or by_segment.get(legacy_segment_id)
        if not visual:
            failures.append({"type": "missing_storyboard_segment", "segment_id": segment_id})
            continue
        elements = [item for item in visual.get("elements", []) or [] if isinstance(item, dict)]
        allowed = {_key(item.get("id")) for item in elements if _key(item.get("id"))}
        for proposition in segment.get("narration_propositions", []) or []:
            if not isinstance(proposition, dict):
                continue
            proposition_id, text = _key(proposition.get("id")), _key(proposition.get("text"))
            if not proposition_id or not text:
                failures.append({"type": "invalid_narration_proposition", "segment_id": segment_id})
                continue
            parsed, raw = client.chat(_messages(text, elements), max_tokens=max_tokens)
            prediction, failure = _prediction(parsed, allowed)
            if failure:
                failures.append({"type": failure, "narration_proposition_id": proposition_id})
            bindings.append(
                {
                    "binding_id": f"{case_id}-cloud-binding-{len(bindings)+1:04d}",
                    "segment_id": _key(visual.get("id") or segment_id),
                    "narration_proposition_id": proposition_id,
                    **prediction,
                    "raw_response": raw,
                }
            )
    bound = sum(item["status"] == "bound" for item in bindings)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "cloud_semantic_binding_predictions",
        "case_id": case_id,
        "method": {
            "name": "cloud_llm_direct_binding",
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "uses_external_model": True,
        },
        "bindings": bindings,
        "metrics": {
            "proposition_count": len(bindings),
            "bound_count": bound,
            "abstained_count": len(bindings) - bound,
            "binding_coverage": round(bound / len(bindings), 6) if bindings else 0.0,
        },
        "failures": failures,
    }


__all__ = ["PROMPT_VERSION", "SCHEMA_VERSION", "build_cloud_binding_report"]
