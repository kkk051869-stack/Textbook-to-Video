import hashlib
import json
from pathlib import Path

from textbook2video.eval.dataset import FileAsset
from textbook2video.eval.evaluators.animation_runtime import evaluate_animation_runtime
from textbook2video.eval.evaluators.hashes import evaluate_hashes
from textbook2video.eval.evaluators.judge_results import evaluate_videoqa_audience
from textbook2video.eval.evaluators.layout import evaluate_layout
from textbook2video.eval.runner import EvalContext


class _Case:
    case_id = "case_demo"
    lesson_id = "lesson_demo"

    def __init__(self, artifacts):
        self.raw = {"baseline_artifacts": artifacts}


def _context(tmp_path: Path, artifacts: dict) -> EvalContext:
    return EvalContext(
        case=_Case(artifacts),
        run_id="run-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
    )


def test_layout_normalizes_failed_page_and_evidence(tmp_path):
    report = tmp_path / "layout.json"
    report.write_text(
        json.dumps(
            {
                "viewport": {"width": 1920, "height": 1080},
                "staticRisks": [],
                "slides": [
                    {"index": 1, "passed": True, "issues": []},
                    {
                        "index": 2,
                        "passed": False,
                        "issues": [
                            {
                                "severity": "fail",
                                "type": "content_out_of_view",
                                "message": "content is clipped",
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_layout(_context(tmp_path, {"layout_report": "layout.json"}))

    assert result["passed"] is False
    assert result["details"]["failed_pages"] == [2]
    assert result["issues"][0]["slide"] == 2
    assert result["evidence_ids"] == ["case_demo-layout-report"]


def test_animation_trace_calculates_runtime_metrics_and_failed_event(tmp_path):
    trace = tmp_path / "animation_trace.json"
    trace.write_text(
        json.dumps(
            {
                "schema_version": "animation-trace-v0.1",
                "events": [
                    {
                        "event_id": "event-1",
                        "slide": 1,
                        "target": "title",
                        "target_resolved": True,
                        "executed": True,
                        "effect_realized": True,
                        "status": "executed",
                        "planned": {"effect": "fade", "start_ms": 100},
                        "actual": {"effect": "fade", "start_ms": 150},
                    },
                    {
                        "event_id": "event-2",
                        "slide": 2,
                        "target": "missing",
                        "target_resolved": False,
                        "executed": False,
                        "effect_realized": False,
                        "status": "error",
                        "planned": {"effect": "grow", "start_ms": 200},
                        "actual": None,
                        "error_code": "TARGET_MISS",
                        "message": "target was not found",
                    },
                ],
                "runtime_errors": [],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_animation_runtime(
        _context(tmp_path, {"animation_trace": "animation_trace.json"})
    )

    assert result["passed"] is False
    assert result["metrics"]["planned_event_count"] == 2
    assert result["metrics"]["target_resolution_rate"] == 0.5
    assert result["metrics"]["timing_mae_ms"] == 50.0
    assert result["issues"][0]["type"] == "TARGET_MISS"
    assert result["issues"][0]["slide"] == 2


def test_normalized_judge_result_keeps_question_and_model_metadata(tmp_path):
    result_path = tmp_path / "audience.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-judge-result-v0.1",
                "result_type": "videoqa_audience",
                "case_id": "case_demo",
                "lesson_id": "lesson_demo",
                "evaluator": "videoqa_audience",
                "status": "ok",
                "passed": None,
                "model": "Qwen2.5-VL-32B-Instruct-AWQ",
                "prompt_version": "videoqa-audience-v1",
                "items": [
                    {
                        "question_id": "q1",
                        "answer_from_video": "demo answer",
                        "evidence_frames": ["frame-001.jpg"],
                    }
                ],
                "metrics": {"answered_count": 1},
                "issues": [],
                "evidence_ids": [],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_videoqa_audience(
        _context(tmp_path, {"videoqa_audience_result": "audience.json"})
    )

    assert result["status"] == "ok"
    assert result["details"]["items"][0]["question_id"] == "q1"
    assert result["details"]["model"] == "Qwen2.5-VL-32B-Instruct-AWQ"
    assert result["evidence_ids"] == ["case_demo-videoqa_audience-result"]


def test_hash_gate_reports_changed_frozen_input(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("original", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    case = _Case({})
    case.status = "frozen"
    case.manifest_path = tmp_path / "case_manifest.json"
    case.manifest_path.write_text("{}", encoding="utf-8")
    case.assets = lambda: [
        FileAsset(role="source_json", path="source.json", sha256=digest)
    ]
    case.resolve_asset = lambda asset: tmp_path / asset.path
    source.write_text("changed", encoding="utf-8")

    result = evaluate_hashes(
        EvalContext(
            case=case,
            run_id="run-test",
            artifacts_root=tmp_path,
            output_root=tmp_path / "eval",
        )
    )

    assert result["passed"] is False
    assert result["issues"][0]["type"] == "INPUT_HASH_MISMATCH"
