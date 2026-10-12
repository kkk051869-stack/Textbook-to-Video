"""Frozen candidate-pool construction for the second P0 study phase.

The pool is a *sampling frame*, not a retrieval engine.  It freezes the exact
decision, proposition, source asset and acquisition result used by a binding
comparison.  A pool is valid for an experiment only when its manifest covers
the four requested outcomes: ``none``, ``reuse``, ``retrieve`` and
``no_acceptable_result``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .visual_decision import normalize_visual_decision, validate_visual_decision_document

POOL_VERSION = "p0-frozen-candidate-pool-v1.0"
OUTCOMES = ("none", "reuse", "retrieve", "no_acceptable_result")


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("source_unit_id") or value.get("id") or "")
    return str(value or "")


def _acquisition_status_by_prop(acquisition: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("proposition_id") or ""): item
        for item in (acquisition or {}).get("assets", [])
        if isinstance(item, dict) and item.get("proposition_id")
    }


def _outcome_for(
    decision: dict[str, Any],
    acquisition: dict[str, Any] | None,
) -> tuple[str, str]:
    action = str(decision.get("action") or "").lower()
    prop_id = str(decision.get("narration_proposition_id") or "")
    asset = _acquisition_status_by_prop(acquisition).get(prop_id, {})
    status = str(asset.get("status") or "")
    if action == "none" or bool(decision.get("abstain")):
        return "none", "explicit_none_or_abstain"
    if action == "reuse":
        return "reuse", "source_image_reuse"
    if action == "retrieve" and status == "RETRIEVED_LOCAL_RAG":
        return "retrieve", "retrieval_materialized_and_licensed"
    if action in {"retrieve", "generate"}:
        return "no_acceptable_result", status or "acquisition_not_materialized"
    return "no_acceptable_result", "unsupported_or_missing_acquisition_action"


def build_frozen_candidate_pool(
    *,
    decision_path: str | Path,
    proposition_graph_path: str | Path,
    source_evidence_path: str | Path,
    output_path: str | Path,
    storyboard_path: str | Path | None = None,
    acquisition_path: str | Path | None = None,
    retrieval_catalog_path: str | Path | None = None,
    require_coverage: bool = True,
) -> Path:
    """Freeze proposition-level cases and fail if required outcomes are absent.

    The function never invents a retrieved asset.  A ``retrieve`` case is
    included only when acquisition materialized a local, provenance-bearing
    asset; failed/thresholded/pending retrievals become
    ``no_acceptable_result``.
    """
    decision_doc = _read(decision_path)
    graph = _read(proposition_graph_path)
    evidence = _read(source_evidence_path)
    storyboard = _read(storyboard_path) if storyboard_path else {}
    acquisition = _read(acquisition_path) if acquisition_path else None
    propositions = {
        str(item.get("id") or ""): item
        for item in graph.get("narration_propositions", [])
        if isinstance(item, dict) and item.get("id")
    }
    if not propositions:
        raise ValueError("candidate pool requires narration propositions")
    source_images = {
        str(item.get("id") or ""): item
        for item in evidence.get("source_images", [])
        if isinstance(item, dict) and item.get("id")
    }
    decision_ids = set(propositions)
    decision_validation = validate_visual_decision_document(
        decision_doc,
        proposition_ids=decision_ids,
        require_evidence=True,
    )
    decisions = {
        str(item.get("narration_proposition_id") or ""): normalize_visual_decision(
            item,
            proposition=propositions.get(str(item.get("narration_proposition_id") or "")),
            available_image_ids=set(source_images),
        )
        for item in decision_doc.get("decisions", [])
        if isinstance(item, dict)
    }
    segment_elements: dict[str, list[dict[str, Any]]] = {}
    for index, segment in enumerate(storyboard.get("segments", []) or [], start=1):
        if isinstance(segment, dict):
            segment_id = str(segment.get("id") or index)
            segment_elements[segment_id] = [
                item for item in segment.get("elements", []) or [] if isinstance(item, dict)
            ]

    cases: list[dict[str, Any]] = []
    for prop_id in sorted(propositions):
        proposition = propositions[prop_id]
        decision = decisions[prop_id]
        outcome, outcome_reason = _outcome_for(decision, acquisition)
        source_image_id = str(decision.get("source_image_id") or "")
        source_image = source_images.get(source_image_id)
        element_ids = [
            str(item.get("id") or "")
            for item in segment_elements.get(str(proposition.get("segment_id") or ""), [])
            if str(item.get("source_image_id") or item.get("src") or "") == source_image_id
        ]
        candidate_visuals = [
            {
                **item,
                "segment_id": str(proposition.get("segment_id") or ""),
                # Preserve the source-evidence relation on the actual
                # storyboard element so source-conditioned binding does not
                # degrade to caption overlap.
                "source_refs": list(
                    source_images.get(source_image_id, {}).get("source_component_ids")
                    or source_images.get(source_image_id, {}).get("source_refs")
                    or item.get("source_refs")
                    or []
                ),
                "source_locator": source_images.get(source_image_id, {}).get("source_locator"),
                "figure_id": source_images.get(source_image_id, {}).get("figure_id"),
                "caption": (
                    item.get("caption") or source_images.get(source_image_id, {}).get("caption")
                ),
                "local_path": (
                    source_images.get(source_image_id, {}).get("local_path")
                    or (
                        str(Path(storyboard_path).parent / "images" / str(item.get("src")))
                        if storyboard_path and item.get("src")
                        else None
                    )
                ),
                "source_evidence_links": [
                    {
                        "proposition_id": prop_id,
                        "source_image_id": source_image_id,
                        "rationale_evidence": decision.get("rationale_evidence") or [],
                        "status": "DECISION_STAGE_SOURCE_BRIDGE",
                    }
                ],
            }
            for item in segment_elements.get(str(proposition.get("segment_id") or ""), [])
            if str(item.get("source_image_id") or item.get("src") or "") == source_image_id
        ]
        if outcome == "reuse" and not candidate_visuals:
            raise ValueError(
                f"reuse decision is not materialized in its storyboard segment: {prop_id}"
            )
        acquisition_asset = _acquisition_status_by_prop(acquisition).get(prop_id)
        cases.append(
            {
                "case_id": f"{prop_id}::{outcome}",
                "proposition_id": prop_id,
                "segment_id": str(proposition.get("segment_id") or ""),
                "proposition_text": str(proposition.get("text") or ""),
                "proposition": proposition,
                "source_refs": list(proposition.get("source_refs") or []),
                "outcome": outcome,
                "outcome_reason": outcome_reason,
                "decision": decision,
                "source_image": source_image,
                "storyboard_element_ids": element_ids,
                "candidate_visuals": candidate_visuals,
                "acquisition": acquisition_asset,
            }
        )

    counts = {outcome: sum(case["outcome"] == outcome for case in cases) for outcome in OUTCOMES}
    missing_outcomes = [outcome for outcome in OUTCOMES if counts[outcome] == 0]
    if require_coverage and missing_outcomes:
        raise ValueError(
            "frozen candidate pool does not cover required outcomes: " + ", ".join(missing_outcomes)
        )
    input_paths = {
        "decision": Path(decision_path),
        "proposition_graph": Path(proposition_graph_path),
        "source_evidence": Path(source_evidence_path),
    }
    for label, optional in (
        ("storyboard", storyboard_path),
        ("acquisition", acquisition_path),
        ("retrieval_catalog", retrieval_catalog_path),
    ):
        if optional:
            input_paths[label] = Path(optional)
    manifest = {
        "schema_version": POOL_VERSION,
        "pool_id": Path(output_path).stem,
        "frozen_inputs": {
            label: {"path": str(path), "sha256": _sha256(path)}
            for label, path in input_paths.items()
            if path.is_file()
        },
        "required_outcomes": list(OUTCOMES),
        "coverage": {
            "counts": counts,
            "missing": missing_outcomes,
            "complete": not missing_outcomes,
        },
        "decision_validation": decision_validation,
        "cases": cases,
        "claim": (
            "Frozen sampling frame. Outcome labels describe materialized pipeline states; "
            "they are not pedagogical gold labels."
        ),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def validate_frozen_candidate_pool(
    pool_path: str | Path,
    *,
    require_coverage: bool = True,
) -> dict[str, Any]:
    """Verify that a frozen pool still points to the same input bytes."""
    pool = _read(pool_path)
    if pool.get("schema_version") != POOL_VERSION:
        raise ValueError(f"unsupported candidate-pool schema: {pool.get('schema_version')!r}")
    for label, record in (pool.get("frozen_inputs") or {}).items():
        path = Path(str(record.get("path") or ""))
        if not path.is_file() or _sha256(path) != str(record.get("sha256") or ""):
            raise ValueError(f"frozen input changed or missing: {label}: {path}")
    for raw_path, record in (pool.get("merged_from") or {}).items():
        path = Path(str(raw_path))
        if not path.is_file() or _sha256(path) != str(record.get("sha256") or ""):
            raise ValueError(f"merged frozen pool changed or missing: {path}")
    cases = [item for item in pool.get("cases", []) if isinstance(item, dict)]
    counts = {
        outcome: sum(item.get("outcome") == outcome for item in cases) for outcome in OUTCOMES
    }
    missing = [outcome for outcome in OUTCOMES if counts[outcome] == 0]
    if require_coverage and missing:
        raise ValueError("candidate-pool coverage is incomplete: " + ", ".join(missing))
    return {
        "valid": True,
        "case_count": len(cases),
        "counts": counts,
        "missing": missing,
        "coverage_complete": not missing,
    }


def merge_frozen_candidate_pools(
    pool_paths: list[str | Path],
    *,
    output_path: str | Path,
    require_coverage: bool = True,
) -> Path:
    """Merge independently frozen document pools without changing case bytes."""
    if not pool_paths:
        raise ValueError("at least one frozen candidate pool is required")
    pools = [_read(path) for path in pool_paths]
    all_cases: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    frozen_inputs: dict[str, Any] = {}
    for path, pool in zip(pool_paths, pools):
        if pool.get("schema_version") != POOL_VERSION:
            raise ValueError(f"unsupported candidate pool: {path}")
        validate_frozen_candidate_pool(path, require_coverage=False)
        for case in pool.get("cases", []):
            case_id = str(case.get("case_id") or "")
            if not case_id or case_id in seen_case_ids:
                raise ValueError(f"duplicate frozen candidate case: {case_id or '<missing>'}")
            seen_case_ids.add(case_id)
            all_cases.append(case)
        frozen_inputs[str(path)] = {
            "sha256": _sha256(Path(path)),
            "pool_id": pool.get("pool_id"),
        }
    counts = {
        outcome: sum(case.get("outcome") == outcome for case in all_cases) for outcome in OUTCOMES
    }
    missing = [outcome for outcome in OUTCOMES if counts[outcome] == 0]
    if require_coverage and missing:
        raise ValueError("merged candidate-pool coverage is incomplete: " + ", ".join(missing))
    manifest = {
        "schema_version": POOL_VERSION,
        "pool_id": Path(output_path).stem,
        "merged_from": frozen_inputs,
        "required_outcomes": list(OUTCOMES),
        "coverage": {"counts": counts, "missing": missing, "complete": not missing},
        "cases": all_cases,
        "claim": "Merged frozen sampling frame; source pool hashes are immutable.",
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


__all__ = [
    "OUTCOMES",
    "POOL_VERSION",
    "build_frozen_candidate_pool",
    "merge_frozen_candidate_pools",
    "validate_frozen_candidate_pool",
]
