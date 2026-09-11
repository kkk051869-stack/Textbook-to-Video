"""Normalize B's animation runtime trace and calculate non-aggregate metrics."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..runner import EvalContext
from ..animation_trace_adapter import adapt_animation_trace
from ..schemas import validate_with_contract
from .common import evidence_for, unavailable


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _slide_html_blocks(html: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r'<div class="slide(?:\s[^>]*)?>', html)]
    return [
        html[start : starts[index + 1] if index + 1 < len(starts) else len(html)]
        for index, start in enumerate(starts)
    ]


def _element_map(storyboard: Any) -> dict[tuple[int, str], dict[str, Any]]:
    segments = storyboard.get("segments", []) if isinstance(storyboard, dict) else storyboard
    result: dict[tuple[int, str], dict[str, Any]] = {}
    if not isinstance(segments, list):
        return result
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        for element in segment.get("elements", []):
            if isinstance(element, dict) and element.get("id") is not None:
                result[(index, str(element["id"]))] = element
    return result


def _target_cause(
    event: dict[str, Any],
    *,
    storyboard_elements: dict[tuple[int, str], dict[str, Any]],
    slide_blocks: list[str],
    missing_by_target: dict[tuple[int, str], dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    slide = int(event.get("slide") or 0)
    target = str(event.get("target") or "")
    element = storyboard_elements.get((slide, target))
    if element is None:
        return "STORYBOARD_TARGET_INVALID", {"target": target}

    element_type = str(element.get("type") or "")
    parent_target = element.get("target") or element.get("target_image") or element.get("image_id")
    if element_type in {"callout", "focus_box"} and parent_target is not None:
        parent_missing = missing_by_target.get((slide, str(parent_target)))
        if parent_missing and parent_missing.get("cause") == "RESOURCE_OMISSION":
            return "CASCADE_TARGET_MISSING", {
                "caused_by_event_id": parent_missing.get("event_id"),
                "caused_by_target": str(parent_target),
            }

    if element_type == "image" and not str(element.get("src") or "").strip():
        return "RESOURCE_OMISSION", {"element_type": element_type}

    block = slide_blocks[slide - 1] if 0 < slide <= len(slide_blocks) else ""
    marker = f'data-anim-id="{target}"'
    if marker not in block:
        return "RENDERER_OMISSION", {"element_type": element_type}
    return "DOM_TARGET_UNRESOLVED", {"element_type": element_type}


def evaluate_animation_runtime(context: EvalContext) -> dict:
    name = "animation_runtime"
    path = context.artifact("animation_trace") or context.artifact("raw_animation_trace")
    if path is None or not path.is_file():
        return unavailable(context, name, "candidate animation_trace.json is missing")

    trace = json.loads(path.read_text(encoding="utf-8"))
    contracts_dir = Path(__file__).resolve().parents[4] / "contracts"
    raw_path = context.artifact("raw_animation_trace")
    raw_adapter_validated = False
    storyboard_path = context.artifact("storyboard")
    if raw_path is not None and raw_path.is_file():
        raw_trace = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(raw_trace, list):
            raise ValueError("raw animation trace must be an array")
        if storyboard_path is None or not storyboard_path.is_file():
            raise FileNotFoundError("raw animation trace requires a candidate storyboard")
        trace = adapt_animation_trace(
            raw_trace,
            manifest=context.case.raw,
            storyboard=json.loads(storyboard_path.read_text(encoding="utf-8")),
        )
        raw_adapter_validated = True
        adapted_path = context.output_root / "animation_trace.json"
        adapted_path.parent.mkdir(parents=True, exist_ok=True)
        adapted_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        evidence_path = adapted_path
    elif isinstance(trace, list):
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
    exported_path = context.output_root / "animation_trace.json"
    exported_path.parent.mkdir(parents=True, exist_ok=True)
    exported_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_with_contract(trace, "animation_trace.schema.json", contracts_dir=contracts_dir)
    events = trace["events"]
    planned = len(events)
    resolved = sum(bool(item["target_resolved"]) for item in events)
    executed = sum(bool(item["executed"]) for item in events)
    effect_observed = [item for item in events if isinstance(item.get("effect_realized"), bool)]
    realized = sum(bool(item.get("effect_realized")) for item in effect_observed)
    execution_errors = sum(item["status"] == "error" for item in events)
    unsupported_effects = sum(item.get("error_code") == "UNSUPPORTED_EFFECT" for item in events)
    unsupported_actions = sum(item.get("error_code") == "UNSUPPORTED_ACTION" for item in events)
    target_missing = sum(item.get("error_code") == "TARGET_MISSING" for item in events)
    storyboard = (
        json.loads(storyboard_path.read_text(encoding="utf-8"))
        if storyboard_path is not None and storyboard_path.is_file()
        else {}
    )
    html_path = context.artifact("html")
    html = html_path.read_text(encoding="utf-8", errors="replace") if html_path and html_path.is_file() else ""
    storyboard_elements = _element_map(storyboard)
    slide_blocks = _slide_html_blocks(html)
    missing_by_target: dict[tuple[int, str], dict[str, Any]] = {}
    for item in events:
        if item.get("error_code") != "TARGET_MISSING":
            continue
        cause, metadata = _target_cause(
            item,
            storyboard_elements=storyboard_elements,
            slide_blocks=slide_blocks,
            missing_by_target=missing_by_target,
        )
        missing_by_target[(int(item.get("slide") or 0), str(item.get("target") or ""))] = {
            "event_id": item.get("event_id"),
            "cause": cause,
            **metadata,
        }
    cause_counts: dict[str, int] = {
        "RESOURCE_OMISSION": 0,
        "RENDERER_OMISSION": 0,
        "COMPACTION_OMISSION": 0,
        "CASCADE_TARGET_MISSING": 0,
    }
    root_missing = 0
    cascade_missing = 0
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
        issue = {
                "case_id": context.case.case_id,
                "stage": "animation",
                "evaluator": name,
                "type": str(item.get("error_code") or "ANIMATION_EVENT_FAILED"),
                "severity": "warning" if item.get("error_code") == "TARGET_MISSING" else "major",
                "message": str(item.get("message") or f"animation event {item['event_id']} failed"),
                "slide": item["slide"],
                "event_id": item["event_id"],
                "evidence_ids": [evidence_id],
                "review_status": "unreviewed",
            }
        if item.get("error_code") == "TARGET_MISSING":
            missing = missing_by_target.get(
                (int(item.get("slide") or 0), str(item.get("target") or "")),
                {},
            )
            cause = str(missing.get("cause") or "TARGET_MISSING")
            issue["category"] = cause
            issue["metadata"] = {
                "cause": cause,
                **{key: value for key, value in missing.items() if key not in {"cause"}},
            }
            cause_counts[cause] = cause_counts.get(cause, 0) + 1
            if cause == "CASCADE_TARGET_MISSING":
                cascade_missing += 1
            else:
                root_missing += 1
        issues.append(issue)
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

    blocking_issues = [item for item in issues if item["severity"] != "warning"]
    passed = not blocking_issues
    return {
        "status": "ok" if passed else "failed",
        "passed": passed,
        "metrics": {
            "planned_event_count": planned,
            "executed_event_count": executed,
            "target_missing_count": target_missing,
            "target_missing_total": target_missing,
            "root_target_missing_count": root_missing,
            "cascade_missing_count": cascade_missing,
            "target_missing_by_cause": cause_counts,
            "target_resolution_rate": _rate(resolved, planned),
            "effect_realization_rate": _rate(realized, len(effect_observed)),
            "effect_realization_verified_count": len(effect_observed),
            "effect_realization_unverified_count": max(executed - len(effect_observed), 0),
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
