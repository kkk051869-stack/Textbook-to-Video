"""Deterministic A-track baselines expressed in the current P0 decision schema.

These policies are diagnostic predictions, not human gold.  Visual-support
need and acquisition are kept as separate fields so candidate availability
cannot silently redefine the primary research label.
"""

from __future__ import annotations

import re
from typing import Any

from textbook2video.research.visual_decision import normalize_visual_decision

BASELINE_VERSION = "a-visual-decision-baselines-v0.2"
BASELINE_POLICIES = (
    "never_retrieve",
    "always_retrieve",
    "keyword_heuristic",
    "pool_availability",
)
VISUAL_KEYWORDS = frozenset(
    {
        "图",
        "示意",
        "过程",
        "步骤",
        "变化",
        "结构",
        "组成",
        "关系",
        "比较",
        "对比",
        "位置",
        "方向",
        "分布",
        "流程",
        "机制",
        "循环",
        "蒸发",
        "凝结",
        "降水",
        "状态",
        "形状",
        "模型",
        "曲线",
        "几何",
        "空间",
        "地图",
        "细胞",
        "分子",
    }
)


def keyword_hits(text: str) -> list[str]:
    """Return matches from the frozen, deliberately small heuristic lexicon."""
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text).lower())
    tokens = set(normalized)
    tokens.update(normalized[index : index + 2] for index in range(max(0, len(normalized) - 1)))
    return sorted(
        keyword for keyword in VISUAL_KEYWORDS if keyword in tokens or keyword in normalized
    )


def predict_baseline(
    *,
    policy: str,
    proposition: dict[str, Any],
    source_image_ids: list[str] | None = None,
    external_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Predict one visual decision without a model, network call, or mutation."""
    if policy not in BASELINE_POLICIES:
        raise ValueError(f"unknown baseline policy: {policy}")
    proposition_id = str(
        proposition.get("narration_proposition_id")
        or proposition.get("knowledge_proposition_id")
        or proposition.get("id")
        or ""
    ).strip()
    if not proposition_id:
        raise ValueError("proposition requires an ID")
    source_ids = sorted({str(value) for value in source_image_ids or [] if str(value)})
    external_ids = sorted({str(value) for value in external_candidate_ids or [] if str(value)})
    hits = keyword_hits(str(proposition.get("text") or proposition.get("proposition_text") or ""))

    if policy == "always_retrieve":
        action = "retrieve"
        need = "extra-support-needed"
        rationale = "Always Retrieve triggers external acquisition for every proposition."
        confidence = 1.0
    elif source_ids:
        action = "reuse"
        need = "source-sufficient"
        rationale = "A linked source image is available, so the source-first baseline reuses it."
        confidence = 0.95
    elif policy == "never_retrieve":
        action = "none"
        need = "none"
        rationale = "Never Retrieve forbids external acquisition and no source image is linked."
        confidence = 1.0
    elif policy == "keyword_heuristic":
        action = "retrieve" if hits else "none"
        need = "extra-support-needed" if hits else "none"
        rationale = (
            "A frozen visual-type keyword triggers external acquisition."
            if hits
            else "No linked source image or frozen visual-type keyword is present."
        )
        confidence = 0.75 if hits else 0.6
    else:
        action = "retrieve" if external_ids else "none"
        need = "extra-support-needed" if external_ids else "none"
        rationale = (
            "A frozen external candidate exists, so acquisition is eligible."
            if external_ids
            else "No linked source image or frozen external candidate is available."
        )
        confidence = 0.8 if external_ids else 0.7

    raw = {
        "narration_proposition_id": proposition_id,
        "action": action,
        "decision_state": "DECIDED",
        "confidence": confidence,
        "rationale": rationale,
        "rationale_evidence": [
            {
                "kind": "deterministic_baseline_rule",
                "id": f"{BASELINE_VERSION}:{policy}",
                "quote": rationale,
                "status": "BASELINE_PREDICTION_NOT_SOURCE_GOLD",
            }
        ],
        "source_image_id": source_ids[0] if action == "reuse" else None,
        "retrieval_query": (
            str(proposition.get("text") or proposition.get("proposition_text") or "").strip()
            if action == "retrieve"
            else None
        ),
    }
    decision = normalize_visual_decision(
        raw,
        proposition=proposition,
        available_image_ids=set(source_ids),
    )
    decision.update(
        {
            "visual_support_need": need,
            "baseline_policy": policy,
            "baseline_version": BASELINE_VERSION,
            "source_image_ids": source_ids,
            "external_candidate_ids": external_ids,
            "keyword_hits": hits,
            "claim": "Deterministic diagnostic prediction; not human gold.",
        }
    )
    return decision


__all__ = [
    "BASELINE_POLICIES",
    "BASELINE_VERSION",
    "VISUAL_KEYWORDS",
    "keyword_hits",
    "predict_baseline",
]
