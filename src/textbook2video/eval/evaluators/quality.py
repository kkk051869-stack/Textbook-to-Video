"""Adapter for the existing deterministic quality report."""

from __future__ import annotations

from textbook2video.pipeline.quality import build_quality_report

from ..runner import EvalContext
from .common import evidence_for, unavailable


def evaluate_quality(context: EvalContext) -> dict:
    name = "quality"
    storyboard = context.artifact("storyboard")
    if storyboard is None or not storyboard.is_file():
        return unavailable(context, name, "baseline_artifacts.storyboard is missing")

    def existing(role: str):
        path = context.artifact(role)
        return path if path and path.exists() else None

    report = build_quality_report(
        storyboard,
        audio_dir=existing("audio_dir"),
        subtitle_path=existing("subtitle"),
        final_video=existing("final_video"),
        output_dir=context.artifacts_root,
        lesson_plan_path=existing("lesson_plan"),
    )
    evidence_id = f"{context.case.case_id}-quality-storyboard"
    issues = [
        {
            "case_id": context.case.case_id,
            "stage": "eval",
            "evaluator": name,
            "type": "QUALITY_WARNING",
            "severity": "minor",
            "message": warning,
            "evidence_ids": [evidence_id],
            "review_status": "unreviewed",
        }
        for warning in report["warnings"]
    ]
    return {
        "status": "ok" if report["ok"] else "failed",
        "passed": report["ok"],
        "metrics": report["scores"],
        "details": report,
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(storyboard, evidence_id=evidence_id, kind="storyboard")],
    }


evaluate_quality.evaluator_name = "quality"
