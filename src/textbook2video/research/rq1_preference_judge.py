"""Forced-choice LLM/VLM Judge for RQ1 visual-support actions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from textbook2video.llm.client import chat_with_images, chat_with_system

PREFERENCE_JUDGE_VERSION = "rq1-visual-preference-judge-v0.3"
CANONICAL_DECISION_JUDGE_VERSION = "rq1-canonical-decision-judge-v1.0"
ALLOWED_ACTIONS = {"none", "reuse", "retrieve", "generate"}
PROPOSAL_AXES = (
    "visual_need",
    "source_sufficiency",
    "acquisition_action",
    "source_fidelity",
    "redundancy_or_decoration",
    "uncertainty_handling",
)


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("RQ1 preference Judge did not return a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("RQ1 preference Judge response must be an object")
    return value


def normalize_preference_judgment(
    value: dict[str, Any],
    *,
    proposition_id: str,
    eligible_actions: list[str],
    judge_kind: str,
) -> dict[str, Any]:
    eligible = set(eligible_actions)
    if not eligible or not eligible <= ALLOWED_ACTIONS:
        raise ValueError("preference Judge has invalid eligible actions")
    abstain = bool(value.get("abstain"))
    ranking = value.get("ranking") or []
    if not isinstance(ranking, list) or any(not isinstance(item, str) for item in ranking):
        raise ValueError("preference Judge ranking must be a string list")
    if abstain:
        ranking = []
    elif len(ranking) != len(eligible) or set(ranking) != eligible:
        raise ValueError("preference Judge must rank every eligible action exactly once")

    reason_by_action = value.get("reason_by_action")
    if not isinstance(reason_by_action, dict):
        raise ValueError("preference Judge requires reason_by_action")
    normalized_reasons: dict[str, str] = {}
    for action in eligible_actions:
        reason = str(reason_by_action.get(action) or "").strip()
        if not reason:
            raise ValueError(f"preference Judge requires a reason for {action}")
        normalized_reasons[action] = reason

    rejected = value.get("rejected_actions") or []
    if not isinstance(rejected, list) or any(action not in eligible for action in rejected):
        raise ValueError("preference Judge rejected_actions must be eligible actions")
    if ranking and ranking[0] in rejected:
        raise ValueError("preference Judge cannot reject its best action")
    if rejected and ranking:
        rejected_set = set(rejected)
        first_rejected = min(ranking.index(action) for action in rejected_set)
        if set(ranking[first_rejected:]) != rejected_set:
            raise ValueError("preference Judge rejected actions must form the ranking suffix")
    try:
        confidence = float(value.get("confidence", 0.5))
    except (TypeError, ValueError) as exc:
        raise ValueError("preference Judge confidence must be numeric") from exc
    confidence = max(0.0, min(1.0, confidence))
    abstain_reason = str(value.get("abstain_reason") or "").strip() or None
    if abstain and not abstain_reason:
        raise ValueError("preference Judge abstention requires abstain_reason")
    return {
        "schema_version": PREFERENCE_JUDGE_VERSION,
        "proposition_id": proposition_id,
        "judge_kind": judge_kind,
        "eligible_actions": eligible_actions,
        "ranking": ranking,
        "best_action": ranking[0] if ranking else None,
        "second_action": ranking[1] if len(ranking) > 1 else None,
        "rejected_actions": sorted(set(rejected)),
        "reason_by_action": normalized_reasons,
        "confidence": round(confidence, 4),
        "abstain": abstain,
        "abstain_reason": abstain_reason,
        "method_blind": True,
    }


def judge_rq1_action_preferences(
    *,
    proposition: dict[str, Any],
    source_evidence: list[dict[str, Any]],
    options: list[dict[str, Any]],
    candidate_images: list[str | Path] | None = None,
    model: str | None = None,
    text_call: Callable[..., str] = chat_with_system,
    image_call: Callable[..., str] = chat_with_images,
) -> dict[str, Any]:
    """Rank all eligible actions in one gold-blind call."""
    proposition_id = str(proposition.get("id") or "").strip()
    if not proposition_id:
        raise ValueError("preference Judge proposition requires id")
    actions = [str(option.get("action") or "") for option in options]
    if len(actions) != len(set(actions)) or not set(actions) <= ALLOWED_ACTIONS:
        raise ValueError("preference Judge options require unique valid actions")
    payload = {
        "task": (
            "Rank the eligible visual-support actions for this proposition. You must choose "
            "one best action unless the evidence is genuinely insufficient."
        ),
        "proposition": {
            "id": proposition_id,
            "text": proposition.get("text") or proposition.get("proposition_text"),
        },
        "source_evidence": source_evidence,
        "options_in_randomized_order": options,
        "rules": [
            "Judge actions comparatively, not as independent yes/no questions.",
            "Prefer the least costly action that still gives a clear instructional benefit.",
            "Reject decorative, redundant, generic, or weakly grounded visuals.",
            "Reuse is eligible only when its supplied image pixels explain the proposition.",
            (
                "For reuse, name the objects or relations actually visible in the image. "
                "Topic similarity is insufficient when the required mechanism is absent."
            ),
            "Retrieve needs a precise query and acceptance criteria.",
            "Generate needs a source-bounded instructional specification.",
            "Rank every eligible action exactly once; ties are not allowed.",
            "Method names, prior predictions, and gold labels are unavailable.",
            "Return JSON only.",
        ],
        "output": {
            "ranking": actions,
            "rejected_actions": ["zero or more actions"],
            "reason_by_action": {action: "short comparative reason" for action in actions},
            "confidence": "0..1",
            "abstain": False,
            "abstain_reason": None,
        },
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    images = list(candidate_images or [])
    call = image_call if images else text_call
    call_kwargs = {
        "system_prompt": "You are a strict comparative instructional-visual evaluator.",
        "model": model,
        "temperature": 0.0,
        "max_tokens": 1800,
        "timeout": 300,
    }
    if images:
        raw = call(
            prompt,
            images,
            **call_kwargs,
        )
        judge_kind = "VLM"
    else:
        raw = call(
            prompt,
            **call_kwargs,
        )
        judge_kind = "LLM"
    try:
        result = normalize_preference_judgment(
            _parse_json(raw),
            proposition_id=proposition_id,
            eligible_actions=actions,
            judge_kind=judge_kind,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        repair_prompt = json.dumps(
            {
                "task": "Repair only the response format; preserve the prior comparative judgment.",
                "validation_error": str(exc),
                "eligible_actions": actions,
                "requirements": [
                    "ranking must contain every eligible action exactly once",
                    "reason_by_action must contain every eligible action",
                    "rejected_actions may contain only eligible actions",
                    "rejected_actions must be a suffix at the end of ranking",
                    "return JSON only",
                ],
                "previous_response": raw,
            },
            ensure_ascii=False,
            indent=2,
        )
        if images:
            repaired_raw = call(repair_prompt, images, **call_kwargs)
        else:
            repaired_raw = call(repair_prompt, **call_kwargs)
        result = normalize_preference_judgment(
            _parse_json(repaired_raw),
            proposition_id=proposition_id,
            eligible_actions=actions,
            judge_kind=judge_kind,
        )
        result["format_repair_used"] = True
        result["initial_validation_error"] = str(exc)
        result["raw_response"] = raw
        result["repair_response"] = repaired_raw
        return result
    result["format_repair_used"] = False
    result["raw_response"] = raw
    return result


def normalize_blind_proposal_judgment(
    value: dict[str, Any], *, proposition_id: str, option_ids: list[str], order: str
) -> dict[str, Any]:
    """Validate rankings over anonymous method proposals, including duplicate actions."""
    allowed = set(option_ids)
    if not allowed or len(allowed) != len(option_ids):
        raise ValueError("blind proposal Judge requires unique option IDs")
    abstain = bool(value.get("abstain"))
    ranking = value.get("ranking") or []
    if not isinstance(ranking, list) or any(not isinstance(item, str) for item in ranking):
        raise ValueError("blind proposal ranking must be a string list")
    if abstain:
        ranking = []
    elif len(ranking) != len(option_ids) or set(ranking) != allowed:
        raise ValueError("blind proposal Judge must rank every anonymous option exactly once")
    acceptable = value.get("acceptable_option_ids") or []
    rejected = value.get("rejected_option_ids") or []
    if (
        not isinstance(acceptable, list)
        or not isinstance(rejected, list)
        or any(not isinstance(item, str) for item in acceptable + rejected)
        or not set(acceptable) <= allowed
        or not set(rejected) <= allowed
        or set(acceptable) & set(rejected)
    ):
        raise ValueError("blind proposal accept/reject sets are invalid or overlap")
    if not abstain and not acceptable:
        raise ValueError("blind proposal Judge must identify at least one acceptable option")
    if not abstain and set(acceptable) | set(rejected) != allowed:
        raise ValueError("every proposal must be marked acceptable or rejected")
    reasons = value.get("reason_by_option")
    if not isinstance(reasons, dict) or any(
        not str(reasons.get(key) or "").strip() for key in option_ids
    ):
        raise ValueError("blind proposal Judge requires a reason for every option")
    scores = value.get("axis_scores")
    if not isinstance(scores, dict) or set(scores) != allowed:
        raise ValueError("blind proposal Judge requires axis scores for every option")
    normalized_scores: dict[str, dict[str, int]] = {}
    for option_id in option_ids:
        row = scores.get(option_id)
        if not isinstance(row, dict) or set(row) != set(PROPOSAL_AXES):
            raise ValueError(f"blind proposal axis schema mismatch: {option_id}")
        normalized_scores[option_id] = {}
        for axis in PROPOSAL_AXES:
            score = row[axis]
            if type(score) is not int or not 1 <= score <= 5:
                raise ValueError(
                    f"blind proposal axis score must be integer 1..5: {option_id}/{axis}"
                )
            normalized_scores[option_id][axis] = score
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence", 0.5))))
    except (TypeError, ValueError) as exc:
        raise ValueError("blind proposal confidence must be numeric") from exc
    abstain_reason = str(value.get("abstain_reason") or "").strip() or None
    if abstain and not abstain_reason:
        raise ValueError("blind proposal abstention requires a reason")
    return {
        "schema_version": "rq1-blind-proposal-judge-v1.0",
        "proposition_id": proposition_id,
        "order": order,
        "ranking": ranking,
        "best_option_id": ranking[0] if ranking else None,
        "acceptable_option_ids": sorted(set(acceptable)),
        "rejected_option_ids": sorted(set(rejected)),
        "reason_by_option": {key: str(reasons[key]).strip() for key in option_ids},
        "axis_scores": normalized_scores,
        "confidence": round(confidence, 4),
        "abstain": abstain,
        "abstain_reason": abstain_reason,
        "method_blind": True,
    }


def judge_rq1_blind_proposals(
    *,
    proposition: dict[str, Any],
    source_evidence: list[dict[str, Any]],
    options: list[dict[str, Any]],
    option_order: list[str],
    order: str,
    attached_image_labels: list[str] | None = None,
    candidate_images: list[str | Path] | None = None,
    model: str | None = None,
    text_call: Callable[..., str] = chat_with_system,
    image_call: Callable[..., str] = chat_with_images,
) -> dict[str, Any]:
    """Judge anonymous, uniformly shaped method outputs; duplicate actions are allowed."""
    proposition_id = str(proposition.get("id") or "").strip()
    by_id = {str(option.get("option_id") or ""): option for option in options}
    if not proposition_id or len(by_id) != len(options) or set(option_order) != set(by_id):
        raise ValueError("blind proposal Judge input IDs are invalid")
    if order not in {"forward", "reverse"}:
        raise ValueError("blind proposal Judge order must be forward or reverse")
    ordered_options = [by_id[key] for key in option_order]
    payload = {
        "task": (
            "Evaluate and rank anonymous proposed visual-support decisions for one source-backed "
            "teaching claim. Judge only the evidence and proposal contents."
        ),
        "claim": {
            "text": proposition.get("text") or proposition.get("proposition_text"),
            "source_refs": proposition.get("source_refs", []),
        },
        "source_evidence": source_evidence,
        "images_attached_in_order": list(attached_image_labels or []),
        "anonymous_options_in_order": ordered_options,
        "rules": [
            "Option identifiers are random labels; do not infer who made an option.",
            "Method names, method rationales, previous Judge results, and gold labels are absent.",
            (
                "Evaluate need, sufficiency of existing material, action, fidelity, redundancy, "
                "and uncertainty separately."
            ),
            "An ungenerated image request is not evidence that a suitable image exists.",
            "A retrieval query without an acceptable returned asset is not a successful retrieval.",
            "Topic overlap alone does not establish that an image explains the claim.",
            (
                "Mark every option acceptable or rejected; retain uncertainty when evidence is "
                "insufficient."
            ),
            "Rank every option exactly once unless abstaining.",
            (
                "Do not treat this judgment as human gold, formal source acceptance, or evidence "
                "of learning gains."
            ),
            "Return JSON only.",
        ],
        "axis_definitions_1_to_5": {
            "visual_need": (
                "How well the proposal avoids both missing needed visual support and adding "
                "unnecessary visuals."
            ),
            "source_sufficiency": (
                "How well it recognizes when source text or existing figures already suffice."
            ),
            "acquisition_action": (
                "Whether none/reuse/retrieve/generate is proportional to the evidence and need."
            ),
            "source_fidelity": (
                "Whether the proposed or selected visual is faithful to the supplied source "
                "and claim."
            ),
            "redundancy_or_decoration": (
                "Higher means less redundant, generic, or decorative visual content."
            ),
            "uncertainty_handling": (
                "Whether confidence, uncertainty, or abstention matches available evidence."
            ),
        },
        "output_schema": {
            "ranking": option_order,
            "acceptable_option_ids": option_order,
            "rejected_option_ids": [],
            "reason_by_option": {key: "short evidence-based reason" for key in option_order},
            "axis_scores": {key: {axis: 1 for axis in PROPOSAL_AXES} for key in option_order},
            "confidence": "0..1",
            "abstain": False,
            "abstain_reason": None,
        },
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    images = list(candidate_images or [])
    kwargs = {
        "system_prompt": "You are an independent, strict instructional-visual evaluator.",
        "model": model,
        "temperature": 0.0,
        "max_tokens": 3600,
        "timeout": 300,
    }
    if images:
        raw = image_call(prompt, images, **kwargs)
        kind = "VLM"
    else:
        raw = text_call(prompt, **kwargs)
        kind = "LLM"
    parsed = _parse_json(raw)
    normalized = normalize_blind_proposal_judgment(
        parsed, proposition_id=proposition_id, option_ids=option_order, order=order
    )
    normalized["judge_kind"] = kind
    normalized["raw_response"] = raw
    normalized["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return normalized


def canonical_decision_view(
    decision: dict[str, Any] | None,
    *,
    source_object_sha256: str | None = None,
) -> dict[str, Any]:
    """Serialize only decision-layer facts for the RQ1 preference Judge.

    Retrieval and generation descriptions, rationales, and acquisition outcomes
    are intentionally excluded. A reuse proposal must retain its concrete
    source-object identity. Retrieved/generated assets are evaluated separately
    in the material-result layer, so a failed fixed-pool lookup cannot redefine
    whether the decision to retrieve was reasonable.
    """
    if not isinstance(decision, dict):
        return {
            "proposal_status": "METHOD_OUTPUT_UNAVAILABLE",
            "action": "NOT_RUN",
            "decision_state": "UNAVAILABLE",
            "uncertainty": {"abstain": False, "uncertain": False},
            "object_reference": {"state": "UNAVAILABLE"},
        }

    action = str(decision.get("action") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        return {
            "proposal_status": "METHOD_OUTPUT_INVALID",
            "action": "NOT_RUN",
            "decision_state": "INVALID",
            "uncertainty": {"abstain": False, "uncertain": False},
            "object_reference": {"state": "INVALID_ACTION"},
        }

    object_reference: dict[str, Any]
    if action == "reuse":
        source_image_id = str(decision.get("source_image_id") or "").strip()
        object_reference = (
            {
                "state": "BOUND_SOURCE_OBJECT",
                "type": "source_image",
                "id": source_image_id,
                "sha256": source_object_sha256,
            }
            if source_image_id
            else {"state": "MISSING_REQUIRED_SOURCE_OBJECT"}
        )
    elif action == "retrieve":
        object_reference = {
            "state": "DEFERRED_TO_ACQUISITION_RESULT",
            "type": "external_candidate",
        }
    elif action == "generate":
        object_reference = {
            "state": "NOT_GENERATED_REQUEST_ONLY",
            "type": "generated_visual",
        }
    else:
        object_reference = {"state": "NO_OBJECT_REQUESTED"}

    return {
        "proposal_status": "DECISION_AVAILABLE",
        "action": action,
        "decision_state": str(decision.get("decision_state") or "UNKNOWN").strip().upper(),
        "uncertainty": {
            "abstain": bool(decision.get("abstain")),
            "uncertain": bool(decision.get("uncertain")),
        },
        "object_reference": object_reference,
    }


def proposal_material_identity(
    decision: dict[str, Any] | None,
    acquisition: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a separate, exact identity for an acquired or reused object."""
    action = str((decision or {}).get("action") or "").strip().lower()
    assets = (acquisition or {}).get("assets") or []
    asset = assets[0] if assets and isinstance(assets[0], dict) else {}
    asset_id = (
        asset.get("catalog_candidate_id")
        or asset.get("source_image_id")
        or asset.get("asset_id")
        or asset.get("best_candidate_id")
    )
    return {
        "action": action or "UNKNOWN",
        "acquisition_status": str(asset.get("status") or "ACQUISITION_RESULT_MISSING"),
        "object_id": str(asset_id) if asset_id is not None else None,
        "sha256": asset.get("sha256"),
        "rights_status": asset.get("rights_status") or asset.get("license"),
    }


def canonical_proposal_groups(
    rows: dict[str, dict[str, Any] | None],
    *,
    source_image_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Group exact decision views and retain every method/material mapping.

    The grouping key includes action, uncertainty state, decision state, and a
    bound reuse object (ID plus hash). It does not include rationale text,
    retrieval query/criteria, generation prose, or whether acquisition happened
    to succeed. Material object identities remain on each method mapping.
    """
    hashes = source_image_hashes or {}
    grouped: dict[str, dict[str, Any]] = {}
    method_views: dict[str, dict[str, Any]] = {}
    material_by_method: dict[str, dict[str, Any]] = {}
    for method_id in sorted(rows):
        row = rows[method_id]
        available = isinstance(row, dict) and row.get("status") == "OK"
        decision = row.get("decision") if available else None
        source_id = str((decision or {}).get("source_image_id") or "").strip()
        view = canonical_decision_view(
            decision,
            source_object_sha256=hashes.get(source_id) if source_id else None,
        )
        serialized = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        proposal_id = "proposal-" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
        method_views[method_id] = {"proposal_id": proposal_id, **view}
        material_by_method[method_id] = proposal_material_identity(
            decision,
            row.get("acquisition") if available else None,
        )
        group = grouped.setdefault(
            proposal_id,
            {"proposal_id": proposal_id, "view": view, "method_ids": [], "material_variants": []},
        )
        group["method_ids"].append(method_id)
        material = material_by_method[method_id]
        if material not in group["material_variants"]:
            group["material_variants"].append(material)

    return {
        "groups": [grouped[key] for key in sorted(grouped)],
        "method_to_proposal": {
            method: method_views[method]["proposal_id"] for method in sorted(method_views)
        },
        "method_views": method_views,
        "material_by_method": material_by_method,
    }


def normalize_canonical_set_judgment(
    value: dict[str, Any],
    *,
    eligible_proposal_ids: list[str],
    proposition_id: str,
    judge_alias: str,
    display_order: str,
) -> dict[str, Any]:
    """Validate a set-valued, tie-permitting decision-layer judgment."""
    eligible = set(eligible_proposal_ids)
    if not eligible or len(eligible) != len(eligible_proposal_ids):
        raise ValueError("canonical Judge requires unique eligible proposal IDs")

    def read_ids(field: str, *, required: bool = True) -> list[str]:
        raw = value.get(field)
        if raw is None and not required:
            return []
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise ValueError(f"canonical Judge {field} must be a string list")
        if len(raw) != len(set(raw)) or not set(raw) <= eligible:
            raise ValueError(f"canonical Judge {field} contains duplicate or unknown proposal IDs")
        return raw

    acceptable = read_ids("acceptable_proposal_ids")
    rejected = read_ids("rejected_proposal_ids")
    preferred = read_ids("preferred_proposal_ids")
    uncertain = read_ids("uncertain_proposal_ids", required=False)
    if set(acceptable) & set(rejected):
        raise ValueError("a proposal cannot be both acceptable and rejected")
    if not set(preferred) <= set(acceptable):
        raise ValueError("preferred proposals must be members of the acceptable set")
    if not set(uncertain) <= eligible:
        raise ValueError("uncertain proposals must be eligible")
    abstain = bool(value.get("abstain"))
    reason = str(value.get("uncertainty_reason") or "").strip() or None
    if abstain and not reason:
        raise ValueError("Judge abstention requires an uncertainty_reason")

    assessment_raw = value.get("assessment_by_proposal")
    if not isinstance(assessment_raw, dict) or set(assessment_raw) != eligible:
        raise ValueError("canonical Judge must assess every eligible proposal exactly once")
    assessment_schema = {
        "visual_need": {"NEEDED", "NOT_NEEDED", "UNCERTAIN"},
        "source_sufficiency": {"SUFFICIENT", "INSUFFICIENT", "UNCERTAIN"},
        "action_fit": {"APPROPRIATE", "INAPPROPRIATE", "UNCERTAIN"},
        "uncertainty_fit": {"APPROPRIATE", "INAPPROPRIATE", "NOT_APPLICABLE", "UNCERTAIN"},
    }
    assessments: dict[str, dict[str, str]] = {}
    for proposal_id in eligible_proposal_ids:
        raw_assessment = assessment_raw.get(proposal_id)
        if not isinstance(raw_assessment, dict) or set(raw_assessment) != set(assessment_schema):
            raise ValueError(f"canonical Judge assessment is incomplete for {proposal_id}")
        normalized_assessment: dict[str, str] = {}
        for axis, allowed_values in assessment_schema.items():
            label = str(raw_assessment.get(axis) or "").strip().upper()
            if label not in allowed_values:
                raise ValueError(f"canonical Judge {axis} label is invalid for {proposal_id}")
            normalized_assessment[axis] = label
        assessments[proposal_id] = normalized_assessment

    strict_raw = value.get("strict_ranking")
    strict_ranking = None
    if strict_raw is not None:
        if (
            not isinstance(strict_raw, list)
            or any(not isinstance(item, str) for item in strict_raw)
            or len(strict_raw) != len(eligible)
            or set(strict_raw) != eligible
        ):
            raise ValueError("optional strict_ranking must order every eligible proposal once")
        strict_ranking = strict_raw

    return {
        "schema_version": CANONICAL_DECISION_JUDGE_VERSION,
        "proposition_id": proposition_id,
        "judge_alias": judge_alias,
        "display_order": display_order,
        "acceptable_proposal_ids": acceptable,
        "rejected_proposal_ids": rejected,
        "preferred_proposal_ids": preferred,
        "uncertain_proposal_ids": uncertain,
        "assessment_by_proposal": assessments,
        "abstain": abstain,
        "uncertainty_reason": reason,
        "strict_ranking_diagnostic": strict_ranking,
    }


def build_canonical_decision_judge_prompt(
    *,
    proposition_id: str,
    proposition_text: str,
    source_context: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    display_order: str,
    attached_image_labels: list[str] | None = None,
) -> str:
    """Build an order-controlled, method-blind decision-layer Judge prompt."""
    if display_order not in {"forward", "reverse"}:
        raise ValueError("display_order must be forward or reverse")
    if not proposals:
        raise ValueError("canonical Judge requires at least one proposal")
    proposal_ids = [item["proposal_id"] for item in proposals]
    if any(not isinstance(item, str) or not item for item in proposal_ids) or len(
        set(proposal_ids)
    ) != len(proposal_ids):
        raise ValueError("canonical Judge requires unique nonempty proposal IDs")
    proposal_ids.sort()
    id_list = {"type": "array", "items": {"enum": proposal_ids}, "uniqueItems": True}
    axes = {
        "visual_need": {"enum": ["NEEDED", "NOT_NEEDED", "UNCERTAIN"]},
        "source_sufficiency": {"enum": ["SUFFICIENT", "INSUFFICIENT", "UNCERTAIN"]},
        "action_fit": {"enum": ["APPROPRIATE", "INAPPROPRIATE", "UNCERTAIN"]},
        "uncertainty_fit": {
            "enum": ["APPROPRIATE", "INAPPROPRIATE", "NOT_APPLICABLE", "UNCERTAIN"]
        },
    }
    assessment = {
        "type": "object",
        "properties": axes,
        "required": list(axes),
        "additionalProperties": False,
    }
    properties = {
        field: id_list
        for field in (
            "acceptable_proposal_ids",
            "rejected_proposal_ids",
            "preferred_proposal_ids",
            "uncertain_proposal_ids",
        )
    }
    properties.update(
        {
            "abstain": {"type": "boolean"},
            "uncertainty_reason": {"type": ["string", "null"]},
            "assessment_by_proposal": {
                "type": "object",
                "properties": {key: assessment for key in proposal_ids},
                "required": proposal_ids,
                "additionalProperties": False,
            },
            "strict_ranking": {
                "anyOf": [
                    {"type": "null"},
                    {**id_list, "minItems": len(proposal_ids), "maxItems": len(proposal_ids)},
                ]
            },
        }
    )
    ordered = list(proposals)
    if display_order == "reverse":
        ordered.reverse()
    payload = {
        "prompt_version": "rq1-canonical-decision-prompt-v1.1",
        "task": (
            "Evaluate the instructional visual-support decision for the proposition using only "
            "the shared source evidence and canonical proposals. This is a decision-layer proxy "
            "judgment, not an evaluation of image quality, retrieval success, or a truth label."
        ),
        "proposition": {"id": proposition_id, "text": proposition_text},
        "shared_source_context": source_context,
        "source_visuals": {
            "attached_image_labels": list(attached_image_labels or []),
            "interpretation_rule": (
                "Inspect supplied source visuals and captions. A visual being on the same page "
                "as a claim does not by itself establish semantic support."
            ),
        },
        "proposals_in_display_order": ordered,
        "evaluation_rules": [
            "Decide whether the proposition benefits from an additional visual.",
            "Judge whether the supplied source text and source visuals are sufficient for this proposition.",
            "Judge whether each proposed action is reasonable given the shared source context.",
            "Treat retrieve as a decision to seek a visual; do not penalize it because a fixed local pool later fails to return an asset.",
            "Treat generate as a request only; no image has been generated by this proposal view.",
            "Assess the exact source object reference for reuse. Do not infer that another object's content is equivalent.",
            "Preserve uncertainty. Multiple proposals may be acceptable or jointly preferred; abstain if evidence is insufficient.",
            "Do not infer which method produced an option, judge search terms or generation wording, infer an acquisition result, or guess an intended winner.",
            "The optional strict_ranking is only a secondary diagnostic. It may be null; never invent distinctions between equivalent proposals.",
            "Return one JSON instance conforming to output_json_schema, not the schema itself. Use only the supplied proposal IDs and one literal enum value per axis. Assess every proposal exactly once.",
            "Acceptable and rejected sets must be disjoint; preferred must be a subset of acceptable. If abstain is true, supply a nonempty uncertainty_reason. These semantic constraints are validated after parsing.",
        ],
        "output_json_schema": {
            "type": "object",
            "properties": properties,
            "required": [
                key for key in properties if key not in {"strict_ranking", "uncertain_proposal_ids"}
            ],
            "additionalProperties": False,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


__all__ = [
    "ALLOWED_ACTIONS",
    "CANONICAL_DECISION_JUDGE_VERSION",
    "PREFERENCE_JUDGE_VERSION",
    "PROPOSAL_AXES",
    "build_canonical_decision_judge_prompt",
    "canonical_decision_view",
    "canonical_proposal_groups",
    "judge_rq1_blind_proposals",
    "judge_rq1_action_preferences",
    "normalize_canonical_set_judgment",
    "normalize_blind_proposal_judgment",
    "normalize_preference_judgment",
    "proposal_material_identity",
]
