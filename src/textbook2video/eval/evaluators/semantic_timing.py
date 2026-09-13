"""Semantic timing evaluator.

This evaluator joins the existing sentence-semantic plan, the Phase 3A
counterfactual baseline, and (when supplied) the public
``animation-trace-v0.1`` events.  It is intentionally an evaluation boundary:
production timing and the trace schema are not changed here.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from textbook2video.pipeline.timing import apply_timing

from ..char_proportional_baseline import (
    aggregate_baseline_rows,
    build_baseline_report,
)
from .common import evidence_for, unavailable

__all__ = [
    "build_semantic_timing_report",
    "evaluate_semantic_timing",
    "evaluate_semantic_timing_data",
    "generate_pilot3_reports",
]

SEMANTIC_SOURCES = frozenset({"text_match", "semantic", "semantic_match"})
RUNTIME_JOINED = "joined"
RUNTIME_NOT_FOUND = "not_found"
RUNTIME_AMBIGUOUS = "ambiguous"
RUNTIME_UNAVAILABLE = "trace_unavailable"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _segment_key(value: Any) -> str:
    return str(value) if value is not None else ""


def _trace_events(trace: Any) -> list[dict[str, Any]] | None:
    if trace is None:
        return None
    if isinstance(trace, dict):
        events = trace.get("events")
    elif isinstance(trace, list):
        # A list is accepted for test/facility use only when it already contains
        # adapted v0.1 event objects.  No second raw trace schema is introduced.
        events = trace
    else:
        return []
    return (
        [event for event in events or [] if isinstance(event, dict)]
        if isinstance(events, list)
        else []
    )


def _runtime_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "target_missing_count": sum(
            event.get("error_code") == "TARGET_MISSING" for event in events
        ),
        "unsupported_count": sum(
            event.get("error_code") in {"UNSUPPORTED_ACTION", "UNSUPPORTED_EFFECT"}
            for event in events
        ),
        "cancelled_count": sum(event.get("error_code") == "CANCELLED" for event in events),
        "runtime_error_count": sum(
            event.get("error_code") == "RUNTIME_ERROR" or event.get("status") == "error"
            for event in events
        ),
    }


def _runtime_metrics(
    rows: list[dict[str, Any]],
    events: list[dict[str, Any]] | None,
    *,
    trace_runtime_error_count: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if events is None:
        return (
            {
                "runtime_trace_available": False,
                "runtime_status": "not_evaluated",
                "runtime_evaluated_count": None,
                "runtime_mae_sec": None,
                "runtime_mae_ms": None,
                "runtime_median_error_sec": None,
                "runtime_p95_error_sec": None,
                "runtime_max_error_sec": None,
                "early_event_count": None,
                "late_event_count": None,
                "unmatched_trace_count": None,
                "target_missing_count": None,
                "unsupported_count": None,
                "cancelled_count": None,
                "runtime_error_count": None,
                "trace_joined_count": None,
            },
            rows,
        )

    by_key: dict[tuple[int, str], list[tuple[int, dict[str, Any]]]] = {}
    for index, event in enumerate(events):
        slide = event.get("slide")
        if isinstance(slide, bool) or not isinstance(slide, int):
            continue
        by_key.setdefault((slide, str(event.get("target") or "")), []).append((index, event))

    consumed: set[int] = set()
    errors: list[float] = []
    early = 0
    late = 0
    joined = 0
    for row in rows:
        key = (int(row["slide_id"]), str(row["element_id"]))
        candidates = by_key.get(key, [])
        if not candidates:
            row.update(
                {
                    "trace_join_status": RUNTIME_NOT_FOUND,
                    "trace_event_id": None,
                    "runtime_status": None,
                    "actual_trigger_sec": None,
                    "runtime_error_sec": None,
                    "executed": None,
                    "target_resolved": None,
                }
            )
            continue
        if len(candidates) > 1:
            row.update(
                {
                    "trace_join_status": RUNTIME_AMBIGUOUS,
                    "trace_event_id": None,
                    "runtime_status": None,
                    "actual_trigger_sec": None,
                    "runtime_error_sec": None,
                    "executed": None,
                    "target_resolved": None,
                }
            )
            continue
        event_index, event = candidates[0]
        consumed.add(event_index)
        joined += 1
        actual = event.get("actual") if isinstance(event.get("actual"), dict) else {}
        actual_sec = _number(actual.get("start_ms"))
        actual_sec = actual_sec / 1000.0 if actual_sec is not None else None
        executed = bool(event.get("executed"))
        target_resolved = bool(event.get("target_resolved"))
        successful = (
            executed
            and target_resolved
            and event.get("status") == "executed"
            and not event.get("error_code")
        )
        runtime_error = (
            actual_sec - float(row["semantic_planned_trigger_sec"])
            if successful and actual_sec is not None
            else None
        )
        row.update(
            {
                "trace_join_status": RUNTIME_JOINED,
                "trace_event_id": event.get("event_id"),
                "runtime_status": event.get("status"),
                "actual_trigger_sec": round(actual_sec, 6) if actual_sec is not None else None,
                "runtime_error_sec": round(runtime_error, 6) if runtime_error is not None else None,
                "executed": executed,
                "target_resolved": target_resolved,
            }
        )
        if runtime_error is not None:
            errors.append(abs(runtime_error))
            if runtime_error < 0:
                early += 1
            elif runtime_error > 0:
                late += 1

    counts = _runtime_counts(events)
    counts["runtime_error_count"] += max(0, int(trace_runtime_error_count))
    runtime_metrics: dict[str, Any] = {
        "runtime_trace_available": True,
        "runtime_status": "evaluated",
        "runtime_evaluated_count": len(errors),
        "runtime_mae_sec": round(sum(errors) / len(errors), 6) if errors else None,
        "runtime_mae_ms": round(sum(errors) / len(errors) * 1000, 3) if errors else None,
        "runtime_median_error_sec": round(float(median(errors)), 6) if errors else None,
        "runtime_p95_error_sec": _percentile(errors, 0.95),
        "runtime_max_error_sec": round(max(errors), 6) if errors else None,
        "early_event_count": early,
        "late_event_count": late,
        "unmatched_trace_count": len(events) - len(consumed),
        "trace_joined_count": joined,
        **counts,
    }
    return runtime_metrics, rows


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] + weight * (ordered[upper] - ordered[lower]), 6)


def _human_review(value: Any) -> dict[str, Any]:
    records: Any = value
    if isinstance(value, dict):
        records = value.get("records")
        if not isinstance(records, list):
            counts = {
                "human_reviewed_count": value.get(
                    "human_reviewed_count",
                    value.get("reviewed_count", value.get("human_reviewed_new_matches")),
                ),
                "human_correct_count": value.get(
                    "human_correct_count",
                    value.get("correct_count", value.get("human_review_correct")),
                ),
                "human_incorrect_count": value.get(
                    "human_incorrect_count",
                    value.get("incorrect_count", value.get("human_review_incorrect")),
                ),
                "human_uncertain_count": value.get(
                    "human_uncertain_count",
                    value.get("uncertain_count", value.get("human_review_uncertain")),
                ),
            }
            if any(_number(item) is not None for item in counts.values()):
                return {
                    "human_review_available": True,
                    **{key: int(_number(item) or 0) for key, item in counts.items()},
                }
    if not isinstance(records, list):
        return {
            "human_review_available": False,
            "human_reviewed_count": None,
            "human_correct_count": None,
            "human_incorrect_count": None,
            "human_uncertain_count": None,
        }
    statuses = [
        str(record.get("status") or record.get("label") or "").lower()
        for record in records
        if isinstance(record, dict)
    ]
    return {
        "human_review_available": True,
        "human_reviewed_count": len(statuses),
        "human_correct_count": statuses.count("correct"),
        "human_incorrect_count": statuses.count("incorrect"),
        "human_uncertain_count": statuses.count("uncertain"),
    }


def _review_from_inputs(
    timed_storyboard: dict[str, Any],
    baseline: dict[str, Any],
    *,
    include_baseline: bool = True,
) -> dict[str, Any]:
    candidates = [
        timed_storyboard.get("human_review"),
        timed_storyboard.get("metadata", {}).get("human_review")
        if isinstance(timed_storyboard.get("metadata"), dict)
        else None,
        baseline.get("human_review") if include_baseline else None,
    ]
    for candidate in candidates:
        result = _human_review(candidate)
        if result["human_review_available"]:
            return result
    return _human_review(None)


def _normalize_rows(
    rows: Iterable[dict[str, Any]],
    storyboard: dict[str, Any],
    *,
    trace_available: bool,
) -> list[dict[str, Any]]:
    segment_order = {
        _segment_key(segment.get("id")): index
        for index, segment in enumerate(storyboard.get("segments", []) or [], start=1)
        if isinstance(segment, dict)
    }
    output: list[dict[str, Any]] = []
    for item in rows:
        row = dict(item)
        row["slide_id"] = segment_order.get(
            _segment_key(row.get("segment_id")), row.get("slide_id")
        )
        if row.get("slide_id") is None:
            continue
        row["semantic_planned_trigger_sec"] = row.get(
            "semantic_planned_trigger_sec", row.get("semantic_trigger_sec")
        )
        row["semantic_trigger_sec"] = row.get(
            "semantic_trigger_sec", row.get("semantic_planned_trigger_sec")
        )
        if not trace_available:
            row.update(
                {
                    "trace_join_status": RUNTIME_UNAVAILABLE,
                    "trace_event_id": None,
                    "runtime_status": None,
                    "actual_trigger_sec": None,
                    "runtime_error_sec": None,
                    "executed": None,
                    "target_resolved": None,
                }
            )
        output.append(row)
    return output


def build_semantic_timing_report(
    storyboard: dict[str, Any],
    timed_storyboard: dict[str, Any],
    sentence_cues: Any = None,
    char_baseline: dict[str, Any] | None = None,
    trace: Any = None,
    *,
    case_id: str | None = None,
    lesson_id: str | None = None,
    source_paths: dict[str, str | Path | None] | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """Build the three-layer semantic timing report from in-memory inputs."""
    resolved_case = case_id or str(timed_storyboard.get("metadata", {}).get("case_id") or "unknown")
    resolved_lesson = lesson_id or str(
        timed_storyboard.get("metadata", {}).get("lesson_id") or resolved_case
    )
    baseline_supplied = char_baseline is not None
    baseline = char_baseline or build_baseline_report(
        storyboard,
        timed_storyboard,
        sentence_cues,
        case_id=resolved_case,
        lesson_id=resolved_lesson,
        top_n=top_n,
    )
    rows = _normalize_rows(
        baseline.get("evaluated_elements", []), storyboard, trace_available=trace is not None
    )
    runtime_events = _trace_events(trace)
    trace_runtime_error_count = (
        len(trace.get("runtime_errors", []))
        if isinstance(trace, dict) and isinstance(trace.get("runtime_errors"), list)
        else 0
    )
    runtime_metrics, rows = _runtime_metrics(
        rows,
        runtime_events,
        trace_runtime_error_count=trace_runtime_error_count,
    )
    planning = aggregate_baseline_rows(rows)

    semantic_count = 0
    fallback_count = 0
    methods: Counter[str] = Counter()
    for segment in timed_storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for animation in segment.get("animations", []) or []:
            if not isinstance(animation, dict):
                continue
            source = str(animation.get("trigger_source") or "")
            if source in SEMANTIC_SOURCES:
                semantic_count += 1
                methods[str(animation.get("match_method") or "unknown")] += 1
            else:
                fallback_count += 1

    exclusions = list(baseline.get("excluded_elements", []))
    top_errors = sorted(
        rows,
        key=lambda row: (
            -float(row.get("char_error_sec") or 0.0),
            str(row.get("lesson_id", "")),
            str(row.get("segment_id", "")),
            str(row.get("element_id", "")),
        ),
    )[: max(0, int(top_n))]
    review = _review_from_inputs(
        timed_storyboard,
        baseline,
        include_baseline=baseline_supplied,
    )
    runtime_details: dict[str, Any] = {
        "status": runtime_metrics["runtime_status"],
        "trace_join_key": "(slide index, element target)",
        "trace_schema": "animation-trace-v0.1",
        "not_evaluated_reason": "trace unavailable" if runtime_events is None else None,
    }
    paths = source_paths or {}
    return {
        "schema_version": "textbookeval-semantic-timing-v0.1",
        "report_type": "semantic_timing",
        "case_id": resolved_case,
        "lesson_id": resolved_lesson,
        "status": "ok",
        "passed": True,
        "metrics": {
            "semantic_matched_count": semantic_count,
            "fallback_count": fallback_count,
            "match_method_distribution": dict(sorted(methods.items())),
            **review,
            **planning,
            **runtime_metrics,
        },
        "semantic_alignment": {
            "semantic_matched_count": semantic_count,
            "fallback_count": fallback_count,
            "match_method_distribution": dict(sorted(methods.items())),
            **review,
        },
        "planning_timing_comparison": {
            "baseline": "char_proportional",
            "semantic_plan_error_interpretation": (
                "implementation consistency only; not semantic correctness"
            ),
            **planning,
        },
        "runtime_execution": runtime_details | runtime_metrics,
        "failure_exclusions": {
            "count": len(exclusions),
            "reasons": dict(
                sorted(Counter(str(item.get("reason") or "unknown") for item in exclusions).items())
            ),
            "items": exclusions,
        },
        "top_timing_errors": top_errors,
        "evaluated_elements": rows,
        "inputs": {
            "storyboard": str(paths.get("storyboard")) if paths.get("storyboard") else None,
            "semantic_timed_storyboard": str(paths.get("semantic_timed_storyboard"))
            if paths.get("semantic_timed_storyboard")
            else None,
            "sentence_cues": str(paths.get("sentence_cues"))
            if paths.get("sentence_cues")
            else None,
            "char_proportional_baseline": str(paths.get("char_proportional_baseline"))
            if paths.get("char_proportional_baseline")
            else None,
            "animation_trace": str(paths.get("animation_trace"))
            if paths.get("animation_trace")
            else None,
        },
    }


def evaluate_semantic_timing_data(
    storyboard: dict[str, Any],
    timed_storyboard: dict[str, Any],
    sentence_cues: Any = None,
    char_baseline: dict[str, Any] | None = None,
    trace: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return build_semantic_timing_report(
        storyboard,
        timed_storyboard,
        sentence_cues,
        char_baseline,
        trace,
        **kwargs,
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_artifact(context: Any, roles: tuple[str, ...], names: tuple[str, ...]) -> Path | None:
    for role in roles:
        try:
            path = context.artifact(role)
        except (AttributeError, ValueError):
            path = None
        if path is not None and path.is_file():
            return path
    root = Path(context.artifacts_root)
    for name in names:
        path = root / name
        if path.is_file():
            return path
    return None


def evaluate_semantic_timing(context: Any) -> dict[str, Any]:
    """Runner-compatible adapter; missing trace is a non-failing condition."""
    name = "semantic_timing"
    timed_path = _find_artifact(
        context,
        ("semantic_timed_storyboard", "timed_storyboard"),
        ("semantic_timed_storyboard.json", "storyboard_timed.json", "timed_storyboard.json"),
    )
    storyboard_path = _find_artifact(context, ("storyboard",), ("storyboard.json",))
    if timed_path is None:
        return unavailable(context, name, "semantic timed storyboard is missing")
    try:
        timed = _load_json(timed_path)
        storyboard = _load_json(storyboard_path) if storyboard_path else timed
    except (OSError, json.JSONDecodeError) as exc:
        return unavailable(context, name, f"semantic timing input cannot be read: {exc}")
    cues_path = _find_artifact(
        context, ("sentence_cues", "cues"), ("sentence_cues.json", "cues.json")
    )
    baseline_path = _find_artifact(
        context,
        ("char_proportional_baseline", "timing_baseline"),
        ("char_proportional_baseline.json", "overall_char_proportional_baseline.json"),
    )
    trace_path = _find_artifact(
        context, ("animation_trace", "raw_animation_trace"), ("animation_trace.json",)
    )
    cues = _load_json(cues_path) if cues_path else None
    baseline = _load_json(baseline_path) if baseline_path else None
    trace = _load_json(trace_path) if trace_path else None
    report = build_semantic_timing_report(
        storyboard,
        timed,
        cues,
        baseline,
        trace,
        case_id=context.case.case_id,
        lesson_id=context.case.lesson_id,
        source_paths={
            "storyboard": storyboard_path,
            "semantic_timed_storyboard": timed_path,
            "sentence_cues": cues_path,
            "char_proportional_baseline": baseline_path,
            "animation_trace": trace_path,
        },
    )
    evidence = []
    evidence_id = f"{context.case.case_id}-semantic-timing"
    for key, path in report["inputs"].items():
        if path:
            evidence.append(evidence_for(Path(path), evidence_id=f"{evidence_id}-{key}", kind=key))
    report["evidence_ids"] = [item["evidence_id"] for item in evidence]
    report["_evidence"] = evidence
    report["details"] = {
        "semantic_alignment": report["semantic_alignment"],
        "planning_timing_comparison": report["planning_timing_comparison"],
        "runtime_execution": report["runtime_execution"],
        "failure_exclusions": report["failure_exclusions"],
        "top_timing_errors": report["top_timing_errors"],
    }
    return report


evaluate_semantic_timing.evaluator_name = "semantic_timing"


def _markdown(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    methods = json.dumps(metrics.get("match_method_distribution", {}), ensure_ascii=False)
    lines = [
        f"# Semantic Timing Evaluator — {report.get('case_id')}",
        "",
        f"- Lesson: `{report.get('lesson_id')}`",
        f"- Status: **{report.get('status')}**",
        "- Semantic plan error is implementation consistency only, not semantic correctness.",
        "",
        "## Semantic Alignment",
        "",
        f"- Semantic matched: `{metrics.get('semantic_matched_count')}`",
        f"- Fallback: `{metrics.get('fallback_count')}`",
        f"- Match methods: `{methods}`",
        f"- Human review available: `{metrics.get('human_review_available')}`; "
        f"reviewed=`{metrics.get('human_reviewed_count')}`, "
        f"correct=`{metrics.get('human_correct_count')}`",
        "",
        "## Planning Timing Comparison",
        "",
        f"- Evaluated elements: `{metrics.get('evaluated_element_count')}`",
        f"- Char MAE: `{metrics.get('char_mae_sec')}` s; "
        f"median=`{metrics.get('char_median_error_sec')}` s; "
        f"P95=`{metrics.get('char_p95_error_sec')}` s; "
        f"max=`{metrics.get('char_max_error_sec')}` s",
        "",
        "## Runtime Execution",
        "",
        f"- Status: `{metrics.get('runtime_status')}`",
        f"- Trace available: `{metrics.get('runtime_trace_available')}`",
        f"- Runtime evaluated: `{metrics.get('runtime_evaluated_count')}`; "
        f"MAE=`{metrics.get('runtime_mae_sec')}` s",
        "",
        "## Failure / Exclusion Reasons",
        "",
        f"- Excluded records: `{report.get('failure_exclusions', {}).get('count', 0)}`",
        f"- Runtime target missing: `{metrics.get('target_missing_count')}`; "
        f"unsupported=`{metrics.get('unsupported_count')}`; "
        f"runtime errors=`{metrics.get('runtime_error_count')}`",
        "",
        "## Top Timing Errors",
        "",
        "| Lesson | Slide | Element | Element text | Matched sentence | "
        "Char trigger | Semantic trigger | Char error |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in report.get("top_timing_errors", []):
        text = str(row.get("element_text", "")).replace("|", "\\|").replace("\n", " ")
        sentence = str(row.get("matched_sentence_text", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row.get('lesson_id')} | {row.get('slide_id')} | "
            f"{row.get('element_id')} | {text} | {sentence} | "
            f"{row.get('char_proportional_trigger_sec')} | "
            f"{row.get('semantic_planned_trigger_sec')} | "
            f"{row.get('char_error_sec')} |"
        )
    return "\n".join(lines) + "\n"


def generate_pilot3_reports(
    repo_root: str | Path,
    cues_root: str | Path,
    output_dir: str | Path,
    *,
    baseline_root: str | Path | None = None,
    lesson_ids: Iterable[str] = ("lesson_001", "lesson_002", "lesson_004"),
    top_n: int = 10,
) -> list[Path]:
    """Generate planning-only reports from the local pilot3 inputs."""
    root = Path(repo_root).resolve()
    cues_base = Path(cues_root).resolve()
    baseline_base = Path(baseline_root).resolve() if baseline_root else None
    reports: list[dict[str, Any]] = []
    for lesson_id in lesson_ids:
        storyboard_path = root / "datasets" / "pilot3" / "artifacts" / lesson_id / "storyboard.json"
        cue_path = cues_base / f"{lesson_id}_sentence_cues.json"
        storyboard = _load_json(storyboard_path)
        cues = _load_json(cue_path) if cue_path.is_file() else None
        timed = apply_timing(storyboard, cues)
        baseline = None
        baseline_path = None
        if baseline_base:
            baseline_path = baseline_base / f"{lesson_id}_char_proportional_baseline.json"
            if baseline_path.is_file():
                baseline = _load_json(baseline_path)
        reports.append(
            build_semantic_timing_report(
                storyboard,
                timed,
                cues,
                baseline,
                None,
                case_id=f"pilot3_{lesson_id}",
                lesson_id=lesson_id,
                source_paths={
                    "storyboard": storyboard_path,
                    "semantic_timed_storyboard": None,
                    "sentence_cues": cue_path if cue_path.is_file() else None,
                    "char_proportional_baseline": baseline_path,
                    "animation_trace": None,
                },
                top_n=top_n,
            )
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for report in reports:
        stem = str(report["lesson_id"])
        json_path = output / f"{stem}_semantic_timing.json"
        md_path = output / f"{stem}_semantic_timing.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        paths.extend([json_path, md_path])
    overall_rows = [row for report in reports for row in report["evaluated_elements"]]
    overall_planning = aggregate_baseline_rows(overall_rows)
    overall_methods: Counter[str] = Counter()
    overall_semantic_count = 0
    overall_fallback_count = 0
    for report in reports:
        metrics = report.get("metrics", {})
        overall_semantic_count += int(metrics.get("semantic_matched_count") or 0)
        overall_fallback_count += int(metrics.get("fallback_count") or 0)
        for method, count in (metrics.get("match_method_distribution") or {}).items():
            overall_methods[str(method)] += int(count or 0)
    review_source = next(
        (
            report.get("semantic_alignment", {})
            for report in reports
            if report.get("semantic_alignment", {}).get("human_review_available")
        ),
        None,
    )
    review = (
        {
            key: review_source.get(key)
            for key in (
                "human_review_available",
                "human_reviewed_count",
                "human_correct_count",
                "human_incorrect_count",
                "human_uncertain_count",
            )
        }
        if review_source is not None
        else {
            "human_review_available": False,
            "human_reviewed_count": None,
            "human_correct_count": None,
            "human_incorrect_count": None,
            "human_uncertain_count": None,
        }
    )
    overall = {
        "schema_version": "textbookeval-semantic-timing-v0.1",
        "report_type": "semantic_timing_overall",
        "case_ids": [report["case_id"] for report in reports],
        "status": "ok",
        "metrics": {
            "semantic_matched_count": overall_semantic_count,
            "fallback_count": overall_fallback_count,
            "match_method_distribution": dict(sorted(overall_methods.items())),
            **review,
            **overall_planning,
            "runtime_trace_available": False,
            "runtime_status": "not_evaluated",
            "runtime_evaluated_count": None,
            "runtime_mae_sec": None,
            "runtime_mae_ms": None,
        },
        "planning_timing_comparison": {
            "baseline": "char_proportional",
            "semantic_plan_error_interpretation": (
                "implementation consistency only; not semantic correctness"
            ),
        },
        "runtime_execution": {
            "status": "not_evaluated",
            "reason": "trace unavailable",
            "runtime_trace_available": False,
        },
        "cases": [
            {
                "case_id": report["case_id"],
                "lesson_id": report["lesson_id"],
                "metrics": report["metrics"],
            }
            for report in reports
        ],
        "top_timing_errors": sorted(
            overall_rows,
            key=lambda row: (
                -float(row.get("char_error_sec") or 0),
                str(row.get("lesson_id")),
                str(row.get("segment_id")),
                str(row.get("element_id")),
            ),
        )[: max(0, int(top_n))],
    }
    overall_json = output / "overall_semantic_timing.json"
    overall_md = output / "overall_semantic_timing.md"
    overall_json.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")
    overall_md.write_text(_markdown(overall), encoding="utf-8")
    paths.extend([overall_json, overall_md])
    return paths
