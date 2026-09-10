"""Audit candidate cases before a human-approved frozen transition."""

from __future__ import annotations

import argparse
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
