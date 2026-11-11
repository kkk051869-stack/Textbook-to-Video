"""Engineering fixtures: repair orchestration and evidence boundaries, not semantic gold."""

import copy
import hashlib
import json

import pytest

from textbook2video.research import binding_methods as b

SOURCE = "Pump moves water into Tank. Tank stores water."


@pytest.fixture
def case(tmp_path):
    path = tmp_path / "raw.txt"
    path.write_bytes(SOURCE.encode())
    prop = {"id": "p", "text": SOURCE, "source_refs": ["source"], "source_context": SOURCE}
    candidates = [
        {"id": "pump", "text": "Pump", "source_locator": "page 1 figure 1"},
        {"id": "water", "text": "water", "source_locator": "page 1 figure 1"},
        {"id": "whole", "text": SOURCE, "source_locator": "page 1 figure 1"},
    ]
    evidence = {
        "document": {"raw_path": str(path), "sha256": hashlib.sha256(SOURCE.encode()).hexdigest()},
        "source_units": [
            {
                "id": "source",
                "text": SOURCE,
                "source_locator": "page 1",
                "char_span": {"start": 0, "end": len(SOURCE)},
            }
        ],
    }
    return prop, candidates, evidence


def response(selected=("pump", "water")):
    value = {"assessment_by_candidate": {}}
    for ident, focus, role in [
        ("pump", "Pump", "actor"),
        ("water", "water", "patient"),
        ("whole", SOURCE, "relation"),
    ]:
        value["assessment_by_candidate"][ident] = {
            "support": "SUPPORTED",
            "polarity": "AFFIRMED",
            "source_quotes": [SOURCE],
            "actor_quote": "Pump",
            "action_quote": "moves",
            "patient_quote": "water",
            "candidate_label_quote": focus,
            "attention_role": role,
            "focus_quote": focus,
            "explanation": "Fixture assertion of role support.",
        }
    value["selected_candidate_ids"] = list(selected)
    value["selection_review"] = {
        "coverage": "SUFFICIENT" if selected else "INSUFFICIENT",
        "minimal": True,
        "source_quotes": [SOURCE],
        "member_contributions": {k: "Explains this relation." for k in selected},
        "explanation": "Selected members explain the narrated relation; "
        "alternatives need not be selected.",
    }
    if len(selected) > 1:
        value["joint_focus"] = {
            "candidate_ids": list(selected),
            "source_quotes": [SOURCE],
            "explanation": "Members jointly explain movement from actor to patient.",
        }
    return value


def invoke(case, model=None, initial=None, **kwargs):
    prop, pool, evidence = case
    original = copy.deepcopy(case)
    result = b.bind_source_conditioned(
        prop,
        pool,
        context_model_fn=model or (lambda _: json.dumps(response())),
        context_method_version=b.CONTEXT_REVISABLE_VERSION,
        source_evidence=evidence,
        initial_context_response=json.dumps(initial) if isinstance(initial, dict) else initial,
        **kwargs,
    )
    assert case == original
    return result


def test_supported_alternatives_not_forced_into_joint(case):
    result = invoke(case)
    assert result["status"] == "BOUND_MULTIPLE"
    assert result["selected_candidate_ids"] == ["pump", "water"]
    assert result["supported_candidate_ids"] == ["pump", "water", "whole"]
    assert result["joint_required_candidate_ids"] == ["pump", "water"]
    assert result["selected_candidate_id"] is None
    assert result["downstream_compatibility"] == "MULTI_TARGET_ADAPTER_REQUIRED"
    assert result["visual_explanation_status"] == "NOT_EVALUATED"
    assert "NOT_INDEPENDENTLY_PROVEN" in result["semantic_verification_status"]


def test_singular_interface_and_declared_abstention(case):
    single = invoke(case, initial=response(("whole",)))
    assert single["selected_candidate_id"] == "whole"
    assert single["selected_candidate_ids"] == ["whole"]
    assert single["downstream_compatibility"] == "SINGLE_TARGET_COMPATIBLE"
    abstain = invoke(case, initial=response(()))
    assert abstain["status"] == "ABSTAINED_INSUFFICIENT_RELATION_COVERAGE"
    assert abstain["model_calls"] == 0
    assert abstain["selected_candidate_ids"] == []


def test_feedback_retains_all_inputs_and_locates_independent_errors(case):
    bad = response()
    bad["assessment_by_candidate"]["pump"]["source_quotes"] = ["Invented quote."]
    bad["assessment_by_candidate"]["water"]["attention_role"] = "invented-role"
    prompts = []

    def repair(prompt):
        value = json.loads(prompt)
        prompts.append(value)
        issues = value["repair_context"]["validation_issues"]
        assert any(i["path"] == "/assessment_by_candidate/pump/source_quotes/0" for i in issues)
        assert any(i["path"] == "/assessment_by_candidate/water/attention_role" for i in issues)
        assert all(i["source_locator"] == "page 1 figure 1" for i in issues)
        assert value["repair_context"]["previous_response"] == json.dumps(bad)
        assert {c["id"] for c in value["candidates"]} == {"pump", "water", "whole"}
        # The model may select a different adequate set; feedback names no desired choice.
        return json.dumps(response(("whole",)))

    result = invoke(case, repair, bad)
    assert result["repair_status"] == "COMPLETED"
    assert result["model_calls"] == 1
    assert result["repair_rounds"] == 1
    assert result["selected_from_round"] == 1
    assert result["selected_candidate_id"] == "whole"
    assert len(prompts) == 1
    assert len(result["repair_trace"]) == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ("unknown", "SCHEMA"),
        ("joint", "JOINT_SELECTION_MISMATCH"),
        ("role", "SCHEMA"),
        ("focus", "ROLE_QUOTE_UNANCHORED"),
        ("support", "SELECTED_WITHOUT_SUPPORT"),
        ("coverage", "INSUFFICIENT_SELECTION"),
        ("joint_quote", "JOINT_QUOTE_NOT_FOUND"),
        ("member", "MEMBER_CONTRIBUTIONS"),
    ],
)
def test_invalid_selection_never_silently_repaired(case, change, code):
    value = response()
    if change == "unknown":
        value["selected_candidate_ids"] = ["missing"]
    elif change == "joint":
        value["joint_focus"]["candidate_ids"] = ["pump", "whole"]
    elif change == "role":
        value["assessment_by_candidate"]["pump"]["attention_role"] = "magical"
    elif change == "focus":
        value["assessment_by_candidate"]["pump"]["focus_quote"] = "Imaginary operator"
    elif change == "support":
        value["assessment_by_candidate"]["pump"]["support"] = "UNCERTAIN"
    elif change == "coverage":
        value["selection_review"]["coverage"] = "INSUFFICIENT"
    elif change == "joint_quote":
        value["joint_focus"]["source_quotes"] = ["Fabricated relation"]
    else:
        value["selection_review"]["member_contributions"] = {"pump": "Only one explained"}
    result = invoke(case, initial=value, max_repair_rounds=0)
    assert result["status"] == "REPAIR_FAILED"
    assert code in {i["code"] for i in result["repair_trace"][0]["issues"]}
    assert result["selected_candidate_id"] is None


def test_role_and_quote_can_be_corrected_without_target_hint(case):
    bad = response(("pump",))
    bad["assessment_by_candidate"]["pump"]["attention_role"] = "unknown"
    fixed = response(("pump",))
    fixed["assessment_by_candidate"]["pump"]["attention_role"] = "action"
    fixed["assessment_by_candidate"]["pump"]["focus_quote"] = "moves"
    result = invoke(case, lambda _: json.dumps(fixed), bad)
    assert result["repair_status"] == "COMPLETED"
    assert result["evidence"][0]["attention_role"] == "action"


def test_honest_abstention_after_error(case):
    result = invoke(case, lambda _: json.dumps(response(())), "invalid JSON")
    assert result["status"].startswith("ABSTAINED")
    assert result["repair_status"] == "COMPLETED"
    assert result["model_calls"] == 1


def test_repeated_errors_stop_before_budget(case):
    def same_error(prompt):
        value = response()
        value["selection_review"]["coverage"] = "INSUFFICIENT"
        value["selection_review"]["explanation"] = str(len(prompt))
        return json.dumps(value)

    result = invoke(case, same_error)
    assert result["repair_status"] == "REPEATED_ERRORS"
    assert result["model_calls"] == 2
    assert result["status"] == "REPAIR_FAILED"


def test_default_three_repair_rounds_bound_distinct_errors(case):
    fields = iter(["coverage", "minimal", "source_quotes", "explanation"])

    def different_errors(_):
        value = response()
        del value["selection_review"][next(fields)]
        return json.dumps(value)

    result = invoke(case, different_errors)
    assert result["repair_status"] == "MAX_REPAIR_ROUNDS"
    assert result["model_calls"] == 4
    assert result["repair_rounds"] == 3


@pytest.mark.parametrize(
    "exception,reason",
    [
        (TimeoutError("timeout"), "MODEL_CALL_TIMEOUT"),
        (RuntimeError("offline"), "MODEL_CALL_FAILED"),
    ],
)
def test_transport_failures_stop(case, exception, reason):
    def fail(_):
        raise exception

    result = invoke(case, fail)
    assert result["repair_status"] == reason
    assert result["model_calls"] == 1


def test_input_hash_failure_never_asks_model_to_fix_provenance(case):
    case[2]["document"]["sha256"] = "0" * 64
    result = invoke(case, lambda _: pytest.fail("Invalid input must not call model"))
    assert result["repair_status"] == "INVALID_INPUT"
    assert result["model_calls"] == 0


def test_local_unselected_failure_is_not_silent_and_retains_earlier_partial(case):
    value = response(("pump",))
    value["assessment_by_candidate"]["whole"]["source_quotes"] = ["invented"]
    result = invoke(case, lambda _: "invalid", value)
    assert result["status"] == "BOUND_PARTIAL_EVIDENCE"
    assert result["selected_from_round"] == 0
    assert result["selected_candidate_id"] == "pump"
    assert result["rejected_candidate_ids"] == ["whole"]
    assert result["validation_warnings"]
    assert result["repair_status"] == "REPEATED_ERRORS"


def test_deadline_detects_late_response(case, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(b.time, "monotonic", lambda: clock[0])

    def late(_):
        clock[0] = 2.0
        return json.dumps(response())

    result = invoke(case, late, repair_deadline_sec=1)
    assert result["repair_status"] == "DEADLINE_EXCEEDED"
    assert result["status"] == "REPAIR_FAILED"


def test_legacy_default_still_uses_original_joint_rule(case):
    prop, candidates, _ = case
    value = response()
    del value["selection_review"], value["selected_candidate_ids"]
    with pytest.raises(ValueError, match="exactly match"):
        b.bind_source_conditioned(prop, candidates, context_model_fn=lambda _: json.dumps(value))


def test_new_version_requires_explicit_model_interface(case):
    with pytest.raises(ValueError, match="context_model_fn"):
        b.bind_source_conditioned(
            case[0], case[1], context_method_version=b.CONTEXT_REVISABLE_VERSION
        )


@pytest.mark.parametrize(
    "role,focus",
    [
        ("actor", "Pump"),
        ("patient", "water"),
        ("input", "water"),
        ("output", "water"),
        ("relation", SOURCE),
    ],
)
def test_new_version_keeps_teaching_roles_and_requires_model_semantic_review(case, role, focus):
    value = response(("whole",))
    value["assessment_by_candidate"]["whole"]["attention_role"] = role
    value["assessment_by_candidate"]["whole"]["focus_quote"] = focus
    result = invoke(case, initial=value)
    assert result["status"] == "BOUND"
    assert result["evidence"][2]["attention_role"] == role
    # This fixture proves anchoring/enum support, never that a quoted word entails its claimed role.
    assert result["semantic_verification_status"] == "MODEL_SELF_REVIEWED_NOT_INDEPENDENTLY_PROVEN"


def test_prompt_uses_stable_id_and_allows_uncertainty_without_actor_only_rules(case):
    def model(prompt):
        payload = json.loads(prompt)
        assert not any(r in payload["rules"] for r in b.ACTOR_BINDING_RULES)
        assert not any("a literal candidate_label_quote" in r for r in payload["rules"])
        assert (
            "action"
            in payload["output_json_schema"]["properties"]["assessment_by_candidate"]["properties"][
                "pump"
            ]["properties"]["attention_role"]["enum"]
        )
        return json.dumps(response(()))

    assert invoke(case, model)["status"] == "ABSTAINED_INSUFFICIENT_RELATION_COVERAGE"
