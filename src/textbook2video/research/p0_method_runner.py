"""Reproducible runner for the second-stage P0 method comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .binding_methods import (
    BindingModel,
    EmbeddingFn,
    compare_binding_methods,
    make_sentence_transformer_embedding,
)
from .candidate_pool import validate_frozen_candidate_pool
from .dynamic_planner import plan_dynamic_events, write_dynamic_plan
from .p0_integration import measure_proposition_intervals

METHOD_RUNNER_VERSION = "p0-method-runner-v1.0"


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_list(case: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        dict(item) for item in case.get("candidate_visuals", []) if isinstance(item, dict)
    ]
    image = case.get("source_image")
    if isinstance(image, dict) and image.get("id") and not candidates:
        candidates.append({**image, "id": str(image["id"]), "segment_id": case.get("segment_id")})
    acquisition = case.get("acquisition")
    if isinstance(acquisition, dict) and acquisition.get("asset_id") and not candidates:
        candidates.append(
            {
                "id": str(acquisition["asset_id"]),
                "segment_id": case.get("segment_id"),
                "caption": acquisition.get("caption"),
                "description": acquisition.get("description"),
                "source_refs": acquisition.get("source_refs") or [],
                "local_path": acquisition.get("local_path"),
            }
        )
    return candidates


def run_p0_method_suite(
    *,
    candidate_pool_path: str | Path,
    output_dir: str | Path,
    selected_binding_method: str = "source_conditioned",
    direct_model_fn: BindingModel | None = None,
    call_direct_model: bool = False,
    direct_model: str | None = None,
    embed_fn: EmbeddingFn | None = None,
    embedding_model: str | None = None,
    segment_durations: dict[str, float] | None = None,
    storyboard_path: str | Path | None = None,
    proposition_graph_path: str | Path | None = None,
    sentence_cues_path: str | Path | None = None,
    require_pool_coverage: bool = True,
    allow_decision_bridge: bool = False,
) -> dict[str, Path]:
    """Compare all binding methods over one immutable pool and plan events.

    Cloud LLM/VLM use is opt-in through ``call_direct_model``.  Callers may
    inject a test/provider callable, or provide ``direct_model`` and let the
    normal OpenAI-compatible client execute the actual text/VLM comparison.
    Offline runs record the direct comparator as ``NOT_RUN`` rather than
    fabricating an abstention response.
    """
    pool_path = Path(candidate_pool_path)
    pool = _read(pool_path)
    validation = validate_frozen_candidate_pool(pool_path, require_coverage=require_pool_coverage)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if call_direct_model and not direct_model and direct_model_fn is None:
        raise ValueError(
            "call_direct_model=True requires direct_model or direct_model_fn"
        )
    if embedding_model and embed_fn is not None:
        raise ValueError("provide embedding_model or embed_fn, not both")
    if embedding_model:
        embed_fn = make_sentence_transformer_embedding(embedding_model)

    comparisons: list[dict[str, Any]] = []
    selected_bindings: list[dict[str, Any]] = []
    propositions: list[dict[str, Any]] = []
    measured_by_id: dict[str, dict[str, Any]] = {}
    if any(
        value is not None for value in (storyboard_path, proposition_graph_path, sentence_cues_path)
    ):
        if not all(
            value is not None
            for value in (storyboard_path, proposition_graph_path, sentence_cues_path)
        ):
            raise ValueError(
                "storyboard_path, proposition_graph_path and sentence_cues_path "
                "are required together"
            )
        cues = _read(sentence_cues_path)
        measured, measured_durations = measure_proposition_intervals(
            storyboard_path=storyboard_path,
            proposition_graph_path=proposition_graph_path,
            sentence_cues=cues,
        )
        measured_by_id = {str(item.get("id") or ""): item for item in measured}
        segment_durations = measured_durations

    for case in pool.get("cases", []):
        if not isinstance(case, dict):
            continue
        proposition = dict(
            case.get("proposition")
            or {
                "id": case.get("proposition_id"),
                "segment_id": case.get("segment_id"),
                "text": case.get("proposition_text"),
                "source_refs": case.get("source_refs") or [],
            }
        )
        proposition.setdefault("id", case.get("proposition_id"))
        proposition.setdefault("segment_id", case.get("segment_id"))
        proposition = {**proposition, **measured_by_id.get(str(proposition.get("id") or ""), {})}
        candidates = _candidate_list(case)
        comparison = compare_binding_methods(
            proposition,
            candidates,
            model_fn=direct_model_fn if call_direct_model else None,
            model=direct_model,
            embed_fn=embed_fn,
            run_direct=call_direct_model,
            allow_decision_bridge=allow_decision_bridge,
        )
        comparison["case_id"] = case.get("case_id")
        comparison["pool_outcome"] = case.get("outcome")
        comparisons.append(comparison)
        selected = next(
            (
                item
                for item in comparison["results"]
                if item.get("method") == selected_binding_method
            ),
            None,
        )
        if selected is None:
            raise ValueError(f"unknown selected binding method: {selected_binding_method}")
        selected_bindings.append(
            {
                "proposition_id": proposition.get("id"),
                "segment_id": proposition.get("segment_id"),
                "selected_candidate_id": selected.get("selected_candidate_id"),
                "score": selected.get("score"),
                "confidence": selected.get("confidence"),
                "status": selected.get("status"),
            }
        )
        propositions.append(proposition)

    comparison_doc = {
        "schema_version": METHOD_RUNNER_VERSION,
        "candidate_pool_path": str(pool_path),
        "candidate_pool_sha256": _sha256(pool_path),
        "selected_binding_method": selected_binding_method,
        "embedding_model": embedding_model,
        "pool_validation": validation,
        "comparisons": comparisons,
        "claim": "All methods receive the same frozen proposition and candidate list.",
        "comparison_mode": (
            "PIPELINE_ASSISTED_DECISION_BRIDGE" if allow_decision_bridge
            else "INDEPENDENT_COMPARISON_NO_DECISION_BRIDGE"
        ),
    }
    comparison_path = output / "binding_comparisons.json"
    comparison_path.write_text(
        json.dumps(comparison_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    dynamic = plan_dynamic_events(
        propositions=propositions,
        bindings=selected_bindings,
        segment_durations=segment_durations,
    )
    dynamic["candidate_pool_path"] = str(pool_path)
    dynamic["binding_comparisons_path"] = str(comparison_path)
    dynamic_path = write_dynamic_plan(output / "dynamic_plan.json", dynamic)
    report = {
        "schema_version": METHOD_RUNNER_VERSION,
        "candidate_pool_validation": validation,
        "comparison_path": str(comparison_path),
        "dynamic_plan_path": str(dynamic_path),
        "selected_binding_method": selected_binding_method,
        "direct_model_invoked": bool(call_direct_model),
        "direct_model": direct_model,
        "embedding_model": embedding_model,
        "decision_bridge_allowed": allow_decision_bridge,
        "status": "READY" if dynamic.get("status") == "READY" else dynamic.get("status"),
    }
    report_path = output / "method_run_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"comparisons": comparison_path, "dynamic_plan": dynamic_path, "report": report_path}


def build_executable_p0_plan(
    *,
    candidate_pool_path: str | Path,
    dynamic_plan_path: str | Path,
    visual_decision_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Materialize a dynamic plan into the schema consumed by ``produce --p0-plan``.

    Reuse bindings point to existing storyboard element IDs.  A retrieve or
    generation binding may add a new P0-only element only when the acquisition
    is local, provenance-bearing and already VLM accepted.  The function never
    invents an asset or silently downgrades an unreviewed visual.
    """
    pool = _read(candidate_pool_path)
    dynamic = _read(dynamic_plan_path)
    decisions = _read(visual_decision_path)
    decision_by_prop = {
        str(item.get("narration_proposition_id") or ""): item
        for item in decisions.get("decisions", [])
        if isinstance(item, dict)
    }
    case_by_prop = {
        str(item.get("proposition_id") or ""): item
        for item in pool.get("cases", [])
        if isinstance(item, dict)
    }
    target_by_prop: dict[str, str] = {}
    retrieved_visuals: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for prop_id, case in case_by_prop.items():
        decision = decision_by_prop.get(prop_id, {})
        action = str(decision.get("action") or "").lower()
        if action in {"retrieve", "generate"}:
            asset = case.get("acquisition") if isinstance(case.get("acquisition"), dict) else {}
            verdict = str(asset.get("vlm_verdict") or "").upper()
            if (
                str(asset.get("status") or "")
                not in {
                    "RETRIEVED_LOCAL_RAG",
                    "GENERATED_CANDIDATE_PENDING_VLM_REVIEW",
                }
                or verdict != "ACCEPT"
                or not asset.get("local_path")
                or not (asset.get("license") or asset.get("provenance"))
            ):
                continue
            target = f"p0-acquired-{prop_id}"
            target_by_prop[prop_id] = target
            retrieved_visuals.append(
                {
                    "segment_id": case.get("segment_id"),
                    "proposition_id": prop_id,
                    "element_id": target,
                    "source_image_id": asset.get("asset_id"),
                    "filename": asset.get("filename"),
                    "local_path": asset.get("local_path"),
                    "license": asset.get("license"),
                    "provenance": asset.get("provenance"),
                    "vlm_verdict": verdict,
                    "description": asset.get("description") or asset.get("caption"),
                }
            )
    events: list[dict[str, Any]] = []
    bound_pairs: set[tuple[str, str]] = set()
    for event in dynamic.get("events", []):
        if not isinstance(event, dict):
            continue
        prop_id = str(event.get("proposition_id") or "")
        case = case_by_prop.get(prop_id, {})
        decision = decision_by_prop.get(prop_id, {})
        action = str(decision.get("action") or "").lower()
        target = target_by_prop.get(prop_id)
        if action == "reuse":
            selected = str(event.get("target_element_id") or "")
            known = {
                str(item.get("id") or "")
                for item in case.get("candidate_visuals", [])
                if isinstance(item, dict)
            }
            target = selected if selected in known else None
        if not target:
            continue
        events.append({**event, "target_element_id": target})
        pair = (prop_id, target)
        if pair not in bound_pairs:
            bindings.append(
                {
                    "proposition_id": prop_id,
                    "segment_id": case.get("segment_id"),
                    "target_element_id": target,
                }
            )
            bound_pairs.add(pair)
    document = {
        "schema_version": "p0-event-plan-v0.1",
        "planner": "phase2_dynamic_method_adapter",
        "candidate_pool_path": str(candidate_pool_path),
        "candidate_pool_sha256": _sha256(Path(candidate_pool_path)),
        "dynamic_plan_path": str(dynamic_plan_path),
        "visual_decision_path": str(visual_decision_path),
        "events": events,
        "bindings": bindings,
        "retrieved_visuals": retrieved_visuals,
        "claim": (
            "Executable phase-two plan; only accepted, local, provenance-bearing "
            "acquired visuals are materialized."
        ),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


__all__ = ["METHOD_RUNNER_VERSION", "build_executable_p0_plan", "run_p0_method_suite"]
