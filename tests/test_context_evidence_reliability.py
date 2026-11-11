"""Mechanical evidence regressions; no model calls or semantic gold."""

import copy
import hashlib
import json

import pytest

from textbook2video.research import binding_methods as b


def sidecar(tmp_path, raw):
    path = tmp_path / "raw.txt"
    path.write_bytes(raw.encode())
    return {
        "document": {"raw_path": str(path), "sha256": hashlib.sha256(raw.encode()).hexdigest()},
        "source_units": [
            {
                "id": "source",
                "text": raw.strip(),
                "source_locator": "PDF page 1 extracted text",
                "char_span": {"start": 0, "end": len(raw)},
            }
        ],
    }


def binding(
    tmp_path,
    *,
    raw="Pump moves water.",
    quote=None,
    label="Pump",
    role="actor",
    validation=None,
    focus="Pump",
    candidate_ids=None,
    joint=None,
):
    context = " ".join(raw.split())
    prop = {
        "id": "p",
        "segment_id": "s",
        "text": context,
        "source_refs": ["source"],
        "source_context": context,
    }
    candidates = [{"id": "pump", "text": "Pump"}, {"id": "water", "text": "water"}]
    rows = {
        "pump": {
            "support": "SUPPORTED",
            "polarity": "AFFIRMED",
            "source_quotes": [context if quote is None else quote],
            "actor_quote": None,
            "action_quote": None,
            "patient_quote": None,
            "candidate_label_quote": label,
            "attention_role": role,
            "focus_quote": focus,
            "explanation": "Fixture asserts source support.",
        },
        "water": {
            "support": "NOT_SUPPORTED",
            "polarity": "UNRESOLVED",
            "source_quotes": [],
            "actor_quote": None,
            "action_quote": None,
            "patient_quote": None,
            "candidate_label_quote": None,
            "attention_role": None,
            "focus_quote": None,
            "explanation": "Not this focus.",
        },
    }
    if candidate_ids is not None:
        rows[candidate_ids] = rows.pop("pump")
    response = {"assessment_by_candidate": rows}
    if joint:
        response["joint_focus"] = joint
    original = copy.deepcopy(response)
    result = b.bind_source_conditioned(
        prop,
        candidates,
        context_model_fn=lambda _: json.dumps(response),
        evidence_validation_version=validation or b.CONTEXT_EVIDENCE_VERSION,
        source_evidence=sidecar(tmp_path, raw),
    )
    assert response == original
    return result


def test_verified_pdf_hyphen_match_preserves_raw_and_context_spans(tmp_path):
    raw = "The black-\nbox Pump moves water. A blackbox label exists."
    result = binding(tmp_path, raw=raw, quote="The blackbox Pump moves water.")
    anchor = result["evidence"][0]["source_quote_anchors"][0][0]
    assert anchor["raw_source_text"] == raw[anchor["raw_start"] : anchor["raw_end"]]
    context = " ".join(raw.split())
    assert anchor["source_text"] == context[anchor["start"] : anchor["end"]]
    assert anchor["match_mode"] == "verified_pdf_linebreak_equivalent"
    assert anchor["source_ref"] == "source"


def test_legacy_policy_does_not_silently_accept_new_normalization(tmp_path):
    with pytest.raises(ValueError, match="source quote"):
        binding(
            tmp_path,
            raw="The black-\nbox Pump moves water. A blackbox label exists.",
            quote="The blackbox Pump moves water.",
            validation="context-evidence-v1.1",
        )


@pytest.mark.parametrize(
    "source,quote",
    [
        ("re calculate", "recalculate"),
        ("black- box", "blackbox"),
        ("x-\ny", "xy"),
        ("ab-\ncd", "abcd"),
        ("re-\ncreation", "recreation"),
        ("x²", "x2"),
        ("Pump does not move water.", "Pump moves water."),
        ("input-\nand output", "inputand output"),
        ("Pump moves gold.", "Pump moves water."),
    ],
)
def test_no_fuzzy_math_negation_or_ordinary_space_changes(tmp_path, source, quote):
    evidence = sidecar(tmp_path, source)
    context = " ".join(source.split())
    regions = b._context_source_regions(context, ["source"], evidence)
    assert b._evidence_anchors(context, quote, regions) == []


def test_unproven_collapsed_linebreak_never_dehyphenates():
    assert b._evidence_anchors("black- box", "blackbox", []) == []


def test_raw_hash_and_reference_scope_checked(tmp_path):
    evidence = sidecar(tmp_path, "Pump moves water.")
    with pytest.raises(ValueError, match="source_refs"):
        b._context_source_regions("Pump moves water.", ["different"], evidence)
    evidence["document"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        b._context_source_regions("Pump moves water.", ["source"], evidence)


def test_stable_id_not_copied_name_controls_identity(tmp_path):
    result = binding(tmp_path, label="function Pump()")
    assert result["selected_candidate_id"] == "pump"
    assert result["evidence"][0]["identity_basis"] == "stable_candidate_id"
    assert result["evidence"][0]["label_copy_matches"] is False
    assert result["evidence"][0]["candidate_label_quote"] == "function Pump()"


def test_unknown_id_and_explicit_other_candidate_identity_stay_invalid(tmp_path):
    with pytest.raises(ValueError, match="schema"):
        binding(tmp_path, candidate_ids="unknown")
    with pytest.raises(ValueError, match="another stable"):
        binding(tmp_path, label="water")


def test_action_is_explicit_enum_not_unrestricted_alias(tmp_path):
    assert binding(tmp_path, role="action")["status"] == "BOUND"
    with pytest.raises(ValueError, match="schema"):
        binding(tmp_path, role="invented-role")


def test_focus_still_must_belong_to_submitted_quotes_not_elsewhere(tmp_path):
    with pytest.raises(ValueError, match="focus_quote"):
        binding(
            tmp_path,
            raw="Pump moves water. Tank stores gold.",
            quote="Pump moves water.",
            focus="Tank",
        )


def test_joint_subset_conflict_is_not_repaired_by_format_policy(tmp_path):
    with pytest.raises(ValueError, match="joint focus"):
        binding(
            tmp_path,
            joint={
                "candidate_ids": ["pump", "water"],
                "source_quotes": ["Pump moves water."],
                "explanation": "A claimed relation, but water not supported.",
            },
        )


def test_original_collapsed_spelling_remains_valid_with_pdf_provenance(tmp_path):
    result = binding(
        tmp_path,
        raw="The black-\nbox Pump moves water. A blackbox label exists.",
        quote="The black- box Pump moves water.",
    )
    assert result["selected_candidate_id"] == "pump"


def test_nested_focus_quote_keeps_raw_role_offsets(tmp_path):
    raw = "The black-\nbox Pump moves water. A blackbox label exists."
    result = binding(tmp_path, raw=raw, quote="The blackbox Pump moves water.", focus="blackbox")
    anchor = result["evidence"][0]["role_anchors"]["focus_quote"][0]
    assert raw[anchor["raw_start"] : anchor["raw_end"]] == "black-\nbox"
    context = " ".join(raw.split())
    assert context[anchor["start"] : anchor["end"]] == "black- box"


def test_unreferenced_context_cannot_supply_replacement_evidence(tmp_path):
    evidence = sidecar(tmp_path, "Pump moves water.")
    context = "Pump moves water. Tank stores gold."
    regions = b._context_source_regions(context, ["source"], evidence)
    assert b._evidence_anchors(context, "Tank stores gold.", regions) == []
