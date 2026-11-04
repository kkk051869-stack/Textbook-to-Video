from copy import deepcopy

import pytest

from textbook2video.research.rq1_controlled_evaluation import summarize_controlled


def rows():
    return [
        dict(
            proposition_id="p1",
            model=m,
            order=o,
            status="OK",
            method_choices={"never": "none", "current": "retrieve"},
            judgment=dict(
                abstain=False,
                best_action="none",
                ranking=["none", "retrieve"],
                eligible_actions=["none", "retrieve"],
                rejected_actions=["retrieve"],
            ),
        )
        for m in ("a", "b")
        for o in ("forward", "reverse")
    ]


def test_agreement_is_proxy_and_not_gold():
    result = summarize_controlled(rows(), ["a", "b"], proposition_ids=["p1"])
    assert result["model_consistent_proxy_count"] == 1
    assert result["items"][0]["status"] == "MODEL_CONSISTENT_PROXY"
    assert result["per_model_order"]["a/forward"]["methods"]["current"]["rejected_count"] == 1


@pytest.mark.parametrize("change", ["abstain", "order", "failed", "missing"])
def test_missing_abstain_and_disagreement_never_become_consensus(change):
    records = rows()
    if change == "missing":
        records.pop()
    elif change == "failed":
        records[-1]["status"] = "FAILED"
        records[-1].pop("judgment")
    elif change == "abstain":
        records[-1]["judgment"].update(abstain=True, best_action=None)
    else:
        records[-1]["judgment"]["best_action"] = "retrieve"
    result = summarize_controlled(records, ["a", "b"], proposition_ids=["p1"])
    assert result["unresolved_count"] == 1
    assert result["items"][0]["proxy_best_action"] is None
    assert result["planned_judgments"] == 4
    assert result["per_model_order"]["b/reverse"]["planned"] == 1


def test_double_abstain_is_not_agreement_and_duplicates_fail():
    records = rows()
    for r in records:
        r["judgment"].update(abstain=True, best_action=None)
    assert (
        summarize_controlled(records, ["a", "b"], proposition_ids=["p1"])["unresolved_count"] == 1
    )
    records.append(deepcopy(records[0]))
    with pytest.raises(ValueError, match="duplicate"):
        summarize_controlled(records, ["a", "b"], proposition_ids=["p1"])


def test_entirely_missing_proposition_stays_in_plan():
    result = summarize_controlled(rows(), ["a", "b"], proposition_ids=["p1", "p2"])
    assert result["planned_judgments"] == 8
    assert result["unresolved_count"] == 1
    assert result["per_model_order"]["a/forward"]["not_run"] == 1


def test_same_top1_different_rejections_is_unresolved():
    records = rows()
    records[-1]["judgment"]["rejected_actions"] = []
    result = summarize_controlled(records, ["a", "b"], proposition_ids=["p1"])
    assert result["items"][0]["top1_consistent_across_model_orders"]
    assert result["items"][0]["status"] == "UNRESOLVED"


def test_runner_rejects_conflicting_cache_and_concurrent_run(tmp_path):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts/run_rq1_controlled_comparison.py"
    spec = importlib.util.spec_from_file_location("controlled_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="identity/protocol"):
        module.validate_cached_row({"model": "wrong"}, {"model": "expected"})
    (tmp_path / "run.lock").write_text("other process")
    with pytest.raises(FileExistsError):
        module.run(tmp_path, execute=True)


def test_offline_analysis_rejects_protocol_drift_without_transport(tmp_path):
    import importlib.util
    import json
    from pathlib import Path

    path = Path(__file__).parents[1] / "scripts/run_rq1_controlled_comparison.py"
    spec = importlib.util.spec_from_file_location("controlled_analysis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "protocol.json").write_text(json.dumps({"inputs": {}}))
    (tmp_path / "report.json").write_text(json.dumps({"protocol_sha256": "wrong"}))
    with pytest.raises(ValueError, match="report/protocol mismatch"):
        module.analyze_saved(tmp_path, tmp_path / "new-analysis.json")
    assert not (tmp_path / "calls.json").exists()
