import hashlib
import json

from textbook2video.eval.case_audit import audit_case, render_audit_markdown
from textbook2video.eval.dataset import load_case


def _hashed(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freeze_audit_distinguishes_valid_files_from_human_review(tmp_path):
    case_dir = tmp_path / "case"
    artifacts = tmp_path / "artifacts"
    case_dir.mkdir()
    artifacts.mkdir()
    source_files = []
    for role, name in (
        ("source_json", "source.json"),
        ("source_pdf", "source.pdf"),
        ("source_manifest", "source_manifest.json"),
    ):
        path = case_dir / name
        if role == "source_json":
            path.write_text(
                json.dumps(
                    {
                        "paragraphs": [{"id": "p001", "text": "source"}],
                        "images": [],
                    }
                ),
                encoding="utf-8",
            )
        elif role == "source_manifest":
            path.write_text(json.dumps({"review_status": "draft"}), encoding="utf-8")
        else:
            path.write_bytes(b"source")
        source_files.append({"role": role, "path": name, "sha256": _hashed(path)})
    questions = [
        {
            "id": "q001",
            "question": "What?",
            "answer": "source",
            "targets": ["c001"],
            "evidence_paragraphs": ["p001"],
        }
    ]
    (case_dir / "annotation.json").write_text(
        json.dumps(
            {
                "annotation_status": "draft",
                "core_concepts": [
                    {"id": "c001", "statement": "source", "evidence_paragraphs": ["p001"]}
                ],
                "required_images": [],
                "heldout_questions": questions,
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "questions.json").write_text(json.dumps({"questions": questions}), encoding="utf-8")
    baseline = {}
    for role in ("storyboard", "timed_storyboard", "html", "layout_report", "run_config"):
        path = artifacts / f"{role}.json"
        path.write_text("{}", encoding="utf-8")
        baseline[role] = {"path": path.name, "sha256": _hashed(path)}
    manifest = case_dir / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case-demo",
                "lesson_id": "lesson-demo",
                "status": "candidate",
                "dataset_version": "pilot-test",
                "source": {"files": source_files},
                "annotation": {
                    "role": "annotation",
                    "path": "annotation.json",
                    "sha256": _hashed(case_dir / "annotation.json"),
                    "review_status": "draft",
                },
                "heldout_questions": {
                    "role": "heldout_questions",
                    "path": "questions.json",
                    "sha256": _hashed(case_dir / "questions.json"),
                    "review_status": "draft",
                },
                "systems": {"baseline": {"system_id": "internal_C01"}},
                "baseline_artifacts": baseline,
                "metadata": {"source_review_status": "draft"},
            }
        ),
        encoding="utf-8",
    )

    report = audit_case(load_case(manifest), artifacts)

    assert report["ready_to_freeze"] is False
    assert {item["name"] for item in report["blockers"]} == {
        "source_review_status",
        "source_document_review_status",
        "annotation_review_status",
        "annotation_document_status",
        "heldout_questions_review_status",
    }
    assert all(
        item["passed"]
        for item in report["checks"]
        if item["name"].startswith("source_asset:") or item["name"].startswith("baseline_artifact:")
    )
    markdown = render_audit_markdown(
        {
            "dataset_dir": str(tmp_path),
            "case_count": 1,
            "ready_count": 0,
            "cases": [report],
        }
    )
    assert "case-demo" in markdown
    assert "annotation_review_status" in markdown
