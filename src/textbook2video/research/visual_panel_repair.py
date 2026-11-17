"""Constrained additive repair when a reviewed panel omitted a later fact."""

from __future__ import annotations

from copy import deepcopy

from textbook2video.research.visual_narration_refs import narration_units


def can_append_missing_panel(review: dict, base: dict, narration: str) -> bool:
    """Offer an additive repair only when the old visual remains factually valid."""
    issues = review.get("issues") if isinstance(review, dict) else None
    checks = review.get("checks", {}) if isinstance(review, dict) else {}
    visuals = base.get("visuals") if isinstance(base, dict) else None
    return (
        isinstance(issues, list)
        and any(isinstance(i, dict) and i.get("category") == "missing_content" for i in issues)
        and all(isinstance(i, dict) and i.get("category") == "missing_content" for i in issues)
        and isinstance(checks, dict)
        and checks.get("accuracy") is not False
        and checks.get("relevance") is not False
        and isinstance(visuals, list)
        and len(visuals) == 1
        and isinstance(visuals[0], dict)
        and visuals[0].get("kind") != "none"
        and len(narration_units(narration)) >= 2
    )


def expand_missing_panel(arguments: dict, base: dict, narration: str) -> dict:
    """Preserve the reviewed visual and split immutable narration into two pages."""
    allowed = {"panel", "existing_narration_refs", "panel_narration_refs"}
    if not isinstance(arguments, dict) or set(arguments) != allowed:
        raise ValueError("missing-content repair needs only panel and two narration ref lists")
    old = base.get("visuals")
    if not isinstance(old, list) or len(old) != 1 or not isinstance(old[0], dict):
        raise ValueError("additive panel repair requires exactly one reviewed visual")
    panel = arguments["panel"]
    if not isinstance(panel, dict) or panel.get("id") == old[0].get("id"):
        raise ValueError("new panel needs a distinct visual ID")
    units = narration_units(narration)
    ids = [unit["id"] for unit in units]
    first, second = (arguments[key] for key in
                     ("existing_narration_refs", "panel_narration_refs"))
    if (
        not isinstance(first, list) or not isinstance(second, list)
        or not first or not second
        or first + second != ids
    ):
        raise ValueError(
            "two panels must partition all narration unit IDs exactly in original order"
        )
    if "narration_refs" in panel or "narration_span" in panel:
        raise ValueError("new panel narration is set only by panel_narration_refs")
    existing = deepcopy(old[0])
    existing.pop("narration_span", None)
    existing.pop("narration_refs", None)
    existing["narration_refs"] = deepcopy(first)
    added = deepcopy(panel)
    added["narration_refs"] = deepcopy(second)
    result = {k: deepcopy(v) for k, v in base.items()
              if k not in {"visuals", "parent", "reason", "applied_updates", "applied_changes"}}
    result["visuals"] = [existing, added]
    result.pop("composition", None)  # Two full-size course pages, never a thumbnail pair.
    return result
