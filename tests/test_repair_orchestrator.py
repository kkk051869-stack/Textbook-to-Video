import json
from pathlib import Path

from textbook2video.eval.evaluators.av_semantic_alignment import AVSemanticAlignmentAdapter
from textbook2video.eval.runner import EvalContext
from textbook2video.repair.orchestrator import RepairOrchestrator, decide_acceptance, route_issue


def _issue(issue_id="i1", **overrides):
    value = {
        "issue_id": issue_id,
        "type": "LAYOUT_ISSUE",
        "stage": "render",
        "severity": "major",
        "slide": 1,
    }
    value.update(overrides)
    return value


def test_issue_router_is_static_and_targeted():
    route = route_issue(_issue())
    assert route.supported is True
    assert route.strategy == "deterministic_css"
    assert route.evaluators == ("layout", "structure")
    assert route_issue(_issue(type="UNKNOWN_SEMANTIC")).supported is False
    assert route_issue(_issue(type="AUDIO_INTEGRITY")).reason


def test_accept_keeps_canonical_and_promotes_candidate(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    artifact = canonical / "artifact.txt"
    artifact.write_text("bad", encoding="utf-8")
    before_report = {"status": "failed", "gates": {"layout": False}, "issues": [_issue()]}
    calls = []

    def repair(path):
        path.write_text("fixed", encoding="utf-8")
        return 5  # A mutating callback may return a write count; path stays implicit.

    def re_evaluate(path, evaluator_names, candidate_dir):
        calls.append((path.read_text(encoding="utf-8"), evaluator_names, candidate_dir))
        return {"status": "pass", "gates": {"layout": True}, "issues": []}

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=tmp_path / "repair-work",
        case_id="case",
        run_id="run",
    ).execute(
        _issue(),
        artifact="artifact.txt",
        before_report=before_report,
        repair_fn=repair,
        re_evaluate=re_evaluate,
    )
    assert result.status == "accepted"
    assert result.accepted_artifact is not None and result.accepted_artifact.read_text(encoding="utf-8") == "fixed"
    assert artifact.read_text(encoding="utf-8") == "bad"
    assert calls[0][1] == ["layout", "structure"]
    lineage = json.loads((tmp_path / "repair-work" / "repair_lineage.json").read_text(encoding="utf-8"))
    record = lineage["repairs"][0]
    assert record["result"] == "succeeded"
    assert record["after_eval_report"]
    assert record["targeted_evaluators"] == ["layout", "structure"]


def test_blocking_regression_rolls_back_and_preserves_candidate(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    artifact = canonical / "artifact.txt"
    artifact.write_text("bad", encoding="utf-8")
    before_report = {"status": "failed", "gates": {"layout": False, "structure": True}, "issues": [_issue()]}

    def repair(path):
        path.write_text("fixed-but-regressed", encoding="utf-8")

    def re_evaluate(_path, _evaluator_names, _candidate_dir):
        return {
            "status": "failed",
            "gates": {"layout": True, "structure": False},
            "issues": [{"issue_id": "new", "type": "STRUCTURE_INVALID", "severity": "error", "stage": "storyboard"}],
        }

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=tmp_path / "repair-work",
        case_id="case",
        run_id="run",
    ).execute(
        _issue(),
        artifact="artifact.txt",
        before_report=before_report,
        repair_fn=repair,
        re_evaluate=re_evaluate,
    )
    assert result.status == "rolled_back"
    assert result.accepted_artifact is None
    assert artifact.read_text(encoding="utf-8") == "bad"
    assert result.candidate_artifact.read_text(encoding="utf-8") == "fixed-but-regressed"
    assert result.decision is not None
    assert result.decision.no_new_blocking_regression is False
    assert any("new issue" in reason for reason in result.decision.reasons)
    lineage = json.loads((tmp_path / "repair-work" / "repair_lineage.json").read_text(encoding="utf-8"))
    assert lineage["repairs"][0]["result"] == "rolled_back"


def test_unsupported_issue_is_recorded_without_guessing_repair(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    artifact = canonical / "artifact.txt"
    artifact.write_text("unchanged", encoding="utf-8")
    called = False

    def repair(_path):
        nonlocal called
        called = True

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=tmp_path / "repair-work",
        case_id="case",
        run_id="run",
    ).execute(
        _issue(type="VISUAL_SEMANTIC"),
        artifact="artifact.txt",
        before_report={"status": "failed", "issues": [_issue(type="VISUAL_SEMANTIC")]},
        repair_fn=repair,
        re_evaluate=lambda *_args: {},
    )
    assert result.status == "rolled_back"
    assert called is False
    assert result.route.family == "unknown"
    assert "unsupported" in (result.lineage_record.get("notes") or "")


def test_acceptance_ignores_runner_position_changes_when_issue_order_shifts():
    target = _issue("case:structure:LAYOUT_ISSUE:1")
    persistent = _issue(
        "case:structure:STRUCTURE_WARNING:2",
        type="STRUCTURE_WARNING",
        severity="error",
    )
    shifted = dict(persistent, issue_id="case:structure:STRUCTURE_WARNING:1")
    decision = decide_acceptance(
        {"status": "failed", "gates": {"structure": True}, "issues": [target, persistent]},
        {"status": "pass", "gates": {"structure": True}, "issues": [shifted]},
        target,
        round=1,
        max_rounds=3,
    )
    assert decision.status == "accepted"
    assert decision.no_new_blocking_regression is True


def test_incomplete_targeted_report_cannot_accept_when_target_disappears():
    target = _issue()
    decision = decide_acceptance(
        {"status": "failed", "gates": {}, "issues": [target]},
        {},
        target,
        round=1,
        max_rounds=3,
    )
    assert decision.status == "rolled_back"
    assert decision.no_new_blocking_regression is False
    assert any("usable evaluator gates" in reason for reason in decision.reasons)


class _AVCase:
    case_id = "repair-av"
    lesson_id = "repair-av-lesson"
    dataset_version = "local-test"

    def __init__(self, root: Path) -> None:
        self.manifest_path = root / "case_manifest.json"
        self.raw = {"case_id": self.case_id, "lesson_id": self.lesson_id}


def _write_av_inputs(root: Path, *, actual_sec: float = 1.0) -> Path:
    storyboard = root / "storyboard.json"
    storyboard.write_text(json.dumps({"segments": []}), encoding="utf-8")
    (root / "storyboard_timed.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": 1,
                        "elements": [{"id": "e1"}],
                        "timeline": [
                            {
                                "event_id": "event-1",
                                "target": "e1",
                                "at_sec": 1.0,
                                "matched_sentence_id": "sentence-1",
                                "lead_sec": 0.0,
                                "trigger_source": "sentence_cue",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "sentence_cues.json").write_text(
        json.dumps({"sentences": [{"id": "sentence-1", "start_sec": 1.0}]}),
        encoding="utf-8",
    )
    (root / "animation_trace.json").write_text(
        json.dumps(
            {
                "events": [
                    {
                        "event_id": "event-1",
                        "slide": 1,
                        "target": "e1",
                        "target_resolved": True,
                        "status": "executed",
                        "actual": {"start_ms": actual_sec * 1000},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return storyboard


def _canonical_av_result(candidate: Path, output: Path) -> dict:
    return AVSemanticAlignmentAdapter().evaluate_case(
        EvalContext(
            case=_AVCase(candidate.parent),
            run_id="repair-av-targeted",
            artifacts_root=candidate.parent,
            output_root=output,
        )
    )


def _storyboard_issue() -> dict:
    return {
        "issue_id": "storyboard-target",
        "type": "STORYBOARD_INVALID",
        "stage": "storyboard",
        "severity": "major",
    }


def test_storyboard_repair_adds_av_when_inputs_are_complete_and_accepts_on_av_pass(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    storyboard = _write_av_inputs(canonical)
    calls: list[list[str]] = []

    def re_evaluate(path: Path, evaluator_names: list[str], candidate_dir: Path) -> dict:
        calls.append(evaluator_names)
        assert evaluator_names[-1] == "av_semantic_alignment"
        result = _canonical_av_result(path, candidate_dir / "eval")
        return {
            "status": "pass" if result["passed"] else "failed",
            "gates": {"structure": True, "av_semantic_alignment": result["passed"]},
            "issues": result["issues"],
            "evaluators": {"av_semantic_alignment": result},
        }

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=tmp_path / "repair-work",
        case_id="repair-av",
        run_id="run-pass",
    ).execute(
        _storyboard_issue(),
        artifact=storyboard.name,
        before_report={"status": "failed", "gates": {"structure": False}, "issues": [_storyboard_issue()]},
        repair_fn=lambda path: path,
        re_evaluate=re_evaluate,
    )

    assert result.status == "accepted"
    assert calls == [["structure", "source_fidelity", "knowledge_grounding", "pedagogy", "av_semantic_alignment"]]
    assert result.route.av_semantic_capability is not None
    assert result.route.av_semantic_capability.available is True
    assert result.accepted_artifact is not None
    assert storyboard.read_bytes() == (canonical / "storyboard.json").read_bytes()


def test_storyboard_repair_rolls_back_on_real_av_regression(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    storyboard = _write_av_inputs(canonical)

    def repair(path: Path) -> Path:
        trace_path = path.parent / "animation_trace.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace["events"][0]["actual"]["start_ms"] = 4000
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        return path

    def re_evaluate(path: Path, evaluator_names: list[str], candidate_dir: Path) -> dict:
        assert "av_semantic_alignment" in evaluator_names
        result = _canonical_av_result(path, candidate_dir / "eval")
        return {
            "status": "failed" if not result["passed"] else "pass",
            "gates": {"structure": True, "av_semantic_alignment": result["passed"]},
            "issues": result["issues"],
            "evaluators": {"av_semantic_alignment": result},
        }

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=tmp_path / "repair-work",
        case_id="repair-av",
        run_id="run-regression",
    ).execute(
        _storyboard_issue(),
        artifact=storyboard.name,
        before_report={"status": "failed", "gates": {"structure": False}, "issues": [_storyboard_issue()]},
        repair_fn=repair,
        re_evaluate=re_evaluate,
    )

    assert result.status == "rolled_back"
    assert result.accepted_artifact is None
    assert result.decision is not None
    assert result.decision.no_new_blocking_regression is False
    assert any("av_semantic_alignment" in reason for reason in result.decision.reasons)
    assert json.loads((canonical / "animation_trace.json").read_text(encoding="utf-8"))["events"][0]["actual"]["start_ms"] == 1000.0


def test_storyboard_repair_without_av_inputs_is_not_blocked_by_unavailable_av(tmp_path):
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    storyboard = canonical / "storyboard.json"
    storyboard.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def re_evaluate(_path: Path, evaluator_names: list[str], _candidate_dir: Path) -> dict:
        calls.append(evaluator_names)
        return {"status": "pass", "gates": {"structure": True}, "issues": []}

    result = RepairOrchestrator(
        canonical_root=canonical,
        work_root=tmp_path / "repair-work",
        case_id="repair-av",
        run_id="run-unavailable",
    ).execute(
        _storyboard_issue(),
        artifact=storyboard.name,
        before_report={"status": "failed", "gates": {"structure": False}, "issues": [_storyboard_issue()]},
        repair_fn=lambda path: path,
        re_evaluate=re_evaluate,
    )

    assert result.status == "accepted"
    assert calls == [["structure", "source_fidelity", "knowledge_grounding", "pedagogy"]]
    assert result.route.av_semantic_capability is not None
    assert result.route.av_semantic_capability.status == "unavailable"
    assert result.route.av_semantic_capability.missing_inputs == (
        "timed_storyboard",
        "animation_trace",
    )
    assert result.lineage_record["provenance"]["targeted_re_evaluation"]["av_semantic_alignment"]["status"] == "unavailable"
