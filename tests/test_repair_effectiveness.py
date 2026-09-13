import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.eval.dataset import load_case
from textbook2video.eval.evaluators.repair_effectiveness import (
    RepairEffectivenessAdapter,
    issue_identity,
)
from textbook2video.eval.runner import EvalContext, run_case

REPO_ROOT = Path(__file__).resolve().parents[1]


def _case(tmp_path: Path):
    assets = []
    for role, name in (
        ("source_json", "source.json"),
        ("source_pdf", "source.pdf"),
        ("source_manifest", "source-manifest.json"),
    ):
        path = tmp_path / name
        path.write_bytes(b"source")
        assets.append({"role": role, "path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in ("annotation.json", "heldout.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    manifest = tmp_path / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case_repair",
                "lesson_id": "lesson_repair",
                "status": "frozen",
                "dataset_version": "repair-test",
                "source": {"files": assets},
                "annotation": {
                    "role": "annotation",
                    "path": "annotation.json",
                    "sha256": hashlib.sha256((tmp_path / "annotation.json").read_bytes()).hexdigest(),
                    "review_status": "frozen",
                },
                "heldout_questions": {
                    "role": "heldout_questions",
                    "path": "heldout.json",
                    "sha256": hashlib.sha256((tmp_path / "heldout.json").read_bytes()).hexdigest(),
                    "review_status": "frozen",
                },
                "review": {
                    "annotation_status": "frozen",
                    "reviewer": "test-reviewer",
                    "reviewed_at": "2026-09-13T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    return load_case(manifest, require_frozen=True)


def _report(path: Path, issues: list[dict] | None = None, status: str = "failed") -> None:
    path.write_text(json.dumps({"status": status, "issues": issues or []}), encoding="utf-8")


def _run(tmp_path: Path, records: list[dict], before: dict, after: dict, *, gold=None):
    root = tmp_path / "lineage"
    root.mkdir()
    (root / "before.bin").write_bytes(b"before")
    (root / "after.bin").write_bytes(b"after")
    _report(root / "before.json", **before)
    _report(root / "after.json", **after)
    lineage = {"case_id": "case_repair", "repairs": records}
    if gold is not None:
        lineage["detection_gold"] = gold
    lineage_path = root / "repair_lineage.json"
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    report = run_case(
        _case(tmp_path),
        run_id="repair-run",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
        evaluators=[],
        repair_effectiveness=RepairEffectivenessAdapter(lineage_path),
        repo_root=REPO_ROOT,
    )
    return report["evaluators"]["repair_effectiveness"], report


def _record(repair_id="r1", **overrides):
    value = {
        "repair_id": repair_id,
        "case_id": "case_repair",
        "round": 1,
        "source_issue_id": "i1",
        "issue_type": "LAYOUT_FAIL",
        "issue_stage": "layout",
        "severity": "error",
        "before_artifact": "before.bin",
        "after_artifact": "after.bin",
        "before_eval_report": "before.json",
        "after_eval_report": "after.json",
        "before_status": "failed",
        "after_status": "pass",
        "repair_action": "adjust layout",
        "repair_source": "deterministic_fixture",
    }
    value.update(overrides)
    return value


def _issue(issue_id="i1", **overrides):
    value = {"issue_id": issue_id, "stage": "layout", "type": "LAYOUT_FAIL", "severity": "error", "slide": 1}
    value.update(overrides)
    return value


def test_successful_repair_and_pending_calibration(tmp_path):
    result, report = _run(
        tmp_path,
        [_record()],
        {"issues": [_issue()]},
        {"issues": [], "status": "pass"},
    )
    assert result["status"] == "ok"
    assert result["metrics"]["repair_success_count"] == 1
    assert result["metrics"]["resolved_issue_count"] == 1
    assert result["metrics"]["repair_success_rate"] == 1
    assert result["metrics"]["net_issue_delta"] == 3
    assert report["status"] == "pass"
    calibration = (tmp_path / "eval" / "repair_calibration.md").read_text(encoding="utf-8")
    assert "| pending |" in calibration


@pytest.mark.parametrize(
    ("after_issue", "expected"),
    [
        (_issue(), "failed"),
        (_issue(severity="warning"), "partial"),
        (_issue(severity="critical"), "worsened"),
    ],
)
def test_failed_partial_and_worsened_repairs(tmp_path, after_issue, expected):
    result, _ = _run(tmp_path, [_record()], {"issues": [_issue()]}, {"issues": [after_issue]})
    assert result["details"]["repairs"][0]["result"] == expected
    assert result["metrics"][f"repair_{expected}_count"] == 1


def test_regression_is_reported_separately_from_source_resolution(tmp_path):
    result, _ = _run(
        tmp_path,
        [_record()],
        {"issues": [_issue()]},
        {"issues": [_issue("new-issue", type="FONT_FAIL", stage="font", severity="warning")]},
    )
    assert result["metrics"]["repair_success_count"] == 1
    assert result["metrics"]["introduced_issue_count"] == 1
    assert result["metrics"]["regression_repair_count"] == 1
    assert result["metrics"]["repairs_with_minor_regression"] == 1
    assert any(issue["type"] == "REPAIR_REGRESSION" for issue in result["issues"])


def test_unnecessary_repair_is_not_counted_as_success(tmp_path):
    result, _ = _run(
        tmp_path,
        [_record(source_issue_id="missing")],
        {"status": "pass", "issues": []},
        {"status": "pass", "issues": []},
    )
    assert result["metrics"]["unnecessary_repair_count"] == 1
    assert result["metrics"]["repair_success_count"] == 0
    assert result["details"]["repairs"][0]["result"] == "failed"
    assert result["details"]["repairs"][0]["unnecessary_repair"] is True


def test_missing_after_artifact_is_not_evaluable(tmp_path):
    root = tmp_path / "lineage"
    root.mkdir()
    (root / "before.bin").write_bytes(b"before")
    _report(root / "before.json", issues=[_issue()])
    _report(root / "after.json", issues=[], status="pass")
    lineage_path = root / "repair_lineage.json"
    lineage_path.write_text(json.dumps({"repairs": [_record(after_artifact="missing.bin")]}), encoding="utf-8")
    result = RepairEffectivenessAdapter(lineage_path).evaluate_case(
        EvalContext(case=_case(tmp_path), run_id="r", artifacts_root=tmp_path, output_root=tmp_path / "out")
    )
    assert result["metrics"]["repair_not_evaluable_count"] == 1
    assert result["details"]["repairs"][0]["result"] == "not_evaluable"
    assert result["issues"][0]["type"] == "REPAIR_ARTIFACT_MISSING"


def test_fallback_identity_keeps_same_type_on_different_slides_distinct(tmp_path):
    record = _record(source_issue_id=None, issue_type="LAYOUT_FAIL", issue_stage="layout", slide=1)
    before = {"issues": [_issue(issue_id=None)]}
    after = {"status": "pass", "issues": [_issue(issue_id=None, slide=2)]}
    result, _ = _run(tmp_path, [record], before, after)
    assert result["details"]["repairs"][0]["result"] == "success"
    assert result["metrics"]["introduced_issue_count"] == 1
    assert issue_identity(_issue(issue_id=None, slide=1)) != issue_identity(_issue(issue_id=None, slide=2))


def test_multiple_rounds_measure_round_at_which_issue_passed(tmp_path):
    root = tmp_path / "lineage"
    root.mkdir()
    (root / "before.bin").write_bytes(b"before")
    (root / "after.bin").write_bytes(b"after")
    for name, value in {
        "b1.json": {"issues": [_issue()]},
        "a1.json": {"issues": [_issue()]},
        "b2.json": {"issues": [_issue()]},
        "a2.json": {"status": "pass", "issues": []},
    }.items():
        _report(root / name, **value)
    first = _record(round=1, before_eval_report="b1.json", after_eval_report="a1.json")
    second = _record("r2", round=2, before_eval_report="b2.json", after_eval_report="a2.json")
    lineage_path = root / "repair_lineage.json"
    lineage_path.write_text(json.dumps({"repairs": [first, second]}), encoding="utf-8")
    result, _ = _run_with_lineage(tmp_path, lineage_path)
    assert result["metrics"]["repair_attempt_count"] == 2
    assert result["metrics"]["average_rounds_to_pass"] == 2
    assert result["metrics"]["max_rounds_to_pass"] == 2


def _run_with_lineage(tmp_path: Path, lineage_path: Path):
    report = run_case(
        _case(tmp_path),
        run_id="repair-run",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval-rounds",
        evaluators=[],
        repair_effectiveness=RepairEffectivenessAdapter(lineage_path),
        repo_root=REPO_ROOT,
    )
    return report["evaluators"]["repair_effectiveness"], report


def test_duplicate_repair_id_is_a_lineage_error(tmp_path):
    result, _ = _run(
        tmp_path,
        [_record("same"), _record("same")],
        {"issues": [_issue()]},
        {"status": "pass", "issues": []},
    )
    assert result["status"] == "error"
    assert result["issues"][0]["type"] == "REPAIR_LINEAGE_INVALID"


def test_duplicate_issue_rows_do_not_inflate_regression_counts(tmp_path):
    result, _ = _run(
        tmp_path,
        [_record()],
        {"issues": [_issue()]},
        {"status": "pass", "issues": [_issue("new"), _issue("new")]},
    )
    assert result["metrics"]["introduced_issue_count"] == 1


def test_no_lineage_is_non_blocking_not_applicable(tmp_path):
    report = run_case(
        _case(tmp_path),
        run_id="repair-none",
        artifacts_root=tmp_path,
        output_root=tmp_path / "no-lineage",
        evaluators=[],
        repair_effectiveness=RepairEffectivenessAdapter(),
        repo_root=REPO_ROOT,
    )
    result = report["evaluators"]["repair_effectiveness"]
    assert result["status"] == "not_applicable"
    assert result["details"]["required"] is False
    assert report["status"] == "pass"
