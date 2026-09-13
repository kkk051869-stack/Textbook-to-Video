"""Optional baseline/candidate regression adapter.

The normal one-case runner does not invent a baseline.  When a caller places a
precomputed ``regression.json`` or ``baseline_eval_report.json`` beside the
candidate artifacts, this adapter preserves it; otherwise the report clearly
records that Before/After comparison must be run with ``eval-compare``.
"""

from __future__ import annotations

import json

from ..runner import EvalContext
from .common import evidence_for


def evaluate_regression(context: EvalContext) -> dict:
    name = "regression"
    path = context.regression_path or context.artifact("regression") or context.artifact("before_after")
    if path is None or not path.is_file():
        baseline = context.artifact("baseline_eval_report")
        if baseline is None or not baseline.is_file():
            return {
                "status": "skipped",
                "passed": None,
                "metrics": {},
                "details": {
                    "reason": "no baseline/candidate comparison supplied; use t2v eval-compare"
                },
                "issues": [],
                "evidence_ids": [],
            }
        path = baseline
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("regression input must be a JSON object")
    # ``eval-compare`` emits a comparison document rather than the legacy
    # single-result regression.json. Derive a real gate result from its case.
    if value.get("schema_version") == "textbookeval-comparison-v0.1":
        cases = value.get("cases", [])
        selected = next((item for item in cases if item.get("case_id") == context.case.case_id), None)
        if selected is None:
            raise ValueError(f"comparison has no case {context.case.case_id!r}")
        manifest_path = context.artifact("cloud_run_manifest")
        provenance = {
            "case_id": selected.get("case_id"),
            "candidate_run_id": selected.get("candidate_run_id"),
            "baseline_run_id": selected.get("baseline_run_id"),
            "baseline_system_id": context.baseline_system_id,
            "baseline_artifact_source": str(context.baseline_artifacts_root)
            if context.baseline_artifacts_root
            else None,
            "candidate_artifact_source": context.candidate_artifact_source
            or str(context.artifacts_root),
        }
        if manifest_path is not None and manifest_path.is_file():
            cloud_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cloud_manifest.get("case") not in {context.case.case_id, context.case.lesson_id}:
                raise ValueError("cloud run manifest case does not match evaluation case")
            if (
                selected.get("candidate_run_id")
                and cloud_manifest.get("run_id")
                and selected["candidate_run_id"] != cloud_manifest["run_id"]
            ):
                raise ValueError("comparison candidate run does not match cloud run manifest")
            if context.candidate_commit and cloud_manifest.get("commit") != context.candidate_commit:
                raise ValueError("cloud candidate commit does not match requested candidate commit")
            provenance.update({"commit": cloud_manifest.get("commit"), "run_id": cloud_manifest.get("run_id")})
        gate_changes = selected.get("gate_changes", [])
        regressions = [item for item in gate_changes if item.get("regressed") is True]
        issues = selected.get("new_issues", [])
        evidence_id = f"{context.case.case_id}-regression"
        return {
            "status": "ok" if not regressions else "failed",
            "passed": not regressions,
            "metrics": {
                "layout_regression": any(item.get("gate") == "layout" for item in regressions),
                "regressed_gate_count": len(regressions),
                "new_issue_count": len(issues),
                "resolved_issue_count": len(selected.get("resolved_issues", [])),
            },
            "details": {"comparison": selected, "provenance": provenance},
            "issues": issues,
            "evidence_ids": [evidence_id],
            "_evidence": [evidence_for(path, evidence_id=evidence_id, kind="before_after_comparison")],
        }

    issues = value.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("regression input issues must be an array")
    evidence_id = f"{context.case.case_id}-regression"
    return {
        "status": str(value.get("status", "ok")),
        "passed": value.get("passed"),
        "metrics": value.get("metrics", {}),
        "details": value,
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(path, evidence_id=evidence_id, kind="regression")],
    }


evaluate_regression.evaluator_name = "regression"
