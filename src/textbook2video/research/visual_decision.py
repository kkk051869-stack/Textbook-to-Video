"""Explicit visual-necessity, retrieval, and generation decisions for P0.

The output is intentionally a separate, inspectable artifact.  It never
silently converts an unavailable visual into a decorative image request.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_images, chat_with_system

DECISION_VERSION = "p0-visual-decision-v2.0"
_ACTIONS = {"none", "reuse", "retrieve", "generate"}
_DECISION_STATES = {"DECIDED", "UNCERTAIN", "ABSTAIN"}
_SOURCE_SUFFICIENCY = {"SUFFICIENT", "INSUFFICIENT", "UNKNOWN", "NOT_APPLICABLE"}
_RETRIEVAL_SUITABILITY = {"SUITABLE", "UNSUITABLE", "UNKNOWN", "NOT_NEEDED"}
RQ1_RESEARCH_CONDITIONS = {
    "direct_llm",
    "proposed",
    "no_source",
    "without_source_sufficiency",
    "without_retrieval_suitability",
    "without_uncertainty_handling",
}


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
    research_condition: str | None = None,
    consider_existing_components: bool = False,
) -> Path:
    """Ask an LLM for exactly one auditable action per narration proposition.

    ``retrieve`` is a real request, not a fake source image.  Its query and
    acceptance criteria are persisted for the retriever.  ``generate`` is
    similarly a candidate request; generation occurs only after that request
    is reviewed/executed by the acquisition stage.
    """
    graph = _read(Path(proposition_graph_path))
    evidence = _read(Path(source_evidence_path))
    if research_condition is not None and research_condition not in RQ1_RESEARCH_CONDITIONS:
        raise ValueError(f"unknown RQ1 research condition: {research_condition}")
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
                "page_number",
                "asset_kind",
                "teaching_asset_status",
                "license",
                "rights_status",
                "local_path",
                "sha256",
            )
        }
        for item in evidence.get("source_images", [])
        if isinstance(item, dict)
        and str(item.get("availability") or "AVAILABLE_LOCAL") == "AVAILABLE_LOCAL"
        and str(item.get("teaching_asset_status") or "") != "INELIGIBLE_ISOLATED_FIGURE_COMPONENT"
    ]
    catalog = _read(Path(retrieval_catalog_path)) if retrieval_catalog_path else {}
    segment_image_ids: dict[str, set[str]] = {}
    segment_components: dict[str, list[dict]] = {}
    if storyboard_path:
        storyboard = _read(Path(storyboard_path))
        for index, segment in enumerate(storyboard.get("segments", []), start=1):
            if not isinstance(segment, dict):
                continue
            segment_id = str(segment.get("id") or index)
            segment_components[segment_id] = segment.get('elements', [])
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
    source_units = {
        str(item.get("id") or ""): item
        for item in evidence.get("source_units", [])
        if isinstance(item, dict) and item.get("id")
    }
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
        prompt_payload = {
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
                    "Source visuals may be linked from another page when section, caption, "
                    "or document structure makes them relevant. Page co-location alone is "
                    "not evidence of semantic support. Inspect the exact visual and caption."
                ),
                    (
                        "A source figure listed for another segment is not reusable here; "
                        "choose none, retrieve, or generate instead."
                    ),
                    "Retrieve/generate are requests, not completed assets.",
                    "Return exactly one decision per narration_proposition_id.",
                ],
                "narration_propositions": by_segment[segment_id],
                "source_images": [
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"local_path", "sha256"}
                    }
                    for item in segment_images
                ],
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
            }
        image_paths: list[str] = []
        if research_condition is not None:
            segment_propositions = by_segment[segment_id]
            prompt_payload["allowed_actions"]["retrieve"] = (
                "select only from the supplied frozen local candidate catalog; include a precise "
                "retrieval_query and acceptance_criteria. This is not open-web retrieval."
            )
            prompt_payload["rules"].append(
                "The same frozen local candidate catalog is available in every condition; "
                "do not claim network retrieval or completed image generation."
            )
            referenced_ids = sorted(
                {
                    str(ref)
                    for proposition in segment_propositions
                    for ref in proposition.get("source_refs", [])
                    if str(ref)
                }
            )
            if research_condition != "no_source":
                missing_refs = [ref for ref in referenced_ids if ref not in source_units]
                if missing_refs:
                    raise ValueError(
                        f"research condition has unresolved source refs: {missing_refs}"
                    )
                prompt_payload["source_context"] = [
                    {
                        "id": ref,
                        "source_locator": source_units[ref].get("source_locator"),
                        "text": source_units[ref].get("text"),
                        "exact_claim_quote": source_units[ref].get("exact_claim_quote"),
                    }
                    for ref in referenced_ids
                ]
                selected_visual_ids = {
                    str(item.get("id") or "") for item in segment_images if item.get("id")
                }
                prompt_payload["source_visual_inventory"] = [
                    {
                        key: item.get(key)
                        for key in (
                            "id",
                            "caption",
                            "description",
                            "source_locator",
                            "page_number",
                            "availability",
                            "teaching_asset_status",
                            "license",
                            "rights_status",
                        )
                    }
                    for item in evidence.get("source_images", [])
                    if isinstance(item, dict)
                    and str(item.get("id") or "") in selected_visual_ids
                ]
                image_paths = [
                    str(item["local_path"])
                    for item in segment_images
                    if item.get("local_path") and Path(str(item["local_path"])).is_file()
                ]
            else:
                # The claim under evaluation remains visible; source references,
                # surrounding source text, captions, IDs, and image pixels do not.
                prompt_payload["source_images"] = []
                prompt_payload["source_visual_inventory"] = []
                prompt_payload["allowed_actions"]["reuse"] = (
                    "unavailable in this condition because no source asset information is visible"
                )
                prompt_payload["narration_propositions"] = [
                    {
                        key: value
                        for key, value in proposition.items()
                        if key not in {"source_refs", "source_anchor", "knowledge_proposition_ids"}
                    }
                    for proposition in segment_propositions
                ]

            if research_condition == "direct_llm":
                prompt_payload["task"] = (
                    "For each claim, directly choose the best visual-support action. "
                    "Do not follow a staged decision procedure."
                )
                prompt_payload["rules"] = [
                    "Choose one action supported by the visible inputs.",
                    "Return one decision for every supplied proposition.",
                ]
            elif research_condition == "proposed":
                prompt_payload["task"] = (
                    "Apply the proposed source-conditioned RQ1 decision procedure to each claim."
                )
                prompt_payload["rules"] = [
                    "First decide whether an additional visual has instructional value.",
                    "Check whether source text and available source visuals already suffice.",
                    "If more support is needed, assess whether a fixed-pool retrieval is suitable.",
                    (
                        "Use generate only as a request when no existing source or pool item is "
                        "suitable."
                    ),
                    "Preserve uncertainty and abstain when evidence cannot support a choice.",
                    "Do not choose visuals for decoration or topic similarity alone.",
                ]
            elif research_condition == "no_source":
                prompt_payload["task"] = (
                    "Choose a visual-support action for each claim without source context."
                )
                prompt_payload["rules"] = [
                    "The claim text is the only source-related input; no source references, "
                    "captions, source images, or source pixels are available.",
                    "Do not choose reuse because no source asset IDs are visible.",
                    "Preserve uncertainty when the visible claim alone is insufficient.",
                ]
            elif research_condition in {
                "without_source_sufficiency",
                "without_retrieval_suitability",
            }:
                prompt_payload["task"] = (
                    "Apply the proposed source-conditioned RQ1 visual-support decision procedure."
                )
                prompt_payload["rules"] = [
                    "Decide whether an additional visual is instructionally useful.",
                    "Use only the decision criteria present in this condition's output schema.",
                    "Preserve uncertainty and abstain when evidence cannot support a choice.",
                    "Do not choose visuals for decoration or topic similarity alone.",
                ]
                field = (
                    "source_sufficiency"
                    if research_condition == "without_source_sufficiency"
                    else "retrieval_suitability"
                )
                prompt_payload["output_schema"]["decisions"][0].pop(field, None)
            elif research_condition == "without_uncertainty_handling":
                prompt_payload["task"] = (
                    "Apply the proposed source-conditioned RQ1 visual-support decision procedure."
                )
                prompt_payload["rules"] = [
                    "Select a single definite action for each proposition.",
                    "This decision condition does not offer uncertainty or abstention.",
                    "Do not choose visuals for decoration or topic similarity alone.",
                ]
                prompt_payload["output_schema"]["decisions"][0].update(
                    {"decision_state": "DECIDED", "abstain": False, "uncertain": False}
                )
            if research_condition != "no_source":
                prompt_payload["rules"].append(
                    "Page co-location alone is not evidence that a source visual semantically supports a claim; use the linked component, caption, and surrounding section evidence."
                )
            prompt_payload["research_condition"] = research_condition

        # Condition-specific reasoning may replace rules, but asset identity is
        # an execution constraint shared by every condition, not an ablation.
        reusable_ids = (
            [] if research_condition == "no_source"
            else sorted(str(item["id"]) for item in segment_images if item.get("id"))
        )
        prompt_payload["allowed_source_image_ids"] = reusable_ids
        prompt_payload["rules"].extend([
            "For action=reuse, source_image_id must be one of allowed_source_image_ids; "
            "an empty list means reuse is unavailable.",
            "Native storyboard components and retrieval catalog IDs are not source image IDs. "
            "Existing native components are handled by binding, not image acquisition; "
            "this decision does not select or bind them. Do not place their IDs in source_image_id.",
        ])
        prompt = json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        if consider_existing_components:
            if research_condition is not None:
                raise ValueError('ordinary page sufficiency context cannot alter research conditions')
            prompt_payload['existing_page_components'] = segment_components.get(segment_id, [])
            refs = sorted({str(ref) for prop in by_segment[segment_id] for ref in prop.get('source_refs', [])})
            if any(ref not in source_units for ref in refs):
                raise ValueError('ordinary visual decision has unresolved source references')
            prompt_payload['source_context'] = [source_units[ref] for ref in refs]
            for entry in prompt_payload["output_schema"]["decisions"][0]["rationale_evidence"]:
                entry.pop("quote", None)
                entry.pop("status", None)
            prompt_payload["rules"].append(
                "For rationale_evidence, submit a supplied source_unit, caption or "
                "storyboard_element ID and its kind. The executor retrieves the text."
            )
            prompt_payload['allowed_actions']['none'] = (
                'No ADDITIONAL visual support is needed for the learning inference; '
                'explain how the existing page conveys it, not why assets are unavailable.'
            )
            prompt_payload['rules'].extend([
                'Reason in this order within rationale: identify the learning inference in the claim; '
                'assess the expressive capability of existing_page_components; then choose acquisition only if a gap remains.',
                'Assess whether learners can infer the relevant objects, relationships, spatial arrangement, '
                'quantities or changes from the actual components. A paragraph naming a relationship does not '
                'by itself establish adequate visual support. Conversely, a concise definition, formula, table '
                'or existing flow may suffice; process/mechanism vocabulary alone never requires a diagram.',
                'Decide the explanatory gap independently of asset availability. No suitable source image, '
                'an empty retrieval catalog or failed acquisition is not a reason for none. If a supported gap '
                'remains, request retrieve or generate; if the need itself cannot be determined, preserve uncertainty.',
                'Only after establishing a gap, prefer an eligible relevant source asset for reuse; '
                'otherwise request retrieval for a suitable real-world visual or generation for a source-supported schematic. '
                'Requests are not successful acquisition or approval.',
                'Do not duplicate adequate existing components. Native component IDs are not source-image reuse IDs. '
                'Do not assume an image description or an unavailable image has been rendered or reviewed.',
            ])
            prompt = json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        system_prompt = (
            "You are an instructional visual decision model. Output only valid JSON."
            if research_condition is not None
            else "You are an instructional visual designer. Output only valid JSON."
        )
        if image_paths:
            raw_reply = chat_with_images(
                prompt,
                image_paths,
                system_prompt=system_prompt,
                model=model,
                temperature=0.0,
                max_tokens=4096,
                timeout=600,
            )
        else:
            raw_reply = chat_with_system(
                prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.0,
                max_tokens=4096,
                timeout=600,
            )
        reply = _parse(raw_reply)
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
        if consider_existing_components:
            from textbook2video.pipeline.visual_page_plan import visible_facts

            cited = set(proposition.get("source_refs", []))
            components = {str(e["id"]): e for e in segment_components.get(segment_id, [])
                          if isinstance(e, dict) and e.get("id")}
            captions = {str(e["id"]): e.get("caption") or e.get("description")
                        for e in images if str(e.get("id")) in allowed_reuse_ids}
            resolved = []
            for ref in item.get("rationale_evidence") or []:
                if not isinstance(ref, dict):
                    continue
                ident = str(ref.get("id") or "")
                kind = ref.get("kind")
                quote = None
                if kind == "source_unit" and ident in cited:
                    quote = source_units[ident]["text"]
                elif kind == "caption":
                    quote = captions.get(ident)
                elif kind == "storyboard_element" and ident in components:
                    quote = "\n".join(visible_facts(components[ident]))
                if quote:
                    resolved.append({
                        "kind": kind, "id": ident, "quote": quote, "status": "RESOLVED_REFERENCE_ID",
                    })
            item = {**item, "rationale_evidence": resolved}
        if action == "reuse" and str(item.get("source_image_id") or "") not in allowed_reuse_ids:
            raise ValueError(f"reuse decision references unavailable source image: {prop_id}")
        if research_condition == "no_source" and action == "reuse":
            raise ValueError(f"no_source condition cannot reuse a hidden source image: {prop_id}")
        if action == "retrieve" and not str(item.get("retrieval_query") or "").strip():
            raise ValueError(f"retrieve decision lacks retrieval_query: {prop_id}")
        if action == "generate" and not str(item.get("generation_prompt") or "").strip():
            raise ValueError(f"generate decision lacks generation_prompt: {prop_id}")
        seen.add(prop_id)
        normalized = normalize_visual_decision(
                item,
                proposition=proposition,
                available_image_ids=allowed_reuse_ids,
            )
        if research_condition in {
            "no_source",
            "without_source_sufficiency",
        }:
            normalized["source_sufficiency"] = "UNKNOWN"
        if research_condition == "without_retrieval_suitability":
            normalized["retrieval_suitability"] = "UNKNOWN"
        if research_condition == "without_uncertainty_handling":
            if bool(item.get("abstain")) or bool(item.get("uncertain")) or str(
                item.get("decision_state") or "DECIDED"
            ).upper() != "DECIDED":
                raise ValueError(
                    f"without_uncertainty_handling returned uncertainty: {prop_id}"
                )
            normalized.update(
                {"decision_state": "DECIDED", "abstain": False, "uncertain": False}
            )
        normalized["research_condition"] = research_condition
        normalized["field_explicitness"] = {
            "source_sufficiency": bool(str(item.get("source_sufficiency") or "").strip()),
            "retrieval_suitability": bool(
                str(item.get("retrieval_suitability") or "").strip()
            ),
            "uncertainty": any(
                key in item for key in ("decision_state", "abstain", "uncertain")
            ),
        }
        decisions.append(normalized)
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
