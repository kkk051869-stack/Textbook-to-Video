"""Proposition-aware dynamic event planning for the second P0 phase.

This planner consumes frozen proposition timings and binding outputs.  It does
not estimate audio duration from character count and does not rewrite a
storyboard.  The result is a research-side event plan that the existing P0
adapter can apply to a copied candidate.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .signaling_policy import NO_SIGNAL, SIGNAL_POLICY_VERSION, choose_signal

DYNAMIC_PLAN_VERSION = "p0-dynamic-event-plan-v1.0"


def _number(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _binding_target(binding: dict[str, Any]) -> str | None:
    value = binding.get("selected_candidate_id") or binding.get("target_element_id")
    return str(value) if value else None


def _normalise_bindings(bindings: Any) -> dict[str, dict[str, Any]]:
    if isinstance(bindings, dict):
        values = bindings.values()
    else:
        values = bindings or []
    output: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        prop_id = str(item.get("proposition_id") or item.get("narration_proposition_id") or "")
        if not prop_id:
            continue
        # A comparison artifact may contain ``results``.  The caller should
        # select a method explicitly; otherwise prefer the proposed method.
        if isinstance(item.get("results"), list):
            proposed = next(
                (
                    result
                    for result in item["results"]
                    if result.get("method") == "source_conditioned"
                ),
                None,
            )
            item = proposed or item["results"][0] if item["results"] else item
        output[prop_id] = item
    return output


def _cleanup_action(
    proposition: dict[str, Any],
    *,
    last_end: float,
    segment_end: float,
    another_target_follows: bool,
) -> str | None:
    if not another_target_follows or segment_end <= last_end + 0.05:
        return None
    if bool(proposition.get("requires_exclusive_visual")):
        return "remove"
    if bool(proposition.get("keep_visual_until_segment_end")):
        return None
    return "dim"


def plan_dynamic_events(
    *,
    propositions: list[dict[str, Any]],
    bindings: list[dict[str, Any]] | dict[str, dict[str, Any]],
    segment_durations: dict[str, float] | None = None,
    require_measured_timing: bool = True,
    max_signals_in_window: int = 1,
) -> dict[str, Any]:
    """Plan show/focus/duration/cleanup from all related propositions.

    A missing ``start_sec``/``end_sec`` is reported as unresolved rather than
    filled by a character-ratio estimate.  For each target, the first bound
    proposition owns ``show``; later propositions may receive ``focus`` only
    if the signaling policy says so.
    """
    by_id = _normalise_bindings(bindings)
    durations = {str(key): float(value) for key, value in (segment_durations or {}).items()}
    grouped: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any], float, float]]] = (
        defaultdict(list)
    )
    unresolved: list[dict[str, Any]] = []
    unbound: list[str] = []
    for proposition in propositions:
        if not isinstance(proposition, dict):
            continue
        prop_id = str(proposition.get("id") or proposition.get("proposition_id") or "")
        binding = by_id.get(prop_id, {})
        target = _binding_target(binding)
        if not prop_id or not target or str(binding.get("status") or "").startswith("ABSTAINED"):
            if prop_id:
                unbound.append(prop_id)
            continue
        start = _number(proposition, "start_sec", "planned_start_sec", "sentence_start_sec")
        end = _number(proposition, "end_sec", "planned_end_sec", "sentence_end_sec")
        if start is None or end is None or end <= start:
            unresolved.append(
                {"proposition_id": prop_id, "reason": "measured_proposition_interval_missing"}
            )
            continue
        segment_id = str(proposition.get("segment_id") or "")
        grouped[(segment_id, target)].append(
            (proposition, binding, max(0.0, start), max(start, end))
        )

    if require_measured_timing and unresolved:
        return {
            "schema_version": DYNAMIC_PLAN_VERSION,
            "planner": "proposition_aware_dynamic_planner",
            "signaling_policy": SIGNAL_POLICY_VERSION,
            "events": [],
            "decisions": [],
            "unbound_propositions": unbound,
            "unresolved_propositions": unresolved,
            "status": "BLOCKED_MISSING_MEASURED_PROPOSITION_TIMING",
        }

    events: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    by_segment_targets: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (segment_id, target), entries in grouped.items():
        entries.sort(key=lambda item: (item[2], str(item[0].get("id") or "")))
        by_segment_targets[segment_id].append((target, entries[0][2]))
    for (segment_id, target), entries in grouped.items():
        entries.sort(key=lambda item: (item[2], str(item[0].get("id") or "")))
        segment_end = durations.get(segment_id, max(item[3] for item in entries))
        first_prop, first_binding, first_start, first_end = entries[0]
        target_count = len([value for value, _ in by_segment_targets[segment_id]])
        show_duration = max(0.1, min(segment_end - first_start, first_end - first_start))
        events.append(
            {
                "id": f"p0-dynamic-{first_prop.get('id')}-show",
                "segment_id": segment_id,
                "proposition_id": str(first_prop.get("id") or ""),
                "target_element_id": target,
                "action": "show",
                "effect": "fadeInUp",
                "at_sec": round(first_start, 4),
                "duration_sec": round(show_duration, 4),
                "signal_action": NO_SIGNAL,
                "decision_reason": "earliest_related_proposition",
            }
        )
        decisions.append(
            {
                "proposition_id": str(first_prop.get("id") or ""),
                "target_element_id": target,
                "show_at_sec": round(first_start, 4),
                "show_duration_sec": round(show_duration, 4),
            }
        )
        # This is a segment-wide budget rather than a per-target one: several
        # different figures appearing together must not each add a cue.
        signal_count = sum(
            1
            for item in events
            if item.get("segment_id") == segment_id and item.get("action") == "focus"
        )
        for proposition, binding, start, end in entries[1:]:
            confidence = float(binding.get("confidence") or binding.get("score") or 0.0)
            signal = choose_signal(
                proposition,
                target_element_id=target,
                related_target_count=target_count,
                signal_count_in_window=signal_count,
                max_signals_in_window=max_signals_in_window,
                confidence=confidence,
            )
            signal["target_element_id"] = target
            signal_count += int(signal["signal_action"] != NO_SIGNAL)
            focus_duration = max(0.1, min(2.0, end - start))
            if signal["signal_action"] != NO_SIGNAL:
                events.append(
                    {
                        "id": f"p0-dynamic-{proposition.get('id')}-focus",
                        "segment_id": segment_id,
                        "proposition_id": str(proposition.get("id") or ""),
                        "target_element_id": target,
                        "action": "focus",
                        "effect": signal["signal_effect"],
                        "at_sec": round(start, 4),
                        "duration_sec": round(focus_duration, 4),
                        "signal_action": signal["signal_action"],
                        "signal_effect": signal["signal_effect"],
                        "signal_reason": signal["reason"],
                    }
                )
            decisions.append(
                {
                    "proposition_id": str(proposition.get("id") or ""),
                    "target_element_id": target,
                    "focus_at_sec": round(start, 4),
                    "focus_duration_sec": round(focus_duration, 4),
                    "signal": signal,
                }
            )
        last_prop, _, _, last_end = entries[-1]
        follows = any(
            other_target != target and other_start >= last_end
            for other_target, other_start in by_segment_targets[segment_id]
        )
        cleanup = _cleanup_action(
            last_prop,
            last_end=last_end,
            segment_end=segment_end,
            another_target_follows=follows,
        )
        if cleanup:
            events.append(
                {
                    "id": f"p0-dynamic-{last_prop.get('id')}-{cleanup}",
                    "segment_id": segment_id,
                    "proposition_id": str(last_prop.get("id") or ""),
                    "target_element_id": target,
                    "action": cleanup,
                    "at_sec": round(last_end, 4),
                    "duration_sec": round(max(0.1, segment_end - last_end), 4),
                    "signal_action": NO_SIGNAL,
                    "decision_reason": "target_no_longer_relevant",
                }
            )
        decisions[-1]["cleanup"] = cleanup or "KEEP"

    priority = {"show": 0, "focus": 1, "dim": 2, "remove": 3}
    events.sort(
        key=lambda item: (
            float(item.get("at_sec") or 0.0),
            priority.get(item.get("action"), 9),
            item["id"],
        )
    )
    return {
        "schema_version": DYNAMIC_PLAN_VERSION,
        "planner": "proposition_aware_dynamic_planner",
        "signaling_policy": SIGNAL_POLICY_VERSION,
        "events": events,
        "decisions": decisions,
        "unbound_propositions": sorted(set(unbound)),
        "unresolved_propositions": unresolved,
        "status": "READY",
        "claim": (
            "Event plan uses measured proposition intervals; no character-ratio timing fallback."
        ),
    }


def write_dynamic_plan(path: str | Path, plan: dict[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


__all__ = ["DYNAMIC_PLAN_VERSION", "plan_dynamic_events", "write_dynamic_plan"]
