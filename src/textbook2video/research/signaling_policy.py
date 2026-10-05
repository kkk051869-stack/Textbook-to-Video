"""Local signaling-policy audit over binding-aware event schedules."""

from __future__ import annotations

from typing import Any

SIGNAL_ACTIONS = {"highlight", "focus", "dim"}


def audit_signaling_policy(
    storyboard: dict[str, Any],
    schedule_report: dict[str, Any],
) -> dict[str, Any]:
    """Detect explicit, missing, and excessive cues without modifying events."""
    elements: dict[str, dict[str, Any]] = {}
    for segment in storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for element in segment.get("elements", []) or []:
            if isinstance(element, dict) and element.get("id"):
                elements[str(element["id"])] = element

    rows: list[dict[str, Any]] = []
    for event in schedule_report.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        element_id = str(event.get("target_element_id") or "")
        element = elements.get(element_id, {})
        action = str(event.get("action") or "")
        role = str(element.get("semantic_role") or "")
        cue_required = role == "signal"
        explicit_cue = action in SIGNAL_ACTIONS
        if cue_required and not explicit_cue:
            status = "missing_signal"
        elif not cue_required and explicit_cue:
            status = "possibly_excessive_signal"
        elif explicit_cue:
            status = "signal_present"
        else:
            status = "not_applicable"
        rows.append(
            {
                "event_id": event.get("event_id"),
                "target_element_id": element_id,
                "action": action,
                "element_semantic_role": role or None,
                "cue_required": cue_required,
                "explicit_cue": explicit_cue,
                "status": status,
            }
        )

    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in {
            "missing_signal",
            "possibly_excessive_signal",
            "signal_present",
            "not_applicable",
        }
    }
    return {
        "schema_version": "signaling-policy-audit-v0.1",
        "report_type": "signaling_policy_audit",
        "case_id": schedule_report.get("case_id"),
        "uses_external_model": False,
        "events": rows,
        "metrics": {"event_count": len(rows), **counts},
        "warning": (
            "This rule audit checks declared role/action consistency, "
            "not pedagogical necessity."
        ),
    }


__all__ = ["SIGNAL_ACTIONS", "audit_signaling_policy"]
