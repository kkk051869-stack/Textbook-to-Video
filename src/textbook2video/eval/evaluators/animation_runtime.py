"""Normalize B's animation runtime trace and calculate non-aggregate metrics."""

from __future__ import annotations

import json
from pathlib import Path

from ..runner import EvalContext
from ..animation_trace_adapter import adapt_animation_trace
from ..schemas import validate_with_contract
from .common import evidence_for, unavailable


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def evaluate_animation_runtime(context: EvalContext) -> dict:
    name = "animation_runtime"
    path = context.artifact("animation_trace") or context.artifact("raw_animation_trace")
    if path is None or not path.is_file():
        return unavailable(context, name, "candidate animation_trace.json is missing")

    trace = json.loads(path.read_text(encoding="utf-8"))
    contracts_dir = Path(__file__).resolve().parents[4] / "contracts"
    raw_path = context.artifact("raw_animation_trace")
    raw_adapter_validated = False
    if isinstance(trace, list):
        storyboard_path = context.artifact("storyboard")
        if storyboard_path is None or not storyboard_path.is_file():
            raise FileNotFoundError("raw animation trace requires a candidate storyboard")
        trace = adapt_animation_trace(
            trace,
            manifest=context.case.raw,
            storyboard=json.loads(storyboard_path.read_text(encoding="utf-8")),
        )
        adapted_path = context.output_root / "animation_trace.json"
        adapted_path.parent.mkdir(parents=True, exist_ok=True)
        adapted_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence_path = adapted_path
    else:
        evidence_path = path
        # Cloud runs commonly publish both forms. Validate that the raw
        # browser output remains adaptable instead of trusting only the copy.
        if raw_path is not None and raw_path.is_file():
            raw_trace = json.loads(raw_path.read_text(encoding="utf-8"))
            if not isinstance(raw_trace, list):
                raise ValueError("raw animation trace must be an array")
            storyboard_path = context.artifact("storyboard")
            if storyboard_path is None or not storyboard_path.is_file():
                raise FileNotFoundError("raw animation trace requires a candidate storyboard")
            adapted_raw = adapt_animation_trace(
                raw_trace,
                manifest=context.case.raw,
                storyboard=json.loads(storyboard_path.read_text(encoding="utf-8")),
            )
            validate_with_contract(adapted_raw, "animation_trace.schema.json", contracts_dir=contracts_dir)
            raw_adapter_validated = True
    exported_path = context.output_root / "animation_trace.json"
    exported_path.parent.mkdir(parents=True, exist_ok=True)
    exported_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_with_contract(trace, "animation_trace.schema.json", contracts_dir=contracts_dir)
    events = trace["events"]
    planned = len(events)
    resolved = sum(bool(item["target_resolved"]) for item in events)
    executed = sum(bool(item["executed"]) for item in events)
    realized = sum(bool(item.get("effect_realized")) for item in events)
    supported_effects = sum(
        item.get("error_code") not in {"UNSUPPORTED_EFFECT", "UNSUPPORTED_ACTION"}
        for item in events
    )
    execution_errors = sum(item["status"] == "error" for item in events)
    unsupported_effects = sum(item.get("error_code") == "UNSUPPORTED_EFFECT" for item in events)
    unsupported_actions = sum(item.get("error_code") == "UNSUPPORTED_ACTION" for item in events)
    target_missing = sum(item.get("error_code") == "TARGET_MISSING" for item in events)
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
            "target_missing_count": target_missing,
            "target_resolution_rate": _rate(resolved, planned),
            "effect_realization_rate": _rate(realized, supported_effects),
            "unsupported_effect_count": unsupported_effects,
            "unsupported_action_count": unsupported_actions,
            "execution_error_count": execution_errors + len(trace.get("runtime_errors", [])),
            "timing_mae_ms": (
                round(sum(timing_errors) / len(timing_errors), 3) if timing_errors else None
            ),
            "late_event_rate_500ms": _rate(late, len(timing_errors)),
        },
        "details": {
            "failed_event_count": len(issues),
            "adapted_trace": str(evidence_path),
            "exported_trace": str(exported_path),
            "raw_trace": str(raw_path) if raw_path else None,
            "raw_adapter_validated": raw_adapter_validated,
        },
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(evidence_path, evidence_id=evidence_id, kind="animation_trace")],
    }


evaluate_animation_runtime.evaluator_name = "animation_runtime"
