"""Local candidate repair orchestration with targeted re-evaluation.

This module coordinates existing repair functions; it does not implement a
new model agent. A repair always starts from a copied canonical artifact in a
unique candidate directory. Only an accepted candidate is copied to the
separate accepted-artifacts directory, so the canonical input remains intact.
"""

from __future__ import annotations

import builtins
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .lineage import RepairLineageWriter

RepairFn = Callable[[Path], Path | None]
ReEvalFn = Callable[[Path, list[str], Path], dict[str, Any]]

SEVERITY_RANK = {
    "info": 0,
    "minor": 1,
    "warning": 1,
    "major": 2,
    "error": 2,
    "critical": 3,
}


@dataclass(frozen=True)
class RepairRoute:
    family: str
    strategy: str | None
    evaluators: tuple[str, ...]
    supported: bool
    reason: str | None = None


@dataclass(frozen=True)
class AcceptanceDecision:
    status: str
    target_issue_resolved: bool
    no_new_blocking_regression: bool
    repair_round_allowed: bool
    budget_not_exceeded: bool
    blocking_regressions: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass
class RepairResult:
    repair_id: str
    status: str
    route: RepairRoute
    candidate_artifact: Path | None
    accepted_artifact: Path | None
    before_report: dict[str, Any]
    after_report: dict[str, Any] | None
    decision: AcceptanceDecision | None
    lineage_record: dict[str, Any]


def _issue_identity(issue: dict[str, Any]) -> tuple[Any, ...]:
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
    location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
    return (
        "fallback",
        str(issue.get("stage") or "eval"),
        str(issue.get("type") or issue.get("category") or "EVAL_ISSUE"),
        issue.get("slide", location.get("slide")),
        issue.get("element_id", location.get("element_id")),
        issue.get("event_id", location.get("event_id")),
        issue.get("question_id", location.get("question_id")),
    )


def _severity_rank(issue: dict[str, Any]) -> int:
    return SEVERITY_RANK.get(str(issue.get("severity") or "warning").lower(), 1)


def _issues(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(report, dict) or not isinstance(report.get("issues"), list):
        return []
    return [item for item in report["issues"] if isinstance(item, dict)]


def _issue_label(issue: dict[str, Any]) -> str:
    return str(issue.get("issue_id") or issue.get("type") or "EVAL_ISSUE")


def route_issue(issue: dict[str, Any]) -> RepairRoute:
    """Resolve a static, auditable issue-family repair policy."""

    issue_type = str(issue.get("type") or issue.get("category") or "").upper()
    if issue_type.startswith("LAYOUT_") or issue_type in {"OVERFLOW", "OVERLAP"}:
        evaluators = ["layout", "structure"]
        if bool((issue.get("metadata") or {}).get("text_changed")):
            evaluators.append("source_fidelity")
        return RepairRoute("layout", "deterministic_css", tuple(evaluators), True)
    if issue_type.startswith("STORYBOARD_") or issue_type.startswith("STRUCTURE_"):
        return RepairRoute(
            "storyboard",
            "storyboard_repair",
            ("structure", "source_fidelity", "knowledge_grounding", "pedagogy"),
            True,
        )
    if issue_type.startswith("ANIMATION_TARGET_") or issue_type in {"TARGET_MISS", "ANIMATION_TARGET_MISS"}:
        return RepairRoute("animation_target", "animation_runtime", ("animation_runtime", "structure"), True)
    if issue_type.startswith("AUDIO_") or issue_type in {"TTS_SUBTITLE", "AUDIO_INTEGRITY"}:
        return RepairRoute("audio", None, ("audio_integrity",), False, "no automatic local audio repair is registered")
    return RepairRoute("unknown", None, (), False, "issue family is not supported by the local repair policy")


def decide_acceptance(
    before_report: dict[str, Any],
    after_report: dict[str, Any] | None,
    target_issue: dict[str, Any],
    *,
    round: int,
    max_rounds: int,
    budget_not_exceeded: bool = True,
) -> AcceptanceDecision:
    """Apply the fail-closed acceptance gate to two report snapshots."""

    reasons: list[str] = []
    blocking: list[str] = []
    target_identity = _issue_identity(target_issue)
    before_issues = _issues(before_report)
    after_issues = _issues(after_report)
    after_by_identity = {_issue_identity(item): item for item in after_issues}
    target_resolved = target_identity not in after_by_identity
    if not target_resolved:
        reasons.append("target issue remains in after report")

    before_identities = {_issue_identity(item) for item in before_issues}
    introduced = [
        item for item in after_issues
        if _issue_identity(item) not in before_identities and _issue_identity(item) != target_identity
    ]
    for item in introduced:
        if _severity_rank(item) >= 2:
            blocking.append(f"new issue: {_issue_label(item)}")

    before_gates = before_report.get("gates", {}) if isinstance(before_report, dict) else {}
    after_gates = after_report.get("gates", {}) if isinstance(after_report, dict) else {}
    if isinstance(before_gates, dict) and isinstance(after_gates, dict):
        for name, value in before_gates.items():
            if value is True and after_gates.get(name) is not True:
                blocking.append(f"gate regressed: {name}")
    if blocking:
        reasons.append("blocking regression detected")
        reasons.extend(blocking)
    round_allowed = isinstance(round, int) and round >= 1 and round <= max_rounds
    if not round_allowed:
        reasons.append("repair round exceeds max_rounds")
    if not budget_not_exceeded:
        reasons.append("repair budget exceeded")
    if after_report is None:
        reasons.append("targeted re-evaluation did not produce a report")
        target_resolved = False

    accepted = target_resolved and not blocking and round_allowed and budget_not_exceeded
    return AcceptanceDecision(
        status="accepted" if accepted else "rolled_back",
        target_issue_resolved=target_resolved,
        no_new_blocking_regression=not blocking,
        repair_round_allowed=round_allowed,
        budget_not_exceeded=budget_not_exceeded,
        blocking_regressions=tuple(blocking),
        reasons=tuple(reasons),
    )


class RepairOrchestrator:
    """Coordinate one local candidate repair and targeted re-evaluation."""

    def __init__(
        self,
        *,
        canonical_root: str | Path,
        work_root: str | Path,
        case_id: str,
        run_id: str,
        lineage_writer: RepairLineageWriter | None = None,
        max_rounds: int = 3,
    ) -> None:
        self.canonical_root = Path(canonical_root).resolve()
        self.work_root = Path(work_root).resolve()
        self.case_id = case_id
        self.run_id = run_id
        self.max_rounds = max(1, int(max_rounds))
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.lineage = lineage_writer or RepairLineageWriter(
            self.work_root / "repair_lineage.json",
            case_id=case_id,
            run_id=run_id,
        )

    def execute(
        self,
        issue: dict[str, Any],
        *,
        artifact: str | Path,
        before_report: dict[str, Any],
        repair_fn: RepairFn,
        re_evaluate: ReEvalFn,
        round: int = 1,
        budget_not_exceeded: bool = True,
        model: str = "N/A",
        token: int | float | None = None,
    ) -> RepairResult:
        route = route_issue(issue)
        repair_id = self.lineage.new_id("repair")
        candidate_dir = self.work_root / "repair_candidates" / repair_id
        before_dir = candidate_dir / "before"
        candidate_subdir = candidate_dir / "candidate"
        before_dir.mkdir(parents=True, exist_ok=True)
        candidate_subdir.mkdir(parents=True, exist_ok=True)
        canonical = (self.canonical_root / Path(artifact)).resolve()
        if self.canonical_root not in canonical.parents or not canonical.is_file():
            raise FileNotFoundError(f"canonical artifact is outside root or missing: {canonical}")
        before_artifact = before_dir / canonical.name
        candidate_artifact = candidate_subdir / canonical.name
        shutil.copy2(canonical, before_artifact)
        shutil.copy2(canonical, candidate_artifact)
        started = time.monotonic()
        after_report: dict[str, Any] | None = None
        accepted_artifact: Path | None = None
        decision: AcceptanceDecision | None = None
        outcome = "failed"
        notes: str | None = None
        after_report_path = candidate_dir / "after_eval_report.json"
        before_report_path = candidate_dir / "before_eval_report.json"
        before_report_path.write_text(json.dumps(before_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        if not route.supported:
            notes = f"unsupported: {route.reason or 'repair route unsupported'}"
            decision = AcceptanceDecision(
                status="rolled_back",
                target_issue_resolved=False,
                no_new_blocking_regression=True,
                repair_round_allowed=round <= self.max_rounds,
                budget_not_exceeded=budget_not_exceeded,
                reasons=(notes,),
            )
        elif round > self.max_rounds:
            notes = "repair round exceeds max_rounds"
            decision = decide_acceptance(
                before_report,
                None,
                issue,
                round=round,
                max_rounds=self.max_rounds,
                budget_not_exceeded=budget_not_exceeded,
            )
        else:
            try:
                repaired = repair_fn(candidate_artifact)
                if isinstance(repaired, (str, Path)):
                    repaired_path = Path(repaired).resolve()
                    if candidate_dir not in repaired_path.parents or not repaired_path.is_file():
                        raise ValueError("repair function returned an artifact outside candidate workspace")
                    candidate_artifact = repaired_path
                after_report = re_evaluate(candidate_artifact, list(route.evaluators), candidate_dir)
                if not isinstance(after_report, dict):
                    raise TypeError("targeted re-evaluation must return a report object")
                after_report_path.write_text(json.dumps(after_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                decision = decide_acceptance(
                    before_report,
                    after_report,
                    issue,
                    round=round,
                    max_rounds=self.max_rounds,
                    budget_not_exceeded=budget_not_exceeded,
                )
                if decision.status == "accepted":
                    accepted_artifact = self.work_root / "accepted_artifacts" / repair_id / candidate_artifact.name
                    accepted_artifact.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate_artifact, accepted_artifact)
                    outcome = "succeeded"
                else:
                    outcome = "rolled_back"
            except Exception as exc:  # noqa: BLE001 - lineage must retain failed attempts
                notes = f"{type(exc).__name__}: {exc}"
                decision = AcceptanceDecision(
                    status="rolled_back",
                    target_issue_resolved=False,
                    no_new_blocking_regression=True,
                    repair_round_allowed=round <= self.max_rounds,
                    budget_not_exceeded=budget_not_exceeded,
                    reasons=(notes,),
                )
                outcome = "failed"

        record = self.lineage.append_record(
            repair_id=repair_id,
            case_id=self.case_id,
            run_id=self.run_id,
            source_issue_id=(str(issue["issue_id"]) if issue.get("issue_id") is not None else None),
            issue_type=str(issue.get("type") or issue.get("category") or "EVAL_ISSUE"),
            stage=str(issue.get("stage") or "eval"),
            severity=str(issue.get("severity") or "warning"),
            repair_strategy=route.strategy or "manual",
            round=round,
            before_artifact=before_artifact,
            after_artifact=candidate_artifact,
            before_eval_report=before_report_path,
            after_eval_report=after_report_path if after_report is not None else None,
            model=model,
            token=token,
            latency_sec=builtins.round(time.monotonic() - started, 6),
            result=outcome,
            provenance={
                "orchestrator": "textbook2video.repair.orchestrator",
                "route_family": route.family,
                "target_issue_id": issue.get("issue_id"),
            },
            candidate_dir=candidate_dir,
            accepted_artifact=accepted_artifact,
            targeted_evaluators=list(route.evaluators),
            notes=notes or ("; ".join(decision.reasons) if decision and decision.reasons else None),
        )
        return RepairResult(
            repair_id=repair_id,
            status=decision.status if decision else "rolled_back",
            route=route,
            candidate_artifact=candidate_artifact,
            accepted_artifact=accepted_artifact,
            before_report=before_report,
            after_report=after_report,
            decision=decision,
            lineage_record=record,
        )


__all__ = [
    "AcceptanceDecision",
    "RepairOrchestrator",
    "RepairResult",
    "RepairRoute",
    "decide_acceptance",
    "route_issue",
]
