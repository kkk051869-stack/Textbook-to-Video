"""Compare two evaluation runs without producing a unified score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .report import write_json


def _load_reports(path: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(path).resolve()
    candidates = [root] if root.is_file() else sorted(root.rglob("eval_report.json"))
    reports: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        value = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or "case_id" not in value:
            raise ValueError(f"invalid eval report: {candidate}")
        case_id = str(value["case_id"])
        if case_id in reports:
            raise ValueError(f"duplicate case_id {case_id!r} under {root}")
        reports[case_id] = value
    if not reports:
        raise FileNotFoundError(f"no eval_report.json found under {root}")
    return reports


def _numeric_metrics(report: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for evaluator, result in report.get("evaluators", {}).items():
        for metric, value in result.get("metrics", {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[f"{evaluator}.{metric}"] = float(value)
    return values


def _issue_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    return (
        issue.get("evaluator"),
        issue.get("type"),
        issue.get("slide"),
        issue.get("element_id"),
        issue.get("event_id"),
    )


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if baseline["case_id"] != candidate["case_id"]:
        raise ValueError("baseline and candidate case_id must match")
    baseline_metrics = _numeric_metrics(baseline)
    candidate_metrics = _numeric_metrics(candidate)
    metric_changes = []
    for name in sorted(baseline_metrics.keys() | candidate_metrics.keys()):
        before = baseline_metrics.get(name)
        after = candidate_metrics.get(name)
        metric_changes.append(
            {
                "metric": name,
                "baseline": before,
                "candidate": after,
                "delta": after - before if before is not None and after is not None else None,
            }
        )

    before_issues = {_issue_key(issue): issue for issue in baseline.get("issues", [])}
    after_issues = {_issue_key(issue): issue for issue in candidate.get("issues", [])}
    new_keys = after_issues.keys() - before_issues.keys()
    resolved_keys = before_issues.keys() - after_issues.keys()
    unchanged_keys = before_issues.keys() & after_issues.keys()
    gate_changes = []
    for name in sorted(baseline.get("gates", {}).keys() | candidate.get("gates", {}).keys()):
        before = baseline.get("gates", {}).get(name)
        after = candidate.get("gates", {}).get(name)
        gate_changes.append(
            {
                "gate": name,
                "baseline": before,
                "candidate": after,
                "regressed": before is True and after is not True,
            }
        )
    return {
        "case_id": baseline["case_id"],
        "lesson_id": candidate["lesson_id"],
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "baseline_status": baseline["status"],
        "candidate_status": candidate["status"],
        "gate_changes": gate_changes,
        "metric_changes": metric_changes,
        "new_issues": [after_issues[key] for key in sorted(new_keys, key=str)],
        "resolved_issues": [before_issues[key] for key in sorted(resolved_keys, key=str)],
        "unchanged_issues": [after_issues[key] for key in sorted(unchanged_keys, key=str)],
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# TextbookEval Baseline / Candidate Comparison",
        "",
        "No cross-metric unified score is calculated.",
        "",
    ]
    for case in comparison["cases"]:
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"- Baseline: `{case['baseline_run_id']}` ({case['baseline_status']})",
                f"- Candidate: `{case['candidate_run_id']}` ({case['candidate_status']})",
                f"- New issues: {len(case['new_issues'])}",
                f"- Resolved issues: {len(case['resolved_issues'])}",
                "",
                "| Gate | Baseline | Candidate | Regressed |",
                "| --- | --- | --- | --- |",
            ]
        )
        for gate in case["gate_changes"]:
            lines.append(
                f"| {gate['gate']} | {gate['baseline']} | {gate['candidate']} | "
                f"{gate['regressed']} |"
            )
        lines.extend(
            [
                "",
                "| Metric | Baseline | Candidate | Delta |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for metric in case["metric_changes"]:
            lines.append(
                f"| {metric['metric']} | {metric['baseline']} | "
                f"{metric['candidate']} | {metric['delta']} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def compare_runs(
    baseline_path: str | Path, candidate_path: str | Path, output_dir: str | Path
) -> dict[str, Any]:
    baseline = _load_reports(baseline_path)
    candidate = _load_reports(candidate_path)
    shared = sorted(baseline.keys() & candidate.keys())
    if not shared:
        raise ValueError("baseline and candidate runs have no shared case_id")
    comparison = {
        "schema_version": "textbookeval-comparison-v0.1",
        "cases": [compare_reports(baseline[case_id], candidate[case_id]) for case_id in shared],
        "baseline_only_cases": sorted(baseline.keys() - candidate.keys()),
        "candidate_only_cases": sorted(candidate.keys() - baseline.keys()),
    }
    output = Path(output_dir).resolve()
    write_json(output / "comparison.json", comparison)
    (output / "comparison.md").write_text(
        render_comparison_markdown(comparison), encoding="utf-8"
    )
    return comparison


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two TextbookEval report runs")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_runs(args.baseline, args.candidate, args.out)
    regressed = any(
        gate["regressed"] for case in comparison["cases"] for gate in case["gate_changes"]
    )
    return 1 if regressed else 0


if __name__ == "__main__":
    raise SystemExit(main())
