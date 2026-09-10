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
EventKey = tuple[str, str]


def _event_key(event: Mapping[str, Any]) -> EventKey:
    """Use slide scope when available, while keeping legacy single-page data usable."""
    return (
        str(event.get("slide_id") or ""),
        str(event.get("event_id") or ""),
    )


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
    planned_by_key: dict[EventKey, dict[str, Any]] = {}
    planned_keys_by_event_id: dict[str, list[EventKey]] = {}
    duplicate_planned_event_count = 0
    for event in planned_events:
        if not isinstance(event, Mapping):
            continue
        event_copy = dict(event)
        key = _event_key(event_copy)
        if key in planned_by_key:
            duplicate_planned_event_count += 1
            continue
        planned_by_key[key] = event_copy
        planned_keys_by_event_id.setdefault(key[1], []).append(key)
    planned = list(planned_by_key.values())

    # A slide can be entered more than once, which legitimately appends another
    # trace row with the same (slide_id, event_id).  Metrics are for one
    # compiled plan, so count each planned event at most once; otherwise rates
    # could exceed 100%.
    observed_by_key: dict[EventKey, dict[str, Any]] = {}
    duplicate_trace_event_count = 0
    for entry in trace:
        if not isinstance(entry, Mapping):
            continue
        entry_copy = dict(entry)
        trace_key = _event_key(entry_copy)
        key = trace_key if trace_key in planned_by_key else None
        if key is None:
            candidates = planned_keys_by_event_id.get(trace_key[1], [])
            # Legacy traces sometimes omit slide_id.  Fall back only when the
            # event_id identifies one plan event and neither side contradicts
            # the known slide scope.
            if len(candidates) == 1 and (
                not trace_key[0] or not candidates[0][0]
            ):
                key = candidates[0]
        if key is None:
            continue
        if key in observed_by_key:
            duplicate_trace_event_count += 1
            continue
        observed_by_key[key] = entry_copy
    observed = list(observed_by_key.items())

    resolved = sum(
        entry.get("status") in {"executed", "unsupported_action"}
        for _, entry in observed
    )
    supported_plan = [
        (key, event)
        for key, event in planned_by_key.items()
        if event.get("action") in SUPPORTED_ACTIONS
        and event.get("effect") in SUPPORTED_EFFECTS
    ]
    supported_keys = {key for key, _ in supported_plan}
    realized = sum(
        entry.get("status") == "executed"
        and key in supported_keys
        and entry.get("action") == planned_by_key[key].get("action")
        and entry.get("effect") == planned_by_key[key].get("effect")
        for key, entry in observed
    )

    unsupported_action_count = 0
    unsupported_effect_count = 0
    for _, entry in observed:
        if entry.get("status") != "unsupported_action":
            continue
        error = str(entry.get("error") or "")
        if error.startswith("unsupported_effect:"):
            unsupported_effect_count += 1
        else:
            unsupported_action_count += 1

    timing_samples = [
        abs(actual - planned_ms)
        for _, entry in observed
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
        "runtime_error_count": sum(
            entry.get("status") == "runtime_error" for _, entry in observed
        ),
        "timing_sample_count": len(timing_samples),
        "timing_mae_ms": sum(timing_samples) / len(timing_samples) if timing_samples else 0.0,
        "unobserved_event_count": max(0, total_targets - len(observed)),
        "duplicate_planned_event_count": duplicate_planned_event_count,
        "duplicate_trace_event_count": duplicate_trace_event_count,
    }
