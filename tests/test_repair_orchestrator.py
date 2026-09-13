import json

from textbook2video.repair.orchestrator import RepairOrchestrator, route_issue


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
