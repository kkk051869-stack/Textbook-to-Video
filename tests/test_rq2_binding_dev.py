import copy

import pytest

from scripts import run_rq2_binding_dev as run


def test_binding_groups_hide_method_rationale_scores_but_preserve_object():
    options, mapping = run.groups_for(
        {
            "method-a": {"selected_candidate_id": "obj1", "rationale": "long", "score": 0.9},
            "method-b": {"selected_candidate_id": "obj1", "rationale": "short", "score": 0.4},
            "method-c": {"selected_candidate_id": None},
            "method-d": {"selected_candidate_id": "obj2"},
        }
    )
    assert len(options) == 3
    assert mapping["method-a"] == mapping["method-b"]
    assert mapping["method-c"] != mapping["method-d"]
    assert all(set(o) == {"option_id", "selected_candidate_id"} for o in options)


@pytest.mark.parametrize(
    "error", ["unknown_option", "invented_quote", "wrong_abstain", "missing_evidence"]
)
def test_judge_rejects_wrong_target_or_fabricated_evidence(error):
    options = [{"option_id": "o1", "selected_candidate_id": "obj1"}]
    value = {
        "assessment_by_option": {
            "o1": {
                "verdict": "BOUND_SUPPORTED",
                "source_quote": "Actual source",
                "visible_evidence": "Named block",
            }
        }
    }
    run.validate_judgment(value, ["o1"], "Actual source context", ["BOUND_SUPPORTED"], options)
    bad = copy.deepcopy(value)
    if error == "unknown_option":
        bad["assessment_by_option"]["unknown"] = bad["assessment_by_option"].pop("o1")
    elif error == "invented_quote":
        bad["assessment_by_option"]["o1"]["source_quote"] = "invented"
    elif error == "wrong_abstain":
        bad["assessment_by_option"]["o1"]["verdict"] = "ABSTAIN_REASONABLE"
    else:
        bad["assessment_by_option"]["o1"]["visible_evidence"] = ""
    with pytest.raises(ValueError):
        run.validate_judgment(
            bad, ["o1"], "Actual source context", ["BOUND_SUPPORTED", "ABSTAIN_REASONABLE"], options
        )


def test_verify_detects_input_and_protocol_tampering(tmp_path):
    run.write(tmp_path / "inputs/tasks.json", [])
    protocol = {
        "source_files": {"inputs/tasks.json": run.sha(tmp_path / "inputs/tasks.json")},
        "budget": {"max_transport_calls": 21},
    }
    run.write(tmp_path / "protocol.json", protocol)
    run.write(tmp_path / "run-01/protocol.json", protocol)
    run.write(tmp_path / "run-01/calls.json", [])
    assert run.verify(tmp_path)["status"] == "PASS"
    run.write(tmp_path / "inputs/tasks.json", [{}])
    with pytest.raises(ValueError, match="frozen input changed"):
        run.verify(tmp_path)
    run.write(tmp_path / "inputs/tasks.json", [])
    run.write(tmp_path / "protocol.json", {**protocol, "budget": {"max_transport_calls": 99}})
    with pytest.raises(ValueError, match="protocol changed"):
        run.verify(tmp_path)


def test_embedding_failure_is_reserved_and_cannot_be_repeated(tmp_path, monkeypatch):
    import requests

    run.write(tmp_path / "calls.json", [])
    protocol = {
        "models": {"embedding_model": "fixture", "timeout_sec": 1},
        "budget": {"max_transport_calls": 21},
    }
    monkeypatch.setattr(run.shared.legacy, "LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(run.shared.legacy, "LLM_API_KEY", "fixture-nonsecret")

    class FakeSession:
        trust_env = False

        def post(self, *args, **kwargs):
            assert run.read(tmp_path / "calls.json")[0]["status"] == "STARTED"
            raise RuntimeError("fixture transport failure")

    monkeypatch.setattr(requests, "Session", FakeSession)
    ledger = []
    with pytest.raises(RuntimeError, match="fixture transport"):
        run.embedding_batch(tmp_path, tmp_path, protocol, ledger, ["query"])
    assert len(ledger) == 1 and ledger[0]["status"] == "FAILED"
    with pytest.raises(ValueError, match="first and only"):
        run.embedding_batch(tmp_path, tmp_path, protocol, ledger, ["query"])
