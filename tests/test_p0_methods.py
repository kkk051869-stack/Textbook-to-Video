import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.research.binding_methods import (
    bind_direct_llm_vlm,
    bind_embedding,
    bind_lexical,
    bind_source_conditioned,
    compare_binding_methods,
)
from textbook2video.research.candidate_pool import (
    build_frozen_candidate_pool,
    merge_frozen_candidate_pools,
    validate_frozen_candidate_pool,
)
from textbook2video.research.dynamic_planner import plan_dynamic_events
from textbook2video.research.p0_integration import prepare_p0_candidate
from textbook2video.research.p0_method_runner import (
    build_executable_p0_plan,
    run_p0_method_suite,
)
from textbook2video.research.p0_planner import build_local_p0_plan
from textbook2video.research.signaling_policy import NO_SIGNAL, choose_signal
from textbook2video.research.visual_acquisition import apply_vlm_review_to_acquisition
from textbook2video.research.visual_decision import (
    normalize_visual_decision,
    validate_visual_decision_document,
)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _proposition(prop_id: str = "p1", *, source: bool = True) -> dict:
    return {
        "id": prop_id,
        "segment_id": "1",
        "text": "motion vector encoder predicts optical flow",
        "source_refs": ["raw-unit-0001"] if source else [],
    }


def _candidates() -> list[dict]:
    return [
        {
            "id": "fig-good",
            "segment_id": "1",
            "caption": "motion vector encoder",
            "description": "optical flow prediction",
            "source_refs": ["raw-unit-0001"],
        },
        {
            "id": "fig-other",
            "segment_id": "1",
            "caption": "unrelated result table",
            "description": "accuracy numbers",
            "source_refs": ["raw-unit-0009"],
        },
    ]


def test_visual_decision_v2_fields_and_abstain_are_validated() -> None:
    decision = normalize_visual_decision(
        {
            "narration_proposition_id": "p1",
            "action": "none",
            "abstain": True,
            "confidence": 0.2,
            "rationale": "source is insufficient",
            "source_sufficiency": "INSUFFICIENT",
            "retrieval_suitability": "SUITABLE",
        }
    )
    assert decision["decision_state"] == "ABSTAIN"
    assert decision["rationale_evidence"][0]["status"] == "MODEL_ASSERTION_NOT_SOURCE_EVIDENCE"
    document = {"schema_version": "p0-visual-decision-v2.0", "decisions": [decision]}
    result = validate_visual_decision_document(document, proposition_ids={"p1"})
    assert result["valid"] is True
    assert result["state_counts"]["ABSTAIN"] == 1


def test_legacy_p0_planner_does_not_schedule_uncertain_decision(tmp_path: Path) -> None:
    storyboard = tmp_path / "storyboard.json"
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    _write(
        storyboard,
        {
            "segments": [
                {
                    "id": "1",
                    "narration": "claim",
                    "elements": [
                        {
                            "id": "fig",
                            "type": "image",
                            "source_image_id": "fig-1",
                            "description": "claim",
                        }
                    ],
                }
            ]
        },
    )
    _write(graph, {"narration_propositions": [{"id": "p1", "segment_id": "1", "text": "claim"}]})
    _write(
        decisions,
        {
            "decisions": [
                {
                    "narration_proposition_id": "p1",
                    "action": "reuse",
                    "source_image_id": "fig-1",
                    "decision_state": "UNCERTAIN",
                    "uncertain": True,
                    "confidence": 0.2,
                    "rationale": "ambiguous",
                    "rationale_evidence": [{"kind": "model_assertion", "quote": "ambiguous"}],
                }
            ]
        },
    )
    paths = prepare_p0_candidate(storyboard, output_dir=tmp_path, proposition_graph_path=graph)
    plan = json.loads(
        build_local_p0_plan(
            paths, visual_decision_path=decisions, require_visual_decisions=True
        ).read_text(encoding="utf-8")
    )
    assert plan["events"] == []
    assert plan["decisions"][0]["acquisition"] == "UNCERTAIN"


def test_binding_methods_use_same_candidates_and_source_conditioned_abstains_without_source() -> (
    None
):
    proposition = _proposition()
    assert bind_lexical(proposition, _candidates())["selected_candidate_id"] == "fig-good"
    assert bind_embedding(proposition, _candidates())["method"] == "embedding"
    direct = bind_direct_llm_vlm(
        proposition,
        _candidates(),
        model_fn=lambda _prompt: json.dumps(
            {
                "selected_candidate_id": "fig-good",
                "confidence": 0.91,
                "rationale": "caption supports the proposition",
            }
        ),
    )
    assert direct["selected_candidate_id"] == "fig-good"
    proposed = bind_source_conditioned(proposition, _candidates())
    assert proposed["selected_candidate_id"] == "fig-good"
    no_source = bind_source_conditioned(_proposition(source=False), _candidates())
    assert no_source["selected_candidate_id"] is None
    comparison = compare_binding_methods(
        proposition,
        _candidates(),
        model_fn=lambda _prompt: json.dumps({"selected_candidate_id": None, "abstain": True}),
    )
    assert {item["method"] for item in comparison["results"]} == {
        "lexical",
        "embedding",
        "direct_llm_vlm",
        "source_conditioned",
    }


def test_source_conditioned_binding_uses_explicit_visual_decision_bridge() -> None:
    proposition = _proposition()
    candidate = {
        "id": "fig-bridge",
        "segment_id": "1",
        "caption": "untranslated figure caption",
        "source_evidence_links": [
            {
                "proposition_id": "p1",
                "source_image_id": "fig-source",
                "status": "DECISION_STAGE_SOURCE_BRIDGE",
                "rationale_evidence": [{"kind": "source_image", "id": "fig-source"}],
            }
        ],
    }
    result = bind_source_conditioned(proposition, [candidate], allow_decision_bridge=True)
    assert result["selected_candidate_id"] == "fig-bridge"
    assert any(item["kind"] == "decision_stage_source_bridge" for item in result["evidence"])


def test_independent_binding_does_not_leak_visual_decision_bridge() -> None:
    proposition = _proposition()
    candidate = {
        "id": "fig-bridge", "segment_id": "1",
        "source_evidence_links": [{
            "proposition_id": "p1", "status": "DECISION_STAGE_SOURCE_BRIDGE",
        }],
    }
    result = bind_source_conditioned(proposition, [candidate])
    assert result["selected_candidate_id"] is None
    assert result["decision_bridge_allowed"] is False


def test_runner_marks_direct_comparator_not_run_without_cloud_model(tmp_path: Path) -> None:
    pool = tmp_path / "pool.json"
    _write(pool, {"schema_version": "p0-frozen-candidate-pool-v1.0", "cases": [{
        "case_id": "p1::reuse", "proposition_id": "p1", "segment_id": "1",
        "proposition": {**_proposition(), "start_sec": 0.0, "end_sec": 1.0},
        "candidate_visuals": _candidates(),
    }]})
    result = run_p0_method_suite(
        candidate_pool_path=pool, output_dir=tmp_path / "run",
        require_pool_coverage=False, segment_durations={"1": 2.0},
    )
    comparison = json.loads(result["comparisons"].read_text(encoding="utf-8"))
    direct = next(item for item in comparison["comparisons"][0]["results"] if item["method"] == "direct_llm_vlm")
    assert direct["status"] == "NOT_RUN"
    assert direct["comparator_mode"] == "NOT_RUN"


def test_vlm_review_is_persisted_on_acquisition_assets(tmp_path: Path) -> None:
    acquisition = tmp_path / "acquisition.json"
    review = tmp_path / "review.json"
    _write(acquisition, {"assets": [{"asset_id": "asset-1", "proposition_id": "p1", "status": "RETRIEVED_LOCAL_RAG"}]})
    _write(review, {"decisions": [{"asset_id": "asset-1", "verdict": "ACCEPT", "reason": "explains claim", "visual_summary": "diagram"}]})
    output = apply_vlm_review_to_acquisition(
        acquisition_path=acquisition, vlm_review_path=review, output_path=tmp_path / "reviewed.json"
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["assets"][0]["vlm_verdict"] == "ACCEPT"
    assert value["assets"][0]["description"] == "diagram"


def test_signaling_policy_allows_no_signal_by_default() -> None:
    decision = choose_signal(_proposition(), target_element_id="fig-good", confidence=0.9)
    assert decision["signal_action"] == NO_SIGNAL
    explicit = choose_signal(
        {**_proposition(), "requires_signal": True},
        target_element_id="fig-good",
        confidence=0.9,
    )
    assert explicit["signal_action"] == "focus"


def test_dynamic_planner_uses_earliest_show_and_later_focus_and_cleanup() -> None:
    propositions = [
        {**_proposition("p1"), "start_sec": 1.0, "end_sec": 3.0},
        {
            **_proposition("p2"),
            "text": "motion vector encoder is reused",
            "start_sec": 4.0,
            "end_sec": 6.0,
            "requires_signal": True,
        },
        {
            **_proposition("p3"),
            "text": "a separate result is shown",
            "start_sec": 7.0,
            "end_sec": 8.0,
        },
    ]
    bindings = [
        {
            "proposition_id": "p1",
            "segment_id": "1",
            "selected_candidate_id": "fig-good",
            "confidence": 0.9,
            "status": "BOUND",
        },
        {
            "proposition_id": "p2",
            "segment_id": "1",
            "selected_candidate_id": "fig-good",
            "confidence": 0.9,
            "status": "BOUND",
        },
        {
            "proposition_id": "p3",
            "segment_id": "1",
            "selected_candidate_id": "fig-other",
            "confidence": 0.9,
            "status": "BOUND",
        },
    ]
    plan = plan_dynamic_events(
        propositions=propositions, bindings=bindings, segment_durations={"1": 10.0}
    )
    assert plan["status"] == "READY"
    assert plan["events"][0]["action"] == "show"
    assert plan["events"][0]["at_sec"] == 1.0
    assert any(
        item["action"] == "focus" and item["proposition_id"] == "p2" for item in plan["events"]
    )
    assert any(
        item["action"] == "focus" and item["effect"] == "highlight" for item in plan["events"]
    )
    assert any(
        item["action"] == "dim" and item["target_element_id"] == "fig-good"
        for item in plan["events"]
    )


def test_dynamic_planner_blocks_missing_measured_timing() -> None:
    plan = plan_dynamic_events(
        propositions=[_proposition()],
        bindings=[{"proposition_id": "p1", "selected_candidate_id": "fig-good", "status": "BOUND"}],
    )
    assert plan["status"] == "BLOCKED_MISSING_MEASURED_PROPOSITION_TIMING"
    assert not plan["events"]


def test_frozen_candidate_pool_requires_all_four_outcomes(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    evidence = tmp_path / "evidence.json"
    decisions = tmp_path / "decisions.json"
    acquisition = tmp_path / "acquisition.json"
    storyboard = tmp_path / "storyboard.json"
    props = []
    decision_rows = []
    assets = []
    for index, (action, prop_id) in enumerate(
        [
            ("none", "p-none"),
            ("reuse", "p-reuse"),
            ("retrieve", "p-retrieve"),
            ("retrieve", "p-no"),
        ],
        start=1,
    ):
        props.append(
            {
                "id": prop_id,
                "segment_id": "1",
                "text": f"claim {index}",
                "source_refs": ["raw-unit-1"],
            }
        )
        row = {
            "narration_proposition_id": prop_id,
            "action": action,
            "rationale": "evidence",
            "rationale_evidence": [{"kind": "source_unit", "id": "raw-unit-1", "quote": "claim"}],
        }
        if action == "reuse":
            row["source_image_id"] = "fig-1"
        if prop_id == "p-retrieve":
            row["retrieval_query"] = "licensed diagram"
            assets.append(
                {"proposition_id": prop_id, "status": "RETRIEVED_LOCAL_RAG", "asset_id": "asset-1"}
            )
        if prop_id == "p-no":
            row["retrieval_query"] = "missing diagram"
            assets.append({"proposition_id": prop_id, "status": "RETRIEVAL_NO_ACCEPTABLE_RESULT"})
        decision_rows.append(row)
    _write(graph, {"narration_propositions": props})
    _write(
        evidence,
        {
            "source_images": [{"id": "fig-1", "filename": "fig.png"}],
            "source_units": [{"id": "raw-unit-1", "text": "claim"}],
        },
    )
    _write(decisions, {"decisions": decision_rows})
    _write(acquisition, {"assets": assets})
    _write(
        storyboard,
        {
            "segments": [
                {
                    "id": "1",
                    "elements": [{"id": "image-1", "type": "image", "source_image_id": "fig-1"}],
                }
            ]
        },
    )
    pool_path = build_frozen_candidate_pool(
        decision_path=decisions,
        proposition_graph_path=graph,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        acquisition_path=acquisition,
        output_path=tmp_path / "pool.json",
    )
    validation = validate_frozen_candidate_pool(pool_path)
    assert validation["coverage_complete"] is True
    assert validation["counts"] == {"none": 1, "reuse": 1, "retrieve": 1, "no_acceptable_result": 1}


def test_frozen_candidate_pool_fails_when_coverage_is_missing(tmp_path: Path) -> None:
    for name, value in {
        "graph.json": {
            "narration_propositions": [
                {"id": "p1", "segment_id": "1", "text": "claim", "source_refs": ["s1"]}
            ]
        },
        "evidence.json": {"source_units": [{"id": "s1", "text": "claim"}], "source_images": []},
        "decisions.json": {
            "decisions": [
                {
                    "narration_proposition_id": "p1",
                    "action": "none",
                    "rationale": "no",
                    "rationale_evidence": [{"kind": "source_unit", "id": "s1", "quote": "claim"}],
                }
            ]
        },
    }.items():
        _write(tmp_path / name, value)
    with pytest.raises(ValueError, match="does not cover required outcomes"):
        build_frozen_candidate_pool(
            decision_path=tmp_path / "decisions.json",
            proposition_graph_path=tmp_path / "graph.json",
            source_evidence_path=tmp_path / "evidence.json",
            output_path=tmp_path / "pool.json",
        )


def test_method_runner_freezes_pool_and_emits_comparison_and_dynamic_plan(tmp_path: Path) -> None:
    graph = tmp_path / "graph.json"
    evidence = tmp_path / "evidence.json"
    decisions = tmp_path / "decisions.json"
    acquisition = tmp_path / "acquisition.json"
    storyboard = tmp_path / "storyboard.json"
    props = []
    rows = []
    assets = []
    for index, (action, prop_id) in enumerate(
        [
            ("none", "p-none"),
            ("reuse", "p-reuse"),
            ("retrieve", "p-retrieve"),
            ("retrieve", "p-no"),
        ],
        start=1,
    ):
        props.append(
            {
                "id": prop_id,
                "segment_id": "1",
                "text": f"claim {index}",
                "source_refs": ["s1"],
                "start_sec": float(index),
                "end_sec": float(index) + 1,
            }
        )
        row = {
            "narration_proposition_id": prop_id,
            "action": action,
            "rationale": "evidence",
            "rationale_evidence": [{"kind": "source_unit", "id": "s1", "quote": "claim"}],
        }
        if action == "reuse":
            row["source_image_id"] = "fig-1"
        if prop_id == "p-retrieve":
            row["retrieval_query"] = "diagram"
            assets.append(
                {"proposition_id": prop_id, "status": "RETRIEVED_LOCAL_RAG", "asset_id": "asset-1"}
            )
        if prop_id == "p-no":
            row["retrieval_query"] = "missing"
            assets.append({"proposition_id": prop_id, "status": "RETRIEVAL_NO_ACCEPTABLE_RESULT"})
        rows.append(row)
    _write(graph, {"narration_propositions": props})
    _write(
        evidence,
        {
            "source_units": [{"id": "s1", "text": "claim"}],
            "source_images": [{"id": "fig-1", "filename": "fig.png"}],
        },
    )
    _write(decisions, {"decisions": rows})
    _write(acquisition, {"assets": assets})
    _write(
        storyboard,
        {
            "segments": [
                {
                    "id": "1",
                    "elements": [
                        {
                            "id": "el-1",
                            "type": "image",
                            "source_image_id": "fig-1",
                            "caption": "claim",
                        }
                    ],
                }
            ]
        },
    )
    pool = build_frozen_candidate_pool(
        decision_path=decisions,
        proposition_graph_path=graph,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        acquisition_path=acquisition,
        output_path=tmp_path / "pool.json",
    )
    outputs = run_p0_method_suite(
        candidate_pool_path=pool,
        output_dir=tmp_path / "run",
        require_pool_coverage=True,
        segment_durations={"1": 8.0},
    )
    report = json.loads(outputs["report"].read_text(encoding="utf-8"))
    assert report["status"] == "READY"
    comparison = json.loads(outputs["comparisons"].read_text(encoding="utf-8"))
    assert len(comparison["comparisons"]) == 4
    dynamic = json.loads(outputs["dynamic_plan"].read_text(encoding="utf-8"))
    assert dynamic["status"] == "READY"


def test_merge_frozen_pools_preserves_case_hashes_and_enforces_union_coverage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    pool_paths = []
    for index, outcome in enumerate(("none", "reuse", "retrieve", "no_acceptable_result"), start=1):
        pool = tmp_path / f"pool-{index}.json"
        pool.write_text(
            json.dumps(
                {
                    "schema_version": "p0-frozen-candidate-pool-v1.0",
                    "pool_id": f"pool-{index}",
                    "frozen_inputs": {
                        "source": {
                            "path": str(source),
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    },
                    "cases": [{"case_id": f"case-{index}", "outcome": outcome}],
                }
            ),
            encoding="utf-8",
        )
        pool_paths.append(pool)
    merged = merge_frozen_candidate_pools(pool_paths, output_path=tmp_path / "merged.json")
    merged_doc = json.loads(merged.read_text(encoding="utf-8"))
    assert merged_doc["coverage"]["complete"] is True
    assert len(merged_doc["merged_from"]) == 4
    pool_paths[0].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="merged frozen pool changed"):
        validate_frozen_candidate_pool(merged)


def test_direct_comparator_uses_real_candidate_pixels_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "figure.png"
    image.write_bytes(b"not-decoded-in-mocked-request")
    seen: list[list[str]] = []

    def fake_vlm(_prompt: str, paths: list[str], **_kwargs: object) -> str:
        seen.append(paths)
        return json.dumps({"selected_candidate_id": "fig-good", "confidence": 0.8})

    monkeypatch.setattr("textbook2video.research.binding_methods.chat_with_images", fake_vlm)
    result = bind_direct_llm_vlm(_proposition(), [{**_candidates()[0], "local_path": str(image)}])
    assert result["comparator_mode"] == "VLM_PIXELS"
    assert result["image_candidate_ids"] == ["fig-good"]
    assert seen == [[str(image)]]


def test_executable_plan_keeps_only_vlm_accepted_retrieval(tmp_path: Path) -> None:
    asset = tmp_path / "licensed.png"
    asset.write_bytes(b"asset")
    pool = tmp_path / "pool.json"
    dynamic = tmp_path / "dynamic.json"
    decisions = tmp_path / "decisions.json"
    _write(
        pool,
        {
            "schema_version": "p0-frozen-candidate-pool-v1.0",
            "cases": [
                {
                    "proposition_id": "p-retrieve",
                    "segment_id": "1",
                    "acquisition": {
                        "status": "RETRIEVED_LOCAL_RAG",
                        "asset_id": "asset-1",
                        "filename": asset.name,
                        "local_path": str(asset),
                        "license": "CC BY 4.0",
                        "vlm_verdict": "ACCEPT",
                    },
                }
            ],
        },
    )
    _write(
        dynamic,
        {
            "events": [
                {
                    "id": "e1",
                    "proposition_id": "p-retrieve",
                    "segment_id": "1",
                    "target_element_id": "asset-1",
                    "action": "show",
                    "at_sec": 1.0,
                }
            ]
        },
    )
    _write(
        decisions, {"decisions": [{"narration_proposition_id": "p-retrieve", "action": "retrieve"}]}
    )
    plan = build_executable_p0_plan(
        candidate_pool_path=pool,
        dynamic_plan_path=dynamic,
        visual_decision_path=decisions,
        output_path=tmp_path / "plan.json",
    )
    value = json.loads(plan.read_text(encoding="utf-8"))
    assert value["events"][0]["target_element_id"] == "p0-acquired-p-retrieve"
    assert value["retrieved_visuals"][0]["vlm_verdict"] == "ACCEPT"


def test_method_runner_uses_measured_sentence_cues_for_dynamic_plan(tmp_path: Path) -> None:
    pool = tmp_path / "pool.json"
    storyboard = tmp_path / "storyboard.json"
    graph = tmp_path / "graph.json"
    cues = tmp_path / "sentence_cues.json"
    _write(
        pool,
        {
            "schema_version": "p0-frozen-candidate-pool-v1.0",
            "cases": [
                {
                    "case_id": "p1::reuse",
                    "proposition_id": "p1",
                    "segment_id": "1",
                    "proposition": _proposition("p1"),
                    "candidate_visuals": [{**_candidates()[0], "id": "element-1"}],
                }
            ],
        },
    )
    _write(
        storyboard,
        {
            "segments": [
                {
                    "id": "1",
                    "narration": "motion vector encoder predicts optical flow",
                    "audio_duration_sec": 4.0,
                }
            ]
        },
    )
    _write(graph, {"narration_propositions": [_proposition("p1")]})
    _write(
        cues,
        {
            "segments": [
                {
                    "segment_id": "1",
                    "cues": [
                        {
                            "sentence_id": "s1",
                            "text": "motion vector encoder predicts optical flow",
                            "start_sec": 0.0,
                            "end_sec": 4.0,
                        }
                    ],
                }
            ]
        },
    )
    outputs = run_p0_method_suite(
        candidate_pool_path=pool,
        output_dir=tmp_path / "out",
        require_pool_coverage=False,
        storyboard_path=storyboard,
        proposition_graph_path=graph,
        sentence_cues_path=cues,
    )
    dynamic = json.loads(outputs["dynamic_plan"].read_text(encoding="utf-8"))
    assert dynamic["status"] == "READY"
    assert dynamic["events"][0]["at_sec"] == 0.0
