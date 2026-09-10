import hashlib
import json
from pathlib import Path

from textbook2video.eval.dataset import load_case
from textbook2video.eval.runner import run_case, run_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]


def _case(tmp_path):
    source_assets = []
    for role, name in (
        ("source_json", "source.json"),
        ("source_pdf", "source.pdf"),
        ("source_manifest", "manifest.json"),
    ):
        source = tmp_path / name
        source.write_bytes(b"source")
        source_assets.append(
            {"role": role, "path": name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        )
    private_assets = {}
    for key, name in (("annotation", "annotation.json"), ("heldout_questions", "quiz.json")):
        source = tmp_path / name
        source.write_text("{}", encoding="utf-8")
        private_assets[key] = {
            "role": key,
            "path": name,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "review_status": "frozen",
        }
    manifest = tmp_path / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case_demo",
                "lesson_id": "lesson_demo",
                "status": "frozen",
                "dataset_version": "pilot3-test",
                "source": {"files": source_assets},
                **private_assets,
                "review": {
                    "annotation_status": "frozen",
                    "reviewer": "test-reviewer",
                    "reviewed_at": "2026-09-09T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    return load_case(manifest, require_frozen=True)


def test_runner_keeps_success_when_another_evaluator_fails(tmp_path):
    def passing(_context):
        return {"status": "ok", "passed": True, "metrics": {"count": 1}}

    def broken(_context):
        raise RuntimeError("deliberate evaluator failure")

    report = run_case(
        _case(tmp_path),
        run_id="run-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
        evaluators=[passing, broken],
        repo_root=REPO_ROOT,
    )

    assert report["status"] == "partial"
    assert report["evaluators"]["passing"]["status"] == "ok"
    assert report["evaluators"]["broken"]["status"] == "error"
    assert report["issues"][0]["type"] == "EVALUATOR_ERROR"
    assert (tmp_path / "eval" / "eval_report.json").exists()
    assert (tmp_path / "eval" / "eval_report.md").exists()
    assert (tmp_path / "eval" / "run_manifest.json").exists()
    assert (tmp_path / "eval" / "summary.csv").exists()
    assert (tmp_path / "eval" / "issues.csv").exists()
    assert (tmp_path / "eval" / "review_index.json").exists()
    assert (tmp_path / "eval" / "review_index.md").exists()


def test_default_runner_reuses_deterministic_pipeline_checks(tmp_path):
    storyboard = tmp_path / "storyboard.json"
    storyboard.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": 1,
                        "narration": "Demo narration.",
                        "visual_type": "definition",
                        "audio_duration_sec": 2.0,
                        "elements": [
                            {"id": "title", "type": "heading", "text": "Demo"},
                            {"id": "body", "type": "text", "text": "Explanation"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    html = tmp_path / "lesson.html"
    html.write_text("<html><script>var slideDurations = [2000];</script></html>", encoding="utf-8")
    case = _case(tmp_path)
    case.raw["baseline_artifacts"] = {
        "storyboard": "storyboard.json",
        "timed_storyboard": "storyboard.json",
        "html": "lesson.html",
    }

    report = run_case(
        case,
        run_id="run-deterministic",
        artifacts_root=tmp_path,
        output_root=tmp_path / "deterministic-eval",
        repo_root=REPO_ROOT,
    )

    assert report["evaluators"]["structure"]["status"] == "ok"
    assert report["evaluators"]["artifact_integrity"]["passed"] is True
    assert report["evaluators"]["quality"]["status"] in {"ok", "failed"}


def test_dataset_runner_continues_after_case_load_failure(tmp_path):
    dataset = tmp_path / "dataset"
    valid = dataset / "valid"
    valid.mkdir(parents=True)
    _case(valid)
    invalid = dataset / "invalid"
    invalid.mkdir()
    (invalid / "case_manifest.json").write_text("{}", encoding="utf-8")

    reports, errors = run_dataset(
        dataset,
        run_id="run-batch",
        artifacts_root=tmp_path / "artifacts",
        output_root=tmp_path / "batch-eval",
        repo_root=REPO_ROOT,
    )

    assert [report["case_id"] for report in reports] == ["case_demo"]
    assert len(errors) == 1
    assert errors[0]["exception_type"] == "SchemaValidationError"
    assert (tmp_path / "batch-eval" / "batch_summary.json").exists()
    assert (tmp_path / "batch-eval" / "summary.csv").exists()
    assert (tmp_path / "batch-eval" / "issues.csv").exists()
    assert (tmp_path / "batch-eval" / "review_index.json").exists()
    assert (tmp_path / "batch-eval" / "review_index.md").exists()
