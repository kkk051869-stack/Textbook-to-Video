"""Gold-blind LLM/VLM Judge contract for RQ1 development comparisons."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from textbook2video.llm.client import chat_with_images, chat_with_system

JUDGE_VERSION = "rq1-visual-judge-v0.1"
VERDICTS = {"ACCEPT", "REVISE", "REJECT", "ABSTAIN"}
SCORE_FIELDS = (
    "necessity_correctness",
    "source_grounding",
    "coherence",
    "candidate_appropriateness",
)


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("RQ1 Judge did not return a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("RQ1 Judge response must be an object")
    return value


def normalize_rq1_judgment(
    value: dict[str, Any],
    *,
    proposition_id: str,
    judge_kind: str,
) -> dict[str, Any]:
    verdict = str(value.get("verdict") or "").upper().strip()
    if verdict not in VERDICTS:
        raise ValueError(f"invalid RQ1 Judge verdict: {verdict!r}")
    scores = value.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("RQ1 Judge requires scores")
    normalized_scores: dict[str, float | None] = {}
    for field in SCORE_FIELDS:
        raw = scores.get(field)
        if raw is None and field == "candidate_appropriateness":
            normalized_scores[field] = None
            continue
        try:
            score = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"RQ1 Judge score {field} must be numeric") from exc
        if not 0.0 <= score <= 4.0:
            raise ValueError(f"RQ1 Judge score {field} must be within 0..4")
        normalized_scores[field] = score
    reason = str(value.get("reason") or "").strip()
    if not reason:
        raise ValueError("RQ1 Judge requires a reason")
    issues = value.get("issues") or []
    if not isinstance(issues, list) or any(not isinstance(item, str) for item in issues):
        raise ValueError("RQ1 Judge issues must be a string list")
    return {
        "schema_version": JUDGE_VERSION,
        "proposition_id": proposition_id,
        "judge_kind": judge_kind,
        "verdict": verdict,
        "scores": normalized_scores,
        "reason": reason,
        "issues": issues,
        "gold_blind": True,
    }


def judge_rq1_decision(
    *,
    proposition: dict[str, Any],
    source_evidence: list[dict[str, Any]],
    decision: dict[str, Any],
    candidate_image: str | Path | None = None,
    model: str | None = None,
    text_call: Callable[..., str] = chat_with_system,
    image_call: Callable[..., str] = chat_with_images,
) -> dict[str, Any]:
    """Judge one decision without exposing reference labels or method identity."""
    proposition_id = str(proposition.get("id") or "").strip()
    if not proposition_id:
        raise ValueError("RQ1 Judge proposition requires id")
    payload = {
        "task": "Judge whether the proposed visual-support decision is instructionally justified.",
        "proposition": {
            "id": proposition_id,
            "text": proposition.get("text") or proposition.get("proposition_text"),
            "learning_context": proposition.get("learning_context"),
        },
        "source_evidence": source_evidence,
        "decision": {
            key: decision.get(key)
            for key in (
                "action",
                "rationale",
                "source_image_id",
                "retrieval_query",
                "acceptance_criteria",
                "generation_prompt",
            )
        },
        "rubric": {
            "necessity_correctness": "Does the proposition genuinely benefit from this amount of visual support?",
            "source_grounding": "Is the decision supported by the supplied source evidence?",
            "coherence": "Does it avoid decorative, redundant, or distracting visual content?",
            "candidate_appropriateness": "If an image is supplied, does it explain this proposition? Otherwise null.",
        },
        "rules": [
            "Use only the supplied proposition, source evidence, decision, and image pixels.",
            "Do not assume that more visual content is better.",
            "A rationale may be omitted to blind the compared method; do not penalize its absence.",
            "ABSTAIN when the supplied evidence cannot support a reliable judgment.",
            "Return JSON only.",
        ],
        "output": {
            "verdict": "ACCEPT|REVISE|REJECT|ABSTAIN",
            "scores": {field: "0..4 or null where allowed" for field in SCORE_FIELDS},
            "reason": "short evidence-based reason",
            "issues": ["short issue"],
        },
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    if candidate_image is None:
        raw = text_call(
            prompt,
            system_prompt="You are a strict instructional-visual RQ1 evaluator.",
            model=model,
            temperature=0.0,
            max_tokens=1200,
            timeout=300,
        )
        judge_kind = "LLM"
    else:
        raw = image_call(
            prompt,
            [candidate_image],
            system_prompt="You are a strict instructional-visual RQ1 evaluator.",
            model=model,
            temperature=0.0,
            max_tokens=1200,
            timeout=300,
        )
        judge_kind = "VLM"
    return normalize_rq1_judgment(
        _parse_json(raw), proposition_id=proposition_id, judge_kind=judge_kind
    )


__all__ = [
    "JUDGE_VERSION",
    "SCORE_FIELDS",
    "judge_rq1_decision",
    "normalize_rq1_judgment",
]
