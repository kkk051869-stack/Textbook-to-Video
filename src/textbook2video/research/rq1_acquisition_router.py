"""Route an accepted visual need to retrieval or source-bounded generation.

The router does not decide whether a proposition needs a visual.  It only
refines an existing ``retrieve`` request, keeping the RQ1 necessity decision
separate from the acquisition-mode decision.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

ROUTER_VERSION = "rq1-acquisition-router-v0.1"

_COMPOSITION_CUES = (
    "schematic",
    "diagram",
    "infographic",
    "timeline",
    "comparison",
    "side-by-side",
    "versus",
    " vs ",
    "mechanism",
    "process",
    "workflow",
    "flowchart",
    "relationship",
    "showing nodes",
    "network diagram",
    "示意图",
    "流程图",
    "时间线",
    "对比图",
    "机制图",
    "关系图",
)

_RETRIEVAL_CUES = (
    "photograph",
    "photo of",
    "archival photo",
    "historical photo",
    "official chart",
    "official table",
    "official document",
    "screenshot",
    "satellite image",
    "map of",
    "public-domain image",
    "实物照片",
    "历史照片",
    "官方图表",
    "官方文件",
    "截图",
    "卫星图",
    "地图",
)


def _text(decision: dict[str, Any]) -> str:
    values = [
        decision.get("retrieval_query"),
        decision.get("rationale"),
        *(decision.get("acceptance_criteria") or []),
    ]
    return " ".join(str(value or "") for value in values).casefold()


def _hits(text: str, cues: tuple[str, ...]) -> list[str]:
    normalized = re.sub(r"\s+", " ", text)
    return [cue for cue in cues if cue in normalized]


def route_acquisition(decision: dict[str, Any]) -> dict[str, Any]:
    """Return an auditable routed copy without mutating the original decision."""
    routed = deepcopy(decision)
    original_action = str(routed.get("action") or "").lower()
    diagnostic = {
        "router_version": ROUTER_VERSION,
        "original_action": original_action,
        "routed_action": original_action,
        "composition_cues": [],
        "retrieval_cues": [],
        "changed": False,
        "review_required": False,
        "reason": "Only existing retrieve requests are routed.",
    }
    if original_action != "retrieve":
        routed["acquisition_routing"] = diagnostic
        return routed

    combined = _text(routed)
    composition_hits = _hits(combined, _COMPOSITION_CUES)
    retrieval_hits = _hits(combined, _RETRIEVAL_CUES)
    diagnostic["composition_cues"] = composition_hits
    diagnostic["retrieval_cues"] = retrieval_hits

    # A bespoke composition combines source facts into a new explanatory
    # relation.  Retrieval remains preferred for concrete existing evidence.
    if composition_hits and not retrieval_hits:
        routed["action"] = "generate"
        routed["generation_prompt"] = (
            "Create a source-bounded instructional visual for: "
            + str(routed.get("retrieval_query") or "").strip()
        )
        routed["retrieval_query"] = None
        routed["retrieval_suitability"] = "UNSUITABLE"
        routed["status"] = "ROUTED_TO_GENERATION"
        diagnostic.update(
            {
                "routed_action": "generate",
                "changed": True,
                "reason": (
                    "The request specifies a composed explanatory visual rather than an "
                    "existing real-world or official asset."
                ),
            }
        )
    elif retrieval_hits:
        if composition_hits:
            diagnostic["review_required"] = True
            diagnostic["reason"] = (
                "The request mixes an existing evidence asset with a composed explanatory "
                "visual; preserve retrieval but require acquisition-mode review."
            )
        else:
            diagnostic["reason"] = (
                "The request targets an existing real-world, archival, map, screenshot, or "
                "official asset suitable for retrieval."
            )
    else:
        diagnostic["reason"] = (
            "No reliable acquisition-mode cue was found; preserve retrieval for review."
        )
    routed["acquisition_routing"] = diagnostic
    return routed


__all__ = ["ROUTER_VERSION", "route_acquisition"]
