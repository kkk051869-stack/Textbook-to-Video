"""Aggregation helpers for B-track case reports."""

from __future__ import annotations

from statistics import mean
from typing import Any


def aggregate_event_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate case metrics without treating events as independent documents."""
    metric_names = (
        "compiled_coverage",
        "runtime_coverage",
        "render_coverage",
        "target_resolution_rate",
        "planned_to_compiled_mae_sec",
        "compiled_to_runtime_mae_sec",
        "semantic_correct_rate",
        "onset_mae_sec",
        "mean_window_overlap_iou",
    )
    macro: dict[str, float | None] = {}
    for name in metric_names:
        values = [
            report.get("metrics", {}).get(name)
            for report in reports
            if isinstance(report.get("metrics", {}).get(name), (int, float))
        ]
        macro[name] = round(mean(values), 6) if values else None
    return {
        "schema_version": "b-track-aggregate-metrics-v0.1",
        "aggregation_unit": "case",
        "case_count": len(reports),
        "case_ids": [report.get("case_id") for report in reports],
        "macro_metrics": macro,
        "totals": {
            "event_count": sum(
                report.get("metrics", {}).get("event_count", 0) or 0 for report in reports
            ),
            "missing_runtime_count": sum(
                report.get("metrics", {}).get("missing_runtime_count", 0) or 0 for report in reports
            ),
            "wrong_target_count": sum(
                report.get("metrics", {}).get("wrong_target_count", 0) or 0 for report in reports
            ),
            "render_unobservable_count": sum(
                report.get("metrics", {}).get("render_unobservable_count", 0) or 0
                for report in reports
            ),
        },
        "warning": (
            "Macro metrics summarize cases; formal inference must use document-level "
            "bootstrap or mixed-effects analysis."
        ),
    }


__all__ = ["aggregate_event_reports"]
