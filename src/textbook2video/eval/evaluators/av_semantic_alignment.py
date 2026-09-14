"""Measure sentence-bound animation timing without re-running semantic matching.

The timing/semantic-matching worktree owns sentence bindings.  This evaluator
only joins those bindings with the existing timed storyboard and browser trace,
then reports planning, runtime, and end-to-end semantic timing separately.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..animation_trace_adapter import adapt_animation_trace
from ..runner import EvalContext
from .common import evidence_for

EVALUATOR_NAME = "av_semantic_alignment"
EVALUATOR_VERSION = "av-semantic-alignment-v0.1"
ALIGNMENT_STATUSES = {
    "aligned",
    "minor_misalignment",
    "misaligned",
    "severely_misaligned",
    "not_evaluable",
}


@dataclass(frozen=True)
class AlignmentThresholds:
    """Configurable semantic timing thresholds, in seconds."""

    aligned_max_sec: float = 0.5
    minor_max_sec: float = 1.0
    severe_min_sec: float = 2.0

    def __post_init__(self) -> None:
        if not (0 <= self.aligned_max_sec <= self.minor_max_sec <= self.severe_min_sec):
            raise ValueError("alignment thresholds must be non-negative and ordered")


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _slide_id(value: Any) -> str:
    return str(value)


def _event_key(slide_id: Any, event_id: Any) -> tuple[str, str]:
    return _slide_id(slide_id), str(event_id)


def _nested_number(value: dict[str, Any], *keys: str) -> float | None:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _number(current)


def _planned_trigger(event: dict[str, Any]) -> float | None:
    for key in ("planned_trigger_sec", "trigger_at_sec", "at_sec"):
        value = _number(event.get(key))
        if value is not None:
            return value
    start_ms = _nested_number(event, "planned", "start_ms")
    return start_ms / 1000 if start_ms is not None else None


def _actual_trigger(event: dict[str, Any]) -> float | None:
    for key in ("actual_trigger_sec", "actual_ms"):
        value = _number(event.get(key))
        if value is not None:
            return value if key.endswith("sec") else value / 1000
    start_ms = _nested_number(event, "actual", "start_ms")
    return start_ms / 1000 if start_ms is not None else None


def _trace_status(event: dict[str, Any]) -> str:
    return str(event.get("status") or "").lower()


def _load_sentence_cues(path: Path | None) -> dict[str, float]:
    value = _read_json(path)
    if value is None:
        return {}
    entries: Any = value
    if isinstance(value, dict):
        for key in ("sentences", "cues", "items"):
            if isinstance(value.get(key), list):
                entries = value[key]
                break
        else:
            entries = [
                {"sentence_id": key, "sentence_start_sec": item}
                for key, item in value.items()
            ]
    if not isinstance(entries, list):
        return {}
    result: dict[str, float] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        sentence_id = item.get("sentence_id", item.get("id", item.get("matched_sentence_id")))
        start = None
        for key in ("sentence_start_sec", "start_sec", "start", "at_sec"):
            start = _number(item.get(key))
            if start is not None:
                break
        if sentence_id is not None and start is not None:
            result[str(sentence_id)] = start
    return result


def _element_ids(storyboard: dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    segments = storyboard.get("segments", [])
    if not isinstance(segments, list):
        return result
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        # The public animation trace uses the 1-based slide index.  Storyboard
        # segment ids may be human-readable strings, so the evaluator joins on
        # the trace contract rather than assuming ids are numeric.
        slide = _slide_id(index)
        for element in segment.get("elements", []):
            if isinstance(element, dict) and element.get("id") is not None:
                result.add((slide, str(element["id"])))
    return result


def _candidate_plan_events(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten timed storyboard events, preserving sentence metadata verbatim."""
    segments = storyboard.get("segments", [])
    if not isinstance(segments, list):
        return []
    result: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        slide = _slide_id(index)
        timeline = segment.get("timeline")
        animations = segment.get("animations")
        timeline_items = timeline if isinstance(timeline, list) else []
        animation_items = animations if isinstance(animations, list) else []
        if timeline_items:
            items = timeline_items
        else:
            items = animation_items
        animation_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in animation_items:
            if isinstance(item, dict) and item.get("target") is not None:
                animation_by_target[str(item["target"])].append(item)
        target_occurrence: Counter[str] = Counter()
        for position, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                result.append({"slide_id": slide, "invalid": True, "position": position})
                continue
            event = dict(raw)
            target = str(event.get("target", ""))
            target_occurrence[target] += 1
            companions = animation_by_target.get(target, [])
            if not event.get("event_id") and len(companions) >= target_occurrence[target]:
                companion = companions[target_occurrence[target] - 1]
                event = {**companion, **event}
            event["slide_id"] = slide
            event["position"] = position
            result.append(event)
    return result


def _load_trace(context: EvalContext, storyboard: dict[str, Any]) -> tuple[list[dict[str, Any]], Path | None]:
    path = context.artifact("animation_trace")
    if path is None or not path.is_file():
        path = context.artifact("raw_animation_trace")
    if path is None or not path.is_file():
        return [], None
    value = _read_json(path)
    if isinstance(value, list):
        value = adapt_animation_trace(value, manifest=context.case.raw, storyboard=storyboard)
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("animation trace must contain an events array")
    segment_map = {
        str(segment.get("id", index)): index
        for index, segment in enumerate(storyboard.get("segments", []) or [], start=1)
        if isinstance(segment, dict)
    }
    events: list[dict[str, Any]] = []
    for item in value["events"]:
        if not isinstance(item, dict):
            continue
        event = dict(item)
        raw_slide = event.get("slide", event.get("slide_id"))
        normalized_slide = segment_map.get(str(raw_slide), raw_slide)
        event["slide"] = normalized_slide
        if "slide_id" in event:
            event["slide_id"] = normalized_slide
        events.append(event)
    return events, path


def _assign_missing_plan_ids(
    plan: list[dict[str, Any]], trace: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in trace:
        if event.get("event_id") is not None and event.get("target") is not None:
            candidates[_event_key(event.get("slide_id", event.get("slide")), event["target"])].append(event)
    used: Counter[tuple[str, str]] = Counter()
    assigned: list[dict[str, Any]] = []
    for event in plan:
        value = dict(event)
        if value.get("event_id") is None and value.get("target") is not None:
            key = _event_key(value["slide_id"], value["target"])
            index = used[key]
            matches = candidates.get(key, [])
            if index < len(matches):
                value["event_id"] = matches[index].get("event_id")
                used[key] += 1
        if value.get("event_id") is None:
            value["event_id"] = f"plan-{value.get('slide_id')}-{value.get('position', len(assigned) + 1)}"
        assigned.append(value)
    return assigned


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _summary(values: list[float]) -> dict[str, float | None]:
    return {
        "MAE_sec": round(sum(values) / len(values), 6) if values else None,
        "P95_sec": _percentile(values, 0.95),
        "max_error_sec": round(max(values), 6) if values else None,
    }


def _status(error: float, thresholds: AlignmentThresholds) -> str:
    magnitude = abs(error)
    if magnitude <= thresholds.aligned_max_sec:
        return "aligned"
    if magnitude <= thresholds.minor_max_sec:
        return "minor_misalignment"
    if magnitude > thresholds.severe_min_sec:
        return "severely_misaligned"
    return "misaligned"


def _issue(
    context: EvalContext,
    issue_type: str,
    message: str,
    *,
    severity: str = "warning",
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = {
        "case_id": context.case.case_id,
        "stage": "eval",
        "evaluator": EVALUATOR_NAME,
        "type": issue_type,
        "severity": severity,
        "message": message,
        "evidence_ids": [f"{context.case.case_id}-av-semantic-inputs"],
        "review_status": "unreviewed",
    }
    if event:
        slide = event.get("slide_id")
        try:
            slide = int(slide) if slide is not None else None
        except (TypeError, ValueError):
            # The public issue contract uses the numeric trace slide index.
            # Keep non-numeric internal ids in metadata without emitting an
            # invalid eval_report field.
            slide = None
        if isinstance(slide, int) and slide < 1:
            slide = None
        value.update(
            {
                "slide": slide,
                "event_id": event.get("event_id"),
                "metadata": {
                    key: event.get(key)
                    for key in ("target", "matched_sentence_id", "blocked_by")
                    if event.get(key) is not None
                },
            }
        )
    return value


def _unavailable(context: EvalContext, reason: str, *, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence_id = f"{context.case.case_id}-av-semantic-inputs"
    return {
        "status": "unavailable",
        "passed": None,
        "metrics": metrics or {},
        "details": {
            "semantic_alignment_status": "unavailable",
            "reason": reason,
            "evaluator_version": EVALUATOR_VERSION,
        },
        "issues": [
            _issue(context, "AV_SEMANTIC_BINDING_MISSING", reason),
        ],
        "evidence_ids": [evidence_id],
    }


class AVSemanticAlignmentAdapter:
    """Join sentence-bound plans to existing browser animation telemetry."""

    def __init__(self, *, thresholds: AlignmentThresholds | None = None) -> None:
        self.thresholds = thresholds or AlignmentThresholds()

    def evaluate_case(self, context: EvalContext) -> dict[str, Any]:
        timed_path = context.artifact("timed_storyboard")
        if timed_path is None or not timed_path.is_file():
            return _unavailable(context, "timed storyboard is missing")
        storyboard = _read_json(timed_path)
        if not isinstance(storyboard, dict):
            return _unavailable(context, "timed storyboard is invalid")
        plan = _candidate_plan_events(storyboard)
        if not plan or any(event.get("invalid") for event in plan):
            return _unavailable(context, "timed storyboard contains invalid animation events")
        try:
            trace, trace_path = _load_trace(context, storyboard)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _unavailable(context, f"animation trace is invalid: {exc}")
        if not trace:
            return _unavailable(context, "animation trace is missing or empty")

        cue_path = context.artifact("sentence_cues")
        cues = _load_sentence_cues(cue_path)
        plan = _assign_missing_plan_ids(plan, trace)
        plan_counts = Counter(_event_key(item.get("slide_id"), item.get("event_id")) for item in plan)
        trace_counts = Counter(
            _event_key(item.get("slide_id", item.get("slide")), item.get("event_id"))
            for item in trace
            if item.get("event_id") is not None
        )
        duplicate_planned = sum(max(count - 1, 0) for count in plan_counts.values())
        duplicate_trace = sum(max(count - 1, 0) for count in trace_counts.values())
        trace_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in trace:
            if item.get("event_id") is not None:
                trace_by_key[_event_key(item.get("slide_id", item.get("slide")), item["event_id"])].append(item)

        planned_keys = set(plan_counts)

        valid_targets = _element_ids(storyboard)
        records: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        planning_errors: list[float] = []
        runtime_errors: list[float] = []
        semantic_runtime_errors: list[float] = []
        narration_offsets: list[float] = []
        early_count = 0
        late_count = 0
        fallback_counts: Counter[str] = Counter()
        semantic_match_count = 0
        semantic_evaluable_count = 0
        semantic_not_evaluable_count = 0
        blocked_count = 0
        aligned_counts: Counter[str] = Counter()

        for raw_plan in plan:
            event = dict(raw_plan)
            key = _event_key(event.get("slide_id"), event.get("event_id"))
            matched_sentence_id = event.get("matched_sentence_id")
            sentence_start = _number(event.get("sentence_start_sec"))
            sentence_start_source = "event"
            if sentence_start is None and matched_sentence_id is not None:
                sentence_start = cues.get(str(matched_sentence_id))
                sentence_start_source = "sentence_cues_sidecar" if sentence_start is not None else "missing"
            trigger_source = str(event.get("trigger_source") or "")
            has_binding = matched_sentence_id is not None or trigger_source == "sentence_cue"
            fallback_type = str(
                event.get("fallback_type")
                or event.get("fallback")
                or ("unclassified_fallback" if not has_binding else "")
            )
            if not has_binding:
                fallback_counts[fallback_type] += 1
            if has_binding:
                semantic_match_count += 1
            planned_trigger = _planned_trigger(event)
            lead = _number(event.get("lead_sec"))
            if lead is None:
                lead = 0.0
            desired = (
                max(0.0, sentence_start - lead)
                if sentence_start is not None and has_binding
                else None
            )
            actuals = trace_by_key.get(key, [])
            target_known = (str(event.get("slide_id")), str(event.get("target"))) in valid_targets
            blocked_by = None
            actual = None
            if len(actuals) > 1:
                issues.append(_issue(context, "AV_SEMANTIC_EVENT_DUPLICATE", "multiple actual events matched one planned event", event=event))
                blocked_by = "AV_SEMANTIC_EVENT_DUPLICATE"
            elif actuals:
                actual = actuals[0]
                if (
                    actual.get("target_resolved") is False
                    or _trace_status(actual) not in {"executed", "ok", "completed"}
                    or _actual_trigger(actual) is None
                ):
                    blocked_by = str(actual.get("error_code") or _trace_status(actual) or "missing_actual_trigger")
            elif has_binding:
                blocked_by = "AV_SEMANTIC_EVENT_MISSING"
                issues.append(_issue(context, "AV_SEMANTIC_EVENT_MISSING", "planned semantic event has no matching trace event", event=event))
            if has_binding and sentence_start is None:
                blocked_by = "AV_SEMANTIC_METADATA_INVALID"
                issues.append(_issue(context, "AV_SEMANTIC_METADATA_INVALID", "matched sentence has no sentence_start_sec", event=event))
            if not target_known:
                blocked_by = "AV_SEMANTIC_METADATA_INVALID"
                issues.append(_issue(context, "AV_SEMANTIC_METADATA_INVALID", "planned event target is not present in timed storyboard elements", event=event))

            actual_trigger = _actual_trigger(actual) if actual else None
            planning_error = planned_trigger - desired if planned_trigger is not None and desired is not None else None
            runtime_error = actual_trigger - planned_trigger if actual_trigger is not None and planned_trigger is not None else None
            semantic_error = actual_trigger - desired if actual_trigger is not None and desired is not None else None
            narration_offset = actual_trigger - sentence_start if actual_trigger is not None and sentence_start is not None else None
            alignment_status = "not_evaluable"
            if has_binding and blocked_by is None and semantic_error is not None:
                alignment_status = _status(semantic_error, self.thresholds)
                aligned_counts[alignment_status] += 1
                semantic_evaluable_count += 1
                if planning_error is not None:
                    planning_errors.append(abs(planning_error))
                if runtime_error is not None:
                    runtime_errors.append(abs(runtime_error))
                semantic_runtime_errors.append(abs(semantic_error))
                if narration_offset is not None:
                    narration_offsets.append(narration_offset)
                if semantic_error < 0:
                    early_count += 1
                elif semantic_error > 0:
                    late_count += 1
                if alignment_status == "severely_misaligned":
                    issues.append(_issue(context, "AV_SEMANTIC_SEVERE_MISALIGNMENT", f"semantic runtime error is {semantic_error:.3f}s", severity="major", event=event))
                elif alignment_status != "aligned":
                    issues.append(_issue(context, "AV_SEMANTIC_MISALIGNMENT", f"semantic runtime error is {semantic_error:.3f}s", event=event))
            elif has_binding:
                semantic_not_evaluable_count += 1
                blocked_count += 1
                issues.append(_issue(context, "AV_SEMANTIC_RUNTIME_BLOCKED", f"semantic event is not evaluable: {blocked_by or 'missing actual trigger'}", event=event))

            records.append(
                {
                    "event_id": event.get("event_id"),
                    "slide": event.get("slide_id"),
                    "target": event.get("target"),
                    "trigger_source": trigger_source or None,
                    "matched_sentence_id": matched_sentence_id,
                    "sentence_start_sec": sentence_start,
                    "sentence_start_source": sentence_start_source if has_binding else None,
                    "lead_sec": lead if has_binding else None,
                    "desired_trigger_sec": desired,
                    "planned_trigger_sec": planned_trigger,
                    "actual_trigger_sec": actual_trigger,
                    "planning_error_sec": planning_error,
                    "runtime_error_sec": runtime_error,
                    "semantic_runtime_error_sec": semantic_error,
                    "narration_offset_sec": narration_offset,
                    "status": alignment_status if has_binding else "fallback_only",
                    "fallback_type": fallback_type or None,
                    "blocked_by": blocked_by,
                }
            )

        for actual in trace:
            actual_key = _event_key(
                actual.get("slide_id", actual.get("slide")), actual.get("event_id")
            )
            if actual.get("event_id") is not None and actual_key not in planned_keys:
                issues.append(
                    _issue(
                        context,
                        "AV_SEMANTIC_METADATA_INVALID",
                        "trace event has no matching planned event",
                        event={
                            "slide_id": actual_key[0],
                            "event_id": actual.get("event_id"),
                            "target": actual.get("target"),
                        },
                    )
                )
            if actual.get("target") is not None and (
                _slide_id(actual.get("slide_id", actual.get("slide"))), str(actual.get("target"))
            ) not in valid_targets:
                issues.append(
                    _issue(
                        context,
                        "AV_SEMANTIC_METADATA_INVALID",
                        "trace event target is not present in timed storyboard elements",
                        event={
                            "slide_id": actual_key[0],
                            "event_id": actual.get("event_id"),
                            "target": actual.get("target"),
                        },
                    )
                )
        if duplicate_planned:
            issues.append(_issue(context, "AV_SEMANTIC_EVENT_DUPLICATE", f"{duplicate_planned} duplicate planned event occurrence(s)"))
        if duplicate_trace:
            issues.append(_issue(context, "AV_SEMANTIC_EVENT_DUPLICATE", f"{duplicate_trace} duplicate trace event occurrence(s)"))
        if not semantic_match_count:
            issues.append(_issue(context, "AV_SEMANTIC_BINDING_MISSING", "no sentence-bound animation events are available; semantic timing is unavailable"))
        metrics = {
            "planned_event_count": len(plan),
            "semantic_match_count": semantic_match_count,
            "fallback_count": sum(fallback_counts.values()),
            "fallback_by_type": dict(sorted(fallback_counts.items())),
            "semantic_match_rate": round(semantic_match_count / len(plan), 6) if plan else None,
            "semantic_evaluable_count": semantic_evaluable_count,
            "semantic_not_evaluable_count": semantic_not_evaluable_count,
            "semantic_alignment_blocked_count": blocked_count,
            "duplicate_planned_event_count": duplicate_planned,
            "duplicate_trace_event_count": duplicate_trace,
            "planning_MAE_sec": _summary(planning_errors)["MAE_sec"],
            "planning_P95_sec": _summary(planning_errors)["P95_sec"],
            "planning_max_error_sec": _summary(planning_errors)["max_error_sec"],
            "runtime_MAE_sec": _summary(runtime_errors)["MAE_sec"],
            "runtime_P95_sec": _summary(runtime_errors)["P95_sec"],
            "runtime_max_error_sec": _summary(runtime_errors)["max_error_sec"],
            "semantic_runtime_MAE_sec": _summary(semantic_runtime_errors)["MAE_sec"],
            "semantic_runtime_P95_sec": _summary(semantic_runtime_errors)["P95_sec"],
            "semantic_runtime_max_error_sec": _summary(semantic_runtime_errors)["max_error_sec"],
            "aligned_count": aligned_counts["aligned"],
            "minor_misalignment_count": aligned_counts["minor_misalignment"],
            "misaligned_count": aligned_counts["misaligned"],
            "severely_misaligned_count": aligned_counts["severely_misaligned"],
            "early_count": early_count,
            "late_count": late_count,
            "mean_narration_offset_sec": round(sum(narration_offsets) / len(narration_offsets), 6) if narration_offsets else None,
            "median_narration_offset_sec": _percentile(narration_offsets, 0.5),
        }
        evidence_id = f"{context.case.case_id}-av-semantic-inputs"
        details = {
            "evaluator_version": EVALUATOR_VERSION,
            "threshold_config": asdict(self.thresholds),
            "semantic_alignment_status": (
                "ok"
                if semantic_evaluable_count
                else ("not_evaluable" if semantic_match_count else "unavailable")
            ),
            "reason": (
                "no semantic sentence binding is present in the timed storyboard"
                if not semantic_match_count
                else None
            ),
            "events": records,
            "timed_storyboard": str(timed_path),
            "animation_trace": str(trace_path) if trace_path else None,
            "sentence_cues": str(cue_path) if cue_path and cue_path.is_file() else None,
            "provenance": {
                "evaluator_version": EVALUATOR_VERSION,
                "threshold_config": asdict(self.thresholds),
                "timed_storyboard_sha256": _sha256(timed_path),
                "sentence_cues_sha256": _sha256(cue_path),
                "animation_trace_sha256": _sha256(trace_path),
                "candidate_commit": context.candidate_commit,
                "run_id": context.run_id,
            },
        }
        if semantic_match_count == 0:
            return {
                "status": "unavailable",
                "passed": None,
                "metrics": metrics,
                "details": details,
                "issues": issues,
                "evidence_ids": [evidence_id],
                "_evidence": [
                    evidence_for(timed_path, evidence_id=evidence_id, kind="timed_storyboard"),
                    *([evidence_for(trace_path, evidence_id=f"{evidence_id}-trace", kind="animation_trace")] if trace_path else []),
                ],
            }
        major = any(item.get("severity") == "major" for item in issues)
        return {
            "status": "failed" if major else "ok",
            "passed": not major,
            "metrics": metrics,
            "details": details,
            "issues": issues,
            "evidence_ids": [evidence_id],
            "_evidence": [
                evidence_for(timed_path, evidence_id=evidence_id, kind="timed_storyboard"),
                *([evidence_for(trace_path, evidence_id=f"{evidence_id}-trace", kind="animation_trace")] if trace_path else []),
                *([evidence_for(cue_path, evidence_id=f"{evidence_id}-sentence-cues", kind="sentence_cues")] if cue_path and cue_path.is_file() else []),
            ],
        }


def evaluate_av_semantic_alignment(context: EvalContext) -> dict[str, Any]:
    adapter = context.av_semantic_alignment
    if adapter is None:
        return _unavailable(context, "AV Semantic Alignment evaluator is not configured")
    return adapter.evaluate_case(context)


evaluate_av_semantic_alignment.evaluator_name = EVALUATOR_NAME
