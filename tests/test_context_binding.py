import copy
import json

import pytest

from textbook2video.research.binding_methods import _quote_anchors, bind_source_conditioned

PROP = {
    "id": "p",
    "segment_id": "s",
    "text": "It moves water.",
    "source_refs": ["sentence-1"],
    "source_context": "Pump moves water. Valve blocks air.",
}
CANDIDATES = [
    {"id": "pump", "segment_id": "s", "text": "Pump", "source_refs": ["pump-label"]},
    {"id": "valve", "segment_id": "s", "text": "Valve", "source_refs": ["valve-label"]},
]


def response():
    return {
        "assessment_by_candidate": {
            "pump": {
                "support": "SUPPORTED",
                "polarity": "AFFIRMED",
                "source_quotes": ["Pump moves water."],
                "actor_quote": "Pump",
                "action_quote": "moves",
                "patient_quote": "water",
                "candidate_label_quote": "Pump",
                "explanation": "The antecedent performs the action.",
            },
            "valve": {
                "support": "NOT_SUPPORTED",
                "polarity": "UNRESOLVED",
                "source_quotes": [],
                "actor_quote": None,
                "action_quote": None,
                "patient_quote": None,
                "candidate_label_quote": None,
                "explanation": "No support for this role.",
            },
        }
    }


def test_context_mode_binds_distinct_source_ids_without_mutating_candidates():
    original = copy.deepcopy(CANDIDATES)

    def model(prompt):
        value = json.loads(prompt)
        assert value["source_context"] == PROP["source_context"]
        assert [c["id"] for c in value["candidates"]] == ["pump", "valve"]
        assert "expected" not in value
        return json.dumps(response())

    result = bind_source_conditioned(PROP, CANDIDATES, context_model_fn=model)
    assert result["selected_candidate_id"] == "pump"
    assert result["threshold"] == 0.45
    assert result["source_support_mode"] == "context_role_model"
    assert result["evidence"][0]["validation"] == "LITERAL_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
    assert CANDIDATES == original


def test_whitespace_quote_keeps_raw_response_and_exact_source_offsets():
    prop = {**PROP, "source_context": "Pump moves\n  water. Valve blocks air."}
    data = response()
    data["assessment_by_candidate"]["pump"]["source_quotes"] = ["Pump  moves water."]
    original = copy.deepcopy(data)
    result = bind_source_conditioned(prop, CANDIDATES, context_model_fn=lambda _: json.dumps(data))
    evidence = result["evidence"][0]
    assert evidence["source_quotes"] == ["Pump  moves water."]
    anchor = evidence["source_quote_anchors"][0][0]
    assert prop["source_context"][anchor["start"] : anchor["end"]] == "Pump moves\n  water."
    assert anchor["match_mode"] == "whitespace_equivalent"
    patient = evidence["role_anchors"]["patient_quote"][0]
    assert prop["source_context"][patient["start"] : patient["end"]] == "water"
    assert result["selected_candidate_id"] == "pump"
    assert data == original


@pytest.mark.parametrize(
    "quote", ["Pumpmoves water.", "Pump moves gold.", "Pump MOVES water.", "Pump moves water!"]
)
def test_format_matching_never_changes_words_case_or_punctuation(quote):
    data = response()
    data["assessment_by_candidate"]["pump"]["source_quotes"] = [quote]
    with pytest.raises(ValueError):
        bind_source_conditioned(PROP, CANDIDATES, context_model_fn=lambda _: json.dumps(data))


def test_repeated_quotes_keep_all_source_occurrences():
    prop = {**PROP, "source_context": "Pump moves water. Pump moves water."}
    result = bind_source_conditioned(
        prop, CANDIDATES, context_model_fn=lambda _: json.dumps(response())
    )
    anchors = result["evidence"][0]["source_quote_anchors"][0]
    assert [a["start"] for a in anchors] == [0, 18]


@pytest.mark.parametrize("action", ["is used ... for obtaining", "used by … for obtaining"])
def test_discontinuous_role_quotes_stay_invalid_after_prompt_clarification(action):
    prop = {**PROP, "source_context": "Pump is used by operators for obtaining water."}
    data = response()
    row = data["assessment_by_candidate"]["pump"]
    row["source_quotes"] = [prop["source_context"]]
    row["action_quote"] = action

    def model(prompt):
        rules = json.loads(prompt)["rules"]
        assert any("ONE contiguous" in rule for rule in rules)
        assert any("interpretation only in explanation" in rule for rule in rules)
        return json.dumps(data)

    with pytest.raises(ValueError, match="action_quote"):
        bind_source_conditioned(prop, CANDIDATES, context_model_fn=model)


def test_passive_contiguous_action_keeps_source_span_without_inventing_full_predicate():
    prop = {**PROP, "source_context": "Pump is used by operators for obtaining water."}
    data = response()
    row = data["assessment_by_candidate"]["pump"]
    row["source_quotes"] = [prop["source_context"]]
    row["action_quote"] = "for obtaining"
    result = bind_source_conditioned(prop, CANDIDATES, context_model_fn=lambda _: json.dumps(data))
    anchor = result["evidence"][0]["role_anchors"]["action_quote"][0]
    assert prop["source_context"][anchor["start"]:anchor["end"]] == "for obtaining"
    assert result["selected_candidate_id"] == "pump"


def test_normalized_role_still_must_belong_to_quoted_source():
    data = response()
    data["assessment_by_candidate"]["pump"]["actor_quote"] = "Valve"
    prop = {**PROP, "source_context": "Pump moves\nwater. Valve blocks air."}
    with pytest.raises(ValueError, match="actor_quote"):
        bind_source_conditioned(prop, CANDIDATES, context_model_fn=lambda _: json.dumps(data))


def test_latin_ligature_match_retains_exact_original_span():
    source = "The motion vector is deﬁned in Step 1."
    quote = "The motion vector is defined in Step 1."
    anchors = _quote_anchors(source, quote)
    assert len(anchors) == 1
    assert source[anchors[0]["start"] : anchors[0]["end"]] == source
    assert anchors[0]["match_mode"] == "latin_ligature_equivalent"


@pytest.mark.parametrize(
    "source,quote", [("ﬁ", "f"), ("ﬁ", "i"), ("ˆxt", "^xt"), ("x−y", "x-y"), ("x²", "x2")]
)
def test_typography_matching_does_not_split_glyphs_or_change_math(source, quote):
    assert _quote_anchors(source, quote) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_quotes", ["Fabricated source."]),
        ("actor_quote", "Valve"),
        ("action_quote", "creates"),
        ("patient_quote", "gold"),
        ("candidate_label_quote", "Valve"),
        ("polarity", "NEGATED"),
        ("source_quotes", []),
    ],
)
def test_invalid_literal_role_evidence_never_falls_back_to_lexical(field, value):
    data = response()
    data["assessment_by_candidate"]["pump"][field] = value
    with pytest.raises(ValueError):
        bind_source_conditioned(PROP, CANDIDATES, context_model_fn=lambda _: json.dumps(data))


def test_multiple_supported_candidates_abstain_instead_of_picking_one():
    data = response()
    data["assessment_by_candidate"]["valve"] = {
        "support": "SUPPORTED",
        "polarity": "AFFIRMED",
        "source_quotes": ["Valve blocks air."],
        "actor_quote": "Valve",
        "action_quote": "blocks",
        "patient_quote": "air",
        "candidate_label_quote": "Valve",
        "explanation": "Model asserts another role.",
    }
    result = bind_source_conditioned(PROP, CANDIDATES, context_model_fn=lambda _: json.dumps(data))
    assert result["selected_candidate_id"] is None
    assert result["status"] == "ABSTAINED_AMBIGUOUS_SOURCE_RELATIONS"


@pytest.mark.parametrize("missing", ["source_refs", "source_context"])
def test_missing_source_does_not_call_model(missing):
    def forbidden(_):
        raise AssertionError("must not call model without source")

    result = bind_source_conditioned(
        {**PROP, missing: [] if missing == "source_refs" else ""},
        CANDIDATES,
        context_model_fn=forbidden,
    )
    assert result["selected_candidate_id"] is None
    assert result["status"].startswith("ABSTAINED")


def test_unknown_or_missing_candidate_assessment_is_invalid():
    data = response()
    data["assessment_by_candidate"]["unknown"] = data["assessment_by_candidate"].pop("pump")
    with pytest.raises(ValueError):
        bind_source_conditioned(PROP, CANDIDATES, context_model_fn=lambda _: json.dumps(data))


def test_no_supported_candidate_is_preserved_as_abstention():
    data = response()
    data["assessment_by_candidate"]["pump"] = copy.deepcopy(
        data["assessment_by_candidate"]["valve"]
    )
    result = bind_source_conditioned(PROP, CANDIDATES, context_model_fn=lambda _: json.dumps(data))
    assert result["selected_candidate_id"] is None
    assert result["supported_candidate_count"] == 0


def test_context_mode_refuses_decision_bridge_even_if_requested():
    with pytest.raises(ValueError, match="cannot use decision-stage"):
        bind_source_conditioned(
            PROP,
            CANDIDATES,
            context_model_fn=lambda _: json.dumps(response()),
            allow_decision_bridge=True,
        )


def test_direct_transport_failure_prevents_context_request(tmp_path, monkeypatch):
    from scripts import run_rq2_binding_dev as run

    config = {
        "context_relation_mode": True,
        "models": {"embedding_model": "fixture", "method_model": "fixture", "max_tokens": 100},
        "thresholds": {"lexical": 0.25, "embedding": 0.2, "source_conditioned": 0.45},
    }
    methods = [
        "lexical",
        "embedding",
        "direct_llm_vlm",
        "source_conditioned_legacy",
        "source_conditioned_context",
        "source_conditioned_context_no_source",
    ]
    protocol = {
        "source_files": {},
        "budget": {"max_transport_calls": 25},
        "methods": methods,
        "models": config["models"],
    }
    task = {
        "id": "p",
        "document_id": "d",
        "proposition": PROP,
        "candidates": [{**CANDIDATES[0], "local_path": "pump.png"}],
        "figure_path": "figure.png",
    }
    run.write(tmp_path / "protocol.json", protocol)
    run.write(tmp_path / "inputs/config.json", config)
    run.write(tmp_path / "inputs/tasks.json", [task])
    run.write(tmp_path / "run-01/calls.json", [])
    monkeypatch.setattr(run, "verify", lambda _: {"status": "PASS"})
    monkeypatch.setattr(run, "embedding_batch", lambda *args: [[1.0], [1.0]])
    stages = []

    def failed_direct(**kwargs):
        stages.append(kwargs["stage"])
        kwargs["ledger"].append({"status": "FAILED"})
        return None, {"status": "FAILED"}

    monkeypatch.setattr(run.shared, "_call_model", failed_direct)
    with pytest.raises(RuntimeError, match="STOPPED_AFTER_TRANSPORT_FAILURE"):
        run.execute(tmp_path)
    assert stages == ["direct_binding"]
    saved = run.read(tmp_path / "run-01/bindings/p.json")
    assert saved["source_conditioned_context"]["status"] == "NOT_RUN_AFTER_TRANSPORT_FAILURE"


def test_declared_object_hash_must_match_supplied_pixels(tmp_path):
    from scripts import run_rq2_binding_dev as run

    image = tmp_path / "inputs/object.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fixture-pixels")
    run.write(tmp_path / "inputs/d-page.json", {"normalized_text": "claim"})
    run.write(
        tmp_path / "inputs/tasks.json",
        [
            {
                "document_id": "d",
                "source_span": [0, 5],
                "proposition": {"text": "claim"},
                "candidates": [
                    {"id": "obj", "local_path": "inputs/object.png", "sha256": "0" * 64}
                ],
            }
        ],
    )
    protocol = {"source_files": {}, "budget": {"max_transport_calls": 25}}
    run.write(tmp_path / "protocol.json", protocol)
    run.write(tmp_path / "run-01/protocol.json", protocol)
    run.write(tmp_path / "run-01/calls.json", [])
    with pytest.raises(ValueError, match="pixel hash"):
        run.verify(tmp_path)
