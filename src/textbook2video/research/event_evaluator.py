"""Event-level evaluation that keeps planned, compiled, runtime and rendered evidence separate."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

SCHEMA_VERSION = "event-evaluation-v0.1"


def _key(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _mae(values: list[float]) -> float | None:
    return round(mean(abs(value) for value in values), 6) if values else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _flatten_compiled(compiled_timeline: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for segment in (compiled_timeline or {}).get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for event in segment.get("events", []) or []:
            if isinstance(event, dict) and _key(event.get("event_id")):
                result[_key(event["event_id"])] = event
    return result


def _trace_index(trace: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        _key(event.get("event_id")): event
        for event in (trace or {}).get("events", []) or []
        if isinstance(event, dict) and _key(event.get("event_id"))
    }


def _render_index(render_evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        _key(item.get("event_id")): item
        for item in (render_evidence or {}).get("observations", []) or []
        if isinstance(item, dict) and _key(item.get("event_id"))
    }


def _gold_index(
    gold_events: dict[str, Any] | list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    rows: Any = gold_events
    if isinstance(gold_events, dict):
        rows = gold_events.get("events", [])
    if not isinstance(rows, list):
        return {}
    return {
        _key(item.get("event_id")): item
        for item in rows
        if isinstance(item, dict) and _key(item.get("event_id"))
    }


def _distance_to_window(value: float, minimum: float, maximum: float) -> tuple[str, float]:
    if value < minimum:
        return "early", minimum - value
    if value > maximum:
        return "late", value - maximum
    return "correct", 0.0


def _interval_iou(
    observed_start: float | None,
    observed_end: float | None,
    expected_start: float | None,
    expected_end: float | None,
) -> float | None:
    if None in {observed_start, observed_end, expected_start, expected_end}:
        return None
    assert observed_start is not None and observed_end is not None
    assert expected_start is not None and expected_end is not None
    if observed_end < observed_start or expected_end < expected_start:
        return None
    intersection = max(0.0, min(observed_end, expected_end) - max(observed_start, expected_start))
    union = max(observed_end, expected_end) - min(observed_start, expected_start)
    return round(intersection / union, 6) if union > 0 else 1.0


def evaluate_events(
    schedule_report: dict[str, Any],
    *,
    compiled_timeline: dict[str, Any] | None = None,
    runtime_trace: dict[str, Any] | None = None,
    render_evidence: dict[str, Any] | None = None,
    gold_events: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate one case without inferring missing rendered or semantic evidence."""
    case_id = _key(schedule_report.get("case_id"))
    if not case_id:
        raise ValueError("schedule report missing case_id")
    compiled = _flatten_compiled(compiled_timeline)
    trace = _trace_index(runtime_trace)
    rendered = _render_index(render_evidence)
    gold = _gold_index(gold_events)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for scheduled in schedule_report.get("events", []) or []:
        if not isinstance(scheduled, dict):
            continue
        event_id = _key(scheduled.get("event_id"))
        target_id = _key(scheduled.get("target_element_id"))
        compiled_event = compiled.get(event_id)
        trace_event = trace.get(event_id)
        render_event = rendered.get(event_id)
        gold_event = gold.get(event_id)

        planned_start = _number(scheduled.get("planned_start_sec"))
        compiled_start = (
            _number(compiled_event.get("start_ms")) / 1000.0
            if compiled_event and _number(compiled_event.get("start_ms")) is not None
            else None
        )
        actual = (
            trace_event.get("actual")
            if trace_event and isinstance(trace_event.get("actual"), dict)
            else {}
        )
        runtime_start = (
            _number(actual.get("start_ms")) / 1000.0
            if _number(actual.get("start_ms")) is not None
            else None
        )
        visible_start = _number((render_event or {}).get("observed_visible_start_sec"))
        visible_end = _number((render_event or {}).get("observed_visible_end_sec"))
        target_resolved = trace_event.get("target_resolved") if trace_event else None
        runtime_target = _key(trace_event.get("target")) if trace_event else ""
        target_match = runtime_target == target_id if runtime_target else None

        outcomes: list[str] = []
        if compiled_event is None:
            outcomes.append("missing_compiled_event")
        if trace_event is None or runtime_start is None:
            outcomes.append("missing_runtime_event")
        if target_resolved is False:
            outcomes.append("unresolved_target")
        if target_match is False:
            outcomes.append("wrong_target")
        render_status = _key((render_event or {}).get("status")) or None
        if render_event is None or render_status in {"unobservable", "not_reviewed"}:
            outcomes.append("render_unobservable")

        temporal_label = "not_evaluated"
        onset_error = None
        window_iou = None
        if gold_event:
            start_min = _number(gold_event.get("acceptable_start_min_sec"))
            start_max = _number(gold_event.get("acceptable_start_max_sec"))
            onset = visible_start if visible_start is not None else runtime_start
            if onset is None:
                temporal_label = "unobservable"
            elif start_min is not None and start_max is not None:
                temporal_label, onset_error = _distance_to_window(onset, start_min, start_max)
                if temporal_label != "correct":
                    outcomes.append(temporal_label)
            expected_targets = {
                _key(value) for value in gold_event.get("expected_target_element_ids", []) or []
            }
            if (
                expected_targets
                and target_id not in expected_targets
                and "wrong_target" not in outcomes
            ):
                outcomes.append("wrong_target")
                target_match = False
            window_iou = _interval_iou(
                visible_start,
                visible_end,
                _number(gold_event.get("acceptable_visible_start_sec")),
                _number(gold_event.get("acceptable_visible_end_sec")),
            )

        row = {
            "event_id": event_id,
            "segment_id": _key(scheduled.get("segment_id")),
            "target_element_id": target_id,
            "narration_proposition_ids": list(scheduled.get("narration_proposition_ids", []) or []),
            "planned_start_sec": _round(planned_start),
            "compiled_start_sec": _round(compiled_start),
            "runtime_start_sec": _round(runtime_start),
            "rendered_visible_start_sec": _round(visible_start),
            "rendered_visible_end_sec": _round(visible_end),
            "planned_to_compiled_delta_sec": _round(
                compiled_start - planned_start
                if compiled_start is not None and planned_start is not None
                else None
            ),
            "compiled_to_runtime_delta_sec": _round(
                runtime_start - compiled_start
                if runtime_start is not None and compiled_start is not None
                else None
            ),
            "target_resolved": target_resolved if isinstance(target_resolved, bool) else None,
            "target_match": target_match,
            "runtime_status": _key((trace_event or {}).get("status")) or None,
            "render_status": render_status,
            "semantic_temporal_label": temporal_label,
            "onset_error_sec": _round(onset_error),
            "window_overlap_iou": window_iou,
            "outcomes": sorted(set(outcomes)),
        }
        rows.append(row)
        for outcome in row["outcomes"]:
            failures.append({"event_id": event_id, "type": outcome})

    count = len(rows)
    compiled_count = sum(row["compiled_start_sec"] is not None for row in rows)
    runtime_count = sum(row["runtime_start_sec"] is not None for row in rows)
    render_count = sum(
        row["rendered_visible_start_sec"] is not None
        and row["rendered_visible_end_sec"] is not None
        for row in rows
    )
    resolution_values = [
        row["target_resolved"] for row in rows if row["target_resolved"] is not None
    ]
    plan_deltas = [
        row["planned_to_compiled_delta_sec"]
        for row in rows
        if row["planned_to_compiled_delta_sec"] is not None
    ]
    runtime_deltas = [
        row["compiled_to_runtime_delta_sec"]
        for row in rows
        if row["compiled_to_runtime_delta_sec"] is not None
    ]
    semantic_rows = [
        row for row in rows if row["semantic_temporal_label"] in {"correct", "early", "late"}
    ]
    onset_errors = [
        row["onset_error_sec"] for row in semantic_rows if row["onset_error_sec"] is not None
    ]
    overlaps = [row["window_overlap_iou"] for row in rows if row["window_overlap_iou"] is not None]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "event_level_alignment_evaluation",
        "case_id": case_id,
        "events": rows,
        "metrics": {
            "event_count": count,
            "compiled_coverage": _rate(compiled_count, count),
            "runtime_coverage": _rate(runtime_count, count),
            "render_coverage": _rate(render_count, count),
            "target_resolution_rate": _rate(
                sum(value is True for value in resolution_values), len(resolution_values)
            ),
            "planned_to_compiled_mae_sec": _mae(plan_deltas),
            "compiled_to_runtime_mae_sec": _mae(runtime_deltas),
            "semantic_evaluable_count": len(semantic_rows),
            "semantic_correct_rate": _rate(
                sum(row["semantic_temporal_label"] == "correct" for row in semantic_rows),
                len(semantic_rows),
            ),
            "onset_mae_sec": _mae(onset_errors),
            "mean_window_overlap_iou": round(mean(overlaps), 6) if overlaps else None,
            "missing_runtime_count": sum(
                "missing_runtime_event" in row["outcomes"] for row in rows
            ),
            "wrong_target_count": sum("wrong_target" in row["outcomes"] for row in rows),
            "render_unobservable_count": sum(
                "render_unobservable" in row["outcomes"] for row in rows
            ),
        },
        "failures": failures,
        "claims": {
            "runtime_execution_evaluated": bool(trace),
            "rendered_visibility_evaluated": render_count > 0,
            "semantic_timing_evaluated": bool(semantic_rows),
        },
    }


def write_event_evaluation(report: dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


__all__ = ["SCHEMA_VERSION", "evaluate_events", "write_event_evaluation"]
