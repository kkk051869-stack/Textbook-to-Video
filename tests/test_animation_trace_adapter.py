from __future__ import annotations

import json
from pathlib import Path

import pytest

from textbook2video.eval.animation_trace_adapter import (
    adapt_animation_trace,
    adapt_animation_trace_file,
)
from textbook2video.eval.schemas import validate_with_contract


def _manifest() -> dict:
    return {"case_id": "pilot3_case", "lesson_id": "lesson_001"}


def _storyboard() -> dict:
    return {
        "segments": [
            {"id": "s1", "narration": "first"},
            {"id": "s2", "narration": "second"},
        ]
    }


def _event(status: str, *, slide_id: str = "s1", event_id: str = "event") -> dict:
    return {
        "event_id": event_id,
        "slide_id": slide_id,
        "target": "e1",
        "action": "show",
        "effect": "fadeInUp",
        "planned_ms": 100,
        "duration_ms": 600,
        "easing": "ease-out",
        "actual_ms": 104,
        "status": status,
        "error": None,
    }


def test_adapter_maps_statuses_and_validates_public_schema():
    missing = _event("target_missing", event_id="missing")
    missing["error"] = 'No element matched [data-anim-id="e1"]'
    unsupported = _event("unsupported_action", event_id="unsupported")
    unsupported["error"] = "unsupported_move:requires data-flip-id and data-step"
    runtime_error = _event("runtime_error", slide_id="s2", event_id="runtime")
    runtime_error["error"] = "querySelector failed"
    cancelled = _event("cancelled", slide_id="s2", event_id="cancelled")
    cancelled["error"] = "Animation timer cancelled"
    scheduled = _event("scheduled", slide_id="s2", event_id="scheduled")
    scheduled["actual_ms"] = None
    observed = _event("executed", event_id="same")
    observed["effect_realized"] = True
    result = adapt_animation_trace(
        [
            observed,
            _event("executed", slide_id="s2", event_id="same"),
            missing,
            unsupported,
            runtime_error,
            cancelled,
            scheduled,
        ],
        manifest=_manifest(),
        storyboard=_storyboard(),
    )

    validate_with_contract(
        result,
        "animation_trace.schema.json",
        contracts_dir=Path(__file__).parents[1] / "contracts",
    )
    assert result["schema_version"] == "animation-trace-v0.1"
    assert result["case_id"] == "pilot3_case"
    assert result["lesson_id"] == "lesson_001"
    assert [event["slide"] for event in result["events"][:2]] == [1, 2]
    assert result["events"][0]["status"] == "executed"
    assert result["events"][0]["executed"] is True
    assert result["events"][0]["effect_realized"] is True
    assert result["events"][0]["error_code"] is None
    assert result["events"][1]["effect_realized"] is None
    assert result["events"][2]["status"] == "skipped"
    assert result["events"][2]["target_resolved"] is False
    assert result["events"][2]["error_code"] == "TARGET_MISSING"
    assert result["events"][2]["actual"] is None
    assert result["events"][3]["status"] == "degraded"
    assert result["events"][3]["target_resolved"] is True
    assert result["events"][3]["effect_realized"] is None
    assert result["events"][3]["error_code"] == "UNSUPPORTED_ACTION"
    assert result["events"][4]["status"] == "error"
    assert result["events"][4]["error_code"] == "RUNTIME_ERROR"
    assert result["events"][4]["actual"] is None
    assert result["events"][5]["error_code"] == "CANCELLED"
    assert result["events"][6]["error_code"] == "UNOBSERVED_EVENT"
    assert result["events"][6]["message"]
    assert result["events"][0]["planned"]["trigger"] == "show"
    assert result["events"][0]["planned"]["start_ms"] == 100
    assert result["events"][0]["actual"]["start_ms"] == 104
    assert result["runtime_errors"][0]["event_id"] == "runtime"


def test_adapter_file_writes_schema_valid_trace(tmp_path):
    raw_path = tmp_path / "raw.json"
    manifest_path = tmp_path / "case_manifest.json"
    storyboard_path = tmp_path / "storyboard.json"
    output_path = tmp_path / "animation_trace.json"
    raw_path.write_text(json.dumps([_event("executed")]), encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    storyboard_path.write_text(json.dumps(_storyboard()), encoding="utf-8")

    assert adapt_animation_trace_file(
        raw_path, manifest_path, storyboard_path, output_path
    ) == output_path
    result = json.loads(output_path.read_text(encoding="utf-8"))
    validate_with_contract(
        result,
        "animation_trace.schema.json",
        contracts_dir=Path(__file__).parents[1] / "contracts",
    )


def test_adapter_rejects_unknown_slide_id():
    with pytest.raises(ValueError, match="unknown slide_id"):
        adapt_animation_trace(
            [_event("executed", slide_id="s9")],
            manifest=_manifest(),
            storyboard=_storyboard(),
        )
