import json
from pathlib import Path

from textbook2video.eval.evaluators.av_semantic_alignment import (
    AVSemanticAlignmentAdapter,
    AlignmentThresholds,
    evaluate_av_semantic_alignment,
)
from textbook2video.eval.runner import EvalContext, run_case


class _Case:
    case_id = "case_av"
    lesson_id = "lesson_av"
    dataset_version = "dataset-test"

    def __init__(self, root: Path):
        self.root = root
        self.manifest_path = root / "case_manifest.json"
        self.raw = {"case_id": self.case_id, "lesson_id": self.lesson_id}

    def assets(self):
        return []

    def resolve_asset(self, asset):
        return self.root / asset.path


def _context(tmp_path: Path) -> EvalContext:
    return EvalContext(
        case=_Case(tmp_path),
        run_id="av-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
        candidate_commit="commit-test",
    )


def _write_fixture(
    tmp_path: Path,
    events: list[dict],
    trace_events: list[dict] | None = None,
    *,
    sentence_cues: list[dict] | None = None,
) -> None:
    timeline = []
    for event in events:
        item = dict(event)
        item.pop("slide_id", None)
        timeline.append(item)
    (tmp_path / "storyboard_timed.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": 1,
                        "elements": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
                        "timeline": timeline,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    trace = trace_events if trace_events is not None else [
        {
            "event_id": event["event_id"],
            "slide": 1,
            "target": event["target"],
            "target_resolved": True,
            "status": "executed",
            "actual": {"start_ms": event["at_sec"] * 1000},
        }
        for event in events
        if event.get("event_id")
    ]
    (tmp_path / "animation_trace.json").write_text(
        json.dumps({"events": trace}), encoding="utf-8"
    )
    if sentence_cues is not None:
        (tmp_path / "sentence_cues.json").write_text(
            json.dumps({"sentences": sentence_cues}), encoding="utf-8"
        )


def _bound(event_id: str, target: str, at: float, start: float, lead: float = 0.0) -> dict:
    return {
        "event_id": event_id,
        "target": target,
        "at_sec": at,
        "matched_sentence_id": "s1",
        "sentence_start_sec": start,
        "lead_sec": lead,
        "trigger_source": "sentence_cue",
    }


def test_perfect_alignment_and_three_independent_errors(tmp_path):
    events = [
        _bound("a1", "e1", 1.0, 2.0, 1.0),
        _bound("a2", "e2", 2.3, 3.0, 1.0),
        _bound("a3", "e3", 5.0, 4.0, 0.0),
    ]
    trace = [
        {"event_id": "a1", "slide": 1, "target": "e1", "target_resolved": True, "status": "executed", "actual": {"start_ms": 1000}},
        {"event_id": "a2", "slide": 1, "target": "e2", "target_resolved": True, "status": "executed", "actual": {"start_ms": 2500}},
        {"event_id": "a3", "slide": 1, "target": "e3", "target_resolved": True, "status": "executed", "actual": {"start_ms": 6200}},
    ]
    _write_fixture(tmp_path, events, trace)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))

    assert result["status"] == "failed"
    assert result["passed"] is False
    metrics = result["metrics"]
    assert metrics["planned_event_count"] == 3
    assert metrics["semantic_match_count"] == 3
    assert metrics["semantic_evaluable_count"] == 3
    assert metrics["planning_MAE_sec"] == 0.433333
    assert metrics["runtime_MAE_sec"] == 0.466667
    assert metrics["semantic_runtime_MAE_sec"] == 0.9
    assert metrics["severely_misaligned_count"] == 1
    assert metrics["early_count"] == 0
    assert metrics["late_count"] == 2


def test_same_sentence_multi_element_and_stagger_are_not_duplicates(tmp_path):
    events = [
        _bound("a1", "e1", 9.0, 10.0, 1.0),
        _bound("a2", "e2", 9.3, 10.0, 1.0),
        _bound("a3", "e3", 9.6, 10.0, 1.0),
    ]
    _write_fixture(tmp_path, events)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    metrics = result["metrics"]
    assert metrics["duplicate_planned_event_count"] == 0
    assert metrics["duplicate_trace_event_count"] == 0
    assert metrics["planning_MAE_sec"] == 0.3
    assert metrics["semantic_runtime_MAE_sec"] == 0.3
    assert metrics["minor_misalignment_count"] == 1


def test_event_join_keeps_same_event_id_separate_across_slides(tmp_path):
    (tmp_path / "storyboard_timed.json").write_text(
        json.dumps(
            {
                "segments": [
                    {"id": "s1", "elements": [{"id": "e1"}], "timeline": [_bound("event", "e1", 1.0, 2.0, 1.0)]},
                    {"id": "s2", "elements": [{"id": "e1"}], "timeline": [_bound("event", "e1", 3.0, 4.0, 1.0)]},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "animation_trace.json").write_text(
        json.dumps(
            {
                "events": [
                    {"event_id": "event", "slide": "s1", "target": "e1", "target_resolved": True, "status": "executed", "actual": {"start_ms": 1000}},
                    {"event_id": "event", "slide": "s2", "target": "e1", "target_resolved": True, "status": "executed", "actual": {"start_ms": 3000}},
                ]
            }
        ),
        encoding="utf-8",
    )
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    assert result["metrics"]["semantic_evaluable_count"] == 2
    assert result["metrics"]["duplicate_planned_event_count"] == 0
    assert result["metrics"]["duplicate_trace_event_count"] == 0


def test_different_leads_change_desired_time_without_matching(tmp_path):
    events = [
        _bound("a1", "e1", 9.0, 10.0, 1.0),
        {**_bound("a2", "e2", 8.0, 10.0, 2.0), "lead_sec": 2.0},
    ]
    _write_fixture(tmp_path, events)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    records = result["details"]["events"]
    assert records[0]["desired_trigger_sec"] == 9.0
    assert records[1]["desired_trigger_sec"] == 8.0


def test_fallback_is_reported_but_excluded_from_semantic_mae(tmp_path):
    events = [_bound("a1", "e1", 1.0, 2.0, 1.0), {"event_id": "a2", "target": "e2", "at_sec": 5.0, "fallback_type": "structural_fallback"}]
    _write_fixture(tmp_path, events)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    assert result["metrics"]["semantic_match_count"] == 1
    assert result["metrics"]["fallback_count"] == 1
    assert result["metrics"]["fallback_by_type"] == {"structural_fallback": 1}
    assert result["metrics"]["semantic_evaluable_count"] == 1
    assert result["metrics"]["semantic_runtime_MAE_sec"] == 0.0
    assert result["details"]["events"][1]["status"] == "fallback_only"


def test_missing_binding_is_unavailable_and_does_not_re_match(tmp_path):
    events = [{"event_id": "a1", "target": "e1", "at_sec": 1.0}]
    _write_fixture(tmp_path, events)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    assert result["status"] == "unavailable"
    assert result["details"]["semantic_alignment_status"] == "unavailable"
    assert result["metrics"]["semantic_evaluable_count"] == 0
    assert result["metrics"]["fallback_count"] == 1
    assert any(issue["type"] == "AV_SEMANTIC_BINDING_MISSING" for issue in result["issues"])


def test_sentence_cue_lookup_and_per_event_lead(tmp_path):
    events = [{
        "event_id": "a1",
        "target": "e1",
        "at_sec": 11.4,
        "matched_sentence_id": "s1",
        "lead_sec": 1.0,
        "trigger_source": "sentence_cue",
    }]
    _write_fixture(tmp_path, events, sentence_cues=[{"id": "s1", "start_sec": 12.4}])
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    record = result["details"]["events"][0]
    assert record["sentence_start_source"] == "sentence_cues_sidecar"
    assert record["desired_trigger_sec"] == 11.4
    assert record["narration_offset_sec"] == -1.0


def test_runtime_blocked_and_missing_actual_are_not_evaluable(tmp_path):
    events = [_bound("a1", "e1", 1.0, 2.0, 1.0), _bound("a2", "e2", 3.0, 4.0, 1.0)]
    trace = [
        {"event_id": "a1", "slide": 1, "target": "e1", "target_resolved": False, "status": "target_missing", "error_code": "TARGET_MISSING"}
    ]
    _write_fixture(tmp_path, events, trace)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    metrics = result["metrics"]
    assert metrics["semantic_evaluable_count"] == 0
    assert metrics["semantic_not_evaluable_count"] == 2
    assert metrics["semantic_alignment_blocked_count"] == 2
    assert any(issue["type"] == "AV_SEMANTIC_RUNTIME_BLOCKED" for issue in result["issues"])


def test_duplicate_trace_event_is_reported(tmp_path):
    event = _bound("a1", "e1", 1.0, 2.0, 1.0)
    trace = [
        {"event_id": "a1", "slide": 1, "target": "e1", "target_resolved": True, "status": "executed", "actual": {"start_ms": 1000}},
        {"event_id": "a1", "slide": 1, "target": "e1", "target_resolved": True, "status": "executed", "actual": {"start_ms": 1100}},
    ]
    _write_fixture(tmp_path, [event], trace)
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    assert result["metrics"]["duplicate_trace_event_count"] == 1
    assert result["metrics"]["semantic_not_evaluable_count"] == 1
    assert any(issue["type"] == "AV_SEMANTIC_EVENT_DUPLICATE" for issue in result["issues"])


def test_invalid_target_and_metadata_are_explicit(tmp_path):
    event = _bound("a1", "unknown", 1.0, 2.0, 1.0)
    _write_fixture(tmp_path, [event])
    result = AVSemanticAlignmentAdapter().evaluate_case(_context(tmp_path))
    assert result["metrics"]["semantic_not_evaluable_count"] == 1
    assert any(issue["type"] == "AV_SEMANTIC_METADATA_INVALID" for issue in result["issues"])


def test_runner_exposes_alignment_as_separate_top_level_result(tmp_path):
    event = _bound("a1", "e1", 1.0, 2.0, 1.0)
    _write_fixture(tmp_path, [event])
    adapter = AVSemanticAlignmentAdapter(
        thresholds=AlignmentThresholds(aligned_max_sec=0.25, minor_max_sec=0.75, severe_min_sec=1.5)
    )
    report = run_case(
        _Case(tmp_path),
        run_id="av-runner-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
        evaluators=[evaluate_av_semantic_alignment],
        av_semantic_alignment=adapter,
        repo_root=Path(__file__).resolve().parents[1],
        candidate_commit="commit-test",
    )
    assert report["av_semantic_alignment"]["status"] == "ok"
    assert report["evaluators"]["av_semantic_alignment"]["details"]["provenance"]["candidate_commit"] == "commit-test"
    saved = json.loads((tmp_path / "eval" / "eval_report.json").read_text(encoding="utf-8"))
    assert saved["av_semantic_alignment"]["metrics"]["semantic_evaluable_count"] == 1


def test_runner_accepts_numeric_slide_in_av_issue_contract(tmp_path):
    _write_fixture(tmp_path, [_bound("a1", "unknown", 1.0, 2.0, 1.0)])
    report = run_case(
        _Case(tmp_path),
        run_id="av-runner-invalid-target-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
        evaluators=[evaluate_av_semantic_alignment],
        av_semantic_alignment=AVSemanticAlignmentAdapter(),
        repo_root=Path(__file__).resolve().parents[1],
        candidate_commit="commit-test",
    )
    issues = report["evaluators"]["av_semantic_alignment"]["issues"]
    assert any(issue["type"] == "AV_SEMANTIC_METADATA_INVALID" for issue in issues)
    assert all(issue["slide"] == 1 for issue in issues if issue["slide"] is not None)
