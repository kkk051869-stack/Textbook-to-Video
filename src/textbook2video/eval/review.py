"""Generate a human-review entry point from normalized eval reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .report import write_json


def build_review_index(reports: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for report in reports:
        evidence = {item["evidence_id"]: item for item in report.get("evidence", [])}
        for ordinal, issue in enumerate(report.get("issues", []), start=1):
            evidence_items = [
                evidence[evidence_id]
                for evidence_id in issue.get("evidence_ids", [])
                if evidence_id in evidence
            ]
            items.append(
                {
                    "review_id": f"{report['case_id']}-issue-{ordinal:03d}",
                    "run_id": report["run_id"],
                    "case_id": report["case_id"],
                    "lesson_id": report.get("lesson_id"),
                    "evaluator": issue.get("evaluator"),
                    "severity": issue["severity"],
                    "type": issue["type"],
                    "message": issue["message"],
                    "slide": issue.get("slide"),
                    "question_id": issue.get("question_id"),
                    "element_id": issue.get("element_id"),
                    "event_id": issue.get("event_id"),
                    "review_status": issue.get("review_status", "unreviewed"),
                    "evidence": evidence_items,
                }
            )
    severity_order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    items.sort(
        key=lambda item: (
            severity_order.get(item["severity"], 99),
            item["case_id"],
            item["evaluator"] or "",
            item["review_id"],
        )
    )
    return {
        "schema_version": "textbookeval-review-index-v0.1",
        "case_count": len({item["case_id"] for item in items}),
        "issue_count": len(items),
        "pending_count": sum(item["review_status"] == "unreviewed" for item in items),
        "items": items,
    }


def render_review_markdown(index: dict[str, Any]) -> str:
    lines = [
        "# TextbookEval Human Review Index",
        "",
        f"- Cases with issues: {index['case_count']}",
        f"- Issues: {index['issue_count']}",
        f"- Pending review: {index['pending_count']}",
        "- Review decisions: `confirmed`, `dismissed`, or `uncertain`",
        "",
    ]
    if not index["items"]:
        lines.append("No issues require review.")
        return "\n".join(lines) + "\n"

    for item in index["items"]:
        locations = []
        if item.get("slide") is not None:
            locations.append(f"slide {item['slide']}")
        if item.get("question_id"):
            locations.append(f"question {item['question_id']}")
        location = f" — {', '.join(locations)}" if locations else ""
        lines.extend(
            [
                f"## {item['review_id']}",
                "",
                f"- Case / lesson: `{item['case_id']}` / `{item['lesson_id']}`",
                f"- Evaluator: `{item['evaluator']}`{location}",
                f"- Severity / type: **{item['severity']}** / `{item['type']}`",
                f"- Current review status: `{item['review_status']}`",
                f"- Problem: {item['message']}",
            ]
        )
        if item["evidence"]:
            lines.append("- Evidence:")
            for evidence in item["evidence"]:
                lines.append(
                    f"  - `{evidence['evidence_id']}` ({evidence['kind']}): `{evidence['path']}`"
                )
        else:
            lines.append("- Evidence: no registered evidence path; reviewer action required")
        lines.append("")
    return "\n".join(lines)


def write_review_index(output_dir: str | Path, reports: list[dict[str, Any]]) -> tuple[Path, Path]:
    output = Path(output_dir)
    index = build_review_index(reports)
    json_path = write_json(output / "review_index.json", index)
    markdown_path = output / "review_index.md"
    markdown_path.write_text(render_review_markdown(index), encoding="utf-8")
    return json_path, markdown_path
