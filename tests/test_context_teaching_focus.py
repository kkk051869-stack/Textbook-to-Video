"""Offline semantic-contract fixtures, not model capability or teaching gold."""

import copy
import json

import pytest

from scripts import run_rq2_binding_dev as run
from textbook2video.research import binding_methods as binding

SOURCE = "Pump moves water into Tank. Tank stores water."
PROP = {
    "id": "p",
    "segment_id": "s",
    "text": "Pump moves water into Tank.",
    "source_refs": ["sentence"],
    "source_context": SOURCE,
}
CANDIDATES = [{"id": "pump", "text": "Pump"}, {"id": "water", "text": "water"}]


def row(focus="Pump", role="actor", support="SUPPORTED"):
    return {
        "support": support,
        "polarity": "AFFIRMED",
        "source_quotes": [SOURCE],
        "actor_quote": "Pump",
        "action_quote": "moves",
        "patient_quote": "water",
        "candidate_label_quote": focus,
        "explanation": "The source establishes this role.",
        "attention_role": role,
        "focus_quote": focus,
    }


def invoke(rows, joint=None, **kwargs):
    value = {"assessment_by_candidate": rows}
    if joint is not None:
        value["joint_focus"] = joint
    original = copy.deepcopy(value)

    def model(prompt):
        payload = json.loads(prompt)
        assert all(r in payload["rules"] for r in binding.TEACHING_FOCUS_RULES)
        assert not any(r in payload["rules"] for r in binding.ACTOR_BINDING_RULES)
        return json.dumps(value)

    result = binding.bind_source_conditioned(PROP, CANDIDATES, context_model_fn=model, **kwargs)
    assert value == original
    assert result["context_method_version"] == binding.CONTEXT_FOCUS_VERSION
    assert result["visual_explanation_status"] == "NOT_EVALUATED"
    return result


@pytest.mark.parametrize(
    "role,focus",
    [
        ("actor", "Pump"),
        ("patient", "water"),
        ("input", "water"),
        ("output", "steam"),
        ("relation", "Pump takes water as input and produces steam as output."),
    ],
)
def test_source_supported_attention_roles_do_not_require_actor_identity(role, focus):
    source = "Pump takes water as input and produces steam as output."
    prop = {**PROP, "text": source, "source_context": source}
    candidate = {"id": "focus", "text": focus}
    assessment = {
        "support": "SUPPORTED",
        "polarity": "AFFIRMED",
        "source_quotes": [source],
        "actor_quote": "Pump",
        "action_quote": "takes",
        "patient_quote": "water",
        "candidate_label_quote": focus,
        "attention_role": role,
        "focus_quote": focus,
        "explanation": f"The source supports attention to the {role} of the narrated process.",
    }
    result = binding.bind_source_conditioned(
        prop,
        [candidate],
        context_model_fn=lambda _: json.dumps({"assessment_by_candidate": {"focus": assessment}}),
    )
    assert result["selected_candidate_id"] == "focus"
    assert result["evidence"][0]["attention_role"] == role


def test_multiple_supported_without_joint_relation_abstains():
    result = invoke({"pump": row(), "water": row("water", "patient")})
    assert result["status"] == "ABSTAINED_AMBIGUOUS_SOURCE_RELATIONS"
    assert result["selected_candidate_ids"] == []


def joint():
    return {
        "candidate_ids": ["pump", "water"],
        "source_quotes": [SOURCE],
        "explanation": "Pump acts on water; both are foci of the same narrated relation.",
    }


def test_joint_source_relation_preserves_all_members_without_arbitrary_single_winner():
    result = invoke({"pump": row(), "water": row("water", "patient")}, joint())
    assert result["status"] == "BOUND_MULTIPLE"
    assert result["selected_candidate_id"] is None
    assert result["selected_candidate_ids"] == ["pump", "water"]
    options, mapping = run.groups_for({"proposed": result})
    assert options[0]["selected_candidate_ids"] == ["pump", "water"]
    assert mapping == {"proposed": "o1"}
    run.validate_judgment(
        {
            "assessment_by_option": {
                "o1": {
                    "verdict": "BOUND_SUPPORTED",
                    "source_quote": SOURCE,
                    "visible_evidence": "Joint source-supported focus.",
                }
            }
        },
        ["o1"],
        SOURCE,
        ["BOUND_SUPPORTED"],
        options,
    )


@pytest.mark.parametrize("change", ["fabricated", "missing_member", "unsupported_member"])
def test_untrusted_joint_relation_is_global_failure(change):
    group = joint()
    rows = {"pump": row(), "water": row("water", "patient")}
    if change == "fabricated":
        group["source_quotes"] = ["Pump creates gold."]
    elif change == "missing_member":
        group["candidate_ids"] = ["pump", "missing"]
    else:
        rows["water"]["support"] = "NOT_SUPPORTED"
    with pytest.raises(ValueError):
        invoke(rows, group)


def test_invalid_rejected_candidate_is_isolated_with_error_and_raw_evidence():
    rows = {"pump": row(), "water": row("water", "patient", "NOT_SUPPORTED")}
    rows["water"]["source_quotes"] = ["invented"]
    result = invoke(rows)
    assert result["selected_candidate_id"] == "pump"
    assert result["status"] == "BOUND_PARTIAL_EVIDENCE"
    assert result["rejected_candidate_ids"] == ["water"]
    assert result["evidence_complete"] is False
    assert result["evidence"][1]["raw_assessment"] == rows["water"]
    assert "error" in result["evidence"][1]
    assert "proposed" in run.valid_results({"proposed": result})


@pytest.mark.parametrize("support", ["SUPPORTED", "UNCERTAIN"])
def test_invalid_supported_or_uncertain_alternative_invalidates_whole_judgment(support):
    rows = {"pump": row(), "water": row("water", "patient", support)}
    rows["water"]["focus_quote"] = "gold"
    with pytest.raises(ValueError, match="focus_quote"):
        invoke(rows)


def test_schema_errors_remain_global_even_in_rejected_row():
    rows = {"pump": row(), "water": row("water", "patient", "NOT_SUPPORTED")}
    del rows["water"]["attention_role"]
    with pytest.raises(ValueError, match="schema"):
        invoke(rows)


def test_valid_uncertain_alternative_prevents_false_unique_selection():
    result = invoke({"pump": row(), "water": row("water", "patient", "UNCERTAIN")})
    assert result["status"] == "ABSTAINED_UNCERTAIN_SOURCE_RELATIONS"
    assert result["selected_candidate_ids"] == []


def test_no_source_never_calls_model_and_high_lexical_overlap_cannot_rescue_bad_evidence():
    def forbidden(_):
        raise AssertionError("transport forbidden")

    result = binding.bind_source_conditioned(
        {**PROP, "source_refs": []}, CANDIDATES, context_model_fn=forbidden
    )
    assert result["selected_candidate_id"] is None
    rows = {"pump": row(), "water": row("water", "patient", "NOT_SUPPORTED")}
    rows["pump"]["focus_quote"] = "gold"
    with pytest.raises(ValueError):
        invoke(rows)


def test_no_supported_candidate_does_not_become_lexical_binding():
    result = invoke(
        {"pump": row(support="NOT_SUPPORTED"), "water": row("water", "patient", "NOT_SUPPORTED")}
    )
    assert result["status"] == "ABSTAINED_NO_SOURCE_SUPPORTED_CANDIDATE"
    assert result["selected_candidate_id"] is None


def test_invalid_negative_rows_without_valid_focus_are_failure_not_reasonable_abstention():
    rows = {"pump": row(support="NOT_SUPPORTED"), "water": row("water", "patient", "NOT_SUPPORTED")}
    rows["water"]["source_quotes"] = ["invented"]
    result = invoke(rows)
    assert result["status"] == "INVALID_CANDIDATE_EVIDENCE"
    assert run.valid_results({"proposed": result}) == {}


def test_affirmative_support_cannot_use_negated_polarity():
    rows = {"pump": row(), "water": row("water", "patient", "NOT_SUPPORTED")}
    rows["pump"]["polarity"] = "NEGATED"
    with pytest.raises(ValueError, match="affirmative"):
        invoke(rows)


def test_legacy_response_is_not_silently_reinterpreted_as_new_method_output():
    rows = {"pump": row(), "water": row("water", "patient", "NOT_SUPPORTED")}
    for assessment in rows.values():
        del assessment["focus_quote"]
        del assessment["attention_role"]
    with pytest.raises(ValueError, match="schema"):
        invoke(rows)


def test_comparison_summary_keeps_partial_evidence_distinct(tmp_path):
    result = {
        "status": "BOUND_PARTIAL_EVIDENCE",
        "selected_candidate_id": "pump",
        "selected_candidate_ids": ["pump"],
        "evidence_complete": False,
    }
    run.write(
        tmp_path / "protocol.json",
        {
            "methods": ["proposed"],
            "scope": "fixture",
            "run_id": "fixture",
            "git_head": "fixture",
            "models": {"judge_models": []},
            "budget": {"max_transport_calls": 0},
        },
    )
    run.write(tmp_path / "inputs/tasks.json", [{"id": "p"}])
    run.write(tmp_path / "run-01/calls.json", [])
    run.write(tmp_path / "run-01/bindings/p.json", {"proposed": result})
    counts = run.summarize(tmp_path)["per_method"]["proposed"]
    assert counts["bound"] == 1
    assert counts["partial_evidence"] == 1
    assert counts["statuses"] == {"BOUND_PARTIAL_EVIDENCE": 1}
