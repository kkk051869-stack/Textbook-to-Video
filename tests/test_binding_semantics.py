"""Deterministic coverage/repair fixtures, not independent semantic gold."""

import base64
import hashlib
import json

import pytest
import test_context_binding_repair as fixtures

from textbook2video.research import binding_methods as b

SOURCE, response, binding_case = fixtures.SOURCE, fixtures.response, fixtures.case


@pytest.fixture
def semantic_case(binding_case, tmp_path):
    image = tmp_path / "fixture.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII="
        )
    )
    full = {"local_path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    for c in binding_case[1]:
        c.update(full)
    return binding_case, full


def check_reply(verdict="SUFFICIENT", ids=("pump", "water")):
    return {
        "verdict": verdict,
        "source_claim": SOURCE,
        "required_relations": ["Movement from actor to patient"],
        "object_relevance": "RELEVANT",
        "satisfied_relations": [
            {
                "relation": "Movement from actor to patient",
                "source_quote": SOURCE,
                "candidate_ids": list(ids),
                "visual_evidence": "Fixture asserts an arrow from actor to patient.",
            }
        ],
        "missing_relations": ["Movement arrow is missing"] if verdict == "INSUFFICIENT" else [],
        "uncertainties": ["Cannot read connector"] if verdict == "UNCERTAIN" else [],
        "explanation": "Fixture judgment of relation coverage, not true pixel review.",
    }


def run(semantic_case, checker, model=None, initial=None, **kwargs):
    case, full = semantic_case
    return b.bind_source_conditioned(
        case[0],
        case[1],
        context_model_fn=model or (lambda _: json.dumps(response())),
        context_method_version=b.CONTEXT_SEMANTIC_VERSION,
        initial_context_response=json.dumps(response() if initial is None else initial),
        source_evidence=case[2],
        semantic_full_figure=full,
        semantic_model_fn=checker,
        **kwargs,
    )


def test_checker_isolated_from_binder_explanations_and_receives_all_pixels(semantic_case):
    def checker(prompt, paths):
        request = json.loads(prompt)
        assert "selection_review" not in prompt
        assert "assessment_by_candidate" not in prompt
        assert request["narration"] == SOURCE
        assert request["textbook_evidence"]["source_context"] == SOURCE
        assert len(paths) == len(request["visual_evidence"]["images"]) == 4
        assert request["visual_evidence"]["selected_candidate_ids"] == ["pump", "water"]
        return json.dumps(check_reply())

    result = run(semantic_case, checker)
    assert result["status"] == "BOUND_MULTIPLE"
    assert result["context_method_version"] == b.CONTEXT_SEMANTIC_VERSION
    assert result["semantic_verification_status"] == "MODEL_ASSISTED_SUFFICIENT_NOT_GOLD"
    assert result["visual_explanation_status"] == "NOT_EVALUATED"
    assert result["semantic_model_calls"] == 1


def test_insufficient_feedback_reselects_and_rechecks_without_preset_answer(semantic_case):
    checks = iter([check_reply("INSUFFICIENT"), check_reply(ids=("whole",))])

    def binder(prompt):
        p = json.loads(prompt)
        issue = p["repair_context"]["validation_issues"][0]
        assert issue["code"] == "SEMANTIC_INSUFFICIENT"
        assert issue["missing_relations"] == ["Movement arrow is missing"]
        assert {c["id"] for c in p["candidates"]} == {"pump", "water", "whole"}
        assert "expected_candidate" not in json.dumps(issue)
        return json.dumps(response(("whole",)))

    result = run(semantic_case, lambda *_: json.dumps(next(checks)), binder)
    assert result["selected_candidate_id"] == "whole"
    assert result["model_calls"] == 1 and result["semantic_model_calls"] == 2
    assert len(result["repair_trace"]) == 2
    assert result["repair_trace"][0]["validated_binding"]["selected_candidate_ids"] == [
        "pump",
        "water",
    ]


def test_insufficient_then_abstain_preserves_failure_but_returns_no_binding(semantic_case):
    result = run(
        semantic_case,
        lambda *_: json.dumps(check_reply("INSUFFICIENT")),
        lambda _: json.dumps(response(())),
    )
    assert result["status"].startswith("ABSTAINED")
    assert result["selected_candidate_ids"] == []
    assert result["semantic_check"]["verdict"] == "INSUFFICIENT"
    assert result["semantic_verification_status"] == "NOT_CHECKED_ABSTENTION"


@pytest.mark.parametrize(
    "verdict,status",
    [("UNCERTAIN", "SEMANTIC_UNCERTAIN"), ("INSUFFICIENT", "SEMANTIC_CHECK_FAILED")],
)
def test_unresolved_semantics_cannot_leak_structurally_valid_binding(
    semantic_case, verdict, status
):
    result = run(semantic_case, lambda *_: json.dumps(check_reply(verdict)), max_repair_rounds=0)
    assert result["status"] == status
    assert result["selected_candidate_id"] is None
    assert result["selected_candidate_ids"] == []
    assert result["repair_trace"][0]["semantic_check"]["raw_response"]


def test_repeated_semantic_failure_stops_and_never_retains_prior_unchecked_binding(semantic_case):
    result = run(semantic_case, lambda *_: json.dumps(check_reply("INSUFFICIENT")))
    assert result["repair_status"] == "REPEATED_ERRORS"
    assert result["semantic_model_calls"] == 2
    assert result["status"] == "SEMANTIC_CHECK_FAILED"


@pytest.mark.parametrize("bad", ["quote", "unselected", "contradiction", "invalid_json"])
def test_checker_invalid_or_unsupported_evidence_is_uncertain_not_success(semantic_case, bad):
    value = check_reply()
    if bad == "quote":
        value["satisfied_relations"][0]["source_quote"] = "Invented source"
    elif bad == "unselected":
        value["satisfied_relations"][0]["candidate_ids"] = ["whole"]
    elif bad == "contradiction":
        value["missing_relations"] = ["Required relation absent"]
    result = run(
        semantic_case,
        lambda *_: "invalid" if bad == "invalid_json" else json.dumps(value),
        max_repair_rounds=0,
    )
    assert result["status"] == "SEMANTIC_UNCERTAIN"
    assert result["repair_trace"][0]["issues"][0]["code"] == "SEMANTIC_CHECK_INVALID"


def test_pixel_hash_failure_prevents_any_model_call(semantic_case):
    semantic_case[1]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="image hash mismatch"):
        run(
            semantic_case,
            lambda *_: pytest.fail("Must not call checker"),
            lambda _: pytest.fail("Must not call binder"),
        )


def test_checker_timeout_stops_without_passing_semantics(semantic_case):
    def fail(*_):
        raise TimeoutError("transport timeout")

    result = run(semantic_case, fail)
    assert result["repair_status"] == "MODEL_CALL_TIMEOUT"
    assert result["semantic_model_calls"] == 1
    assert result["selected_candidate_id"] is None


def test_empty_selection_does_not_claim_semantic_pass(semantic_case):
    result = run(semantic_case, lambda *_: pytest.fail("No selected pixels"), initial=response(()))
    assert result["semantic_model_calls"] == 0
    assert result["semantic_verification_status"] == "NOT_CHECKED_ABSTENTION"
