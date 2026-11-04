from __future__ import annotations

import json

import pytest

from textbook2video.research.rq1_preference_judge import (
    build_canonical_decision_judge_prompt,
    canonical_proposal_groups,
    normalize_canonical_set_judgment,
)


def _row(action: str, *, uncertain: bool = False, source_id: str | None = None,
         object_id: str | None = None, digest: str | None = None, query: str = "unused") -> dict:
    acquisition = {"assets": []}
    if object_id or digest:
        acquisition["assets"].append({
            "status": "RETRIEVED_LOCAL_RAG",
            "catalog_candidate_id": object_id,
            "sha256": digest,
        })
    return {
        "status": "OK",
        "decision": {
            "action": action,
            "decision_state": "UNCERTAIN" if uncertain else "DECIDED",
            "abstain": uncertain,
            "uncertain": uncertain,
            "source_image_id": source_id,
            "retrieval_query": query,
            "rationale": "This field must not enter the decision Judge view.",
            "generation_prompt": "This field must not enter the decision Judge view.",
        },
        "acquisition": acquisition,
    }


def test_decision_groups_keep_uncertainty_and_reuse_object_identity() -> None:
    grouped = canonical_proposal_groups(
        {
            "reuse-a": _row("reuse", source_id="source-a"),
            "reuse-a-copy": _row("reuse", source_id="source-a"),
            "reuse-b": _row("reuse", source_id="source-b"),
            "reuse-a-uncertain": _row("reuse", source_id="source-a", uncertain=True),
        },
        source_image_hashes={"source-a": "hash-a", "source-b": "hash-b"},
    )

    mapping = grouped["method_to_proposal"]
    assert mapping["reuse-a"] == mapping["reuse-a-copy"]
    assert mapping["reuse-a"] != mapping["reuse-b"]
    assert mapping["reuse-a"] != mapping["reuse-a-uncertain"]
    assert len(grouped["groups"]) == 3


def test_decision_equivalence_does_not_erase_different_material_objects() -> None:
    grouped = canonical_proposal_groups({
        "retrieval-one": _row("retrieve", object_id="candidate-one", digest="hash-one", query="long query"),
        "retrieval-two": _row("retrieve", object_id="candidate-two", digest="hash-two", query="short"),
    })

    assert grouped["method_to_proposal"]["retrieval-one"] == grouped["method_to_proposal"]["retrieval-two"]
    method_material = grouped["material_by_method"]
    assert method_material["retrieval-one"]["object_id"] != method_material["retrieval-two"]["object_id"]
    assert method_material["retrieval-one"]["sha256"] != method_material["retrieval-two"]["sha256"]
    variants = grouped["groups"][0]["material_variants"]
    assert len(variants) == 2


def test_forward_reverse_prompt_changes_only_proposal_order_and_has_fixed_fields() -> None:
    proposals = [
        {"proposal_id": "p1", "proposal_status": "DECISION_AVAILABLE", "action": "none"},
        {"proposal_id": "p2", "proposal_status": "DECISION_AVAILABLE", "action": "retrieve"},
    ]
    common = {
        "proposition_id": "claim-1",
        "proposition_text": "A fixed claim.",
        "source_context": [{"id": "src-1", "exact_claim_quote": "A fixed claim."}],
        "proposals": proposals,
        "attached_image_labels": ["source-image-01"],
    }
    forward = json.loads(build_canonical_decision_judge_prompt(**common, display_order="forward"))
    reverse = json.loads(build_canonical_decision_judge_prompt(**common, display_order="reverse"))
    repeated = build_canonical_decision_judge_prompt(**common, display_order="forward")

    assert forward["proposals_in_display_order"] == proposals
    assert reverse["proposals_in_display_order"] == list(reversed(proposals))
    assert repeated == build_canonical_decision_judge_prompt(**common, display_order="forward")
    for key in forward:
        if key != "proposals_in_display_order":
            assert forward[key] == reverse[key]
    prompt = json.dumps(forward, ensure_ascii=False)
    for forbidden in ("method_id", "rationale", "retrieval_query", "generation_prompt", "acquisition_status"):
        assert forbidden not in prompt
    assert "same page" in prompt
    assert "fails to return an asset" in prompt


def _judgment() -> dict:
    return {
        "acceptable_proposal_ids": ["p1", "p2"],
        "rejected_proposal_ids": ["p3"],
        "preferred_proposal_ids": ["p1", "p2"],
        "uncertain_proposal_ids": ["p2"],
        "abstain": False,
        "uncertainty_reason": None,
        "assessment_by_proposal": {
            proposal_id: {
                "visual_need": "NEEDED",
                "source_sufficiency": "INSUFFICIENT",
                "action_fit": "APPROPRIATE",
                "uncertainty_fit": "UNCERTAIN",
            }
            for proposal_id in ("p1", "p2", "p3")
        },
        "strict_ranking": None,
    }


def test_set_judgment_allows_ties_and_uncertainty_without_forced_ranking() -> None:
    normalized = normalize_canonical_set_judgment(
        _judgment(),
        eligible_proposal_ids=["p1", "p2", "p3"],
        proposition_id="claim-1",
        judge_alias="judge-a",
        display_order="forward",
    )
    assert normalized["preferred_proposal_ids"] == ["p1", "p2"]
    assert normalized["strict_ranking_diagnostic"] is None
    assert normalized["uncertain_proposal_ids"] == ["p2"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(acceptable_proposal_ids=["p1", "p1"]),
        lambda value: value.update(preferred_proposal_ids=["p3"]),
        lambda value: value.update(rejected_proposal_ids=["p1"]),
        lambda value: value.update(strict_ranking=["p1", "p1", "p3"]),
        lambda value: value["assessment_by_proposal"].pop("p3"),
    ],
)
def test_set_judgment_rejects_duplicate_conflicting_or_incomplete_outputs(mutate) -> None:
    value = _judgment()
    mutate(value)
    with pytest.raises(ValueError):
        normalize_canonical_set_judgment(
            value,
            eligible_proposal_ids=["p1", "p2", "p3"],
            proposition_id="claim-1",
            judge_alias="judge-a",
            display_order="forward",
        )


def test_set_judgment_requires_abstention_reason() -> None:
    value = _judgment()
    value["abstain"] = True
    with pytest.raises(ValueError, match="uncertainty_reason"):
        normalize_canonical_set_judgment(
            value,
            eligible_proposal_ids=["p1", "p2", "p3"],
            proposition_id="claim-1",
            judge_alias="judge-a",
            display_order="forward",
        )
