"""Validate signaling events before they enter the production timeline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


SIGNAL_ACTIONS = frozenset({"focus", "highlight", "pulse", "dim"})


def diagnose_signaling(
    *,
    events: list[dict[str, Any]],
    elements_by_segment: dict[str, set[str]],
    propositions: dict[str, dict[str, Any]],
    max_signals_per_window: int = 2,
    window_sec: float = 3.0,
) -> dict[str, Any]:
    """Return target, grounding, duplicate, and overload diagnostics.

    This is a production-adjacent validator, not an assertion that a signal is
    pedagogically beneficial.  It fails closed on a missing target/proposition
    and reports density separately so a reviewer can inspect real candidates.
    """
    findings: list[dict[str, Any]] = []
    signal_events = [event for event in events if str(event.get("action") or "") in SIGNAL_ACTIONS]
    by_segment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str, str]] = set()
    for event in signal_events:
        event_id = str(event.get("id") or "")
        segment_id = str(event.get("segment_id") or "")
        target = str(event.get("target_element_id") or "")
        proposition_id = str(event.get("proposition_id") or "")
        if target not in elements_by_segment.get(segment_id, set()):
            findings.append({"event_id": event_id, "severity": "ERROR", "code": "SIGNAL_TARGET_MISSING"})
        if proposition_id not in propositions:
            findings.append({"event_id": event_id, "severity": "ERROR", "code": "SIGNAL_PROPOSITION_MISSING"})
        elif str(propositions[proposition_id].get("segment_id") or "") != segment_id:
            findings.append({"event_id": event_id, "severity": "ERROR", "code": "SIGNAL_CROSS_SEGMENT_BINDING"})
        pair = (segment_id, target, proposition_id)
        if pair in seen_pairs:
            findings.append({"event_id": event_id, "severity": "WARNING", "code": "DUPLICATE_SIGNAL_BINDING"})
        seen_pairs.add(pair)
        by_segment[segment_id].append(event)
    for segment_id, segment_events in by_segment.items():
        ordered = sorted(segment_events, key=lambda item: float(item.get("lead_sec") or 0.0))
        for index, event in enumerate(ordered):
            start = float(event.get("lead_sec") or 0.0)
            density = [
                other for other in ordered
                if abs(float(other.get("lead_sec") or 0.0) - start) <= window_sec
            ]
            if len(density) > max_signals_per_window:
                findings.append({
                    "event_id": str(event.get("id") or ""), "severity": "WARNING",
                    "code": "SIGNAL_DENSITY_EXCEEDED", "segment_id": segment_id,
                    "window_sec": window_sec, "count": len(density),
                })
    return {
        "schema_version": "p0-signaling-diagnostics-v1.0",
        "signal_event_count": len(signal_events),
        "findings": findings,
        "pass": not any(item["severity"] == "ERROR" for item in findings),
        "claim": "Structural and timing-density validation; pedagogical appropriateness remains an evaluable hypothesis.",
    }


__all__ = ["SIGNAL_ACTIONS", "diagnose_signaling"]
