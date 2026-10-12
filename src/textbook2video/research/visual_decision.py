"""Explicit visual-necessity, retrieval, and generation decisions for P0.

The output is intentionally a separate, inspectable artifact.  It never
silently converts an unavailable visual into a decorative image request.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_system

DECISION_VERSION = "p0-visual-decision-v2.0"
_ACTIONS = {"none", "reuse", "retrieve", "generate"}
_DECISION_STATES = {"DECIDED", "UNCERTAIN", "ABSTAIN"}
_SOURCE_SUFFICIENCY = {"SUFFICIENT", "INSUFFICIENT", "UNKNOWN", "NOT_APPLICABLE"}
_RETRIEVAL_SUITABILITY = {"SUITABLE", "UNSUITABLE", "UNKNOWN", "NOT_NEEDED"}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _parse(raw: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("visual decision model did not return JSON")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict) or not isinstance(value.get("decisions"), list):
        raise ValueError("visual decision output requires decisions array")
    return value


def _confidence(value: Any, *, default: float = 0.5) -> float:
    """Coerce a model confidence into a bounded, auditable number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(1.0, number)), 4)


def _normalise_evidence(value: Any, *, rationale: str) -> list[dict[str, Any]]:
    """Normalize rationale evidence without pretending free text is source gold."""
    evidence: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                kind = str(item.get("kind") or item.get("type") or "model_assertion").strip()
                evidence_id = str(item.get("id") or item.get("source_id") or "").strip()
                quote = str(item.get("quote") or item.get("text") or "").strip()
                if kind or evidence_id or quote:
                    evidence.append(
                        {
                            "kind": kind or "model_assertion",
                            "id": evidence_id or None,
                            "quote": quote or None,
                            "status": str(item.get("status") or "MODEL_SUPPLIED"),
                        }
                    )
            elif str(item).strip():
                evidence.append(
                    {
                        "kind": "model_assertion",
                        "id": None,
                        "quote": str(item).strip(),
                        "status": "MODEL_SUPPLIED",
                    }
                )
    # Old v1 artifacts contain only rationale.  Preserve them as explicit
    # model assertions instead of silently calling them source evidence.
    if not evidence and rationale:
        evidence.append(
            {
                "kind": "rationale_text",
                "id": None,
                "quote": rationale,
                "status": "MODEL_ASSERTION_NOT_SOURCE_EVIDENCE",
            }
        )
    return evidence


def normalize_visual_decision(
    item: dict[str, Any],
    *,
    proposition: dict[str, Any] | None = None,
    available_image_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return the v2 decision record used by every second-stage method.

    This function is deliberately deterministic.  It upgrades v1 decisions,
    but marks missing provenance as ``MODEL_ASSERTION_NOT_SOURCE_EVIDENCE`` so
    an upgrade cannot be mistaken for a new VLM judgement.
    """
    if not isinstance(item, dict):
        raise ValueError("visual decision must be an object")
    prop_id = str(item.get("narration_proposition_id") or "").strip()
    action = str(item.get("action") or "").lower().strip()
    if not prop_id or action not in _ACTIONS:
        raise ValueError(f"invalid visual decision: {prop_id}/{action}")
    rationale = str(item.get("rationale") or "").strip()
    state = str(item.get("decision_state") or "").upper().strip()
    abstain = bool(item.get("abstain", False))
    uncertain = bool(item.get("uncertain", False))
    if state not in _DECISION_STATES:
        state = "ABSTAIN" if abstain else ("UNCERTAIN" if uncertain else "DECIDED")
    if state == "ABSTAIN":
        abstain = True
        action = "none"
    if state == "UNCERTAIN":
        uncertain = True
    confidence = _confidence(item.get("confidence"), default=0.35 if uncertain else 0.5)
    source_image_id = str(item.get("source_image_id") or "").strip() or None
    available = available_image_ids or set()
    source_sufficiency = str(item.get("source_sufficiency") or "").upper().strip()
    if source_sufficiency not in _SOURCE_SUFFICIENCY:
        if action == "none" or abstain:
            source_sufficiency = "NOT_APPLICABLE"
        elif (
            action == "reuse"
            and source_image_id
            and (not available or source_image_id in available)
        ):
            source_sufficiency = "SUFFICIENT"
        elif action in {"retrieve", "generate"}:
            source_sufficiency = "INSUFFICIENT"
        else:
            source_sufficiency = "UNKNOWN"
    retrieval_suitability = str(item.get("retrieval_suitability") or "").upper().strip()
    if retrieval_suitability not in _RETRIEVAL_SUITABILITY:
        if action == "retrieve":
            retrieval_suitability = "SUITABLE"
        elif action in {"none", "reuse"} or abstain:
            retrieval_suitability = "NOT_NEEDED"
        elif action == "generate":
            retrieval_suitability = "UNSUITABLE"
        else:
            retrieval_suitability = "UNKNOWN"
    record = {
        "narration_proposition_id": prop_id,
        "action": action,
        "decision_state": state,
        "abstain": abstain,
        "uncertain": uncertain,
        "confidence": confidence,
        "source_sufficiency": source_sufficiency,
        "retrieval_suitability": retrieval_suitability,
        "rationale": rationale,
        "rationale_evidence": _normalise_evidence(
            item.get("rationale_evidence"), rationale=rationale
        ),
        "source_image_id": source_image_id,
        "retrieval_query": str(item.get("retrieval_query") or "").strip() or None,
        "acceptance_criteria": [
            str(value).strip()
            for value in (item.get("acceptance_criteria") or [])
            if str(value).strip()
        ],
        "generation_prompt": str(item.get("generation_prompt") or "").strip() or None,
        "status": str(item.get("status") or ("ABSTAINED" if abstain else "DECIDED")),
    }
    if proposition is not None:
        record["segment_id"] = str(proposition.get("segment_id") or "")
        record["source_refs"] = list(proposition.get("source_refs") or [])
    return record


def validate_visual_decision_document(
    document: dict[str, Any],
    *,
    proposition_ids: set[str] | None = None,
    require_evidence: bool = True,
) -> dict[str, Any]:
    """Validate v2 decisions before they enter planning or comparison."""
    if not isinstance(document, dict) or not isinstance(document.get("decisions"), list):
        raise ValueError("visual decision document requires a decisions array")
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for raw in document["decisions"]:
        record = normalize_visual_decision(raw)
        prop_id = record["narration_proposition_id"]
        if prop_id in seen:
            raise ValueError(f"duplicate visual decision: {prop_id}")
        if proposition_ids is not None and prop_id not in proposition_ids:
            raise ValueError(f"visual decision references unknown proposition: {prop_id}")
        if record["action"] == "reuse" and not record["source_image_id"]:
            raise ValueError(f"reuse decision lacks source_image_id: {prop_id}")
        if record["action"] == "retrieve" and not record["retrieval_query"]:
            raise ValueError(f"retrieve decision lacks retrieval_query: {prop_id}")
        if record["action"] == "generate" and not record["generation_prompt"]:
            raise ValueError(f"generate decision lacks generation_prompt: {prop_id}")
        if require_evidence and not record["rationale_evidence"]:
            raise ValueError(f"visual decision lacks rationale_evidence: {prop_id}")
        if record["abstain"] and record["action"] != "none":
            raise ValueError(f"abstain decision must have action=none: {prop_id}")
        seen.add(prop_id)
        records.append(record)
    if proposition_ids is not None and seen != proposition_ids:
        missing = sorted(proposition_ids - seen)
        extra = sorted(seen - proposition_ids)
        raise ValueError(
            f"visual decisions do not cover propositions: missing={missing}, extra={extra}"
        )
    return {
        "valid": True,
        "schema_version": DECISION_VERSION,
        "decision_count": len(records),
        "state_counts": {
            state: sum(record["decision_state"] == state for record in records)
            for state in sorted(_DECISION_STATES)
        },
        "action_counts": {
            action: sum(record["action"] == action for record in records)
            for action in sorted(_ACTIONS)
        },
    }


def decide_visual_support(
    *,
    proposition_graph_path: str | Path,
    source_evidence_path: str | Path,
    output_path: str | Path,
    model: str | None = None,
    retrieval_catalog_path: str | Path | None = None,
    storyboard_path: str | Path | None = None,
) -> Path:
    """Ask an LLM for exactly one auditable action per narration proposition.

    ``retrieve`` is a real request, not a fake source image.  Its query and
    acceptance criteria are persisted for the retriever.  ``generate`` is
    similarly a candidate request; generation occurs only after that request
    is reviewed/executed by the acquisition stage.
    """
    graph = _read(Path(proposition_graph_path))
    evidence = _read(Path(source_evidence_path))
    images = [
        {
            key: item.get(key)
            for key in (
                "id",
                "filename",
                "caption",
                "description",
                "figure_id",
                "source_locator",
                "asset_kind",
                "teaching_asset_status",
            )
        }
        for item in evidence.get("source_images", [])
        if isinstance(item, dict)
        and str(item.get("availability") or "AVAILABLE_LOCAL") == "AVAILABLE_LOCAL"
        and str(item.get("teaching_asset_status") or "") != "INELIGIBLE_ISOLATED_FIGURE_COMPONENT"
    ]
    catalog = _read(Path(retrieval_catalog_path)) if retrieval_catalog_path else {}
    segment_image_ids: dict[str, set[str]] = {}
    if storyboard_path:
        storyboard = _read(Path(storyboard_path))
        for index, segment in enumerate(storyboard.get("segments", []), start=1):
            if not isinstance(segment, dict):
                continue
            segment_id = str(segment.get("id") or index)
            segment_image_ids[segment_id] = {
                str(element.get("source_image_id") or "")
                for element in segment.get("elements", [])
                if isinstance(element, dict)
                and element.get("type") == "image"
                and str(element.get("source_image_id") or "").strip()
            }
    prop_ids = {
        str(item.get("id"))
        for item in graph.get("narration_propositions", [])
        if isinstance(item, dict)
    }
    image_ids = {str(item.get("id")) for item in images}
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    propositions = [
        item for item in graph.get("narration_propositions", []) if isinstance(item, dict)
    ]
    by_segment: dict[str, list[dict[str, Any]]] = {}
    for proposition in propositions:
        by_segment.setdefault(str(proposition.get("segment_id") or ""), []).append(proposition)
    model_items: list[dict[str, Any]] = []
    for segment_id in sorted(by_segment):
        segment_images = (
            [
                item
                for item in images
                if str(item.get("id") or "") in segment_image_ids.get(segment_id, set())
            ]
            if storyboard_path
            else images
        )
        prompt = json.dumps(
            {
                "task": (
                    "For each narration proposition, decide whether an explanatory visual "
                    "is needed and how to acquire it."
                ),
                "allowed_actions": {
                    "none": "no visual improves this proposition; state why",
                    "reuse": "reuse one source_image_id already present in this storyboard segment",
                    "retrieve": (
                        "retrieve a copyright-safe external visual; include a precise "
                        "retrieval_query and acceptance_criteria"
                    ),
                    "generate": (
                        "request a new schematic visual only when source/retrieval are "
                        "unsuitable; include generation_prompt"
                    ),
                },
                "rules": [
                    "Do not select a visual for decoration or merely to make a page rich.",
                    (
                        "Never treat an isolated PDF image component as a complete Figure; "
                        "only supplied eligible assets may be reused."
                    ),
                    (
                        "Reuse requires a listed source_image_id and must name what the "
                        "figure explains."
                    ),
                    (
                        "A source figure listed for another segment is not reusable here; "
                        "choose none, retrieve, or generate instead."
                    ),
                    "Retrieve/generate are requests, not completed assets.",
                    "Return exactly one decision per narration_proposition_id.",
                ],
                "narration_propositions": by_segment[segment_id],
                "source_images": segment_images,
                "retrieval_catalog_summary": catalog.get("summary")
                if isinstance(catalog, dict)
                else None,
                "output_schema": {
                    "decisions": [
                        {
                            "narration_proposition_id": "id",
                            "action": "none|reuse|retrieve|generate",
                            "decision_state": "DECIDED|UNCERTAIN|ABSTAIN",
                            "abstain": "boolean",
                            "uncertain": "boolean",
                            "confidence": "0..1",
                            "source_sufficiency": "SUFFICIENT|INSUFFICIENT|UNKNOWN|NOT_APPLICABLE",
                            "retrieval_suitability": "SUITABLE|UNSUITABLE|UNKNOWN|NOT_NEEDED",
                            "rationale": "why",
                            "rationale_evidence": [
                                {
                                    "kind": (
                                        "source_unit|caption|storyboard_element|model_assertion"
                                    ),
                                    "id": "id or null",
                                    "quote": "short evidence",
                                    "status": "...",
                                }
                            ],
                            "source_image_id": "only reuse",
                            "retrieval_query": "only retrieve",
                            "acceptance_criteria": ["only retrieve"],
                            "generation_prompt": "only generate",
                        }
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        reply = _parse(
            chat_with_system(
                prompt,
                system_prompt="You are an instructional visual designer. Output only valid JSON.",
                model=model,
                temperature=0.0,
                max_tokens=4096,
                timeout=600,
            )
        )
        model_items.extend(reply["decisions"])
    for item in model_items:
        if not isinstance(item, dict):
            raise ValueError("visual decision entries must be objects")
        prop_id = str(item.get("narration_proposition_id") or "")
        action = str(item.get("action") or "").lower()
        if prop_id not in prop_ids or prop_id in seen or action not in _ACTIONS:
            raise ValueError(f"invalid or duplicate visual decision: {prop_id}/{action}")
        proposition = next(value for value in propositions if str(value.get("id") or "") == prop_id)
        segment_id = str(proposition.get("segment_id") or "")
        allowed_reuse_ids = (
            segment_image_ids.get(segment_id, image_ids) if storyboard_path else image_ids
        )
        if action == "reuse" and str(item.get("source_image_id") or "") not in allowed_reuse_ids:
            raise ValueError(f"reuse decision references unavailable source image: {prop_id}")
        if action == "retrieve" and not str(item.get("retrieval_query") or "").strip():
            raise ValueError(f"retrieve decision lacks retrieval_query: {prop_id}")
        if action == "generate" and not str(item.get("generation_prompt") or "").strip():
            raise ValueError(f"generate decision lacks generation_prompt: {prop_id}")
        seen.add(prop_id)
        decisions.append(
            normalize_visual_decision(
                item,
                proposition=proposition,
                available_image_ids=allowed_reuse_ids,
            )
        )
    if seen != prop_ids:
        raise ValueError(
            "visual decisions must cover every narration proposition; "
            f"missing={sorted(prop_ids - seen)}"
        )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": DECISION_VERSION,
        "proposition_graph_path": str(proposition_graph_path),
        "source_evidence_path": str(source_evidence_path),
        "retrieval_catalog_path": str(retrieval_catalog_path) if retrieval_catalog_path else None,
        "storyboard_path": str(storyboard_path) if storyboard_path else None,
        "decisions": decisions,
    }
    validate_visual_decision_document(document, proposition_ids=prop_ids)
    destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


__all__ = [
    "DECISION_VERSION",
    "decide_visual_support",
    "normalize_visual_decision",
    "validate_visual_decision_document",
]
