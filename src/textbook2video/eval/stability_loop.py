"""Executable local end-to-end stability loop demo.

The demo creates an isolated candidate case under the requested output
directory.  It uses the real evaluator runner, the real Storyboard production
repair boundary, the real RepairOrchestrator, repair-effectiveness evaluator,
and regression replay.  Model behavior is supplied by deterministic local
functions; no network client is imported or called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Sequence

from .dataset import load_case
from .evaluators.content import evaluate_knowledge_grounding, evaluate_source_fidelity
from .evaluators.layout import evaluate_layout
from .evaluators.pedagogy import evaluate_pedagogy
from .evaluators.repair_effectiveness import RepairEffectivenessAdapter
from .evaluators.structure import evaluate_structure
from .runner import run_case
from .stability import run_repeated
from ..animation_gen import run_layout_qa
from ..pipeline.checks import validate_storyboard
from ..repair.orchestrator import RepairOrchestrator
from ..repair.production import execute_layout_repair, repair_storyboard_candidate


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_EVALUATORS = [
    evaluate_structure,
    evaluate_source_fidelity,
    evaluate_knowledge_grounding,
    evaluate_pedagogy,
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _storyboard(*, valid: bool = False, narration: str = "core") -> dict[str, Any]:
    element: dict[str, Any] = {"id": "body", "type": "text"}
    if valid:
        element["text"] = "A repaired explanation."
    return {
        "lesson_title": "Local stability loop",
        "metadata": {"total_slides": 1},
        "segments": [{
            "id": 1,
            "visual_type": "definition",
            "narration": narration,
            "elements": [element],
        }],
    }


def _make_case(root: Path, *, case_id: str, with_core: bool) -> tuple[Any, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.json"
    annotation = root / "annotation.json"
    storyboard = root / "storyboard.json"
    source.write_text(
        json.dumps({"paragraphs": [{"id": "p1", "text": "core"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    annotation.write_text(
        json.dumps(
            {
                "core_concepts": (
                    [{
                        "id": "c1",
                        "statement": "core",
                        "must_mention_terms": ["core"],
                        "evidence_paragraphs": ["p1"],
                    }]
                    if with_core
                    else []
                ),
                "required_images": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storyboard.write_text(json.dumps(_storyboard(), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = root / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": case_id,
                "lesson_id": f"{case_id}-lesson",
                "status": "candidate",
                "dataset_version": "local-stability-fixture-v1",
                "source": {"files": [{
                    "role": "source_json",
                    "path": source.name,
                    "sha256": _sha256(source),
                }]},
                "annotation": {
                    "role": "annotation",
                    "path": annotation.name,
                    "sha256": _sha256(annotation),
                },
                "candidate_artifacts": {"storyboard": storyboard.name},
                "metadata": {"config": {"renderer": "local-deterministic"}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return load_case(manifest), storyboard


def _run_targeted(case: Any, artifacts: Path, output: Path, run_id: str) -> dict[str, Any]:
    return run_case(
        case,
        run_id=run_id,
        artifacts_root=artifacts,
        output_root=output,
        evaluators=TARGET_EVALUATORS,
        repo_root=REPO_ROOT,
    )


def _local_review(
    data: dict[str, Any],
    _lesson_plan: dict[str, Any] | None,
    _model: str | None,
) -> dict[str, Any]:
    validation = validate_storyboard(data)
    return {
        "pass": validation.ok,
        "severity": "pass" if validation.ok else "major",
        "issues": [{"type": "STORYBOARD_INVALID", "message": item} for item in validation.errors],
        "summary": "local deterministic review",
    }


def _repair_storyboard(
    data: dict[str, Any],
    _review: dict[str, Any],
    _lesson_plan: dict[str, Any] | None,
    _model: str | None,
) -> dict[str, Any]:
    repaired = deepcopy(data)
    repaired["segments"][0]["elements"][0]["text"] = "A repaired explanation."
    return repaired


def _summary(result: Any) -> dict[str, Any]:
    return {
        "repair_id": result.repair_id,
        "status": result.status,
        "route": {
            "family": result.route.family,
            "strategy": result.route.strategy,
            "evaluators": list(result.route.evaluators),
        },
        "candidate_artifact": str(result.candidate_artifact) if result.candidate_artifact else None,
        "accepted_artifact": str(result.accepted_artifact) if result.accepted_artifact else None,
        "before_issue_types": [item.get("type") for item in result.before_report.get("issues", [])],
        "after_issue_types": [item.get("type") for item in (result.after_report or {}).get("issues", [])],
        "decision": {
            "target_issue_resolved": result.decision.target_issue_resolved if result.decision else False,
            "no_new_blocking_regression": result.decision.no_new_blocking_regression if result.decision else False,
            "reasons": list(result.decision.reasons) if result.decision else [],
        },
        "lineage_path": result.lineage_record.get("candidate_dir"),
    }


def _run_storyboard_accept(output: Path) -> dict[str, Any]:
    case, canonical_storyboard = _make_case(
        output / "case-accept",
        case_id="local-accept",
        with_core=False,
    )
    canonical = canonical_storyboard.parent
    original = canonical_storyboard.read_bytes()
    before = _run_targeted(case, canonical, output / "accept" / "before-eval", "accept-before")
    issue = next(item for item in before["issues"] if item["type"] == "STORYBOARD_INVALID")
    work = output / "accept" / "repair-work"
    orchestrator = RepairOrchestrator(
        canonical_root=canonical,
        work_root=work,
        case_id=case.case_id,
        run_id="accept-run",
    )

    def repair(path: Path) -> Path:
        return repair_storyboard_candidate(
            path,
            model="local-deterministic",
            review_fn=_local_review,
            repair_fn=_repair_storyboard,
        )

    def re_evaluate(path: Path, evaluator_names: list[str], candidate_dir: Path) -> dict[str, Any]:
        if evaluator_names != ["structure", "source_fidelity", "knowledge_grounding", "pedagogy"]:
            raise ValueError(f"unexpected targeted evaluator route: {evaluator_names}")
        return _run_targeted(
            case,
            path.parent,
            candidate_dir / "targeted-re-eval",
            "accept-targeted",
        )

    result = orchestrator.execute(
        issue,
        artifact=canonical_storyboard.name,
        before_report=before,
        repair_fn=repair,
        re_evaluate=re_evaluate,
        model="local-deterministic",
    )
    if result.status != "accepted" or result.accepted_artifact is None:
        raise RuntimeError(f"local accept demo did not accept candidate: {result.status}")
    if canonical_storyboard.read_bytes() != original:
        raise RuntimeError("accept demo mutated canonical artifact")

    effect_output = output / "accept" / "repair-effectiveness-eval"
    effectiveness = run_case(
        case,
        run_id="accept-effectiveness",
        artifacts_root=result.candidate_artifact.parent,
        output_root=effect_output,
        evaluators=[evaluate_structure],
        repair_effectiveness=RepairEffectivenessAdapter(work / "repair_lineage.json"),
        repo_root=REPO_ROOT,
    )
    effect_result = effectiveness["evaluators"]["repair_effectiveness"]
    if effect_result["metrics"]["repair_success_count"] != 1:
        raise RuntimeError("repair effectiveness did not confirm the accepted repair")

    promoted_path = output / "regression" / "local-accept.json"
    from .regression_promotion import promote_failure, replay_regression_fixture

    promoted = promote_failure(
        case_id=case.case_id,
        issue=issue,
        input_conditions={"repair_id": result.repair_id, "artifact": "storyboard.json"},
        expected_invariants=[{"evaluator": "structure", "must_pass": True}],
        evaluator="structure",
        confirmed=True,
        output_path=promoted_path,
        replay={
            "kind": "storyboard",
            "fault_storyboard": _storyboard(valid=False),
            "repaired_storyboard": json.loads(result.candidate_artifact.read_text(encoding="utf-8")),
        },
    )
    replay_result = replay_regression_fixture(promoted_path)
    replay_path = promoted_path.with_name("local-accept-replay.json")
    replay_path.write_text(json.dumps(replay_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not replay_result["passed"]:
        raise RuntimeError("promoted regression fixture did not pass replay contract")

    summary = _summary(result)
    summary.update({
        "case_manifest": str(case.manifest_path),
        "before_eval_report": str(output / "accept" / "before-eval" / "eval_report.json"),
        "after_eval_report": result.lineage_record.get("after_eval_report"),
        "repair_lineage": str(work / "repair_lineage.json"),
        "repair_effectiveness_report": str(effect_output / "eval_report.json"),
        "repair_effectiveness": effect_result,
        "promoted_regression_fixture": str(promoted_path),
        "regression_replay_report": str(replay_path),
        "regression_replay": replay_result,
        "canonical_unchanged": True,
    })
    (output / "accept" / "accept_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _run_storyboard_rollback(output: Path) -> dict[str, Any]:
    case, canonical_storyboard = _make_case(
        output / "case-rollback",
        case_id="local-rollback",
        with_core=True,
    )
    canonical = canonical_storyboard.parent
    original = canonical_storyboard.read_bytes()
    before = _run_targeted(case, canonical, output / "rollback" / "before-eval", "rollback-before")
    issue = next(item for item in before["issues"] if item["type"] == "STORYBOARD_INVALID")

    def regressing_repair(
        data: dict[str, Any],
        review: dict[str, Any],
        lesson_plan: Any,
        model: Any,
    ) -> dict[str, Any]:
        repaired = _repair_storyboard(data, review, lesson_plan, model)
        repaired["segments"][0]["narration"] = "regression removed the annotated concept"
        return repaired

    def repair(path: Path) -> Path:
        return repair_storyboard_candidate(
            path,
            model="local-deterministic",
            review_fn=_local_review,
            repair_fn=regressing_repair,
        )

    def re_evaluate(path: Path, _evaluator_names: list[str], candidate_dir: Path) -> dict[str, Any]:
        return _run_targeted(case, path.parent, candidate_dir / "targeted-re-eval", "rollback-targeted")

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=output / "rollback" / "repair-work",
        case_id=case.case_id,
        run_id="rollback-run",
    ).execute(
        issue,
        artifact=canonical_storyboard.name,
        before_report=before,
        repair_fn=repair,
        re_evaluate=re_evaluate,
    )
    if result.status != "rolled_back" or canonical_storyboard.read_bytes() != original:
        raise RuntimeError("local rollback demo did not preserve canonical artifact")
    if result.after_report is None or not any(
        item.get("severity") == "error" for item in result.after_report.get("issues", [])
    ):
        raise RuntimeError("local rollback demo lacks an actual blocking evaluator regression")

    summary = _summary(result)
    summary.update({
        "case_manifest": str(case.manifest_path),
        "before_eval_report": str(output / "rollback" / "before-eval" / "eval_report.json"),
        "after_eval_report": result.lineage_record.get("after_eval_report"),
        "repair_lineage": str(output / "rollback" / "repair-work" / "repair_lineage.json"),
        "canonical_unchanged": True,
        "blocking_regression_issue_types": [
            item.get("type") for item in result.after_report.get("issues", [])
            if item.get("severity") == "error"
        ],
    })
    (output / "rollback" / "rollback_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _run_repeated(case: Any, accepted_artifact: str | Path, output: Path, repeats: int) -> dict[str, Any]:
    source = json.loads(Path(accepted_artifact).read_text(encoding="utf-8"))

    def run_variant(index: int, run_id: str, *, flapping: bool = False) -> dict[str, Any]:
        artifacts = output / ("flapping-artifacts" if flapping else "stable-artifacts") / run_id
        artifacts.mkdir(parents=True, exist_ok=True)
        value = deepcopy(source)
        if flapping and index == 3:
            value["segments"][0]["elements"][0].pop("text", None)
        elif not flapping and index % 2 == 0:
            value["segments"][0].pop("audio_duration_sec", None)
        else:
            value["segments"][0]["audio_duration_sec"] = 2.0
        storyboard = artifacts / "storyboard.json"
        storyboard.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_case(
            case,
            run_id=run_id,
            artifacts_root=artifacts,
            output_root=output / ("flapping-reports" if flapping else "stable-reports") / run_id,
            evaluators=[evaluate_structure],
            repo_root=REPO_ROOT,
        )

    stable = run_repeated(
        repeats,
        lambda index, run_id: run_variant(index, run_id),
        run_id_prefix="stable",
        output_dir=output / "stable",
    )
    flapping = run_repeated(
        max(5, repeats),
        lambda index, run_id: run_variant(index, run_id, flapping=True),
        run_id_prefix="flip",
        output_dir=output / "flapping",
    )
    if not stable["stable_pass_at_n"] or stable["metrics"]["structure.warning_count"]["std"] <= 0:
        raise RuntimeError("stable repeated executor did not produce stable pass plus metric variation")
    if flapping["stable_pass_at_n"] or flapping["gates"]["structure"]["flip_count"] < 2:
        raise RuntimeError("flapping repeated executor did not capture the third-run gate flip")
    return {
        "stable": stable,
        "flapping": flapping,
        "stable_report": str(output / "stable" / "stability_report.json"),
        "flapping_report": str(output / "flapping" / "stability_report.json"),
    }


def _make_layout_case(layout: Path, canonical: Path) -> Any:
    source = layout / "source.json"
    annotation = layout / "annotation.json"
    storyboard = layout / "storyboard.json"
    source.write_text(
        json.dumps({"paragraphs": [{"id": "p1", "text": "layout"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    annotation.write_text(json.dumps({"required_images": []}, ensure_ascii=False), encoding="utf-8")
    storyboard.write_text(
        json.dumps(_storyboard(valid=True, narration="layout"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = layout / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "local-layout",
                "lesson_id": "local-layout-lesson",
                "status": "candidate",
                "dataset_version": "local-stability-fixture-v1",
                "source": {"files": [{
                    "role": "source_json",
                    "path": source.name,
                    "sha256": _sha256(source),
                }]},
                "annotation": {
                    "role": "annotation",
                    "path": annotation.name,
                    "sha256": _sha256(annotation),
                },
                "candidate_artifacts": {
                    "html": canonical.name,
                    "layout_report": "layout-report.json",
                    "layout_report_1366": "layout-report-1366x768.json",
                    "storyboard": storyboard.name,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return load_case(manifest)


def _run_layout_orchestrated(output: Path) -> dict[str, Any]:
    layout = output / "layout-boundary"
    layout.mkdir(parents=True, exist_ok=True)
    canonical = layout / "canonical.html"
    original = """<!doctype html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }
.slide-container { position: relative; width: 100vw; height: 100vh; }
.slide { position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex;
  align-items: center; justify-content: center; visibility: visible; opacity: 1; }
.main-content { width: 720px; height: 100px; overflow: hidden; font-size: 48px; line-height: 1.2; }
</style></head><body><div class="slide-container"><div class="slide active">
<div class="main-content">This local layout fixture deliberately contains enough text to overflow its fixed box and require the existing CSS hotfix.</div>
</div></div></body></html>"""
    canonical.write_text(original, encoding="utf-8")
    case = _make_layout_case(layout, canonical)
    before_layout_path = layout / "layout-report.json"
    before_qa_passed, before_layout = run_layout_qa(
        canonical,
        before_layout_path,
        browser_channel="msedge",
        wait_ms=0,
    )
    if before_qa_passed:
        raise RuntimeError("layout accept demo did not start from a real layout failure")
    before = run_case(
        case,
        run_id="layout-before",
        artifacts_root=layout,
        output_root=layout / "before-eval",
        evaluators=[evaluate_layout, evaluate_structure],
        repo_root=REPO_ROOT,
    )
    issue = next(item for item in before["issues"] if item["type"] == "LAYOUT_ISSUE")
    original_bytes = canonical.read_bytes()

    def re_evaluate(path: Path, evaluator_names: list[str], candidate_dir: Path) -> dict[str, Any]:
        if evaluator_names != ["layout", "structure"]:
            raise ValueError(f"unexpected targeted evaluator route: {evaluator_names}")
        candidate_root = path.parent
        shutil.copy2(layout / "storyboard.json", candidate_root / "storyboard.json")
        run_layout_qa(
            path,
            candidate_root / "layout-report.json",
            browser_channel="msedge",
            wait_ms=0,
        )
        return run_case(
            case,
            run_id="layout-targeted",
            artifacts_root=candidate_root,
            output_root=candidate_dir / "targeted-re-eval",
            evaluators=[evaluate_layout, evaluate_structure],
            repo_root=REPO_ROOT,
        )

    result = execute_layout_repair(
        canonical_root=layout,
        work_root=layout / "repair-work",
        case_id=case.case_id,
        run_id="layout-run",
        issue=issue,
        artifact=canonical.name,
        before_report=before,
        segments=_storyboard(valid=True, narration="layout")["segments"],
        layout_report=before_layout,
        re_evaluate=re_evaluate,
        generate_fn=lambda _prompt, **_kwargs: '<div class="slide"><div class="main-content">fixed</div></div>',
        browser_channel="msedge",
    )
    if result.status != "accepted" or result.accepted_artifact is None:
        raise RuntimeError(f"layout demo did not accept candidate: {result.status}")
    return {
        "canonical_artifact": str(canonical),
        "candidate_artifact": str(result.candidate_artifact),
        "accepted_artifact": str(result.accepted_artifact),
        "canonical_unchanged": canonical.read_bytes() == original_bytes,
        "candidate_changed": result.candidate_artifact.read_bytes() != original_bytes,
        "status": result.status,
        "route": {
            "family": result.route.family,
            "strategy": result.route.strategy,
            "evaluators": list(result.route.evaluators),
        },
        "before_issue_types": [item.get("type") for item in before.get("issues", [])],
        "after_issue_types": [item.get("type") for item in (result.after_report or {}).get("issues", [])],
        "repair_lineage": str(layout / "repair-work" / "repair_lineage.json"),
        "repair_boundary": "RepairOrchestrator -> css_hotfix -> targeted evaluate_layout (single-slide fallback available)",
    }


def run_local_stability_loop(output_dir: str | Path, *, repeats: int = 5) -> dict[str, Any]:
    """Run and persist the complete local stability demonstration."""

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    accept = _run_storyboard_accept(output)
    rollback = _run_storyboard_rollback(output)
    repeated = _run_repeated(
        load_case(Path(accept["case_manifest"])),
        accept["accepted_artifact"],
        output / "repeated",
        repeats,
    )
    layout = _run_layout_orchestrated(output)
    result = {
        "schema_version": "textbookeval-local-stability-loop-v0.1",
        "output_dir": str(output),
        "local_only": True,
        "model_mode": "deterministic local adapters",
        "accept": accept,
        "rollback": rollback,
        "repeated": repeated,
        "layout_boundary": layout,
    }
    report_path = output / "local_stability_loop_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Textbook-to-Video stability loop demo")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_local_stability_loop(args.out, repeats=args.repeats)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["parse_args", "run_local_stability_loop"]
