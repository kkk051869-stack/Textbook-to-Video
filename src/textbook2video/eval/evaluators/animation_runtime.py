"""Normalize B's animation runtime trace and calculate non-aggregate metrics."""

from __future__ import annotations

import json
from pathlib import Path

from ..runner import EvalContext
from ..schemas import validate_with_contract
from .common import evidence_for, unavailable


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def evaluate_animation_runtime(context: EvalContext) -> dict:
    name = "animation_runtime"
    path = context.artifact("animation_trace")
    if path is None or not path.is_file():
        return unavailable(context, name, "baseline_artifacts.animation_trace is missing")

    trace = json.loads(path.read_text(encoding="utf-8"))
    contracts_dir = Path(__file__).resolve().parents[4] / "contracts"
    validate_with_contract(trace, "animation_trace.schema.json", contracts_dir=contracts_dir)
    events = trace["events"]
    planned = len(events)
    resolved = sum(bool(item["target_resolved"]) for item in events)
    executed = sum(bool(item["executed"]) for item in events)
    realized = sum(bool(item.get("effect_realized")) for item in events)
    supported_effects = sum(item.get("effect_realized") is not None for item in events)
    execution_errors = sum(item["status"] == "error" for item in events)
    unsupported = sum(item.get("error_code") == "UNSUPPORTED_EFFECT" for item in events)
    timing_errors = []
    late = 0
    for item in events:
        actual = item.get("actual") or {}
        planned_params = item.get("planned") or {}
        if actual.get("start_ms") is None or planned_params.get("start_ms") is None:
            continue
        delta = float(actual["start_ms"]) - float(planned_params["start_ms"])
        timing_errors.append(abs(delta))
        late += delta > 500

    evidence_id = f"{context.case.case_id}-animation-trace"
    issues = []
    for item in events:
        if item["target_resolved"] and item["status"] not in {"error", "skipped"}:
            continue
        issues.append(
            {
                "case_id": context.case.case_id,
                "stage": "animation",
                "evaluator": name,
                "type": str(item.get("error_code") or "ANIMATION_EVENT_FAILED"),
                "severity": "major",
                "message": str(item.get("message") or f"animation event {item['event_id']} failed"),
                "slide": item["slide"],
                "event_id": item["event_id"],
                "evidence_ids": [evidence_id],
                "review_status": "unreviewed",
            }
        )
    for error in trace.get("runtime_errors", []):
        issues.append(
            {
                "case_id": context.case.case_id,
                "stage": "animation",
                "evaluator": name,
                "type": "ANIMATION_RUNTIME_ERROR",
                "severity": "major",
                "message": str(error.get("message") or error),
                "evidence_ids": [evidence_id],
                "review_status": "unreviewed",
                "evidence": error,
            }
        )

    passed = not issues
    return {
        "status": "ok" if passed else "failed",
        "passed": passed,
        "metrics": {
            "planned_event_count": planned,
            "executed_event_count": executed,
            "target_resolution_rate": _rate(resolved, planned),
            "effect_realization_rate": _rate(realized, supported_effects),
            "unsupported_effect_count": unsupported,
            "execution_error_count": execution_errors + len(trace.get("runtime_errors", [])),
            "timing_mae_ms": (
                round(sum(timing_errors) / len(timing_errors), 3) if timing_errors else None
            ),
            "late_event_rate_500ms": _rate(late, len(timing_errors)),
        },
        "details": {"failed_event_count": len(issues)},
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(path, evidence_id=evidence_id, kind="animation_trace")],
    }


evaluate_animation_runtime.evaluator_name = "animation_runtime"
