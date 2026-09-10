"""Prepare reviewable candidate Case directories from the formal-review package."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from .dataset import sha256_file
from .report import write_json
from .schemas import validate_with_contract


def _contracts_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "contracts"


def _asset(role: str, path: Path, root: Path, *, review_status: str | None = None) -> dict:
    value = {
        "role": role,
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "required": True,
    }
    if review_status:
        value["review_status"] = review_status
    return value


def prepare_candidate_case(
    package_root: str | Path,
    output_root: str | Path,
    lesson_id: str,
    *,
    dataset_version: str,
) -> Path:
    package = Path(package_root).resolve()
    output = Path(output_root).resolve()
    source = package / "sources" / "frozen" / lesson_id
    annotation_source = package / "private_annotations" / "B" / lesson_id / "annotation.json"
    if not source.is_dir() or not annotation_source.is_file():
        raise FileNotFoundError(f"package assets are incomplete for {lesson_id}")

    case_root = output / lesson_id
    if case_root.exists():
        raise FileExistsError(f"candidate Case already exists: {case_root}")
    source_output = case_root / "source"
    private_output = case_root / "private"
    shutil.copytree(source, source_output)
    private_output.mkdir(parents=True)
    annotation_path = private_output / "annotation.json"
    shutil.copy2(annotation_source, annotation_path)

    annotation: dict[str, Any] = json.loads(annotation_path.read_text(encoding="utf-8"))
    if annotation.get("lesson_id") != lesson_id:
        raise ValueError(f"annotation lesson_id mismatch for {lesson_id}")
    questions = annotation.get("heldout_questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"annotation has no heldout questions for {lesson_id}")
    heldout_path = private_output / "heldout_questions.json"
    write_json(
        heldout_path,
        {
            "schema_version": "textbookeval-heldout-v0.1",
            "lesson_id": lesson_id,
            "questions": questions,
        },
    )

    source_manifest_path = source_output / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("lesson_id") != lesson_id:
        raise ValueError(f"source manifest lesson_id mismatch for {lesson_id}")
    source_files = [
        _asset("source_json", source_output / "source.json", case_root),
        _asset("source_pdf", source_output / "source.pdf", case_root),
        _asset("source_manifest", source_manifest_path, case_root),
    ]
    for index, image in enumerate(sorted((source_output / "images").glob("*")), start=1):
        if image.is_file():
            source_files.append(_asset(f"source_image_{index:02d}", image, case_root))

    annotation_status = str(annotation.get("annotation_status") or "draft")
    manifest = {
        "schema_version": "textbookeval-case-v0.1",
        "case_id": f"pilot3_{lesson_id}",
        "lesson_id": lesson_id,
        "status": "candidate",
        "dataset_version": dataset_version,
        "source": {"files": source_files},
        "annotation": _asset(
            "annotation", annotation_path, case_root, review_status=annotation_status
        ),
        "heldout_questions": _asset(
            "heldout_questions", heldout_path, case_root, review_status=annotation_status
        ),
        "expected": {
            "title": source_manifest.get("title"),
            "source_type": source_manifest.get("source_type"),
            "source_locator": source_manifest.get("source_locator"),
            "paragraph_count": source_manifest.get("paragraph_count"),
            "image_count": source_manifest.get("image_count"),
            "heldout_question_count": len(questions),
        },
        "systems": {},
        "baseline_artifacts": {},
        "metadata": {
            "selected_for_pilot3": True,
            "prepared_at": date.today().isoformat(),
            "source_review_status": source_manifest.get("review_status"),
            "annotation_status": annotation_status,
            "freeze_blocked": (
                source_manifest.get("review_status") != "frozen"
                or annotation_status != "frozen"
            ),
        },
    }
    validate_with_contract(
        manifest, "case_manifest.schema.json", contracts_dir=_contracts_dir()
    )
    return write_json(case_root / "case_manifest.json", manifest)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare candidate TextbookEval Case directories")
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--lesson", action="append", required=True)
    parser.add_argument(
        "--dataset-version",
        default=f"textbookeval-v1-pilot3-candidate-{date.today().strftime('%Y%m%d')}",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    for lesson_id in args.lesson:
        path = prepare_candidate_case(
            args.package_root,
            args.output_root,
            lesson_id,
            dataset_version=args.dataset_version,
        )
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
