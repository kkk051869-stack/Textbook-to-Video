import copy
import json

import pytest

from textbook2video.research.binding_methods import bind_source_conditioned

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
