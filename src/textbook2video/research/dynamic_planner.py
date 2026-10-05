"""Model-free assembly of binding-aware visual-event schedule predictions.

This module never mutates the production storyboard.  It joins existing visual
events and the canonical timed storyboard, producing an experiment report that
references the one authoritative schedule instead of inventing a second one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "visual-event-schedule-predictions-v0.1"


def _key(value: Any) -> str:
    return str(value or "").strip()


def _segment_index(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, segment in enumerate(document.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        for value in (
            segment.get("id"),
            segment.get("segment_id"),
            segment.get("legacy_segment_id"),
            index,
        ):
            key = _key(value)
            if key:
                result.setdefault(key, segment)
    return result


def _proposition_index(script: dict[str, Any]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for segment in script.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for proposition in segment.get("narration_propositions", []) or []:
            if not isinstance(proposition, dict):
                continue
            proposition_id = _key(proposition.get("id"))
            if proposition_id:
                result[proposition_id] = (segment, proposition)
    return result


def _fallback_time(
    script_segment: dict[str, Any],
    proposition: dict[str, Any],
    timed_segment: dict[str, Any] | None,
) -> float | None:
    """Local span-ratio fallback used only when the canonical schedule is absent."""
    if not timed_segment:
        return None
    duration = timed_segment.get("audio_duration_sec")
    span = proposition.get("span") if isinstance(proposition.get("span"), dict) else {}
    narration = str(script_segment.get("narration_text") or "")
    start = span.get("start")
    if not isinstance(duration, (int, float)) or duration <= 0:
        return None
    if not isinstance(start, int) or not narration:
        return None
    return round(min(float(duration), max(0.0, start / len(narration) * float(duration))), 6)


def build_event_schedule_report(
    script: dict[str, Any],
    storyboard: dict[str, Any],
    timed_storyboard: dict[str, Any],
    binding_report: dict[str, Any],
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Join bound propositions to existing visual events and their planned time."""
    resolved_case_id = _key(
        case_id
        or script.get("case_id")
        or storyboard.get("case_id")
        or binding_report.get("case_id")
    )
    if not resolved_case_id:
        raise ValueError("case_id is required")

    storyboard_segments = _segment_index(storyboard)
    timed_segments = _segment_index(timed_storyboard)
    propositions = _proposition_index(script)
    assignments: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    scheduled: dict[str, dict[str, Any]] = {}

    for binding in binding_report.get("bindings", []) or []:
        if not isinstance(binding, dict) or binding.get("status") != "bound":
            continue
        segment_id = _key(binding.get("segment_id"))
        proposition_id = _key(binding.get("narration_proposition_id"))
        visual_segment = storyboard_segments.get(segment_id)
        timed_segment = timed_segments.get(segment_id)
        if visual_segment is None:
            failures.append(
                {
                    "type": "missing_storyboard_segment",
                    "segment_id": segment_id,
                    "narration_proposition_id": proposition_id,
                }
            )
            continue
        event_candidates = [
            event for event in visual_segment.get("events", []) or [] if isinstance(event, dict)
        ]
        timed_events = {
            _key(event.get("event_id")): event
            for event in (timed_segment or {}).get("scheduled_events", []) or []
            if isinstance(event, dict) and _key(event.get("event_id"))
        }

        for target_id in binding.get("target_element_ids", []) or []:
            target_id = _key(target_id)
            matching = [
                event
                for event in event_candidates
                if _key(event.get("target_element_id")) == target_id
            ]
            exact = [
                event
                for event in matching
                if proposition_id
                in {_key(value) for value in event.get("narration_proposition_ids", []) or []}
            ]
            event = (exact or matching or [None])[0]
            if event is None:
                failures.append(
                    {
                        "type": "missing_visual_event",
                        "segment_id": segment_id,
                        "narration_proposition_id": proposition_id,
                        "target_element_id": target_id,
                    }
                )
                continue
            event_id = _key(event.get("id") or event.get("event_id"))
            if not event_id:
                failures.append(
                    {
                        "type": "visual_event_missing_id",
                        "segment_id": segment_id,
                        "narration_proposition_id": proposition_id,
                        "target_element_id": target_id,
                    }
                )
                continue

            planned = timed_events.get(event_id)
            timing_source = _key((planned or {}).get("timing_source"))
            trigger = (planned or {}).get("trigger_at_sec")
            duration = (planned or {}).get("planned_duration_sec")
            if not isinstance(trigger, (int, float)) or isinstance(trigger, bool):
                pair = propositions.get(proposition_id)
                trigger = _fallback_time(pair[0], pair[1], timed_segment) if pair else None
                timing_source = "narration_span_ratio" if trigger is not None else "missing"

            assignments.append(
                {
                    "segment_id": segment_id,
                    "narration_proposition_id": proposition_id,
                    "target_element_id": target_id,
                    "event_id": event_id,
                    "binding_source": binding.get("binding_source"),
                }
            )
            row = scheduled.setdefault(
                event_id,
                {
                    "event_id": event_id,
                    "segment_id": segment_id,
                    "target_element_id": target_id,
                    "action": _key(event.get("action") or (planned or {}).get("action") or "show"),
                    "narration_proposition_ids": [],
                    "planned_start_sec": round(float(trigger), 6) if trigger is not None else None,
                    "planned_duration_sec": (
                        round(float(duration), 6)
                        if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                        else None
                    ),
                    "timing_source": timing_source or "missing",
                    "schedule_authority": "storyboard_timed",
                },
            )
            if proposition_id not in row["narration_proposition_ids"]:
                row["narration_proposition_ids"].append(proposition_id)

    events = sorted(scheduled.values(), key=lambda item: (item["segment_id"], item["event_id"]))
    timed_count = sum(item["planned_start_sec"] is not None for item in events)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "binding_aware_schedule_predictions",
        "case_id": resolved_case_id,
        "uses_external_model": False,
        "assignments": assignments,
        "events": events,
        "metrics": {
            "assignment_count": len(assignments),
            "unique_event_count": len(events),
            "timed_event_count": timed_count,
            "timing_coverage": round(timed_count / len(events), 6) if events else 0.0,
        },
        "failures": failures,
    }


def write_event_schedule_report(report: dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


__all__ = ["SCHEMA_VERSION", "build_event_schedule_report", "write_event_schedule_report"]
