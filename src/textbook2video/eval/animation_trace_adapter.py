"""Adapt B's raw animation trace to A's animation-trace-v0.1 contract.

The browser Runtime deliberately keeps its raw trace as a simple JSON array.
This module is an Eval/Integration boundary: it adds case identity, resolves
slide ids using the frozen storyboard order, maps Runtime statuses to the
formal evaluator statuses, and validates the result against the public schema.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .schemas import load_json_object, validate_with_contract

STATUS_MAP = {
    "executed": "executed",
    "target_missing": "skipped",
    "unsupported_action": "degraded",
    "runtime_error": "error",
    "cancelled": "skipped",
    "scheduled": "skipped",
}


def _load_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {source}: {exc}") from exc


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"animation trace event missing {field}")
    return text


def _slide_index_map(storyboard: Any) -> dict[str, int]:
    if isinstance(storyboard, dict):
        segments = storyboard.get("segments")
    else:
        segments = storyboard
    if not isinstance(segments, list) or not segments:
        raise ValueError("storyboard must contain a non-empty segments array")

    result: dict[str, int] = {}
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError(f"storyboard segment {index} must be an object")
        slide_id = _required_text(segment.get("id"), field=f"storyboard segment {index}.id")
        if slide_id in result:
            raise ValueError(f"storyboard has duplicate slide id: {slide_id}")
        result[slide_id] = index
    return result


def _number_or_none(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value >= 0 else None
    return None


def _params(event: dict[str, Any], *, actual: bool) -> dict[str, Any]:
    start = event.get("actual_ms") if actual else event.get("planned_ms")
    return {
        "trigger": event.get("action"),
        "effect": event.get("effect"),
        "start_ms": _number_or_none(start),
        "duration_ms": _number_or_none(event.get("duration_ms")),
        "easing": event.get("easing"),
    }


def _error_code(status: str, error: Any) -> str | None:
    if status == "target_missing":
        return "TARGET_MISSING"
    if status == "unsupported_action":
        if str(error or "").startswith("unsupported_effect:"):
            return "UNSUPPORTED_EFFECT"
        return "UNSUPPORTED_ACTION"
    if status == "runtime_error":
        return "RUNTIME_ERROR"
    if status == "cancelled":
        return "CANCELLED"
    if status == "scheduled":
        return "UNOBSERVED_EVENT"
    # A normal executed event is not an error.  Keep the formal trace quiet
    # unless the Runtime supplied an actual failure state.
    if status == "executed":
        return None
    return "UNKNOWN_STATUS"


def _message(status: str, error: Any) -> str | None:
    if error:
        return str(error)
    if status == "scheduled":
        return "event remained scheduled and was not observed"
    if status not in STATUS_MAP:
        return f"unknown B runtime status: {status}"
    return None


def _adapt_event(event: Any, slide_map: dict[str, int]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("raw animation trace events must be objects")
    event_id = _required_text(event.get("event_id"), field="event_id")
    slide_id = _required_text(event.get("slide_id"), field=f"{event_id}.slide_id")
    target = _required_text(event.get("target"), field=f"{event_id}.target")
    if slide_id not in slide_map:
        raise ValueError(f"trace event {event_id} references unknown slide_id: {slide_id}")

    status = _required_text(event.get("status"), field=f"{event_id}.status")
    output_status = STATUS_MAP.get(status, "error")
    executed = status == "executed"
    target_resolved = status in {"executed", "unsupported_action"}
    error = event.get("error")
    effect_realized = event.get("effect_realized")
    if not isinstance(effect_realized, bool):
        # The browser trace proves scheduling/execution, but not the visual
        # CSS/DOM effect unless an independent observation was recorded.
        effect_realized = None
    return {
        "event_id": event_id,
        "slide": slide_map[slide_id],
        "target": target,
        "target_resolved": target_resolved,
        "executed": executed,
        "effect_realized": effect_realized,
        "status": output_status,
        "planned": _params(event, actual=False),
        "actual": _params(event, actual=True) if executed else None,
        "fallback": "runtime_unsupported" if status == "unsupported_action" else None,
        "error_code": _error_code(status, error),
        "message": _message(status, error),
    }


def adapt_animation_trace(
    raw_trace: list[Any],
    *,
    manifest: dict[str, Any],
    storyboard: Any,
) -> dict[str, Any]:
    """Convert a B raw trace array into a schema-valid A trace object."""
    if not isinstance(raw_trace, list):
        raise ValueError("B raw animation trace must be a JSON array")
    case_id = _required_text(manifest.get("case_id"), field="manifest.case_id")
    lesson_id = _required_text(manifest.get("lesson_id"), field="manifest.lesson_id")
    slide_map = _slide_index_map(storyboard)
    events = [_adapt_event(event, slide_map) for event in raw_trace]
    runtime_errors = [
        {
            "event_id": event["event_id"],
            "slide": event["slide"],
            "message": event["message"],
        }
        for event in events
        if event["status"] == "error"
    ]
    result: dict[str, Any] = {
        "schema_version": "animation-trace-v0.1",
        "case_id": case_id,
        "lesson_id": lesson_id,
        "events": events,
    }
    if runtime_errors:
        result["runtime_errors"] = runtime_errors
    return result


def adapt_animation_trace_file(
    raw_trace_path: str | Path,
    manifest_path: str | Path,
    storyboard_path: str | Path,
    output_path: str | Path,
) -> Path:
    manifest = load_json_object(manifest_path)
    raw_trace = _load_json(raw_trace_path)
    storyboard = _load_json(storyboard_path)
    result = adapt_animation_trace(raw_trace, manifest=manifest, storyboard=storyboard)
    contracts_dir = Path(__file__).resolve().parents[3] / "contracts"
    validate_with_contract(result, "animation_trace.schema.json", contracts_dir=contracts_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adapt B raw animation trace to A v0.1 trace")
    parser.add_argument("--trace", required=True, type=Path, help="B raw trace JSON array")
    parser.add_argument("--manifest", required=True, type=Path, help="case_manifest.json")
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output = adapt_animation_trace_file(
        args.trace,
        args.manifest,
        args.storyboard,
        args.out,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
