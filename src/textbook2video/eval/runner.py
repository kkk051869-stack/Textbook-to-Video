"""One-case TextbookEval runner with per-evaluator fault isolation."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .dataset import CaseManifest, discover_case_manifests, load_case
from .report import report_status, write_json, write_markdown, write_report_csv
from .review import write_review_index
from .schemas import validate_with_contract

Evaluator = Callable[["EvalContext"], dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_value(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


@dataclass(frozen=True)
class EvalContext:
    case: CaseManifest
    run_id: str
    artifacts_root: Path
    output_root: Path

    def artifact(self, role: str) -> Path | None:
        mappings = []
        candidate = self.case.raw.get("candidate_artifacts")
        baseline = self.case.raw.get("baseline_artifacts")
        if isinstance(candidate, dict):
            mappings.append(candidate)
        if isinstance(baseline, dict):
            mappings.append(baseline)
        for artifacts in mappings:
            value = artifacts.get(role)
            if isinstance(value, dict):
                value = value.get("path")
            if not isinstance(value, str) or not value.strip():
                continue
            relative = Path(value)
            if relative.is_absolute():
                raise ValueError(f"artifact {role} must use a relative path: {value}")
            resolved = (self.artifacts_root / relative).resolve()
            if resolved != self.artifacts_root and self.artifacts_root not in resolved.parents:
                raise ValueError(f"artifact {role} escapes artifacts_root: {value}")
            return resolved

        # Candidate runs may be produced by B before the case manifest is
        # updated.  Keep the conventional filenames discoverable without
        # mutating the frozen manifest.
        conventional = {
            "animation_trace": ("animation_trace.json", "animation-trace.json"),
            "raw_animation_trace": ("animation_trace.raw.json", "raw_animation_trace.json"),
            "layout_report_1366": ("storyboard.layout-1366x768.json",),
            "baseline_eval_report": ("baseline_eval_report.json",),
            "regression": ("regression.json",),
        }
        for name in conventional.get(role, ()):
            candidate = (self.artifacts_root / name).resolve()
            if candidate.is_file() and self.artifacts_root in candidate.parents:
                return candidate
        return None


def evaluator_name(evaluator: Evaluator) -> str:
    return str(getattr(evaluator, "evaluator_name", getattr(evaluator, "__name__", "evaluator")))


def normalize_issue(
    issue: dict[str, Any], *, case_id: str, evaluator: str, index: int
) -> dict[str, Any]:
    """Add the stable issue contract while retaining legacy report fields."""
    category = str(issue.get("category") or issue.get("type") or "EVAL_ISSUE")
    summary = str(issue.get("summary") or issue.get("message") or category)
    legacy_severity = str(issue.get("severity") or "warning")
    severity = {
        "minor": "warning",
        "major": "error",
        "critical": "error",
    }.get(legacy_severity, legacy_severity)
    if severity not in {"info", "warning", "error"}:
        severity = "warning"
    location = issue.get("location")
    if not isinstance(location, dict):
        location = {
            key: issue[key]
            for key in ("slide", "question_id", "element_id", "event_id")
            if issue.get(key) is not None
        }
    evidence = issue.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {"evidence_ids": list(issue.get("evidence_ids", []))}
    normalized = dict(issue)
    normalized.update(
        {
            "issue_id": str(issue.get("issue_id") or f"{case_id}:{evaluator}:{category}:{index}"),
            "case_id": case_id,
            "evaluator": evaluator,
            "category": category,
            "severity": severity,
            "location": location,
            "summary": summary,
            "evidence": evidence,
            "expected": issue.get("expected"),
            "actual": issue.get("actual"),
            "metadata": issue.get("metadata") if isinstance(issue.get("metadata"), dict) else {},
            # Keep the old renderer/CSV/test fields available.
            "type": str(issue.get("type") or category),
            "message": summary,
            "stage": str(issue.get("stage") or "eval"),
            "evidence_ids": list(issue.get("evidence_ids", evidence.get("evidence_ids", []))),
            "review_status": str(issue.get("review_status") or "unreviewed"),
        }
    )
    return normalized


def run_evaluator_safely(evaluator: Evaluator, context: EvalContext) -> dict[str, Any]:
    name = evaluator_name(evaluator)
    started = utc_now()
    before = time.monotonic()
    try:
        value = evaluator(context)
        if not isinstance(value, dict):
            raise TypeError(f"evaluator {name} returned {type(value).__name__}, expected dict")
        result = {
            "evaluator": name,
            "status": value.get("status", "ok"),
            "passed": value.get("passed"),
            "started_at": started,
            "finished_at": utc_now(),
            "duration_sec": round(time.monotonic() - before, 6),
            "metrics": value.get("metrics", {}),
            "details": value.get("details", {}),
            "issues": value.get("issues", []),
            "evidence_ids": value.get("evidence_ids", []),
        }
        if value.get("_evidence"):
            result["_evidence"] = value["_evidence"]
        return result
    except Exception as exc:  # noqa: BLE001 - isolation is the runner contract
        evidence_id = f"{context.case.case_id}-{name}-exception"
        evidence_dir = context.output_root / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / f"{name}-exception.txt"
        evidence_path.write_text(traceback.format_exc(), encoding="utf-8")
        return {
            "evaluator": name,
            "status": "error",
            "passed": None,
            "started_at": started,
            "finished_at": utc_now(),
            "duration_sec": round(time.monotonic() - before, 6),
            "metrics": {},
            "details": {"exception_type": type(exc).__name__},
            "issues": [
                {
                    "case_id": context.case.case_id,
                    "stage": "eval",
                    "evaluator": name,
                    "type": "EVALUATOR_ERROR",
                    "severity": "major",
                    "message": str(exc),
                    "evidence_ids": [evidence_id],
                    "review_status": "unreviewed",
                }
            ],
            "evidence_ids": [evidence_id],
            "_evidence": [
                {
                    "evidence_id": evidence_id,
                    "kind": "exception_traceback",
                    "path": str(evidence_path.relative_to(context.output_root)),
                    "description": f"Unhandled exception from evaluator {name}",
                }
            ],
        }


def run_case(
    case: CaseManifest,
    *,
    run_id: str,
    artifacts_root: str | Path,
    output_root: str | Path,
    evaluators: Sequence[Evaluator] | None = None,
    command: Sequence[str] = (),
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    context = EvalContext(
        case=case,
        run_id=run_id,
        artifacts_root=Path(artifacts_root).resolve(),
        output_root=output,
    )
    results: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if evaluators is None:
        from .evaluators import full_evaluators

        evaluators = full_evaluators()
    for evaluator in evaluators:
        result = run_evaluator_safely(evaluator, context)
        evidence.extend(result.pop("_evidence", []))
        result["issues"] = [
            normalize_issue(item, case_id=case.case_id, evaluator=result["evaluator"], index=index)
            for index, item in enumerate(result.get("issues", []), start=1)
        ]
        results[result["evaluator"]] = result
        issues.extend(result["issues"])

    evidence_by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        evidence_id = item["evidence_id"]
        previous = evidence_by_id.get(evidence_id)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting evidence records use id {evidence_id!r}")
        evidence_by_id[evidence_id] = item
    evidence = list(evidence_by_id.values())

    root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    baseline_system = (
        case.raw.get("systems", {}).get("baseline", {}).get("system_id")
        if isinstance(case.raw.get("systems"), dict)
        else None
    )
    candidate_system = (
        case.raw.get("systems", {}).get("candidate", {}).get("system_id")
        if isinstance(case.raw.get("systems"), dict)
        else None
    )
    report = {
        "schema_version": "textbookeval-report-v0.2",
        "case_id": case.case_id,
        "lesson_id": case.lesson_id,
        "run_id": run_id,
        "status": report_status(results),
        "gates": {
            name: result.get("passed")
            for name, result in results.items()
            if result.get("passed") is not None
        },
        "metrics": {},
        "source_fidelity": results.get("source_fidelity", {"status": "unavailable", "metrics": {}}),
        "knowledge_grounding": results.get(
            "knowledge_grounding", {"status": "unavailable", "metrics": {}}
        ),
        "video_qa": {
            "audience": results.get("videoqa_audience", {"status": "unavailable", "metrics": {}}),
            "reference": results.get(
                "videoqa_reference", {"status": "unavailable", "metrics": {}}
            ),
        },
        "animation": results.get(
            "animation_runtime", {"status": "unavailable", "metrics": {}}
        ),
        "layout": results.get("layout", {"status": "unavailable", "metrics": {}}),
        "regression": results.get("regression", {"status": "skipped", "metrics": {}}),
        "evaluators": results,
        "issues": issues,
        "evidence": evidence,
        "artifacts": {
            "case_manifest": str(case.manifest_path),
            "artifacts_root": str(context.artifacts_root),
            "inputs": [
                {
                    "role": asset.role,
                    "path": str(case.resolve_asset(asset)),
                    "sha256": asset.sha256,
                }
                for asset in case.assets()
            ],
        },
        "review": {"required": bool(issues), "status": "pending" if issues else "not_required"},
        "metadata": {
            "case_id": case.case_id,
            "lesson_id": case.lesson_id,
            "dataset_version": case.dataset_version,
            "candidate_system": candidate_system or "unknown",
            "baseline_system": baseline_system or "unknown",
            "git_commit": git_value(root, "rev-parse", "HEAD"),
            "branch": git_value(root, "branch", "--show-current"),
            "command": list(command),
            "model_config": {
                name: value.get("details", {}).get("model")
                or value.get("details", {}).get("config", {})
                for name, value in results.items()
                if value.get("details", {}).get("model")
                or value.get("details", {}).get("config")
            },
            "timestamp": utc_now(),
        },
    }
    contracts_dir = root / "contracts"
    validate_with_contract(report, "eval_report.schema.json", contracts_dir=contracts_dir)
    write_json(output / "eval_report.json", report)
    write_markdown(output / "eval_report.md", report)
    write_review_index(output, [report])

    case_metadata = case.raw.get("metadata", {})
    prompt_hashes = (
        dict(case_metadata.get("prompt_hashes", {}))
        if isinstance(case_metadata, dict)
        and isinstance(case_metadata.get("prompt_hashes", {}), dict)
        else {}
    )
    for name, value in results.items():
        model_metadata = value.get("details", {}).get("metadata", {})
        prompt_sha256 = (
            model_metadata.get("prompt_sha256") if isinstance(model_metadata, dict) else None
        )
        if isinstance(prompt_sha256, str):
            prompt_hashes[name] = prompt_sha256
    manifest = {
        "schema_version": "textbookeval-run-v0.1",
        "run_id": run_id,
        "dataset_version": case.dataset_version,
        "case_ids": [case.case_id],
        "git_commit": report["metadata"]["git_commit"] or "unknown",
        "branch": report["metadata"]["branch"],
        "command": list(command),
        "environment": {"python": sys.version, "platform": platform.platform()},
        "models": {
            name: value["details"]["model"]
            for name, value in results.items()
            if isinstance(value.get("details", {}).get("model"), str)
        },
        "prompt_hashes": prompt_hashes,
        "config": {
            "systems": case.raw.get("systems", {}),
            "judge_prompt_versions": {
                name: value["details"]["prompt_version"]
                for name, value in results.items()
                if isinstance(value.get("details", {}).get("prompt_version"), str)
            },
        },
        "artifacts_root": str(context.artifacts_root),
        "started_at": min((value["started_at"] for value in results.values()), default=utc_now()),
        "finished_at": utc_now(),
        "evaluators": {name: value["status"] for name, value in results.items()},
        "metadata": {},
    }
    validate_with_contract(manifest, "run_manifest.schema.json", contracts_dir=contracts_dir)
    write_json(output / "run_manifest.json", manifest)
    write_report_csv(output, [report])
    return report


def run_dataset(
    dataset_dir: str | Path,
    *,
    run_id: str,
    artifacts_root: str | Path,
    output_root: str | Path,
    require_frozen: bool = True,
    command: Sequence[str] = (),
    repo_root: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Evaluate all discoverable cases while isolating case-load and case-run failures."""
    artifacts = Path(artifacts_root).resolve()
    output = Path(output_root).resolve()
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for manifest_path in discover_case_manifests(dataset_dir):
        try:
            case = load_case(manifest_path, verify_files=False, require_frozen=require_frozen)
            metadata = case.raw.get("metadata", {})
            artifact_subdir = (
                metadata.get("artifacts_subdir") if isinstance(metadata, dict) else None
            )
            candidates = (
                [artifacts / str(artifact_subdir)]
                if artifact_subdir
                else [artifacts / case.case_id, artifacts / case.lesson_id]
            )
            case_artifacts = next(
                (candidate for candidate in candidates if candidate.is_dir()), artifacts
            )
            report = run_case(
                case,
                run_id=run_id,
                artifacts_root=case_artifacts,
                output_root=output / "cases" / case.case_id,
                command=command,
                repo_root=repo_root,
            )
            reports.append(report)
        except Exception as exc:  # noqa: BLE001 - one bad case must not stop the run
            errors.append(
                {
                    "manifest": str(manifest_path),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    write_report_csv(output, reports)
    write_review_index(output, reports)
    write_json(
        output / "batch_summary.json",
        {
            "run_id": run_id,
            "dataset_dir": str(Path(dataset_dir).resolve()),
            "case_count": len(reports),
            "case_statuses": {report["case_id"]: report["status"] for report in reports},
            "errors": errors,
        },
    )
    return reports, errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate frozen TextbookEval cases")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", type=Path, help="Path to case_manifest.json")
    source.add_argument("--dataset", type=Path, help="Directory containing case manifests")
    parser.add_argument("--artifacts", required=True, type=Path, help="Existing run artifacts")
    parser.add_argument("--out", required=True, type=Path, help="Evaluation output directory")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--allow-candidate", action="store_true", help="Allow non-frozen cases for development"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command = [sys.executable, "-m", "textbook2video.eval.runner", *(argv or sys.argv[1:])]
    repo_root = Path(__file__).resolve().parents[3]
    if args.dataset:
        run_id = args.run_id or f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-dataset"
        reports, errors = run_dataset(
            args.dataset,
            run_id=run_id,
            artifacts_root=args.artifacts,
            output_root=args.out,
            require_frozen=not args.allow_candidate,
            command=command,
            repo_root=repo_root,
        )
        failed = any(report["status"] in {"failed", "error"} for report in reports)
        return 1 if errors or failed else 0

    case = load_case(args.case, verify_files=False, require_frozen=not args.allow_candidate)
    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{case.case_id}"
    report = run_case(
        case,
        run_id=run_id,
        artifacts_root=args.artifacts,
        output_root=args.out,
        command=command,
        repo_root=repo_root,
    )
    return 1 if report["status"] in {"failed", "error"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
