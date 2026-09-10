"""Normalize the JSON emitted by ``scripts/check_layout.py``."""

from __future__ import annotations

import json

from ..runner import EvalContext
from .common import evidence_for, unavailable


def evaluate_layout(context: EvalContext) -> dict:
    name = "layout"
    path = context.artifact("layout_report")
    if path is None or not path.is_file():
        return unavailable(context, name, "baseline_artifacts.layout_report is missing")

    report = json.loads(path.read_text(encoding="utf-8"))
    slides = report.get("slides")
    if not isinstance(slides, list):
        raise ValueError("layout report must contain a slides array")

    evidence_id = f"{context.case.case_id}-layout-report"
    issues = []
    failed_pages = []
    for slide in slides:
        if not isinstance(slide, dict):
            raise ValueError("layout report slides must contain objects")
        page = int(slide.get("index", 0))
        if slide.get("passed") is False:
            failed_pages.append(page)
        for item in slide.get("issues", []):
            if not isinstance(item, dict) or item.get("severity") != "fail":
                continue
            issues.append(
                {
                    "case_id": context.case.case_id,
                    "stage": "render",
                    "evaluator": name,
                    "type": "LAYOUT_ISSUE",
                    "severity": "major",
                    "message": str(item.get("message") or item.get("type") or "layout failure"),
                    "slide": page,
                    "evidence_ids": [evidence_id],
                    "review_status": "unreviewed",
                    "evidence": item,
                }
            )

    static_failures = [
        item
        for item in report.get("staticRisks", [])
        if isinstance(item, dict) and item.get("severity") == "fail"
    ]
    for item in static_failures:
        issue = {
            "case_id": context.case.case_id,
            "stage": "render",
            "evaluator": name,
            "type": "LAYOUT_STATIC_RISK",
            "severity": "major",
            "message": str(item.get("message") or item.get("type") or "static layout risk"),
            "evidence_ids": [evidence_id],
            "review_status": "unreviewed",
            "evidence": item,
        }
        if isinstance(item.get("slide"), int) and item["slide"] >= 1:
            issue["slide"] = item["slide"]
        issues.append(issue)

    passed = not failed_pages and not static_failures
    return {
        "status": "ok" if passed else "failed",
        "passed": passed,
        "metrics": {
            "slide_count": len(slides),
            "failed_slide_count": len(failed_pages),
            "static_failure_count": len(static_failures),
        },
        "details": {"failed_pages": failed_pages, "viewport": report.get("viewport")},
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(path, evidence_id=evidence_id, kind="layout_report")],
    }


evaluate_layout.evaluator_name = "layout"
