import hashlib
import json

from textbook2video.eval.dataset import load_case
from textbook2video.eval.freeze_cases import freeze_case


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freeze_case_updates_documents_hashes_and_review_record(tmp_path):
    case_dir = tmp_path / "case"
    artifacts = tmp_path / "artifacts"
    case_dir.mkdir()
    artifacts.mkdir()

    source_json = case_dir / "source.json"
    source_json.write_text(
        json.dumps(
            {
                "paragraphs": [{"id": "p1", "text": "source"}],
                "images": [],
            }
        ),
        encoding="utf-8",
    )
    source_manifest = case_dir / "source_manifest.json"
    source_manifest.write_text(json.dumps({"review_status": "draft"}), encoding="utf-8")
    questions = [
        {
            "id": "q1",
            "question": "What?",
            "answer": "answer",
            "evidence_paragraphs": ["p1"],
            "targets": ["c1"],
        }
    ]
    annotation = case_dir / "annotation.json"
    annotation.write_text(
        json.dumps(
            {
                "annotation_status": "draft",
                "core_concepts": [
                    {
                        "id": "c1",
                        "statement": "concept",
                        "evidence_paragraphs": ["p1"],
                    }
                ],
                "required_images": [],
                "heldout_questions": questions,
                "review_notes": [],
            }
        ),
        encoding="utf-8",
    )
    heldout = case_dir / "questions.json"
    heldout.write_text(json.dumps({"questions": questions}), encoding="utf-8")

    baseline = {}
    for role in ("storyboard", "timed_storyboard", "html", "layout_report", "run_config"):
        path = artifacts / f"{role}.json"
        path.write_text("{}", encoding="utf-8")
        baseline[role] = {"path": path.name, "sha256": _hash(path)}

    assets = [
        {"role": "source_json", "path": source_json.name, "sha256": _hash(source_json)},
        {
            "role": "source_manifest",
            "path": source_manifest.name,
            "sha256": _hash(source_manifest),
        },
        {"role": "source_pdf", "path": "source.pdf", "sha256": ""},
    ]
    source_pdf = case_dir / "source.pdf"
    source_pdf.write_bytes(b"pdf")
    assets[-1]["sha256"] = _hash(source_pdf)
    manifest = case_dir / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case-demo",
                "lesson_id": "lesson-demo",
                "status": "candidate",
                "dataset_version": "pilot-test",
                "source": {"files": assets},
                "annotation": {
                    "role": "annotation",
                    "path": annotation.name,
                    "sha256": _hash(annotation),
                    "review_status": "draft",
                },
                "heldout_questions": {
                    "role": "heldout_questions",
                    "path": heldout.name,
                    "sha256": _hash(heldout),
                    "review_status": "draft",
                },
                "systems": {"baseline": {"system_id": "internal_C01"}},
                "baseline_artifacts": baseline,
                "metadata": {"source_review_status": "draft", "freeze_blocked": True},
            }
        ),
        encoding="utf-8",
    )

    audit = freeze_case(
        manifest,
        artifacts,
        reviewer="A-eval-owner",
        approval_note="Explicit project-owner approval.",
        reviewed_at="2026-09-10T00:00:00+00:00",
    )

    frozen = load_case(manifest, require_frozen=True)
    assert audit["ready_to_freeze"] is True
    assert frozen.status == "frozen"
    assert frozen.raw["review"]["reviewer"] == "A-eval-owner"
    assert frozen.raw["metadata"]["freeze_blocked"] is False
    assert json.loads(source_manifest.read_text())["review_status"] == "frozen"
    assert json.loads(annotation.read_text())["annotation_status"] == "frozen"
