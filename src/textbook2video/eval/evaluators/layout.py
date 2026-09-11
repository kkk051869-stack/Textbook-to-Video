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
    secondary_path = context.artifact("layout_report_1366")
    secondary = None
    secondary_failed_pages: list[int] = []
    if secondary_path is not None and secondary_path.is_file():
        secondary = json.loads(secondary_path.read_text(encoding="utf-8"))
        for slide in secondary.get("slides", []):
            if isinstance(slide, dict) and slide.get("passed") is False:
                secondary_failed_pages.append(int(slide.get("index", 0)))
        for slide in secondary.get("slides", []):
            if not isinstance(slide, dict):
                continue
            for item in slide.get("issues", []):
                if isinstance(item, dict) and item.get("severity") == "fail":
                    issues.append(
                        {
                            "case_id": context.case.case_id,
                            "stage": "render",
                            "evaluator": name,
                            "type": "LAYOUT_ISSUE_1366",
                            "severity": "major",
                            "message": str(item.get("message") or item.get("type") or "layout failure"),
                            "slide": int(slide.get("index", 0)),
                            "evidence_ids": [f"{evidence_id}-1366"],
                            "review_status": "unreviewed",
                            "evidence": item,
                        }
                    )
    all_failed_pages = failed_pages + secondary_failed_pages
    return {
        "status": "ok" if not all_failed_pages and not static_failures else "failed",
        "passed": not all_failed_pages and not static_failures,
        "metrics": {
            "slide_count": len(slides),
            "failed_slide_count": len(all_failed_pages),
            "failed_slide_count_1920": len(failed_pages),
            "failed_slide_count_1366": len(secondary_failed_pages),
            "static_failure_count": len(static_failures),
        },
        "details": {
            "failed_pages": all_failed_pages,
            "failed_pages_1920": failed_pages,
            "failed_pages_1366": secondary_failed_pages,
            "viewport": report.get("viewport"),
            "viewport_1366": secondary.get("viewport") if isinstance(secondary, dict) else None,
            "layout_1920": {
                "status": "ok" if not failed_pages and not static_failures else "failed",
                "failed_slide_count": len(failed_pages),
                "static_failure_count": len(static_failures),
                "viewport": report.get("viewport"),
            },
            "layout_1366": {
                "status": "ok" if not secondary_failed_pages and secondary is not None else "unavailable",
                "failed_slide_count": len(secondary_failed_pages),
                "viewport": secondary.get("viewport") if isinstance(secondary, dict) else None,
            },
        },
        "issues": issues,
        "evidence_ids": [evidence_id] + ([f"{evidence_id}-1366"] if secondary_path else []),
        "_evidence": [evidence_for(path, evidence_id=evidence_id, kind="layout_report")]
        + ([evidence_for(secondary_path, evidence_id=f"{evidence_id}-1366", kind="layout_report_1366")]
           if secondary_path and secondary_path.is_file() else []),
    }


evaluate_layout.evaluator_name = "layout"
