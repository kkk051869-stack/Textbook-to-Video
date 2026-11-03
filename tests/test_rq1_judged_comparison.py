import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_rq1_judged_comparison.py"
SPEC = importlib.util.spec_from_file_location("run_rq1_judged_comparison", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_action_stratified_sample_selects_one_per_action() -> None:
    propositions = [
        {"id": f"p{index}", "text": f"text {index}"} for index in range(1, 6)
    ]
    decisions = [
        {"narration_proposition_id": "p2", "action": "none"},
        {"narration_proposition_id": "p1", "action": "none"},
        {"narration_proposition_id": "p3", "action": "reuse"},
        {"narration_proposition_id": "p4", "action": "retrieve"},
        {"narration_proposition_id": "p5", "action": "generate"},
    ]

    sample = MODULE.select_action_stratified_sample(propositions, decisions)

    assert [item["proposition"]["id"] for item in sample] == ["p1", "p3", "p4", "p5"]


def test_judge_aggregation_keeps_scores_cost_and_verdicts_separate() -> None:
    rows = [
        {
            "method": "m1",
            "decision": {"action": "none"},
            "judgment": {
                "judge_kind": "LLM",
                "verdict": "ACCEPT",
                "scores": {
                    "necessity_correctness": 4,
                    "source_grounding": 3,
                    "coherence": 4,
                    "candidate_appropriateness": None,
                },
            },
        },
        {
            "method": "m1",
            "decision": {"action": "retrieve"},
            "judgment": {
                "judge_kind": "LLM",
                "verdict": "REVISE",
                "scores": {
                    "necessity_correctness": 2,
                    "source_grounding": 1,
                    "coherence": 2,
                    "candidate_appropriateness": None,
                },
            },
        },
    ]

    result = MODULE.aggregate_judged_methods(rows)["m1"]

    assert result["accept_rate"] == 0.5
    assert result["mean_scores"]["necessity_correctness"] == 3.0
    assert result["external_retrieval_requests"] == 1
    assert result["generation_requests"] == 0


def test_blinded_decision_keeps_action_but_removes_policy_rationale() -> None:
    blinded = MODULE._blind_decision(
        {
            "action": "retrieve",
            "rationale": "Always Retrieve triggers every proposition.",
            "retrieval_query": "区块链结构",
        }
    )

    assert blinded["action"] == "retrieve"
    assert blinded["retrieval_query"] == "区块链结构"
    assert blinded["rationale"] is None
    assert blinded["rationale_withheld_for_method_blinding"] is True


def test_accepted_action_conflicts_are_reported_per_proposition() -> None:
    rows = [
        {
            "method": "none-method",
            "proposition_id": "p1",
            "decision": {"action": "none"},
            "judgment": {"verdict": "ACCEPT"},
        },
        {
            "method": "retrieve-method",
            "proposition_id": "p1",
            "decision": {"action": "retrieve"},
            "judgment": {"verdict": "ACCEPT"},
        },
        {
            "method": "other",
            "proposition_id": "p2",
            "decision": {"action": "none"},
            "judgment": {"verdict": "ACCEPT"},
        },
    ]

    assert MODULE.find_accepted_action_conflicts(rows) == [
        {
            "proposition_id": "p1",
            "accepted_actions": ["none", "retrieve"],
            "accepted_methods": ["none-method", "retrieve-method"],
        }
    ]
