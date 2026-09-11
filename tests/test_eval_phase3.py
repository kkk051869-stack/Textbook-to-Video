import json
from pathlib import Path

from textbook2video.eval.dataset import FileAsset, load_case
from textbook2video.eval.evaluators.content import (
    evaluate_knowledge_grounding,
    evaluate_source_fidelity,
)
from textbook2video.eval.evaluators.animation_runtime import evaluate_animation_runtime
from textbook2video.eval.evaluators.regression import evaluate_regression
from textbook2video.eval.runner import EvalContext, run_case


REPO_ROOT = Path(__file__).resolve().parents[1]


class _Case:
    case_id = "case_demo"
    lesson_id = "lesson_demo"
    dataset_version = "dataset-test"

    def __init__(self, root: Path):
        self.root = root
        self.raw = {
            "case_id": self.case_id,
            "lesson_id": self.lesson_id,
            "baseline_artifacts": {"storyboard": "storyboard.json"},
        }

    def assets(self):
        return [
            FileAsset("source_json", "source.json", ""),
            FileAsset("annotation", "annotation.json", ""),
        ]

    def resolve_asset(self, asset):
        return self.root / asset.path


def _content_context(tmp_path: Path) -> EvalContext:
    (tmp_path / "source.json").write_text(
        json.dumps(
            {
                "paragraphs": [
                    {"id": "p1", "text": "数字化转型是一场产业革命。"},
                    {"id": "p2", "text": "数字基础设施需要缩小数字鸿沟。"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "annotation.json").write_text(
        json.dumps(
            {
                "core_concepts": [
                    {
                        "id": "c1",
                        "statement": "数字化转型是产业革命",
                        "evidence_paragraphs": ["p1"],
                        "must_mention_terms": ["产业革命"],
                    },
                    {
                        "id": "c2",
                        "statement": "数字基础设施缩小数字鸿沟",
                        "evidence_paragraphs": ["p2"],
                        "must_mention_terms": ["数字基础设施", "数字鸿沟"],
                    },
                ],
                "required_images": [],
                "misconceptions": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "storyboard.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": 1,
                        "narration": "数字化转型是一场产业革命。数字基础设施需要缩小数字鸿沟。",
                        "elements": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return EvalContext(
        case=_Case(tmp_path),
        run_id="run-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
    )


def test_content_evaluators_keep_traceable_concept_records(tmp_path):
    context = _content_context(tmp_path)
    source = evaluate_source_fidelity(context)
    grounding = evaluate_knowledge_grounding(context)

    assert source["metrics"]["evidence_coverage"]["supported"] == 2
    assert source["details"]["evidence_coverage"][0]["paragraph_id"] == ["p1"]
    assert grounding["metrics"]["covered_count"] == 2
    assert grounding["details"]["concepts"][1]["concept_id"] == "c2"


def test_lesson001_unified_report_contains_phase3_sections(tmp_path):
    manifest = REPO_ROOT / "datasets/pilot3/cases/lesson_001/case_manifest.json"
    artifacts = REPO_ROOT / "datasets/pilot3/artifacts/lesson_001"
    case = load_case(manifest, verify_files=False, require_frozen=True)
    report = run_case(
        case,
        run_id="phase3-lesson001-test",
        artifacts_root=artifacts,
        output_root=tmp_path / "lesson001",
        repo_root=REPO_ROOT,
    )

    assert {
        "metadata",
        "source_fidelity",
        "knowledge_grounding",
        "video_qa",
        "animation",
        "layout",
        "regression",
        "issues",
    }.issubset(report)
    assert report["metadata"]["dataset_version"] == "textbookeval-v1-8case-20260911"
    assert report["video_qa"]["audience"]["metrics"]["question_count"] == 6
    assert report["video_qa"]["reference"]["metrics"]["correct_count"] == 5
    assert report["layout"]["metrics"]["failed_slide_count_1366"] == 0
    assert all(
        field in report["issues"][0]
        for field in ("issue_id", "category", "location", "summary", "expected", "actual", "metadata")
    )


def test_animation_runner_discovers_and_adapts_raw_trace(tmp_path):
    context = _content_context(tmp_path)
    (tmp_path / "animation_trace.json").write_text(
        json.dumps(
            [
                {
                    "event_id": "event-1",
                    "slide_id": "1",
                    "target": "e1",
                    "action": "show",
                    "effect": "fadeIn",
                    "start_ms": 100,
                    "duration_ms": 600,
                    "easing": "ease-out",
                    "actual_ms": 108,
                    "status": "executed",
                    "error": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    result = evaluate_animation_runtime(context)

    assert result["status"] == "ok"
    assert result["metrics"]["planned_event_count"] == 1
    assert result["metrics"]["target_resolution_rate"] == 1.0
    assert (tmp_path / "out" / "animation_trace.json").exists()


def test_candidate_and_baseline_artifacts_are_resolved_separately(tmp_path):
    candidate = tmp_path / "candidate"
    baseline = tmp_path / "baseline"
    candidate.mkdir()
    baseline.mkdir()
    (candidate / "storyboard.json").write_text("candidate", encoding="utf-8")
    (baseline / "storyboard.json").write_text("baseline", encoding="utf-8")
    case = _Case(tmp_path)
    context = EvalContext(
        case=case,
        run_id="run-test",
        artifacts_root=candidate,
        baseline_artifacts_root=baseline,
        output_root=tmp_path / "out",
    )

    assert context.artifact("storyboard").read_text(encoding="utf-8") == "candidate"
    assert context.baseline_artifact("storyboard").read_text(encoding="utf-8") == "baseline"


def test_comparison_json_becomes_a_real_regression_result(tmp_path):
    comparison = tmp_path / "comparison.json"
    comparison.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-comparison-v0.1",
                "cases": [
                    {
                        "case_id": "case_demo",
                        "candidate_run_id": "cloud-run",
                        "baseline_run_id": "baseline-run",
                        "gate_changes": [{"gate": "layout", "regressed": False}],
                        "new_issues": [],
                        "resolved_issues": [{"type": "old"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    case = _Case(tmp_path)
    result = evaluate_regression(
        EvalContext(
            case=case,
            run_id="run-test",
            artifacts_root=tmp_path,
            output_root=tmp_path / "out",
            baseline_system_id="internal_C01",
            regression_path=comparison,
        )
    )

    assert result["status"] == "ok"
    assert result["passed"] is True
    assert result["metrics"]["resolved_issue_count"] == 1
