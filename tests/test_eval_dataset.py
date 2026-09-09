import hashlib
import json

import pytest

from textbook2video.eval.dataset import load_case
from textbook2video.eval.schemas import SchemaValidationError


def _manifest(tmp_path, *, status="candidate", asset_path="source.json", digest=None):
    source = tmp_path / "source.json"
    source.write_text('{"title":"demo"}', encoding="utf-8")
    digest = digest or hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case_demo",
                "lesson_id": "lesson_demo",
                "status": status,
                "dataset_version": "pilot3-test",
                "source": {
                    "files": [
                        {
                            "role": "source_json",
                            "path": asset_path,
                            "sha256": digest,
                            "required": True,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _frozen_manifest(tmp_path):
    assets = []
    for role, name in (
        ("source_json", "source.json"),
        ("source_pdf", "source.pdf"),
        ("source_manifest", "manifest.json"),
    ):
        path = tmp_path / name
        path.write_bytes(b"source")
        assets.append(
            {"role": role, "path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    for role, name in (("annotation", "annotation.json"), ("heldout_questions", "quiz.json")):
        path = tmp_path / name
        path.write_text("{}", encoding="utf-8")
        value = {
            "role": role,
            "path": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "review_status": "frozen",
        }
        if role == "annotation":
            annotation = value
        else:
            questions = value
    manifest = tmp_path / "frozen_case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case_frozen",
                "lesson_id": "lesson_frozen",
                "status": "frozen",
                "dataset_version": "pilot3-test",
                "source": {"files": assets},
                "annotation": annotation,
                "heldout_questions": questions,
                "review": {
                    "annotation_status": "frozen",
                    "reviewer": "test-reviewer",
                    "reviewed_at": "2026-09-09T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_load_case_verifies_relative_asset_and_sha256(tmp_path):
    case = load_case(_manifest(tmp_path))
    assert case.case_id == "case_demo"
    assert case.lesson_id == "lesson_demo"


def test_load_case_rejects_hash_mismatch(tmp_path):
    manifest = _manifest(tmp_path, digest="0" * 64)
    with pytest.raises(SchemaValidationError, match="hash mismatch"):
        load_case(manifest)


def test_formal_run_requires_frozen_status(tmp_path):
    with pytest.raises(SchemaValidationError, match="requires status='frozen'"):
        load_case(_manifest(tmp_path), require_frozen=True)


def test_frozen_case_requires_complete_reviewed_assets(tmp_path):
    case = load_case(_frozen_manifest(tmp_path), require_frozen=True)
    assert case.status == "frozen"


def test_asset_may_not_escape_case_directory(tmp_path):
    manifest = _manifest(tmp_path, asset_path="../source.json")
    with pytest.raises(SchemaValidationError, match="escapes the case directory"):
        load_case(manifest)
