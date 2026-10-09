import json
from pathlib import Path

import pytest

from textbook2video.research.p0_integration import (
    P0_PLAN_VERSION,
    apply_p0_event_schedule,
    prepare_p0_candidate,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _storyboard() -> dict:
    return {
        "lesson_title": "Test lesson",
        "segments": [
            {
                "id": "seg-01",
                "narration": "先介绍概念。再解释关键机制。",
                "audio_duration_sec": 8.0,
                "elements": [
                    {"id": "existing-title", "type": "heading", "text": "概念"},
                    {"id": "existing-diagram", "type": "flow_step", "text": "关键机制"},
                ],
                "animations": [
                    {"target": "existing-title", "effect": "fadeInUp", "trigger_at_sec": 0.0}
                ],
            }
        ],
    }


def test_p0_candidate_preserves_baseline_and_schedules_existing_element(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    plan = tmp_path / "p0_plan.json"
    _write_json(baseline, _storyboard())
    _write_json(
        plan,
        {
            "schema_version": P0_PLAN_VERSION,
            "events": [
                {
                    "id": "p0-event-001",
                    "segment_id": "seg-01",
                    "proposition_id": "seg-01-nprop-02",
                    "target_element_id": "existing-diagram",
                    "lead_sec": 0.0,
                }
            ],
        },
    )

    paths = prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan)
    assert json.loads(baseline.read_text(encoding="utf-8")) == _storyboard()
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    assert candidate["metadata"]["research_p0"]["enabled"] is True
    assert candidate["segments"][0]["elements"][1]["id"] == "existing-diagram"

    sidecar = apply_p0_event_schedule(paths)
    scheduled = sidecar["events"][0]
    assert scheduled["status"] == "SCHEDULED_ON_PRODUCTION_ANIMATION"
    assert scheduled["planned_trigger_at_sec"] > 0
    candidate = json.loads(paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    animation = next(
        item
        for item in candidate["segments"][0]["animations"]
        if item["target"] == "existing-diagram"
    )
    assert animation["research_p0"]["event_id"] == "p0-event-001"
    assert paths.candidate_storyboard_path.with_name("lesson_p0_timed_storyboard.json").is_file()


def test_p0_candidate_rejects_nonexistent_production_target(tmp_path: Path) -> None:
    baseline = tmp_path / "lesson_storyboard.json"
    plan = tmp_path / "p0_plan.json"
    _write_json(baseline, _storyboard())
    _write_json(
        plan,
        {
            "schema_version": P0_PLAN_VERSION,
            "events": [
                {
                    "segment_id": "seg-01",
                    "proposition_id": "seg-01-nprop-01",
                    "target_element_id": "invented-element",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="missing production element"):
        prepare_p0_candidate(baseline, output_dir=tmp_path, plan_path=plan)
