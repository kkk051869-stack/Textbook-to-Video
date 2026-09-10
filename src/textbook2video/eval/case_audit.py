"""Audit candidate cases before a human-approved frozen transition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .dataset import CaseManifest, discover_case_manifests, load_case, sha256_file
from .report import write_json

REQUIRED_SOURCE_ROLES = {"source_json", "source_pdf", "source_manifest"}
REQUIRED_BASELINE_ROLES = {
    "storyboard",
    "timed_storyboard",
    "html",
    "layout_report",
    "run_config",
}


def _check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    message: str,
    path: str | None = None,
) -> None:
    value: dict[str, Any] = {"name": name, "passed": passed, "message": message}
    if path is not None:
        value["path"] = path
    checks.append(value)


def _asset_path(case: CaseManifest, role: str) -> Path | None:
    return next((case.resolve_asset(asset) for asset in case.assets() if asset.role == role), None)


def _ids(items: Any, key: str = "id") -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item.get(key)) for item in items if isinstance(item, dict) and item.get(key)]


def _semantic_checks(case: CaseManifest, checks: list[dict[str, Any]]) -> None:
    paths = {
        role: _asset_path(case, role)
        for role in ("source_json", "source_manifest", "annotation", "heldout_questions")
    }
    if any(path is None or not path.is_file() for path in paths.values()):
        _check(
            checks,
            name="semantic_inputs_available",
            passed=False,
            message="source JSON, annotation, and held-out questions are required",
        )
        return
    try:
        source = json.loads(paths["source_json"].read_text(encoding="utf-8"))
        source_manifest = json.loads(paths["source_manifest"].read_text(encoding="utf-8"))
        annotation = json.loads(paths["annotation"].read_text(encoding="utf-8"))
        question_pack = json.loads(paths["heldout_questions"].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        _check(
            checks,
            name="semantic_json_parse",
            passed=False,
            message=f"semantic input JSON cannot be parsed: {exc}",
        )
        return

    _check(
        checks,
        name="source_document_review_status",
        passed=source_manifest.get("review_status") == "frozen",
        message=(
            f"source manifest review status is {source_manifest.get('review_status')!r}; "
            "expected 'frozen'"
        ),
    )
    _check(
        checks,
        name="annotation_document_status",
        passed=annotation.get("annotation_status") == "frozen",
        message=(
            f"annotation document status is {annotation.get('annotation_status')!r}; "
            "expected 'frozen'"
        ),
    )

    paragraph_ids = _ids(source.get("paragraphs"))
    image_ids = _ids(source.get("images"))
    image_files = {
        str(item.get("filename"))
        for item in source.get("images", [])
        if isinstance(item, dict) and item.get("filename")
    }
    concepts = annotation.get("core_concepts", [])
    concept_ids = _ids(concepts)
    questions = question_pack.get("questions", [])
    question_ids = _ids(questions)
    required_images = annotation.get("required_images", [])

    identifier_groups = {
        "paragraph": paragraph_ids,
        "source_image": image_ids,
        "concept": concept_ids,
        "question": question_ids,
    }
    for group, values in identifier_groups.items():
        unique = len(values) == len(set(values)) and (bool(values) or group == "source_image")
        _check(
            checks,
            name=f"unique_{group}_ids",
            passed=unique,
            message=(
                f"{len(values)} unique {group} IDs"
                if unique
                else f"{group} IDs are empty or duplicated"
            ),
        )

    evidence_refs = []
    for item in [*concepts, *questions]:
        if isinstance(item, dict):
            evidence_refs.extend(str(value) for value in item.get("evidence_paragraphs", []))
    missing_paragraphs = sorted(set(evidence_refs) - set(paragraph_ids))
    _check(
        checks,
        name="evidence_paragraph_references",
        passed=not missing_paragraphs,
        message=(
            "all evidence paragraph references resolve"
            if not missing_paragraphs
            else f"unknown paragraph IDs: {', '.join(missing_paragraphs)}"
        ),
    )

    target_refs = {
        str(target)
        for item in questions
        if isinstance(item, dict)
        for target in item.get("targets", [])
    }
    missing_targets = sorted(target_refs - set(concept_ids))
    _check(
        checks,
        name="question_target_references",
        passed=not missing_targets,
        message=(
            "all question targets resolve"
            if not missing_targets
            else f"unknown concept IDs: {', '.join(missing_targets)}"
        ),
    )

    required_files = {
        str(item.get("filename"))
        for item in required_images
        if isinstance(item, dict) and item.get("filename")
    }
    missing_images = sorted(required_files - image_files)
    _check(
        checks,
        name="required_image_references",
        passed=not missing_images,
        message=(
            "all required image filenames resolve"
            if not missing_images
            else f"unknown image filenames: {', '.join(missing_images)}"
        ),
    )

    annotation_questions = annotation.get("heldout_questions", [])
    split_matches = annotation_questions == questions
    _check(
        checks,
        name="heldout_split_matches_annotation",
        passed=split_matches,
        message=(
            "held-out question split exactly matches annotation"
            if split_matches
            else "held-out question split differs from annotation"
        ),
    )


def audit_case(case: CaseManifest, artifacts_root: str | Path) -> dict[str, Any]:
    artifacts = Path(artifacts_root).resolve()
    checks: list[dict[str, Any]] = []
    roles = {asset.role for asset in case.assets()}
    missing_source = sorted(REQUIRED_SOURCE_ROLES - roles)
    _check(
        checks,
        name="required_source_roles",
        passed=not missing_source,
        message=(
            "all required source roles are present"
            if not missing_source
            else f"missing source roles: {', '.join(missing_source)}"
        ),
    )

    for asset in case.assets():
        path = case.resolve_asset(asset)
        exists = path.is_file()
        digest_ok = exists and sha256_file(path) == asset.sha256
        _check(
            checks,
            name=f"source_asset:{asset.role}",
            passed=digest_ok,
            message=("file and SHA-256 match" if digest_ok else "file missing or SHA-256 mismatch"),
            path=str(path),
        )

    _semantic_checks(case, checks)

    source_review_status = case.raw.get("metadata", {}).get("source_review_status")
    _check(
        checks,
        name="source_review_status",
        passed=source_review_status == "frozen",
        message=f"source review status is {source_review_status!r}; expected 'frozen'",
    )
    annotation_status = case.raw.get("annotation", {}).get("review_status")
    question_status = case.raw.get("heldout_questions", {}).get("review_status")
    _check(
        checks,
        name="annotation_review_status",
        passed=annotation_status == "frozen",
        message=f"annotation review status is {annotation_status!r}; expected 'frozen'",
    )
    _check(
        checks,
        name="heldout_questions_review_status",
        passed=question_status == "frozen",
        message=f"held-out review status is {question_status!r}; expected 'frozen'",
    )

    declared = case.raw.get("baseline_artifacts", {})
    missing_baseline = sorted(REQUIRED_BASELINE_ROLES - set(declared))
    _check(
        checks,
        name="required_baseline_roles",
        passed=not missing_baseline,
        message=(
            "all required baseline roles are declared"
            if not missing_baseline
            else f"missing baseline roles: {', '.join(missing_baseline)}"
        ),
    )
    for role, value in sorted(declared.items()):
        if not isinstance(value, dict):
            _check(
                checks,
                name=f"baseline_artifact:{role}",
                passed=False,
                message="artifact must declare path and SHA-256",
            )
            continue
        relative = value.get("path")
        expected = str(value.get("sha256", "")).lower()
        path = (artifacts / relative).resolve() if isinstance(relative, str) else artifacts
        contained = path == artifacts or artifacts in path.parents
        passed = (
            contained and path.is_file() and len(expected) == 64 and sha256_file(path) == expected
        )
        _check(
            checks,
            name=f"baseline_artifact:{role}",
            passed=passed,
            message=(
                "file and SHA-256 match" if passed else "file missing, unsafe, or SHA-256 mismatch"
            ),
            path=str(path),
        )

    systems = case.raw.get("systems", {})
    baseline = systems.get("baseline") if isinstance(systems, dict) else None
    system_ready = isinstance(baseline, dict) and bool(baseline.get("system_id"))
    _check(
        checks,
        name="baseline_system_config",
        passed=system_ready,
        message="baseline system_id is declared"
        if system_ready
        else "baseline system_id is missing",
    )
    blockers = [check for check in checks if not check["passed"]]
    return {
        "schema_version": "textbookeval-freeze-audit-v0.1",
        "case_id": case.case_id,
        "lesson_id": case.lesson_id,
        "current_status": case.status,
        "ready_to_freeze": not blockers,
        "checks": checks,
        "blockers": blockers,
    }


def audit_dataset(
    dataset_dir: str | Path, artifacts_root: str | Path, output: str | Path
) -> dict[str, Any]:
    artifacts = Path(artifacts_root).resolve()
    reports = []
    for manifest_path in discover_case_manifests(dataset_dir):
        case = load_case(manifest_path, verify_files=False)
        metadata = case.raw.get("metadata", {})
        subdir = metadata.get("artifacts_subdir") if isinstance(metadata, dict) else None
        case_artifacts = artifacts / str(subdir) if subdir else artifacts / case.lesson_id
        reports.append(audit_case(case, case_artifacts))
    result = {
        "schema_version": "textbookeval-freeze-audit-batch-v0.1",
        "dataset_dir": str(Path(dataset_dir).resolve()),
        "artifacts_root": str(artifacts),
        "case_count": len(reports),
        "ready_count": sum(report["ready_to_freeze"] for report in reports),
        "cases": reports,
    }
    json_path = write_json(output, result)
    markdown_path = json_path.with_suffix(".md")
    markdown_path.write_text(render_audit_markdown(result), encoding="utf-8")
    return result


def render_audit_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# TextbookEval Case Freeze Audit",
        "",
        f"- Dataset: `{result['dataset_dir']}`",
        f"- Cases ready: {result['ready_count']} / {result['case_count']}",
        "- This report is an audit, not a human approval record.",
        "",
    ]
    for case in result["cases"]:
        state = "READY" if case["ready_to_freeze"] else "BLOCKED"
        lines.extend(
            [
                f"## {case['case_id']} — {state}",
                "",
                f"- Lesson: `{case['lesson_id']}`",
                f"- Current status: `{case['current_status']}`",
            ]
        )
        if not case["blockers"]:
            lines.append("- Blockers: none")
        else:
            lines.append("- Blockers:")
            for blocker in case["blockers"]:
                suffix = f" — `{blocker['path']}`" if blocker.get("path") else ""
                lines.append(f"  - `{blocker['name']}`: {blocker['message']}{suffix}")
        lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit TextbookEval cases for freeze readiness")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit_dataset(args.dataset, args.artifacts, args.out)
    return 0 if result["ready_count"] == result["case_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
