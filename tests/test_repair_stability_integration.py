"""Local production-boundary integration tests for the stability loop.

All model behavior in this file is deterministic and injected.  The evaluator
and repair functions under test are the repository's actual implementations.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from textbook2video.eval.evaluators.content import (
    evaluate_knowledge_grounding,
    evaluate_source_fidelity,
)
from textbook2video.eval.evaluators.pedagogy import evaluate_pedagogy
from textbook2video.eval.evaluators.quality import evaluate_quality
from textbook2video.eval.evaluators.structure import evaluate_structure
from textbook2video.eval.regression_promotion import (
    promote_failure,
    replay_regression_fixture,
)
from textbook2video.eval.runner import run_case
from textbook2video.eval.stability import run_repeated
from textbook2video.eval.stability_loop import run_local_stability_loop
from textbook2video.pipeline.checks import validate_storyboard
from textbook2video.pipeline.checks import _check_browser
from textbook2video.repair.orchestrator import RepairOrchestrator
from textbook2video.repair.production import (
    repair_layout_candidate,
    repair_storyboard_candidate,
)
from textbook2video.eval.dataset import load_case


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_EVALUATORS = [
    evaluate_structure,
    evaluate_source_fidelity,
    evaluate_knowledge_grounding,
    evaluate_pedagogy,
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _storyboard(*, valid: bool = False, core: str = "core") -> dict[str, Any]:
    element: dict[str, Any] = {"id": "body", "type": "text"}
    if valid:
        element["text"] = "A repaired explanation."
    return {
        "lesson_title": "Local stability loop",
        "metadata": {"total_slides": 1},
        "segments": [
            {
                "id": 1,
                "visual_type": "definition",
                "narration": core,
                "elements": [element],
            }
        ],
    }


def _make_case(root: Path, *, case_id: str, storyboard: dict[str, Any], with_core: bool) -> tuple[Any, Path]:
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.json"
    annotation = root / "annotation.json"
    storyboard_path = root / "storyboard.json"
    source.write_text(
        json.dumps({"paragraphs": [{"id": "p1", "text": "core"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    annotation.write_text(
        json.dumps(
            {
                "core_concepts": (
                    [{"id": "c1", "statement": "core", "must_mention_terms": ["core"], "evidence_paragraphs": ["p1"]}]
                    if with_core
                    else []
                ),
                "required_images": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storyboard_path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = root / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": case_id,
                "lesson_id": f"{case_id}-lesson",
                "status": "candidate",
                "dataset_version": "local-stability-fixture-v1",
                "source": {
                    "files": [
                        {"role": "source_json", "path": source.name, "sha256": _sha256(source)}
                    ]
                },
                "annotation": {
                    "role": "annotation",
                    "path": annotation.name,
                    "sha256": _sha256(annotation),
                },
                "candidate_artifacts": {"storyboard": storyboard_path.name},
                "metadata": {"config": {"renderer": "local-deterministic"}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return load_case(manifest), storyboard_path


def _run_targeted(case: Any, artifacts: Path, output: Path, run_id: str) -> dict[str, Any]:
    return run_case(
        case,
        run_id=run_id,
        artifacts_root=artifacts,
        output_root=output,
        evaluators=TARGET_EVALUATORS,
        repo_root=REPO_ROOT,
    )


def _local_review(data: dict[str, Any], _lesson_plan: dict[str, Any] | None, _model: str | None) -> dict[str, Any]:
    validation = validate_storyboard(data)
    return {
        "pass": validation.ok,
        "severity": "pass" if validation.ok else "major",
        "issues": [{"type": "STORYBOARD_INVALID", "message": item} for item in validation.errors],
        "summary": "local deterministic review",
    }


def _local_repair(
    data: dict[str, Any],
    _review: dict[str, Any],
    _lesson_plan: dict[str, Any] | None,
    _model: str | None,
) -> dict[str, Any]:
    repaired = deepcopy(data)
    repaired["segments"][0]["elements"][0]["text"] = "A repaired explanation."
    return repaired


def test_local_storyboard_accept_e2e_and_regression_replay(tmp_path):
    case, canonical_storyboard = _make_case(
        tmp_path / "case-accept",
        case_id="local-accept",
        storyboard=_storyboard(valid=False),
        with_core=False,
    )
    canonical = canonical_storyboard.parent
    original_bytes = canonical_storyboard.read_bytes()
    before = _run_targeted(case, canonical, tmp_path / "accept-before", "accept-before")
    source_issue = next(item for item in before["issues"] if item["type"] == "STORYBOARD_INVALID")

    work = tmp_path / "accept-repair-work"
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
            repair_fn=_local_repair,
        )

    def re_evaluate(path: Path, evaluator_names: list[str], candidate_dir: Path) -> dict[str, Any]:
        assert evaluator_names == ["structure", "source_fidelity", "knowledge_grounding", "pedagogy"]
        return _run_targeted(case, path.parent, candidate_dir / "targeted-re-eval", "accept-targeted")

    result = orchestrator.execute(
        source_issue,
        artifact=canonical_storyboard.name,
        before_report=before,
        repair_fn=repair,
        re_evaluate=re_evaluate,
        model="local-deterministic",
    )
    assert result.status == "accepted"
    assert result.accepted_artifact is not None
    assert canonical_storyboard.read_bytes() == original_bytes
    assert result.after_report is not None
    assert result.after_report["evaluators"]["structure"]["passed"] is True

    from textbook2video.eval.evaluators.repair_effectiveness import RepairEffectivenessAdapter

    effectiveness = _run_targeted(
        case,
        result.candidate_artifact.parent,
        tmp_path / "accept-effectiveness",
        "accept-effectiveness",
    )
    # Run the real evaluator in the same runner, using the lineage generated by
    # the orchestrator rather than a hand-written effectiveness report.
    effectiveness = run_case(
        case,
        run_id="accept-effectiveness",
        artifacts_root=result.candidate_artifact.parent,
        output_root=tmp_path / "accept-effectiveness",
        evaluators=[evaluate_structure],
        repair_effectiveness=RepairEffectivenessAdapter(work / "repair_lineage.json"),
        repo_root=REPO_ROOT,
    )
    assert effectiveness["evaluators"]["repair_effectiveness"]["metrics"]["repair_success_count"] == 1

    promoted_path = tmp_path / "regression" / "local-accept.json"
    promoted = promote_failure(
        case_id=case.case_id,
        issue=source_issue,
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
    assert promoted["replay"]["kind"] == "storyboard"
    replay = replay_regression_fixture(promoted_path)
    assert replay["fault_detected"] is True
    assert replay["repaired_passed"] is True
    assert replay["reinjected_fault_detected"] is True
    assert replay["passed"] is True


def test_local_storyboard_rollback_comes_from_real_evaluator_regression(tmp_path):
    case, canonical_storyboard = _make_case(
        tmp_path / "case-rollback",
        case_id="local-rollback",
        storyboard=_storyboard(valid=False),
        with_core=True,
    )
    canonical = canonical_storyboard.parent
    original_bytes = canonical_storyboard.read_bytes()
    before = _run_targeted(case, canonical, tmp_path / "rollback-before", "rollback-before")
    source_issue = next(item for item in before["issues"] if item["type"] == "STORYBOARD_INVALID")

    def regressing_repair(data: dict[str, Any], review: dict[str, Any], lesson_plan: Any, model: Any) -> dict[str, Any]:
        repaired = _local_repair(data, review, lesson_plan, model)
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
        work_root=tmp_path / "rollback-repair-work",
        case_id=case.case_id,
        run_id="rollback-run",
    ).execute(
        source_issue,
        artifact=canonical_storyboard.name,
        before_report=before,
        repair_fn=repair,
        re_evaluate=re_evaluate,
    )
    assert result.status == "rolled_back"
    assert canonical_storyboard.read_bytes() == original_bytes
    assert result.after_report is not None
    after_types = {item["type"] for item in result.after_report["issues"]}
    # The runner coalesces the two content evaluator outputs into the
    # canonical CONTENT_CONCEPT_GAP issue while retaining evaluator-local
    # evidence.  This is a real blocking evaluator result, not a hand-written
    # regression row.
    assert "CONTENT_CONCEPT_GAP" in after_types
    assert any(item["severity"] == "error" for item in result.after_report["issues"])
    assert result.decision is not None
    assert result.decision.no_new_blocking_regression is False


def test_real_repeated_executor_runs_runner_and_keeps_independent_outputs(tmp_path):
    case, storyboard = _make_case(
        tmp_path / "case-repeated",
        case_id="local-repeated",
        storyboard=_storyboard(valid=True),
        with_core=False,
    )
    source = json.loads(storyboard.read_text(encoding="utf-8"))

    def factory(index: int, run_id: str) -> dict[str, Any]:
        artifacts = tmp_path / "run-artifacts" / run_id
        artifacts.mkdir(parents=True)
        value = deepcopy(source)
        if index % 2 == 0:
            value["segments"][0].pop("audio_duration_sec", None)
        else:
            value["segments"][0]["audio_duration_sec"] = 2.0
        path = artifacts / "storyboard.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_case(
            case,
            run_id=run_id,
            artifacts_root=artifacts,
            output_root=tmp_path / "reports" / run_id,
            evaluators=[evaluate_structure],
            repo_root=REPO_ROOT,
        )

    report = run_repeated(4, factory, run_id_prefix="real", output_dir=tmp_path / "stability")
    assert report["stable_pass_at_n"] is True
    assert report["gate_flip_rate"] == 0.0
    assert report["metrics"]["structure.warning_count"]["std"] > 0
    assert {item["run_id"] for item in report["runs"]} == {"real-001", "real-002", "real-003", "real-004"}
    assert all((tmp_path / "reports" / item["run_id"] / "eval_report.json").is_file() for item in report["runs"])

    def flapping_factory(index: int, run_id: str) -> dict[str, Any]:
        artifacts = tmp_path / "flapping-artifacts" / run_id
        artifacts.mkdir(parents=True)
        value = deepcopy(source)
        if index == 3:
            value["segments"][0]["elements"][0].pop("text")
        path = artifacts / "storyboard.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_case(
            case,
            run_id=run_id,
            artifacts_root=artifacts,
            output_root=tmp_path / "flapping-reports" / run_id,
            evaluators=[evaluate_structure],
            repo_root=REPO_ROOT,
        )

    flapping = run_repeated(5, flapping_factory, run_id_prefix="flip", output_dir=tmp_path / "flapping")
    assert flapping["stable_pass_at_n"] is False
    assert flapping["gates"]["structure"]["flip_count"] == 2
    assert flapping["candidate_failure_count"] == 1


def test_layout_production_chain_invokes_css_then_existing_single_slide_repair(tmp_path, monkeypatch):
    import textbook2video.css_hotfix as css_hotfix

    candidate = tmp_path / "candidate.html"
    candidate.write_text(
        '<html><body><div class="slide"><div class="anim">bad</div></div></body></html>',
        encoding="utf-8",
    )
    calls = {"css": 0, "generator": 0}

    def fake_css_hotfix(*_args: Any, **_kwargs: Any) -> int:
        calls["css"] += 1
        raise RuntimeError("browser intentionally unavailable in local deterministic test")

    monkeypatch.setattr(css_hotfix, "apply_css_hotfixes", fake_css_hotfix)

    def generator(_prompt: str, **_kwargs: Any) -> str:
        calls["generator"] += 1
        return '<div class="slide"><div class="anim">fixed</div></div>'

    repaired = repair_layout_candidate(
        candidate,
        segments=[
            {
                "id": 1,
                "visual_type": "definition",
                "narration": "layout",
                "elements": [{"id": "body", "type": "text", "text": "layout"}],
            }
        ],
        layout_report={
            "slides": [{
                "index": 1,
                "passed": False,
                "issues": [{"severity": "fail", "type": "text_out_of_view", "message": "overflow"}],
            }]
        },
        generate_fn=generator,
    )
    assert repaired == candidate.resolve()
    assert calls == {"css": 1, "generator": 1}
    assert "fixed" in candidate.read_text(encoding="utf-8")


def test_local_stability_loop_demo_persists_complete_evidence(tmp_path):
    browser = _check_browser("msedge")
    if not browser.ok or not browser.required:
        pytest.skip(f"msedge channel unavailable for this integration demo: {browser.detail}")
    report = run_local_stability_loop(tmp_path / "local-stability-demo", repeats=5)
    assert report["local_only"] is True
    assert report["accept"]["status"] == "accepted"
    assert report["rollback"]["status"] == "rolled_back"
    assert report["repeated"]["stable"]["stable_pass_at_n"] is True
    assert report["repeated"]["flapping"]["gates"]["structure"]["flip_count"] >= 2
    assert report["accept"]["regression_replay"]["passed"] is True
    assert report["layout_boundary"]["status"] == "accepted"
    assert report["layout_boundary"]["route"]["evaluators"] == ["layout", "structure"]
    assert report["layout_boundary"]["canonical_unchanged"] is True
    assert Path(report["report"]).is_file()
    assert Path(report["accept"]["repair_lineage"]).is_file()
    assert Path(report["accept"]["promoted_regression_fixture"]).is_file()
