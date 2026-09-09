"""Adapter for timed storyboard, HTML, and optional audio integrity checks."""

from __future__ import annotations

from textbook2video.pipeline.artifact_integrity import verify_render_bundle

from ..runner import EvalContext
from .common import evidence_for, unavailable


def evaluate_artifact_integrity(context: EvalContext) -> dict:
    name = "artifact_integrity"
    storyboard = context.artifact("timed_storyboard") or context.artifact("storyboard")
    html = context.artifact("html")
    if storyboard is None or not storyboard.is_file() or html is None or not html.is_file():
        return unavailable(
            context,
            name,
            "baseline_artifacts requires timed_storyboard/storyboard and html",
        )
    audio_dir = context.artifact("audio_dir")
    report = verify_render_bundle(
        storyboard,
        html,
        audio_dir=audio_dir if audio_dir and audio_dir.is_dir() else None,
    )
    storyboard_evidence = f"{context.case.case_id}-timed-storyboard"
    html_evidence = f"{context.case.case_id}-html"
    return {
        "status": "ok",
        "passed": True,
        "metrics": {
            "slide_count": report["slide_count"],
            "total_duration_sec": report["total_duration_sec"],
        },
        "details": report,
        "issues": [],
        "evidence_ids": [storyboard_evidence, html_evidence],
        "_evidence": [
            evidence_for(storyboard, evidence_id=storyboard_evidence, kind="timed_storyboard"),
            evidence_for(html, evidence_id=html_evidence, kind="rendered_html"),
        ],
    }


evaluate_artifact_integrity.evaluator_name = "artifact_integrity"
