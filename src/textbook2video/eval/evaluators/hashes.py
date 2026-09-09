"""SHA-256 Gate for frozen inputs and declared baseline artifacts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..dataset import sha256_file
from ..runner import EvalContext
from .common import evidence_for

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    if path.is_dir():
        return _sha256_tree(path)
    raise FileNotFoundError(path)


def evaluate_hashes(context: EvalContext) -> dict:
    name = "hashes"
    issues = []
    evidence = []
    checked = 0
    manifest_evidence_id = f"{context.case.case_id}-case-manifest"
    evidence.append(
        evidence_for(
            context.case.manifest_path,
            evidence_id=manifest_evidence_id,
            kind="case_manifest",
        )
    )

    for asset in context.case.assets():
        path = context.case.resolve_asset(asset)
        if not path.is_file():
            if asset.required:
                issues.append(
                    {
                        "case_id": context.case.case_id,
                        "stage": "input",
                        "evaluator": name,
                        "type": "INPUT_MISSING",
                        "severity": "critical",
                        "message": f"required input {asset.role} is missing: {path}",
                        "evidence_ids": [manifest_evidence_id],
                        "review_status": "unreviewed",
                    }
                )
            continue
        checked += 1
        actual = sha256_file(path)
        evidence_id = f"{context.case.case_id}-input-{asset.role}"
        evidence.append(evidence_for(path, evidence_id=evidence_id, kind=asset.role))
        evidence[-1]["sha256"] = actual
        if actual != asset.sha256:
            issues.append(
                {
                    "case_id": context.case.case_id,
                    "stage": "input",
                    "evaluator": name,
                    "type": "INPUT_HASH_MISMATCH",
                    "severity": "critical",
                    "message": (
                        f"{asset.role} SHA-256 mismatch: expected {asset.sha256}, got {actual}"
                    ),
                    "evidence_ids": [evidence_id],
                    "review_status": "unreviewed",
                }
            )

    baseline = context.case.raw.get("baseline_artifacts", {})
    baseline_checked = 0
    for role, declaration in baseline.items():
        if not isinstance(declaration, dict):
            if context.case.status == "frozen":
                issues.append(
                    {
                        "case_id": context.case.case_id,
                        "stage": "input",
                        "evaluator": name,
                        "type": "BASELINE_HASH_MISSING",
                        "severity": "critical",
                        "message": f"frozen baseline artifact {role} has no SHA-256 declaration",
                        "evidence_ids": [manifest_evidence_id],
                        "review_status": "unreviewed",
                    }
                )
            continue
        expected = declaration.get("sha256")
        if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
            if context.case.status == "frozen":
                issues.append(
                    {
                        "case_id": context.case.case_id,
                        "stage": "input",
                        "evaluator": name,
                        "type": "BASELINE_HASH_MISSING",
                        "severity": "critical",
                        "message": f"frozen baseline artifact {role} has no valid SHA-256",
                        "evidence_ids": [manifest_evidence_id],
                        "review_status": "unreviewed",
                    }
                )
            continue
        path = context.artifact(role)
        if path is None or not path.exists():
            issues.append(
                {
                    "case_id": context.case.case_id,
                    "stage": "input",
                    "evaluator": name,
                    "type": "BASELINE_ARTIFACT_MISSING",
                    "severity": "critical",
                    "message": f"declared baseline artifact {role} is missing: {path}",
                    "evidence_ids": [manifest_evidence_id],
                    "review_status": "unreviewed",
                }
            )
            continue
        baseline_checked += 1
        actual = _sha256_path(path)
        evidence_id = f"{context.case.case_id}-baseline-{role}"
        evidence.append(evidence_for(path, evidence_id=evidence_id, kind=role))
        evidence[-1]["sha256"] = actual
        if actual.lower() != expected.lower():
            issues.append(
                {
                    "case_id": context.case.case_id,
                    "stage": "input",
                    "evaluator": name,
                    "type": "BASELINE_HASH_MISMATCH",
                    "severity": "critical",
                    "message": f"{role} SHA-256 mismatch: expected {expected}, got {actual}",
                    "evidence_ids": [evidence_id],
                    "review_status": "unreviewed",
                }
            )

    passed = not issues
    return {
        "status": "ok" if passed else "failed",
        "passed": passed,
        "metrics": {"input_files_checked": checked, "baseline_artifacts_checked": baseline_checked},
        "details": {},
        "issues": issues,
        "evidence_ids": [item["evidence_id"] for item in evidence],
        "_evidence": evidence,
    }


evaluate_hashes.evaluator_name = "hashes"
