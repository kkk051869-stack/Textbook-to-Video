import json

from textbook2video.eval.compare import compare_runs


def _report(run_id, gate, rate, issues):
    return {
        "case_id": "case_demo",
        "lesson_id": "lesson_demo",
        "run_id": run_id,
        "status": "ok" if gate else "failed",
        "gates": {"animation_runtime": gate},
        "evaluators": {
            "animation_runtime": {
                "metrics": {"target_resolution_rate": rate},
            }
        },
        "issues": issues,
    }


def test_compare_reports_preserves_gate_and_issue_changes(tmp_path):
    baseline = tmp_path / "baseline" / "case"
    candidate = tmp_path / "candidate" / "case"
    baseline.mkdir(parents=True)
    candidate.mkdir(parents=True)
    issue = {
        "case_id": "case_demo",
        "evaluator": "animation_runtime",
        "type": "TARGET_MISS",
        "slide": 2,
        "message": "missing",
    }
    (baseline / "eval_report.json").write_text(
        json.dumps(_report("baseline", False, 0.5, [issue])), encoding="utf-8"
    )
    (candidate / "eval_report.json").write_text(
        json.dumps(_report("candidate", True, 1.0, [])), encoding="utf-8"
    )

    comparison = compare_runs(baseline.parent, candidate.parent, tmp_path / "comparison")

    case = comparison["cases"][0]
    assert case["gate_changes"][0]["regressed"] is False
    assert case["metric_changes"][0]["delta"] == 0.5
    assert case["resolved_issues"][0]["type"] == "TARGET_MISS"
    assert (tmp_path / "comparison" / "comparison.json").exists()
    assert (tmp_path / "comparison" / "comparison.md").exists()
