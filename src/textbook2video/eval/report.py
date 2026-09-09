"""Create stable JSON and Markdown reports without a cross-metric total score."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def report_status(evaluators: dict[str, dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in evaluators.values()}
    if "error" in statuses:
        return "partial"
    if "failed" in statuses:
        return "failed"
    if statuses & {"skipped", "unavailable"}:
        return "partial"
    return "ok"


def write_json(path: str | Path, value: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return output


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Eval Report {report['case_id']}",
        "",
        f"- Lesson: `{report['lesson_id']}`",
        f"- Run: `{report['run_id']}`",
        f"- Status: **{report['status']}**",
        "- Cross-metric total score: not calculated",
        "",
        "## Evaluators",
        "",
        "| Evaluator | Status | Passed | Issues |",
        "| --- | --- | --- | ---: |",
    ]
    for name, result in report["evaluators"].items():
        passed = result.get("passed")
        lines.append(f"| {name} | {result['status']} | {passed} | {len(result['issues'])} |")
    lines.extend(["", "## Issues", ""])
    if not report["issues"]:
        lines.append("No issues were reported.")
    else:
        for issue in report["issues"]:
            location = f" slide {issue['slide']}" if issue.get("slide") else ""
            lines.append(
                f"- **{issue['severity']} {issue['type']}**{location}: {issue['message']}"
            )
            for evidence_id in issue.get("evidence_ids", []):
                lines.append(f"  - Evidence: `{evidence_id}`")
    lines.extend(["", "## Evidence", ""])
    if not report["evidence"]:
        lines.append("No evidence files were registered.")
    else:
        for evidence in report["evidence"]:
            lines.append(
                f"- `{evidence['evidence_id']}` [{evidence['kind']}]: `{evidence['path']}`"
            )
    return "\n".join(lines) + "\n"


def write_markdown(path: str | Path, report: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    return output


def write_report_csv(output_dir: str | Path, reports: list[dict[str, Any]]) -> tuple[Path, Path]:
    """Write spreadsheet-friendly case summary and issue detail tables."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    for report in reports:
        row: dict[str, Any] = {
            "run_id": report["run_id"],
            "case_id": report["case_id"],
            "lesson_id": report["lesson_id"],
            "status": report["status"],
            "issue_count": len(report["issues"]),
        }
        for name, result in report["evaluators"].items():
            row[f"evaluator.{name}.status"] = result["status"]
            row[f"evaluator.{name}.passed"] = result.get("passed")
            for metric, value in result.get("metrics", {}).items():
                if not isinstance(value, (dict, list)):
                    row[f"metric.{name}.{metric}"] = value
        summary_rows.append(row)

    summary_fields = sorted({field for row in summary_rows for field in row})
    summary_path = output / "summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    issue_fields = [
        "run_id",
        "case_id",
        "lesson_id",
        "stage",
        "evaluator",
        "type",
        "severity",
        "slide",
        "element_id",
        "event_id",
        "message",
        "evidence_ids",
        "review_status",
    ]
    issues_path = output / "issues.csv"
    with issues_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=issue_fields)
        writer.writeheader()
        for report in reports:
            for issue in report["issues"]:
                writer.writerow(
                    {
                        **{field: issue.get(field) for field in issue_fields},
                        "run_id": report["run_id"],
                        "lesson_id": report["lesson_id"],
                        "evidence_ids": ";".join(issue.get("evidence_ids", [])),
                    }
                )
    return summary_path, issues_path
