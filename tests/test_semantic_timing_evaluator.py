import copy
import json
from pathlib import Path

from textbook2video.eval.runner import run_case

from textbook2video.eval.evaluators.semantic_timing import (
    build_semantic_timing_report,
    evaluate_semantic_timing,
)


class _RunnerCase:
    case_id = "semantic_runner"
    lesson_id = "semantic_lesson"
    dataset_version = "test"

    def __init__(self, root: Path):
        self.manifest_path = root / "case_manifest.json"
        self.raw = {"case_id": self.case_id, "lesson_id": self.lesson_id}

    def assets(self):
        return []

    def resolve_asset(self, asset):
        return Path(asset.path)


def _inputs():
    storyboard = {
        "metadata": {"lesson_id": "lesson_test"},
        "segments": [
            {
                "id": "s1",
                "narration": "展示芯片和传感器。",
                "audio_duration_sec": 5.0,
                "elements": [
                    {"id": "e1", "type": "heading", "text": "芯片与传感器"},
                    {"id": "e2", "type": "text", "text": "芯片"},
                    {"id": "e3", "type": "text", "text": "传感器"},
                ],
            }
        ],
    }
    timed = copy.deepcopy(storyboard)
    timed["segments"][0]["animations"] = [
        {
            "target": "e1",
            "trigger_at_sec": 0.0,
            "trigger_source": "text_match",
            "matched_sentence_id": "sentence_1",
            "matched_sentence_text": "展示芯片和传感器。",
            "match_method": "substring",
            "match_score": 0.96,
            "lead_sec": 1.0,
        },
        {
            "target": "e2",
            "trigger_at_sec": 1.0,
            "trigger_source": "text_match",
            "matched_sentence_id": "sentence_1",
            "matched_sentence_text": "展示芯片和传感器。",
            "match_method": "token_overlap",
            "match_score": 0.9,
            "lead_sec": 1.0,
        },
        {
            "target": "e3",
            "trigger_at_sec": 2.0,
            "trigger_source": "decorative_fallback",
            "lead_sec": 1.0,
        },
    ]
    return storyboard, timed


def _event(
    event_id,
    target,
    *,
    status="executed",
    planned_ms=1000,
    actual_ms=1100,
    target_resolved=True,
    executed=True,
    error_code=None,
):
    return {
        "event_id": event_id,
        "slide": 1,
        "target": target,
        "target_resolved": target_resolved,
        "executed": executed,
        "status": status,
        "planned": {"start_ms": planned_ms},
        "actual": {"start_ms": actual_ms} if actual_ms is not None else None,
        "error_code": error_code,
    }


def test_lead_report_separates_clamped_and_unclamped_semantic_elements():
    storyboard, timed = _inputs()
    timed["segments"][0]["animations"][0]["trigger_at_sec"] = 1.0
    timed["segments"][0]["animations"][1]["trigger_at_sec"] = 2.0
    cues = {
        "segments": [
            {
                "segment_id": "s1",
                "cues": [
                    {
                        "sentence_id": "sentence_1",
                        "text": "展示芯片和传感器。",
                        "start_sec": 2.0,
                        "end_sec": 5.0,
                    }
                ],
            }
        ]
    }
    trace = {
        "schema_version": "animation-trace-v0.1",
        "events": [
            _event("e1", "e1", planned_ms=1000, actual_ms=1100),
            _event("e2", "e2", planned_ms=2000, actual_ms=2100),
        ],
    }

    report = build_semantic_timing_report(storyboard, timed, cues, trace=trace)
    e1 = next(row for row in report["evaluated_elements"] if row["element_id"] == "e1")
    e2 = next(row for row in report["evaluated_elements"] if row["element_id"] == "e2")

    assert e1["configured_lead_sec"] == 1.0
    assert e1["planned_lead_sec"] == 1.0
    assert e1["actual_lead_sec"] == 0.9
    assert e1["lead_execution_error_sec"] == -0.1
    assert e1["lead_clamped"] is False
    assert e2["planned_lead_sec"] == 0.0
    assert e2["lead_clamped"] is True
    assert report["metrics"]["lead_successfully_executed_count"] == 2
    assert report["metrics"]["lead_clamped_count"] == 1
    assert report["metrics"]["lead_unclamped_count"] == 1
    assert report["metrics"]["unclamped_actual_lead_mean_sec"] == 0.9
    assert report["metrics"]["lead_execution_error_mae_sec"] == 0.1


def test_planning_report_is_available_without_runtime_trace():
    storyboard, timed = _inputs()
    report = build_semantic_timing_report(storyboard, timed)
    assert report["status"] == "ok"
    assert report["metrics"]["semantic_matched_count"] == 2
    assert report["metrics"]["fallback_count"] == 1
    assert report["metrics"]["runtime_status"] == "not_evaluated"
    assert report["metrics"]["runtime_trace_available"] is False
    assert report["metrics"]["runtime_mae_sec"] is None
    assert all(
        row["trace_join_status"] == "trace_unavailable" for row in report["evaluated_elements"]
    )


def test_sentence_storyboard_and_baseline_join_and_char_metrics_match_phase3a():
    storyboard, timed = _inputs()
    baseline = build_semantic_timing_report(storyboard, timed)
    report = build_semantic_timing_report(
        storyboard,
        timed,
        char_baseline=baseline,
    )
    assert (
        report["metrics"]["evaluated_element_count"]
        == baseline["metrics"]["evaluated_element_count"]
    )
    assert report["metrics"]["char_mae_sec"] == baseline["metrics"]["char_mae_sec"]
    assert report["metrics"]["char_p95_error_sec"] == baseline["metrics"]["char_p95_error_sec"]
    assert report["evaluated_elements"][0]["matched_sentence_id"] == "sentence_1"
    assert report["evaluated_elements"][0]["semantic_planned_trigger_sec"] == 0.0


def test_supplied_historical_baseline_keeps_char_metrics_but_uses_current_semantic_plan():
    storyboard, historical_timed = _inputs()
    baseline = build_semantic_timing_report(storyboard, historical_timed)
    current_timed = copy.deepcopy(historical_timed)
    current_timed["segments"][0]["animations"][0]["trigger_at_sec"] = 1.25

    report = build_semantic_timing_report(
        storyboard,
        current_timed,
        char_baseline=baseline,
    )

    historical_row = next(
        row for row in baseline["evaluated_elements"] if row["element_id"] == "e1"
    )
    current_row = next(
        row for row in report["evaluated_elements"] if row["element_id"] == "e1"
    )
    assert current_row["semantic_planned_trigger_sec"] == 1.25
    assert current_row["semantic_trigger_sec"] == 1.25
    assert current_row["semantic_plan_error_sec"] == 1.25
    assert current_row["char_proportional_trigger_sec"] == historical_row[
        "char_proportional_trigger_sec"
    ]
    assert report["metrics"]["char_mae_sec"] == baseline["metrics"]["char_mae_sec"]


def test_semantic_plan_error_uses_sentence_start_and_lead():
    storyboard, timed = _inputs()
    timed["segments"][0]["animations"][0]["trigger_at_sec"] = 0.4
    report = build_semantic_timing_report(storyboard, timed)
    heading = next(row for row in report["evaluated_elements"] if row["element_id"] == "e1")
    assert heading["target_trigger_sec"] == 0.0
    assert heading["semantic_plan_error_sec"] == 0.4


def test_stable_slide_target_join_and_unmatched_trace_do_not_become_timing_errors():
    storyboard, timed = _inputs()
    trace = {"schema_version": "animation-trace-v0.1", "events": [_event("a-e1", "e1")]}
    report = build_semantic_timing_report(storyboard, timed, trace=trace)
    e1 = next(row for row in report["evaluated_elements"] if row["element_id"] == "e1")
    e2 = next(row for row in report["evaluated_elements"] if row["element_id"] == "e2")
    assert e1["trace_join_status"] == "joined"
    assert e1["trace_event_id"] == "a-e1"
    assert e1["actual_trigger_sec"] == 1.1
    assert e2["trace_join_status"] == "not_found"
    assert report["metrics"]["runtime_evaluated_count"] == 1
    assert report["metrics"]["unmatched_trace_count"] == 0


def test_target_missing_is_separate_from_runtime_timing_error():
    storyboard, timed = _inputs()
    trace = {
        "schema_version": "animation-trace-v0.1",
        "events": [
            _event(
                "missing",
                "e1",
                status="skipped",
                actual_ms=None,
                target_resolved=False,
                executed=False,
                error_code="TARGET_MISSING",
            )
        ],
    }
    report = build_semantic_timing_report(storyboard, timed, trace=trace)
    assert report["metrics"]["target_missing_count"] == 1
    assert report["metrics"]["runtime_error_count"] == 0
    assert report["metrics"]["runtime_evaluated_count"] == 0
    assert report["metrics"]["runtime_mae_sec"] is None


def test_runtime_error_event_is_counted_but_excluded_from_runtime_mae():
    storyboard, timed = _inputs()
    trace = {
        "schema_version": "animation-trace-v0.1",
        "events": [_event("err", "e1", status="error", actual_ms=1200, error_code="RUNTIME_ERROR")],
    }
    report = build_semantic_timing_report(storyboard, timed, trace=trace)
    assert report["metrics"]["runtime_error_count"] == 1
    assert report["metrics"]["runtime_evaluated_count"] == 0
    assert report["metrics"]["runtime_mae_sec"] is None


def test_runtime_error_summary_is_not_double_counted():
    storyboard, timed = _inputs()
    trace = {
        "schema_version": "animation-trace-v0.1",
        "events": [_event("err", "e1", status="error", actual_ms=None, error_code="RUNTIME_ERROR")],
        "runtime_errors": [{"event_id": "err"}],
    }

    report = build_semantic_timing_report(storyboard, timed, trace=trace)

    assert report["metrics"]["runtime_error_count"] == 1


def test_runtime_percentiles_and_early_late_counts_are_aggregated():
    storyboard, timed = _inputs()
    timed["segments"][0]["animations"][2] = {
        "target": "e3",
        "trigger_at_sec": 3.0,
        "trigger_source": "text_match",
        "matched_sentence_id": "sentence_1",
        "matched_sentence_text": "展示芯片和传感器。",
        "match_method": "token_overlap",
        "match_score": 0.9,
        "lead_sec": 1.0,
    }
    trace = {
        "schema_version": "animation-trace-v0.1",
        "events": [
            _event("e1", "e1", planned_ms=0, actual_ms=100),
            _event("e2", "e2", planned_ms=0, actual_ms=900),
            _event("e3", "e3", planned_ms=0, actual_ms=4600),
        ],
    }
    report = build_semantic_timing_report(storyboard, timed, trace=trace)
    metrics = report["metrics"]
    assert metrics["runtime_evaluated_count"] == 3
    assert metrics["runtime_mae_sec"] == 0.6
    assert metrics["runtime_median_error_sec"] == 0.1
    assert metrics["runtime_p95_error_sec"] == 1.45
    assert metrics["runtime_max_error_sec"] == 1.6
    assert metrics["early_event_count"] == 1
    assert metrics["late_event_count"] == 2


def test_same_sentence_elements_join_independently_and_fallback_is_excluded():
    storyboard, timed = _inputs()
    trace = {
        "schema_version": "animation-trace-v0.1",
        "events": [_event("e1", "e1"), _event("e2", "e2")],
    }
    report = build_semantic_timing_report(storyboard, timed, trace=trace)
    rows = report["evaluated_elements"]
    assert {row["element_id"] for row in rows} == {"e1", "e2"}
    assert {row["matched_sentence_id"] for row in rows} == {"sentence_1"}
    assert all(row["trace_join_status"] == "joined" for row in rows)
    assert report["metrics"]["evaluated_element_count"] == 2


def test_human_review_only_counts_supplied_records():
    storyboard, timed = _inputs()
    timed["metadata"]["human_review"] = {
        "records": [
            {"element_id": "e1", "status": "correct"},
            {"element_id": "e2", "status": "uncertain"},
        ]
    }
    report = build_semantic_timing_report(storyboard, timed)
    metrics = report["metrics"]
    assert metrics["human_review_available"] is True
    assert metrics["human_reviewed_count"] == 2
    assert metrics["human_correct_count"] == 1
    assert metrics["human_incorrect_count"] == 0
    assert metrics["human_uncertain_count"] == 1


def test_no_human_review_metadata_is_not_inferred_from_semantic_count():
    storyboard, timed = _inputs()
    report = build_semantic_timing_report(storyboard, timed)
    assert report["metrics"]["human_review_available"] is False
    assert report["metrics"]["human_reviewed_count"] is None


def test_runner_keeps_semantic_report_in_standard_details_contract(tmp_path):
    storyboard, timed = _inputs()
    (tmp_path / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
    (tmp_path / "storyboard_timed.json").write_text(json.dumps(timed), encoding="utf-8")
    (tmp_path / "sentence_cues.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "segment_id": "s1",
                        "cues": [
                            {
                                "sentence_id": "sentence_1",
                                "text": "topic",
                                "start_sec": 1.0,
                                "end_sec": 5.0,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = run_case(
        _RunnerCase(tmp_path),
        run_id="semantic-runner-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
        evaluators=[evaluate_semantic_timing],
        repo_root=Path(__file__).resolve().parents[1],
        candidate_commit="commit-test",
    )

    result = report["evaluators"]["semantic_timing"]
    assert result["status"] == "ok"
    assert result["details"]["evaluated_elements"]
    assert result["details"]["provenance"]["candidate_commit"] == "commit-test"
