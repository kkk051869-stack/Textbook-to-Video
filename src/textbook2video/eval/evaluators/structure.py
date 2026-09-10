"""Adapter for the existing storyboard validator."""

from __future__ import annotations

import json

from textbook2video.pipeline.checks import validate_storyboard

from ..runner import EvalContext
from .common import evidence_for, unavailable


def evaluate_structure(context: EvalContext) -> dict:
    name = "structure"
    storyboard = context.artifact("storyboard")
    if storyboard is None or not storyboard.is_file():
        return unavailable(context, name, "baseline_artifacts.storyboard is missing")
    script = context.artifact("script")
    data = json.loads(storyboard.read_text(encoding="utf-8"))
    report = validate_storyboard(
        data,
        base_dir=storyboard.parent,
        script_path=script if script and script.is_file() else None,
    )
    evidence_id = f"{context.case.case_id}-storyboard"
    issues = []
    for message in report.errors:
        issues.append(
            {
                "case_id": context.case.case_id,
                "stage": "storyboard",
                "evaluator": name,
                "type": "STORYBOARD_INVALID",
                "severity": "critical",
                "message": message,
                "evidence_ids": [evidence_id],
                "review_status": "unreviewed",
            }
        )
    for message in report.warnings:
        issues.append(
            {
                "case_id": context.case.case_id,
                "stage": "storyboard",
                "evaluator": name,
                "type": "STORYBOARD_WARNING",
                "severity": "minor",
                "message": message,
                "evidence_ids": [evidence_id],
                "review_status": "unreviewed",
            }
        )
    return {
        "status": "ok" if report.ok else "failed",
        "passed": report.ok,
        "metrics": {
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "segment_count": len(data.get("segments", [])),
        },
        "details": {"errors": report.errors, "warnings": report.warnings},
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(storyboard, evidence_id=evidence_id, kind="storyboard")],
    }


evaluate_structure.evaluator_name = "structure"
