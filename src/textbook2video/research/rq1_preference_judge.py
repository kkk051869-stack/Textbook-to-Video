"""Forced-choice LLM/VLM Judge for RQ1 visual-support actions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from textbook2video.llm.client import chat_with_images, chat_with_system

PREFERENCE_JUDGE_VERSION = "rq1-visual-preference-judge-v0.3"
ALLOWED_ACTIONS = {"none", "reuse", "retrieve", "generate"}


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("RQ1 preference Judge did not return a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("RQ1 preference Judge response must be an object")
    return value


def normalize_preference_judgment(
    value: dict[str, Any],
    *,
    proposition_id: str,
    eligible_actions: list[str],
    judge_kind: str,
) -> dict[str, Any]:
    eligible = set(eligible_actions)
    if not eligible or not eligible <= ALLOWED_ACTIONS:
        raise ValueError("preference Judge has invalid eligible actions")
    abstain = bool(value.get("abstain"))
    ranking = value.get("ranking") or []
    if not isinstance(ranking, list) or any(not isinstance(item, str) for item in ranking):
        raise ValueError("preference Judge ranking must be a string list")
    if abstain:
        ranking = []
    elif len(ranking) != len(eligible) or set(ranking) != eligible:
        raise ValueError("preference Judge must rank every eligible action exactly once")

    reason_by_action = value.get("reason_by_action")
    if not isinstance(reason_by_action, dict):
        raise ValueError("preference Judge requires reason_by_action")
    normalized_reasons: dict[str, str] = {}
    for action in eligible_actions:
        reason = str(reason_by_action.get(action) or "").strip()
        if not reason:
            raise ValueError(f"preference Judge requires a reason for {action}")
        normalized_reasons[action] = reason

    rejected = value.get("rejected_actions") or []
    if not isinstance(rejected, list) or any(action not in eligible for action in rejected):
        raise ValueError("preference Judge rejected_actions must be eligible actions")
    if ranking and ranking[0] in rejected:
        raise ValueError("preference Judge cannot reject its best action")
    if rejected and ranking:
        rejected_set = set(rejected)
        first_rejected = min(ranking.index(action) for action in rejected_set)
        if set(ranking[first_rejected:]) != rejected_set:
            raise ValueError("preference Judge rejected actions must form the ranking suffix")
    try:
        confidence = float(value.get("confidence", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError("preference Judge confidence must be numeric") from exc
    confidence = max(0.0, min(1.0, confidence))
    abstain_reason = str(value.get("abstain_reason") or "").strip() or None
    if abstain and not abstain_reason:
        raise ValueError("preference Judge abstention requires abstain_reason")
    return {
        "schema_version": PREFERENCE_JUDGE_VERSION,
        "proposition_id": proposition_id,
        "judge_kind": judge_kind,
        "eligible_actions": eligible_actions,
        "ranking": ranking,
        "best_action": ranking[0] if ranking else None,
        "second_action": ranking[1] if len(ranking) > 1 else None,
        "rejected_actions": sorted(set(rejected)),
        "reason_by_action": normalized_reasons,
        "confidence": round(confidence, 4),
        "abstain": abstain,
        "abstain_reason": abstain_reason,
        "method_blind": True,
    }


def judge_rq1_action_preferences(
    *,
    proposition: dict[str, Any],
    source_evidence: list[dict[str, Any]],
    options: list[dict[str, Any]],
    candidate_images: list[str | Path] | None = None,
    model: str | None = None,
    text_call: Callable[..., str] = chat_with_system,
    image_call: Callable[..., str] = chat_with_images,
) -> dict[str, Any]:
    """Rank all eligible actions in one gold-blind call."""
    proposition_id = str(proposition.get("id") or "").strip()
    if not proposition_id:
        raise ValueError("preference Judge proposition requires id")
    actions = [str(option.get("action") or "") for option in options]
    if len(actions) != len(set(actions)) or not set(actions) <= ALLOWED_ACTIONS:
        raise ValueError("preference Judge options require unique valid actions")
    payload = {
        "task": (
            "Rank the eligible visual-support actions for this proposition. You must choose "
            "one best action unless the evidence is genuinely insufficient."
        ),
        "proposition": {
            "id": proposition_id,
            "text": proposition.get("text") or proposition.get("proposition_text"),
        },
        "source_evidence": source_evidence,
        "options_in_randomized_order": options,
        "rules": [
            "Judge actions comparatively, not as independent yes/no questions.",
            "Prefer the least costly action that still gives a clear instructional benefit.",
            "Reject decorative, redundant, generic, or weakly grounded visuals.",
            "Reuse is eligible only when its supplied image pixels explain the proposition.",
            (
                "For reuse, name the objects or relations actually visible in the image. "
                "Topic similarity is insufficient when the required mechanism is absent."
            ),
            "Retrieve needs a precise query and acceptance criteria.",
            "Generate needs a source-bounded instructional specification.",
            "Rank every eligible action exactly once; ties are not allowed.",
            "Method names, prior predictions, and gold labels are unavailable.",
            "Return JSON only.",
        ],
        "output": {
            "ranking": actions,
            "rejected_actions": ["zero or more actions"],
            "reason_by_action": {action: "short comparative reason" for action in actions},
            "confidence": "0..1",
            "abstain": False,
            "abstain_reason": None,
        },
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    images = list(candidate_images or [])
    call = image_call if images else text_call
    call_kwargs = {
        "system_prompt": "You are a strict comparative instructional-visual evaluator.",
        "model": model,
        "temperature": 0.0,
        "max_tokens": 1800,
        "timeout": 300,
    }
    if images:
        raw = call(
            prompt,
            images,
            **call_kwargs,
        )
        judge_kind = "VLM"
    else:
        raw = call(
            prompt,
            **call_kwargs,
        )
        judge_kind = "LLM"
    try:
        result = normalize_preference_judgment(
            _parse_json(raw),
            proposition_id=proposition_id,
            eligible_actions=actions,
            judge_kind=judge_kind,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        repair_prompt = json.dumps(
            {
                "task": "Repair only the response format; preserve the prior comparative judgment.",
                "validation_error": str(exc),
                "eligible_actions": actions,
                "requirements": [
                    "ranking must contain every eligible action exactly once",
                    "reason_by_action must contain every eligible action",
                    "rejected_actions may contain only eligible actions",
                    "rejected_actions must be a suffix at the end of ranking",
                    "return JSON only",
                ],
                "previous_response": raw,
            },
            ensure_ascii=False,
            indent=2,
        )
        if images:
            repaired_raw = call(repair_prompt, images, **call_kwargs)
        else:
            repaired_raw = call(repair_prompt, **call_kwargs)
        result = normalize_preference_judgment(
            _parse_json(repaired_raw),
            proposition_id=proposition_id,
            eligible_actions=actions,
            judge_kind=judge_kind,
        )
        result["format_repair_used"] = True
        result["initial_validation_error"] = str(exc)
        result["raw_response"] = raw
        result["repair_response"] = repaired_raw
        return result
    result["format_repair_used"] = False
    result["raw_response"] = raw
    return result


__all__ = [
    "ALLOWED_ACTIONS",
    "PREFERENCE_JUDGE_VERSION",
    "judge_rq1_action_preferences",
    "normalize_preference_judgment",
]
