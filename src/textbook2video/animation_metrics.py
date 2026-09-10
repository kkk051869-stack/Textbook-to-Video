"""Small, schema-agnostic metrics over a compiled plan and browser trace.

This is deliberately not an evaluation harness.  It only gives the A line a
deterministic way to aggregate the raw animation plan and ``animationTrace``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


SUPPORTED_ACTIONS = frozenset({"show", "highlight", "dim", "focus", "draw", "grow", "move"})
SUPPORTED_EFFECTS = frozenset({
    "fadeIn", "fadeInUp", "fadeInLeft", "fadeInRight", "fadeInDown",
    "bounceIn", "zoomIn", "slideInLeft", "slideInRight", "drawPath", "growBar",
    "pulse", "highlight", "fadeOut", "legacy",
})


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def compute_animation_metrics(
    planned_events: Iterable[Mapping[str, Any]],
    trace: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate B-owned metrics from one compiled plan and one raw trace.

    The denominator for target resolution is every compiled event, including
    events retained for an unresolved target.  Compiler-rejected invalid
    actions are not compiled events and therefore require a separate compiler
    diagnostic if A wants to include them in a planning denominator.
    """
    planned_by_id: dict[str, dict[str, Any]] = {}
    duplicate_planned_event_count = 0
    for event in planned_events:
        if not isinstance(event, Mapping):
            continue
        event_copy = dict(event)
        event_id = str(event_copy.get("event_id"))
        if event_id in planned_by_id:
            duplicate_planned_event_count += 1
            continue
        planned_by_id[event_id] = event_copy
    planned = list(planned_by_id.values())
    plan_by_id = planned_by_id

    # A slide can be entered more than once, which legitimately appends another
    # trace row with the same event_id.  Metrics are for one compiled plan, so
    # count each planned event at most once; otherwise rates could exceed 100%.
    observed_by_id: dict[str, dict[str, Any]] = {}
    duplicate_trace_event_count = 0
    for entry in trace:
        if not isinstance(entry, Mapping):
            continue
        entry_copy = dict(entry)
        event_id = str(entry_copy.get("event_id"))
        if event_id not in plan_by_id:
            continue
        if event_id in observed_by_id:
            duplicate_trace_event_count += 1
            continue
        observed_by_id[event_id] = entry_copy
    observed = list(observed_by_id.values())

    resolved = sum(entry.get("status") in {"executed", "unsupported_action"} for entry in observed)
    supported_plan = [
        event
        for event in planned
        if event.get("action") in SUPPORTED_ACTIONS
        and event.get("effect") in SUPPORTED_EFFECTS
    ]
    supported_ids = {str(event.get("event_id")) for event in supported_plan}
    realized = sum(
        entry.get("status") == "executed"
        and str(entry.get("event_id")) in supported_ids
        and entry.get("action") == plan_by_id[str(entry.get("event_id"))].get("action")
        and entry.get("effect") == plan_by_id[str(entry.get("event_id"))].get("effect")
        for entry in observed
    )

    unsupported_action_count = 0
    unsupported_effect_count = 0
    for entry in observed:
        if entry.get("status") != "unsupported_action":
            continue
        error = str(entry.get("error") or "")
        if error.startswith("unsupported_effect:"):
            unsupported_effect_count += 1
        else:
            unsupported_action_count += 1

    timing_samples = [
        abs(actual - planned_ms)
        for entry in observed
        if entry.get("status") == "executed"
        for planned_ms, actual in [(_number(entry.get("planned_ms")), _number(entry.get("actual_ms")))]
        if planned_ms is not None and actual is not None
    ]

    total_targets = len(planned)
    total_supported = len(supported_plan)
    return {
        "target_total": total_targets,
        "target_resolved": resolved,
        "target_resolution_rate": resolved / total_targets if total_targets else 0.0,
        "effect_supported_total": total_supported,
        "effect_realized": realized,
        "effect_realization_rate": realized / total_supported if total_supported else 0.0,
        "unsupported_action_count": unsupported_action_count,
        "unsupported_effect_count": unsupported_effect_count,
        "runtime_error_count": sum(entry.get("status") == "runtime_error" for entry in observed),
        "timing_sample_count": len(timing_samples),
        "timing_mae_ms": sum(timing_samples) / len(timing_samples) if timing_samples else 0.0,
        "unobserved_event_count": max(0, total_targets - len(observed)),
        "duplicate_planned_event_count": duplicate_planned_event_count,
        "duplicate_trace_event_count": duplicate_trace_event_count,
    }
