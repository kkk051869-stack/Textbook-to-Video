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
from dataclasses import dataclass, replace
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
class AVSemanticCapability:
    """Whether a candidate can be evaluated by the canonical AV adapter.

    This is an input-presence check only.  It never computes an AV score or
    manufactures an evaluator result; the canonical adapter remains the only
    source of AV evidence.
    """

    available: bool
    missing_inputs: tuple[str, ...] = ()
    inputs: tuple[tuple[str, str], ...] = ()

    @property
    def status(self) -> str:
        return "available" if self.available else "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "missing_inputs": list(self.missing_inputs),
            "inputs": dict(self.inputs),
        }


@dataclass(frozen=True)
class RepairRoute:
    family: str
    strategy: str | None
    evaluators: tuple[str, ...]
    supported: bool
    reason: str | None = None
    av_semantic_capability: AVSemanticCapability | None = None


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


_AV_ARTIFACT_NAMES = {
    "timed_storyboard": ("storyboard_timed.json", "storyboard.timed.json"),
    "sentence_cues": ("sentence_cues.json", "sentence-cues.json"),
    "animation_trace": (
        "animation_trace.json",
        "animation-trace.json",
        "animation_trace.raw.json",
        "raw_animation_trace.json",
    ),
}


def _first_file(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _sentence_starts(value: Any) -> dict[str, float]:
    """Read the supported flat and sentence-audio cue sidecar shapes."""

    result: dict[str, float] = {}

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        sentence_id = item.get("sentence_id", item.get("id", item.get("matched_sentence_id")))
        start = None
        for key in ("sentence_start_sec", "start_sec", "start", "at_sec"):
            start = _finite_number(item.get(key))
            if start is not None:
                break
        if sentence_id is not None and start is not None:
            result[str(sentence_id)] = start
        for key in ("segments", "sentences", "cues", "items"):
            child = item.get(key)
            if isinstance(child, (dict, list)):
                visit(child)
        # Also accept the canonical evaluator's {sentence_id: start_sec} form.
        for key, child in item.items():
            if key in {"schema_version", "segments", "sentences", "cues", "items"}:
                continue
            number = _finite_number(child)
            if number is not None:
                result[str(key)] = number

    visit(value)
    return result


def _timed_plan_events(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten enough of the canonical timed storyboard shape for detection."""

    events: list[dict[str, Any]] = []
    segments = storyboard.get("segments")
    if not isinstance(segments, list):
        return events
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        timeline = segment.get("timeline")
        animations = segment.get("animations")
        timeline_items = timeline if isinstance(timeline, list) else []
        animation_items = animations if isinstance(animations, list) else []
        items = timeline_items or animation_items
        by_target: dict[str, list[dict[str, Any]]] = {}
        for item in animation_items:
            if isinstance(item, dict) and item.get("target") is not None:
                by_target.setdefault(str(item["target"]), []).append(item)
        occurrences: dict[str, int] = {}
        for raw in items:
            if not isinstance(raw, dict):
                continue
            event = dict(raw)
            target = str(event.get("target", ""))
            occurrences[target] = occurrences.get(target, 0) + 1
            companions = by_target.get(target, [])
            if not event.get("event_id") and len(companions) >= occurrences[target]:
                event = {**companions[occurrences[target] - 1], **event}
            events.append(event)
    return events


def detect_av_semantic_capability(artifacts_root: str | Path) -> AVSemanticCapability:
    """Inspect candidate files without running or fabricating the AV evaluator."""

    root = Path(artifacts_root).resolve()
    missing: list[str] = []
    paths: dict[str, Path] = {}
    for role, names in _AV_ARTIFACT_NAMES.items():
        path = _first_file(root, names)
        if path is None:
            # The canonical evaluator accepts sentence_start_sec embedded in
            # each bound timed event, so the cue sidecar is optional here.
            if role != "sentence_cues":
                missing.append(role)
        else:
            paths[role] = path
    timed_path = paths.get("timed_storyboard")
    cues_path = paths.get("sentence_cues")
    trace_path = paths.get("animation_trace")
    if missing:
        return AVSemanticCapability(False, tuple(missing))

    try:
        timed = _read_json_file(timed_path)  # type: ignore[arg-type]
        cues = (
            _sentence_starts(_read_json_file(cues_path))
            if cues_path is not None
            else {}
        )
        trace = _read_json_file(trace_path)  # type: ignore[arg-type]
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return AVSemanticCapability(False, ("valid_av_input_files",))

    if not isinstance(timed, dict):
        return AVSemanticCapability(False, ("timed_storyboard_object",))
    plan = _timed_plan_events(timed)
    bound = [
        event
        for event in plan
        if str(event.get("matched_sentence_id") or "").strip()
        or str(event.get("trigger_source") or "") == "sentence_cue"
    ]
    if not bound:
        return AVSemanticCapability(False, ("semantic_sentence_binding",))
    for event in bound:
        sentence_id = str(event.get("matched_sentence_id") or "").strip()
        start = next(
            (
                _finite_number(event.get(key))
                for key in ("sentence_start_sec",)
                if _finite_number(event.get(key)) is not None
            ),
            None,
        )
        if start is None and sentence_id:
            start = cues.get(sentence_id)
        if start is None:
            return AVSemanticCapability(False, ("sentence_timing_metadata",))
        if all(
            _finite_number(event.get(key)) is None
            for key in ("planned_trigger_sec", "trigger_at_sec", "at_sec")
        ):
            return AVSemanticCapability(False, ("timed_storyboard_trigger_metadata",))

    if isinstance(trace, dict):
        trace_events = trace.get("events")
    elif isinstance(trace, list):
        trace_events = trace
    else:
        trace_events = None
    if not isinstance(trace_events, list) or not any(isinstance(item, dict) for item in trace_events):
        return AVSemanticCapability(False, ("usable_animation_trace",))

    return AVSemanticCapability(
        True,
        inputs=tuple((role, str(path)) for role, path in sorted(paths.items())),
    )


def _stage_av_artifacts(source_root: Path, destination_root: Path) -> None:
    """Copy existing AV sidecars into the isolated candidate workspace."""

    destination_root.mkdir(parents=True, exist_ok=True)
    for names in _AV_ARTIFACT_NAMES.values():
        for name in names:
            source = source_root / name
            destination = destination_root / name
            if source.is_file() and not destination.exists():
                shutil.copy2(source, destination)


def _add_av_capability(route: RepairRoute, candidate_root: Path) -> RepairRoute:
    if route.family != "storyboard":
        return route
    capability = detect_av_semantic_capability(candidate_root)
    evaluators = list(route.evaluators)
    if capability.available and "av_semantic_alignment" not in evaluators:
        evaluators.append("av_semantic_alignment")
    return replace(
        route,
        evaluators=tuple(evaluators),
        av_semantic_capability=capability,
    )


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
    required_evaluators: tuple[str, ...] = (),
) -> AcceptanceDecision:
    """Apply the fail-closed acceptance gate to two report snapshots."""

    reasons: list[str] = []
    blocking: list[str] = []
    target_identity = _issue_identity(target_issue)
    before_issues = _issues(before_report)
    after_issues = _issues(after_report)
    before_gates = before_report.get("gates", {}) if isinstance(before_report, dict) else {}
    after_gates = after_report.get("gates", {}) if isinstance(after_report, dict) else {}
    after_status = after_report.get("status") if isinstance(after_report, dict) else None
    after_report_complete = (
        isinstance(after_report, dict)
        and isinstance(after_report.get("status"), str)
        and isinstance(after_report.get("gates"), dict)
        and isinstance(after_report.get("issues"), list)
        and bool(after_gates)
    )
    if not after_report_complete:
        blocking.append("targeted re-evaluation report is incomplete")
        reasons.append("targeted re-evaluation did not provide usable evaluator gates")
    elif after_status not in {"pass", "pass_with_warnings"}:
        blocking.append(f"targeted re-evaluation status is not successful: {after_status}")
        reasons.append("targeted re-evaluation reported failure")
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

    if isinstance(before_gates, dict) and isinstance(after_gates, dict):
        for name, value in before_gates.items():
            if value is True and after_gates.get(name) is not True:
                blocking.append(f"gate regressed: {name}")
    after_evaluators = after_report.get("evaluators", {}) if isinstance(after_report, dict) else {}
    for evaluator_name in required_evaluators:
        evaluator_result = (
            after_evaluators.get(evaluator_name)
            if isinstance(after_evaluators, dict)
            else None
        )
        if not isinstance(evaluator_result, dict):
            blocking.append(f"required targeted evaluator missing: {evaluator_name}")
            continue
        if evaluator_result.get("passed") is not True or evaluator_result.get("status") in {
            "unavailable",
            "not_evaluable",
            "skipped",
            "error",
        }:
            blocking.append(f"required targeted evaluator did not pass: {evaluator_name}")
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
                if route.family == "storyboard":
                    _stage_av_artifacts(canonical.parent, candidate_subdir)
                repaired = repair_fn(candidate_artifact)
                if isinstance(repaired, (str, Path)):
                    repaired_path = Path(repaired).resolve()
                    if candidate_dir not in repaired_path.parents or not repaired_path.is_file():
                        raise ValueError("repair function returned an artifact outside candidate workspace")
                    candidate_artifact = repaired_path
                if route.family == "storyboard":
                    _stage_av_artifacts(canonical.parent, candidate_artifact.parent)
                    route = _add_av_capability(route, candidate_artifact.parent)
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
                    required_evaluators=(
                        ("av_semantic_alignment",)
                        if route.av_semantic_capability is not None
                        and route.av_semantic_capability.available
                        else ()
                    ),
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
                "targeted_re_evaluation": {
                    "evaluators": list(route.evaluators),
                    "av_semantic_alignment": (
                        route.av_semantic_capability.to_dict()
                        if route.av_semantic_capability is not None
                        else None
                    ),
                },
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
    "AVSemanticCapability",
    "detect_av_semantic_capability",
    "decide_acceptance",
    "route_issue",
]
