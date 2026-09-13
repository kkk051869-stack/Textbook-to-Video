"""Repeated, local-only stability evaluation for TextbookEval reports."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence

from .report import write_json
from .schemas import validate_with_contract

RunFactory = Callable[[int, str], dict[str, Any]]
_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _run_record(index: int, run_id: str, report: dict[str, Any], duration_sec: float) -> dict[str, Any]:
    gates = report.get("gates", {})
    metrics = report.get("metrics", {})
    issues = report.get("issues", [])
    metadata = report.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "repetition": index,
        "run_id": run_id,
        "status": str(report.get("status") or "unknown"),
        "run_completed": True,
        "system_error": False,
        "candidate_failure": str(report.get("status") or "") in {"failed", "partial"}
        or any(value is False for value in gates.values()) if isinstance(gates, dict) else False,
        "duration_sec": round(duration_sec, 6),
        "gates": dict(gates) if isinstance(gates, dict) else {},
        "metrics": dict(metrics) if isinstance(metrics, dict) else {},
        "issues": [item for item in issues if isinstance(item, dict)] if isinstance(issues, list) else [],
        "seed": report.get("seed", metadata.get("seed")),
        "config": report.get("config", metadata.get("config")),
        "report": report,
    }


def _error_record(index: int, run_id: str, exc: Exception, duration_sec: float) -> dict[str, Any]:
    return {
        "repetition": index,
        "run_id": run_id,
        "status": "system_error",
        "run_completed": False,
        "system_error": True,
        "candidate_failure": False,
        "duration_sec": round(duration_sec, 6),
        "gates": {},
        "metrics": {},
        "issues": [],
        "error": {
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        },
    }


def run_repeated(
    repeats: int,
    run_factory: RunFactory,
    *,
    run_id_prefix: str = "stability",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run a deterministic or injected factory repeatedly and aggregate it."""

    if isinstance(repeats, bool) or int(repeats) < 1:
        raise ValueError("repeats must be a positive integer")
    records: list[dict[str, Any]] = []
    for index in range(1, int(repeats) + 1):
        run_id = f"{run_id_prefix}-{index:03d}"
        started = time.monotonic()
        try:
            report = run_factory(index, run_id)
            if not isinstance(report, dict):
                raise TypeError(f"run factory returned {type(report).__name__}, expected dict")
            records.append(_run_record(index, run_id, report, time.monotonic() - started))
        except Exception as exc:  # noqa: BLE001 - one repetition must not erase the others
            records.append(_error_record(index, run_id, exc, time.monotonic() - started))
    aggregate = aggregate_stability(records, run_id_prefix=run_id_prefix)
    if output_dir is not None:
        write_stability_report(output_dir, aggregate)
    return aggregate


def _gate_summary(records: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], float]:
    names = sorted({str(name) for record in records for name in record.get("gates", {})})
    summaries: dict[str, dict[str, Any]] = {}
    total_comparisons = 0
    total_flips = 0
    for name in names:
        states = [record.get("gates", {}).get(name) for record in records]
        comparable = [(left, right) for left, right in zip(states, states[1:]) if isinstance(left, bool) and isinstance(right, bool)]
        flips = sum(left != right for left, right in comparable)
        total_flips += flips
        total_comparisons += len(comparable)
        summaries[name] = {
            "pass_count": sum(value is True for value in states),
            "fail_count": sum(value is False for value in states),
            "unknown_count": sum(value is not True and value is not False for value in states),
            "flip_count": flips,
            "flip_rate": round(flips / len(comparable), 6) if comparable else None,
            "states": states,
        }
    return summaries, (round(total_flips / total_comparisons, 6) if total_comparisons else None)


def _metric_summary(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    names = sorted({str(name) for record in records for name in record.get("metrics", {})})
    summary: dict[str, dict[str, Any]] = {}
    for name in names:
        values = [
            number
            for record in records
            for value in [record.get("metrics", {}).get(name)]
            for number in [_number(value)]
            if number is not None
        ]
        summary[name] = {
            "count": len(values),
            "mean": round(statistics.fmean(values), 6) if values else None,
            "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0 if values else None,
            "values": values,
            "std_kind": "population",
        }
    return summary


def _issue_frequency(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts: Counter[str] = Counter()
    for record in records:
        types = {
            str(issue.get("type") or issue.get("category") or "EVAL_ISSUE")
            for issue in record.get("issues", [])
            if isinstance(issue, dict)
        }
        counts.update(types)
    total = len(records)
    return {
        name: {"count": count, "frequency": round(count / total, 6) if total else None}
        for name, count in sorted(counts.items())
    }


def aggregate_stability(records: list[dict[str, Any]], *, run_id_prefix: str = "stability") -> dict[str, Any]:
    """Aggregate repeated records without inventing a cross-metric total score."""

    if not records:
        raise ValueError("at least one repetition record is required")
    normalized = [dict(record) for record in records]
    gate_summaries, gate_flip_rate = _gate_summary(normalized)
    metric_summaries = _metric_summary(normalized)
    issue_frequency = _issue_frequency(normalized)
    key_gate_names = sorted(gate_summaries)
    stable_pass = bool(key_gate_names) and all(
        not record.get("system_error")
        and all(record.get("gates", {}).get(name) is True for name in key_gate_names)
        for record in normalized
    )
    for record in normalized:
        record.pop("report", None)
        error = record.get("error")
        if isinstance(error, dict):
            error.pop("traceback", None)
    def worst_key(record: dict[str, Any]) -> tuple[int, int, int, int]:
        failed_gates = sum(value is False for value in record.get("gates", {}).values())
        return (
            1 if record.get("system_error") else 0,
            failed_gates,
            len(record.get("issues", [])),
            int(record.get("repetition") or 0),
        )
    worst = max(normalized, key=worst_key)
    run_count = len(normalized)
    completed = sum(bool(record.get("run_completed")) for record in normalized)
    system_errors = sum(bool(record.get("system_error")) for record in normalized)
    candidate_failures = sum(bool(record.get("candidate_failure")) for record in normalized)
    result = {
        "schema_version": "textbookeval-stability-v0.1",
        "run_id_prefix": run_id_prefix,
        "repeats": run_count,
        "stable_pass_at_n": stable_pass,
        "gate_flip_rate": gate_flip_rate,
        "gates": gate_summaries,
        "metrics": metric_summaries,
        "issue_frequency": issue_frequency,
        "worst_run": {
            "run_id": worst.get("run_id"),
            "repetition": worst.get("repetition"),
            "status": worst.get("status"),
            "system_error": bool(worst.get("system_error")),
            "candidate_failure": bool(worst.get("candidate_failure")),
            "failed_gate_count": sum(value is False for value in worst.get("gates", {}).values()),
            "issue_count": len(worst.get("issues", [])),
        },
        "run_success_rate": round(completed / run_count, 6),
        "candidate_failure_rate": round(candidate_failures / run_count, 6),
        "system_error_rate": round(system_errors / run_count, 6),
        "system_error_count": system_errors,
        "candidate_failure_count": candidate_failures,
        "runs": normalized,
        "metadata": {
            "key_gates": key_gate_names,
            "metric_std_kind": "population",
            "aggregate_has_no_unified_score": True,
        },
    }
    validate_with_contract(result, "stability_report.schema.json", contracts_dir=_CONTRACTS_DIR)
    return result


def render_stability_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TextbookEval Repeated Stability Report",
        "",
        f"- Repeats: {report['repeats']}",
        f"- StablePass@N: `{report['stable_pass_at_n']}`",
        f"- Gate Flip Rate: `{report['gate_flip_rate']}`",
        f"- Run Success Rate: `{report['run_success_rate']}`",
        f"- Candidate Failure Rate: `{report['candidate_failure_rate']}`",
        f"- System Error Rate: `{report['system_error_rate']}`",
        "",
        "No unified cross-metric score is calculated.",
        "",
        "## Gates",
        "",
        "| Gate | Pass | Fail | Unknown | Flips | Flip Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, value in report["gates"].items():
        lines.append(f"| {name} | {value['pass_count']} | {value['fail_count']} | {value['unknown_count']} | {value['flip_count']} | {value['flip_rate']} |")
    lines.extend(["", "## Metrics", "", "| Metric | Count | Mean | Std |", "| --- | ---: | ---: | ---: |"])
    for name, value in report["metrics"].items():
        lines.append(f"| {name} | {value['count']} | {value['mean']} | {value['std']} |")
    lines.extend(["", "## Issue Frequency", "", "| Issue | Count | Frequency |", "| --- | ---: | ---: |"])
    for name, value in report["issue_frequency"].items():
        lines.append(f"| {name} | {value['count']} | {value['frequency']} |")
    lines.extend([
        "",
        "## Worst Run",
        "",
        f"- Run: `{report['worst_run']['run_id']}`",
        f"- Status: `{report['worst_run']['status']}`",
        f"- Failed gates: {report['worst_run']['failed_gate_count']}",
        f"- Issues: {report['worst_run']['issue_count']}",
        "",
    ])
    return "\n".join(lines)


def write_stability_report(output_dir: str | Path, report: dict[str, Any]) -> tuple[Path, Path]:
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output / "stability_report.json", report)
    markdown_path = output / "stability_report.md"
    markdown_path.write_text(render_stability_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _load_reports(path: Path) -> list[dict[str, Any]]:
    candidates = [path] if path.is_file() else sorted(path.rglob("eval_report.json"))
    reports: list[dict[str, Any]] = []
    for candidate in candidates:
        value = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(value, list):
            reports.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            reports.append(value)
        else:
            raise ValueError(f"stability input must contain report objects: {candidate}")
    if not reports:
        raise FileNotFoundError(f"no reports found under {path}")
    return reports


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repeated local TextbookEval stability benchmark")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--reports", type=Path, help="Existing eval_report.json or directory of reports")
    source.add_argument("--case", type=Path, help="Frozen case_manifest.json to evaluate repeatedly")
    parser.add_argument("--artifacts", type=Path, help="Existing artifact directory used with --case")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--run-prefix", default="stability")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.reports:
        reports = _load_reports(args.reports)
        if len(reports) < args.repeats:
            raise ValueError(f"--reports contains {len(reports)} reports, but --repeats={args.repeats}")
        records = []
        for index, report in enumerate(reports[: args.repeats], 1):
            run_id = f"{args.run_prefix}-{index:03d}"
            records.append(_run_record(index, run_id, report, _number(report.get("duration_sec")) or 0.0))
    else:
        if args.artifacts is None:
            raise ValueError("--case requires --artifacts")
        from .dataset import load_case
        from .evaluators import deterministic_evaluators
        from .runner import run_case

        case = load_case(args.case, require_frozen=True)

        def factory(_index: int, run_id: str) -> dict[str, Any]:
            return run_case(
                case,
                run_id=run_id,
                artifacts_root=args.artifacts,
                output_root=args.out / "repetitions" / run_id,
                evaluators=deterministic_evaluators(),
                repo_root=Path(__file__).resolve().parents[3],
            )

        report = run_repeated(args.repeats, factory, run_id_prefix=args.run_prefix, output_dir=args.out)
        return 0 if report["stable_pass_at_n"] else 1
    report = aggregate_stability(records, run_id_prefix=args.run_prefix)
    write_stability_report(args.out, report)
    return 0 if report["stable_pass_at_n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
