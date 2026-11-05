import json

import pytest

from scripts import run_rq2_binding_dev as run
from textbook2video.research import binding_methods as binding


def test_actor_requirement_shared_by_direct_context_and_blind_judge():
    prop = {
        "id": "p",
        "segment_id": "s",
        "text": "Machine moves water.",
        "source_refs": ["s1"],
        "source_context": "Machine moves water.",
    }
    candidates = [{"id": "machine", "text": "Machine"}, {"id": "water", "text": "water"}]
    captured = []

    class Captured(RuntimeError):
        pass

    def model(prompt):
        captured.append(json.loads(prompt))
        raise Captured()

    with pytest.raises(Captured):
        binding.bind_direct_llm_vlm(prop, candidates, model_fn=model, required_target_role="actor")
    with pytest.raises(Captured):
        binding.bind_source_conditioned(prop, candidates, context_model_fn=model)
    task = {"proposition": prop, "source_context": prop["source_context"], "candidates": candidates}
    judge = json.loads(
        run.judge_prompt(
            task,
            [{"option_id": "o1", "selected_candidate_id": "water"}],
            ["WRONG", "UNCERTAIN"],
            required_target_role="actor",
        )
    )
    for prompt in [*captured, judge]:
        assert all(rule in prompt["rules"] for rule in binding.ACTOR_BINDING_RULES)
    assert any("is WRONG" in r for r in judge["rules"])
    assert "actor_quote" not in judge
    assert "rationale" not in judge


def test_default_direct_does_not_silently_become_actor_experiment():
    def model(prompt):
        rules = json.loads(prompt)["rules"]
        assert not any(r in rules for r in binding.ACTOR_BINDING_RULES)
        return json.dumps(
            {
                "selected_candidate_id": None,
                "abstain": True,
                "confidence": 0,
                "rationale": "No match",
            }
        )

    result = binding.bind_direct_llm_vlm({"id": "p"}, [], model_fn=model)
    assert result["selected_candidate_id"] is None


def test_unknown_role_fails_before_model_or_output_directory(tmp_path):
    config = tmp_path / "config.json"
    run.write(config, {"required_target_role": "invented"})
    with pytest.raises(ValueError, match="target role"):
        run.prepare(tmp_path / "out", config)
    assert not (tmp_path / "out").exists()
