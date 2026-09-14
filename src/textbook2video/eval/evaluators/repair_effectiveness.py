"""Measure whether recorded repairs improve the same evaluator outcome.

This module is deliberately a consumer of repair lineage.  It does not run a
repair agent, mutate candidate artifacts, or re-evaluate a candidate.  A
lineage file joins one or more before/after reports produced by the existing
evaluators and makes the result reproducible for later human calibration.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from ..runner import EvalContext

EVALUATOR_NAME = "repair_effectiveness"
EVALUATOR_VERSION = "repair-effectiveness-v0.1"

DEFAULT_SEVERITY_WEIGHTS = {
    "info": 1.0,
    "minor": 1.0,
    "warning": 1.0,
    "major": 3.0,
    "error": 3.0,
    "critical": 5.0,
}
SEVERITY_RANK = {"info": 0, "minor": 1, "warning": 1, "major": 2, "error": 2, "critical": 3}


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _severity(value: Any) -> str:
    normalized = str(value or "warning").lower()
    return normalized if normalized in SEVERITY_RANK else "warning"


def _rank(value: Any) -> int:
    return SEVERITY_RANK[_severity(value)]


def _location_value(issue: dict[str, Any], name: str) -> Any:
    if issue.get(name) is not None:
        return issue.get(name)
    location = issue.get("location")
    if isinstance(location, dict) and location.get(name) is not None:
        return location.get(name)
    metadata = issue.get("metadata")
    if isinstance(metadata, dict) and metadata.get(name) is not None:
        return metadata.get(name)
    return None


def issue_identity(issue: dict[str, Any]) -> tuple[Any, ...]:
    """Return the stable identity used to compare before and after issues.

    Explicit issue IDs win.  Runner-generated IDs end in a list position
    (``case:evaluator:type:index``); those positions are deliberately
    canonicalized to the location fallback so removing an earlier issue does
    not make every later warning look new.  The fallback intentionally does
    not use message text, so wording changes do not turn a persistent issue
    into a new one.
    """

    issue_id = issue.get("issue_id")
    if issue_id is not None and str(issue_id).strip():
        issue_id_text = str(issue_id)
        issue_type = str(issue.get("type") or issue.get("category") or "EVAL_ISSUE")
        evaluator = str(issue.get("evaluator") or "")
        parts = issue_id_text.rsplit(":", 3)
        runner_position_id = (
            len(parts) == 4
            and parts[-1].isdigit()
            and parts[-2] == issue_type
            and (not evaluator or parts[-3] == evaluator)
        )
        if not runner_position_id:
            return ("issue_id", issue_id_text)
    return (
        "fallback",
        str(issue.get("stage") or "eval"),
        str(issue.get("type") or issue.get("category") or "EVAL_ISSUE"),
        str(_location_value(issue, "slide")) if _location_value(issue, "slide") is not None else None,
        str(_location_value(issue, "element_id"))
        if _location_value(issue, "element_id") is not None
        else None,
        str(_location_value(issue, "event_id"))
        if _location_value(issue, "event_id") is not None
        else None,
        str(_location_value(issue, "question_id"))
        if _location_value(issue, "question_id") is not None
        else None,
    )


def _record_fallback_identity(record: dict[str, Any]) -> tuple[Any, ...] | None:
    issue_type = record.get("issue_type")
    issue_stage = record.get("issue_stage")
    fields = {
        "slide": record.get("slide"),
        "element_id": record.get("element_id"),
        "event_id": record.get("event_id"),
        "question_id": record.get("question_id"),
    }
    if issue_type is None and issue_stage is None and not any(value is not None for value in fields.values()):
        return None
    return (
        "fallback",
        str(issue_stage or "eval"),
        str(issue_type or "EVAL_ISSUE"),
        str(fields["slide"]) if fields["slide"] is not None else None,
        str(fields["element_id"]) if fields["element_id"] is not None else None,
        str(fields["event_id"]) if fields["event_id"] is not None else None,
        str(fields["question_id"]) if fields["question_id"] is not None else None,
    )


def _issues(report: Any) -> list[dict[str, Any]]:
    if not isinstance(report, dict) or not isinstance(report.get("issues"), list):
        return []
    return [item for item in report["issues"] if isinstance(item, dict)]


def _unique_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate report rows before computing issue deltas."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for issue in issues:
        identity = issue_identity(issue)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(issue)
    return result


def _resolve_path(value: Any, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _load_reference(value: Any, root: Path) -> tuple[Any | None, Path | None]:
    if isinstance(value, dict):
        return value, None
    path = _resolve_path(value, root)
    if path is None or not path.is_file():
        return None, path
    return _read_json(path), path


def _artifact_reference(record: dict[str, Any], side: str, root: Path) -> tuple[Path | None, str | None]:
    value = record.get(f"{side}_artifact")
    if isinstance(value, dict):
        declared_hash = value.get("sha256") or value.get("hash")
        value = value.get("path")
    else:
        declared_hash = None
    path = _resolve_path(value, root)
    return path, str(declared_hash) if declared_hash else None


def _find_source_issue(
    record: dict[str, Any], issues: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, tuple[Any, ...] | None]:
    source_id = record.get("source_issue_id")
    if source_id is not None and str(source_id).strip():
        source_id = str(source_id)
        for issue in issues:
            if str(issue.get("issue_id")) == source_id:
                return issue, issue_identity(issue)
        # An explicit ID is preferred and must not silently become a fuzzy
        # match.  This keeps a stale lineage visible as unnecessary/invalid.
        return None, ("issue_id", source_id)
    fallback = _record_fallback_identity(record)
    if fallback is None:
        return None, None
    for issue in issues:
        if issue_identity(issue) == fallback:
            return issue, fallback
    return None, fallback


def _find_after_issue(
    source_id: Any, source_identity: tuple[Any, ...] | None, issues: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if source_id is not None and str(source_id).strip():
        source_id = str(source_id)
        for issue in issues:
            if str(issue.get("issue_id")) == source_id:
                return issue
        return None
    if source_identity is None:
        return None
    return next((issue for issue in issues if issue_identity(issue) == source_identity), None)


def _status(record: dict[str, Any], side: str, report: Any) -> str | None:
    value = record.get(f"{side}_status")
    if value is not None:
        return str(value)
    if isinstance(report, dict) and report.get("status") is not None:
        return str(report["status"])
    return None


def _issue(
    context: EvalContext,
    issue_type: str,
    summary: str,
    *,
    repair_id: str | None = None,
    severity: str = "warning",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "issue_id": f"{context.case.case_id}:repair:{repair_id or 'lineage'}:{issue_type}",
        # Repair Effectiveness is an evaluator; keep its issue stage within
        # the existing public issue-stage enum rather than expanding it.
        "stage": "eval",
        "type": issue_type,
        "severity": severity,
        "message": summary,
        "summary": summary,
        "metadata": metadata or {},
        "evidence_ids": [],
        "review_status": "unreviewed",
    }


def _not_applicable(context: EvalContext, reason: str) -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "passed": None,
        "metrics": {},
        "details": {
            "required": False,
            "evaluator_version": EVALUATOR_VERSION,
            "reason": reason,
            "detection_status": "not_evaluable_without_human_gold",
        },
        "issues": [],
        "evidence_ids": [],
    }


def _load_lineage(context: EvalContext, path: Path | None) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    lineage_path = path or context.artifact("repair_lineage")
    if lineage_path is None:
        return None, None, None
    if not lineage_path.is_file():
        return None, lineage_path, f"repair lineage is missing: {lineage_path}"
    try:
        value = _read_json(lineage_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, lineage_path, f"repair lineage is invalid: {type(exc).__name__}: {exc}"
    if isinstance(value, list):
        value = {"repairs": value}
    if not isinstance(value, dict) or not isinstance(value.get("repairs"), list):
        return None, lineage_path, "repair lineage must be an object with a repairs array"
    return value, lineage_path, None


def _write_calibration(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [
        "# Repair Effectiveness Calibration",
        "",
        "Human labels are intentionally left as `pending`; this evaluator does not infer gold labels.",
        "",
        "| Repair | Source issue | Before | After | Auto result | New regressions | Human label | Notes |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| {repair_id} | {source} | {before} | {after} | {result} | {regressions} | pending | {notes} |".format(
                repair_id=record.get("repair_id", ""),
                source=record.get("source_issue_id") or "(none)",
                before=record.get("before_status") or "unknown",
                after=record.get("after_status") or "unknown",
                result=record.get("result", "not_evaluable"),
                regressions=record.get("new_issue_count", 0),
                notes=str(
                    record.get("notes")
                    or ("unnecessary_repair" if record.get("unnecessary_repair") else "")
                ).replace("|", "\\|"),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class RepairEffectivenessAdapter:
    """Evaluate one explicit repair lineage without changing any artifacts."""

    def __init__(
        self,
        lineage_path: str | Path | None = None,
        *,
        severity_weights: dict[str, float] | None = None,
    ) -> None:
        self.lineage_path = Path(lineage_path).resolve() if lineage_path else None
        self.severity_weights = dict(DEFAULT_SEVERITY_WEIGHTS)
        if severity_weights:
            for key, value in severity_weights.items():
                if key in self.severity_weights and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    self.severity_weights[key] = float(value)

    def evaluate_case(self, context: EvalContext) -> dict[str, Any]:
        lineage, lineage_path, error = _load_lineage(context, self.lineage_path)
        if lineage is None:
            if error and lineage_path is not None:
                return {
                    "status": "error",
                    "passed": None,
                    "metrics": {},
                    "details": {"required": False, "evaluator_version": EVALUATOR_VERSION, "reason": error},
                    "issues": [_issue(context, "REPAIR_LINEAGE_INVALID", error, severity="major")],
                    "evidence_ids": [],
                }
            return _not_applicable(context, "no repair lineage is configured")

        records = lineage["repairs"]
        seen_ids: set[str] = set()
        for raw in records:
            if not isinstance(raw, dict) or not str(raw.get("repair_id") or "").strip():
                return {
                    "status": "error",
                    "passed": None,
                    "metrics": {},
                    "details": {"required": False, "evaluator_version": EVALUATOR_VERSION, "reason": "every repair must have a non-empty repair_id"},
                    "issues": [_issue(context, "REPAIR_LINEAGE_INVALID", "every repair must have a non-empty repair_id", severity="major")],
                    "evidence_ids": [],
                }
            repair_id = str(raw["repair_id"])
            if repair_id in seen_ids:
                message = f"duplicate repair_id in lineage: {repair_id}"
                return {
                    "status": "error",
                    "passed": None,
                    "metrics": {},
                    "details": {"required": False, "evaluator_version": EVALUATOR_VERSION, "reason": message},
                    "issues": [_issue(context, "REPAIR_LINEAGE_INVALID", message, repair_id=repair_id, severity="major")],
                    "evidence_ids": [],
                }
            seen_ids.add(repair_id)

        base = lineage_path.parent if lineage_path else context.output_root
        normalized: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        lineage_case_id = lineage.get("case_id")
        if lineage_case_id is not None and str(lineage_case_id) != context.case.case_id:
            issues.append(
                _issue(
                    context,
                    "REPAIR_LINEAGE_INVALID",
                    f"lineage belongs to {lineage_case_id}, not {context.case.case_id}",
                    severity="major",
                )
            )
        resolved_weight = 0.0
        introduced_weight = 0.0
        resolved_count = persistent_count = introduced_count = 0
        regression_repair_count = 0
        minor_regression_repairs = 0
        blocking_regression_repairs = 0
        result_counts: Counter[str] = Counter()
        pass_rounds: list[int] = []
        confirmed_detection_count = false_positive_count = review_pending_count = 0
        unnecessary_count = 0
        gold = lineage.get("detection_gold")
        detected_ids: set[str] = set()
        gold_ids: set[str] = set()
        formal_gold = isinstance(gold, list)
        if formal_gold:
            gold_ids = {str(item) for item in gold if not isinstance(item, dict)}
            gold_ids.update(str(item.get("issue_id")) for item in gold if isinstance(item, dict) and item.get("issue_id") is not None)

        for raw in records:
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            repair_id = str(record["repair_id"])
            case_id = record.get("case_id")
            if case_id is not None and str(case_id) != context.case.case_id:
                issues.append(_issue(context, "REPAIR_LINEAGE_INVALID", f"repair {repair_id} belongs to {case_id}, not {context.case.case_id}", repair_id=repair_id, severity="major"))
            round_value = _number(record.get("round"))
            if round_value is None or round_value < 1 or round_value != int(round_value):
                issues.append(_issue(context, "REPAIR_LINEAGE_INVALID", f"repair {repair_id} has an invalid round", repair_id=repair_id, severity="major"))
                round_number = 0
            else:
                round_number = int(round_value)
            before_report, before_report_path = _load_reference(
                record.get("before_eval_report", record.get("before_report")), base
            )
            after_report, after_report_path = _load_reference(
                record.get("after_eval_report", record.get("after_report")), base
            )
            before_artifact, before_declared_hash = _artifact_reference(record, "before", base)
            after_artifact, after_declared_hash = _artifact_reference(record, "after", base)
            missing_artifact = (
                before_artifact is None
                or not before_artifact.is_file()
                or after_artifact is None
                or not after_artifact.is_file()
            )
            before_actual_hash = _sha256(before_artifact)
            after_actual_hash = _sha256(after_artifact)
            artifact_hash_invalid = bool(
                (before_declared_hash and before_actual_hash != before_declared_hash)
                or (after_declared_hash and after_actual_hash != after_declared_hash)
            )
            not_evaluable = (
                before_report is None
                or after_report is None
                or missing_artifact
                or artifact_hash_invalid
            )
            before_issues = _unique_issues(_issues(before_report))
            after_issues = _unique_issues(_issues(after_report))
            source_issue, source_identity = _find_source_issue(record, before_issues)
            after_source_issue = _find_after_issue(record.get("source_issue_id"), source_identity, after_issues)
            before_keys = {issue_identity(item) for item in before_issues}
            after_keys = {issue_identity(item) for item in after_issues}
            source_key = issue_identity(source_issue) if source_issue else source_identity
            introduced_keys = after_keys - before_keys
            if source_key is not None:
                introduced_keys.discard(source_key)
            introduced_issues = [item for item in after_issues if issue_identity(item) in introduced_keys]
            source_id = record.get("source_issue_id")
            if source_id is not None:
                detected_ids.add(str(source_id))
            if record.get("detection_label") == "false_positive":
                false_positive_count += 1
            elif source_issue is not None:
                confirmed_detection_count += 1
            if not record.get("detection_label"):
                review_pending_count += 1

            before_status = _status(record, "before", before_report)
            after_status = _status(record, "after", after_report)
            result = "not_evaluable"
            if not_evaluable:
                if artifact_hash_invalid:
                    issues.append(_issue(context, "REPAIR_LINEAGE_INVALID", f"repair {repair_id} artifact SHA-256 does not match lineage", repair_id=repair_id, severity="major"))
                issues.append(_issue(context, "REPAIR_ARTIFACT_MISSING", f"repair {repair_id} lacks a usable before/after report or artifact", repair_id=repair_id, severity="major"))
            elif source_issue is None:
                # Unnecessary is a diagnostic flag, not a new result enum. A
                # repair without a confirmed source issue is a failed attempt
                # while remaining separately countable.
                result = "failed"
                unnecessary_count += 1
                issues.append(
                    _issue(
                        context,
                        "REPAIR_UNNECESSARY",
                        f"repair {repair_id} has no confirmed source issue in the before report",
                        repair_id=repair_id,
                        severity="major" if introduced_issues else "warning",
                    )
                )
            elif after_source_issue is None:
                result = "success"
                resolved_count += 1
                resolved_weight += self.severity_weights[_severity(source_issue.get("severity"))]
            else:
                before_rank = _rank(source_issue.get("severity"))
                after_rank = _rank(after_source_issue.get("severity"))
                if after_rank > before_rank:
                    result = "worsened"
                    issues.append(_issue(context, "REPAIR_WORSENED", f"repair {repair_id} increased source issue severity", repair_id=repair_id, severity="major"))
                elif after_rank < before_rank:
                    result = "partial"
                    issues.append(_issue(context, "REPAIR_PARTIAL", f"repair {repair_id} reduced but did not resolve the source issue", repair_id=repair_id))
                else:
                    result = "failed"
                    issues.append(_issue(context, "REPAIR_FAILED", f"repair {repair_id} did not resolve the source issue", repair_id=repair_id))
                persistent_count += 1

            if introduced_issues:
                regression_repair_count += 1
                introduced_count += len(introduced_issues)
                introduced_weight += sum(self.severity_weights[_severity(item.get("severity"))] for item in introduced_issues)
                if any(_rank(item.get("severity")) >= 2 for item in introduced_issues):
                    blocking_regression_repairs += 1
                else:
                    minor_regression_repairs += 1
                has_blocking_regression = any(
                    _rank(item.get("severity")) >= 2 for item in introduced_issues
                )
                issues.append(_issue(context, "REPAIR_REGRESSION", f"repair {repair_id} introduced {len(introduced_issues)} new issue(s)", repair_id=repair_id, severity="major" if has_blocking_regression else "warning"))
            if result in {"success", "partial", "failed", "worsened"} and result == "success":
                pass_rounds.append(round_number)
            result_counts[result] += 1
            normalized.append(
                {
                    **record,
                    "case_id": str(case_id or context.case.case_id),
                    "round": round_number,
                    "before_status": before_status,
                    "after_status": after_status,
                    "result": result,
                    "unnecessary_repair": source_issue is None and not not_evaluable,
                    "resolved_issue_count": 1 if result == "success" else 0,
                    "persistent_issue_count": 1 if result in {"partial", "failed", "worsened"} else 0,
                    "new_issue_count": len(introduced_issues),
                    "source_issue_identity": list(source_key) if source_key is not None else None,
                    "before_report_path": str(before_report_path) if before_report_path else None,
                    "after_report_path": str(after_report_path) if after_report_path else None,
                    "before_artifact_path": str(before_artifact) if before_artifact else None,
                    "after_artifact_path": str(after_artifact) if after_artifact else None,
                    "before_report_sha256": _sha256(before_report_path),
                    "after_report_sha256": _sha256(after_report_path),
                    "before_artifact_sha256": _sha256(before_artifact),
                    "after_artifact_sha256": _sha256(after_artifact),
                    "before_artifact_declared_sha256": before_declared_hash,
                    "after_artifact_declared_sha256": after_declared_hash,
                }
            )

        if formal_gold:
            true_positive = len(detected_ids & gold_ids)
            false_positive = len(detected_ids - gold_ids)
            false_negative = len(gold_ids - detected_ids)
        else:
            true_positive = false_positive = false_negative = None

        attempts = len(records)
        not_evaluable_count = result_counts["not_evaluable"]
        completed = attempts - not_evaluable_count - unnecessary_count
        metrics: dict[str, Any] = {
            "repair_attempt_count": attempts,
            "repair_success_count": result_counts["success"],
            "repair_partial_count": result_counts["partial"],
            "repair_failed_count": result_counts["failed"],
            "repair_worsened_count": result_counts["worsened"],
            "repair_not_evaluable_count": not_evaluable_count,
            "repair_unnecessary_count": unnecessary_count,
            "unnecessary_repair_count": unnecessary_count,
            "repair_success_rate": round(result_counts["success"] / attempts, 6) if attempts else None,
            "resolved_issue_count": resolved_count,
            "persistent_issue_count": persistent_count,
            "introduced_issue_count": introduced_count,
            "new_issue_count": introduced_count,
            "regression_repair_count": regression_repair_count,
            "repair_regression_rate": round(regression_repair_count / completed, 6) if completed > 0 else None,
            "repairs_without_regression": completed - regression_repair_count if completed >= 0 else 0,
            "repairs_with_minor_regression": minor_regression_repairs,
            "repairs_with_blocking_regression": blocking_regression_repairs,
            "net_issue_delta": round(resolved_weight - introduced_weight, 6),
            "resolved_issue_weight": round(resolved_weight, 6),
            "introduced_issue_weight": round(introduced_weight, 6),
            "average_rounds_to_pass": round(sum(pass_rounds) / len(pass_rounds), 6) if pass_rounds else None,
            "max_rounds_to_pass": max(pass_rounds) if pass_rounds else None,
            "confirmed_detection_count": confirmed_detection_count,
            "false_positive_count": false_positive if formal_gold else false_positive_count,
            "review_pending_count": review_pending_count,
            "unobserved_event_count": not_evaluable_count,
        }
        if formal_gold:
            metrics.update(
                {
                    "detection_true_positive_count": true_positive,
                    "detection_false_positive_count": false_positive,
                    "detection_false_negative_count": false_negative,
                    "detection_precision": round(true_positive / (true_positive + false_positive), 6)
                    if true_positive + false_positive
                    else None,
                    "detection_recall": round(true_positive / (true_positive + false_negative), 6)
                    if true_positive + false_negative
                    else None,
                }
            )

        calibration_path = context.output_root / "repair_calibration.md"
        _write_calibration(calibration_path, normalized)
        provenance = {
            "evaluator_version": EVALUATOR_VERSION,
            "lineage_path": str(lineage_path) if lineage_path else None,
            "lineage_sha256": _sha256(lineage_path),
            "severity_weights": dict(self.severity_weights),
            "issue_identity": "issue_id preferred; fallback stage/type/slide/element_id/event_id/question_id",
            "before_after_evaluator": "same report evaluator output supplied by lineage",
            "candidate_commit": context.candidate_commit,
            "run_id": context.run_id,
        }
        details = {
            "required": False,
            "evaluator_version": EVALUATOR_VERSION,
            "detection_status": "formal_gold_available" if formal_gold else "review_pending_without_human_gold",
            "repairs": normalized,
            "calibration_path": str(calibration_path),
            "provenance": provenance,
        }
        blocking = any(item.get("severity") == "major" for item in issues)
        return {
            "status": "failed" if blocking else "ok",
            "passed": not blocking,
            "metrics": metrics,
            "details": details,
            "issues": issues,
            "evidence_ids": [],
        }


def evaluate_repair_effectiveness(context: EvalContext) -> dict[str, Any]:
    adapter = context.repair_effectiveness
    if adapter is None:
        return _not_applicable(context, "Repair Effectiveness evaluator is not configured")
    return adapter.evaluate_case(context)


evaluate_repair_effectiveness.evaluator_name = EVALUATOR_NAME
