"""Optional model-assisted relation coverage check, never semantic gold."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

SEMANTIC_VERSION = "context-semantic-sufficiency-v1"


def semantic_images(candidates: list[dict], full_figure: dict) -> list[dict]:
    """Resolve all original pixels, checking binary integrity before model calls."""
    images = []
    for role, item in [("full_figure", full_figure)] + [(c["id"], c) for c in candidates]:
        path = Path(item["local_path"]).resolve(strict=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"semantic image hash mismatch: {role}")
        images.append({"index": len(images) + 1, "role": role, "path": str(path), "sha256": digest})
    return images


def check_semantic_sufficiency(
    prop, candidates, selected_ids, images, source_evidence, model_fn, trace
):
    # Lazy import keeps the existing locator as the sole evidence implementation.
    from .binding_methods import _context_source_regions, _evidence_anchors, _parse_model_json

    context = prop["source_context"]
    regions = _context_source_regions(context, prop["source_refs"], source_evidence)
    text = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": text}
    relation = {
        "type": "object",
        "properties": {
            "relation": text,
            "source_quote": text,
            "visual_evidence": text,
            "candidate_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"enum": selected_ids},
            },
        },
        "required": ["relation", "source_quote", "visual_evidence", "candidate_ids"],
        "additionalProperties": False,
    }
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"enum": ["SUFFICIENT", "INSUFFICIENT", "UNCERTAIN"]},
            "source_claim": text,
            "required_relations": {**strings, "minItems": 1},
            "object_relevance": {"enum": ["RELEVANT", "IRRELEVANT", "UNCERTAIN"]},
            "satisfied_relations": {"type": "array", "items": relation},
            "missing_relations": strings,
            "uncertainties": strings,
            "explanation": text,
        },
        "additionalProperties": False,
    }
    schema["required"] = list(schema["properties"])
    payload = {
        "version": SEMANTIC_VERSION,
        "task": "Independently check whether selected pixels explain the "
        "core teaching proposition.",
        "narration": prop["text"],
        "textbook_evidence": {"source_context": context, "source_refs": prop["source_refs"]},
        "visual_evidence": {
            "images": images,
            "candidates": [
                {"id": c["id"], "label": c.get("text"), "source_locator": c.get("source_locator")}
                for c in candidates
            ],
            "selected_candidate_ids": selected_ids,
        },
        "rules": [
            "Derive required teaching relations from narration and textbook "
            "BEFORE assessing pixels. "
            "Distinguish textbook claims from facts actually shown in the selected regions.",
            "Object relevance is not relation coverage. Check direction, operands, operations, "
            "composition, comparison, causality or dependencies as required by this proposition; "
            "never fill missing visual relations from general knowledge or nearby labels.",
            "The full figure and unselected crops supply context only. They "
            "do not count as selected "
            "content. A selected whole figure can cover multiple roles; do not require every crop.",
            "For each satisfied relation cite a contiguous supplied source quote, the selected IDs "
            "and concrete visible evidence (labels, connectors, equations or "
            "other shown structure). "
            "If required detail is absent, report INSUFFICIENT; "
            "unreadable/ambiguous evidence means "
            "UNCERTAIN. State missing relations and uncertainties, not an expected replacement ID.",
            "SUFFICIENT requires all necessary relations visible in the selected set, not just "
            "relevant entities. It is model-assisted judgment, not independent gold, final page "
            "readability or learning effectiveness. Return only the requested JSON instance.",
        ],
        "output_json_schema": schema,
    }
    trace["prompt"] = json.dumps(payload, ensure_ascii=False, indent=2)
    raw = model_fn(trace["prompt"], [i["path"] for i in images])
    trace["raw_response"] = raw
    value = _parse_model_json(raw)
    errors = [
        f"/{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(value)
    ]
    if errors:
        raise ValueError("semantic checker output invalid: " + "; ".join(errors))
    anchors = []
    for item in value["satisfied_relations"]:
        located = _evidence_anchors(context, item["source_quote"], regions)
        if not located:
            raise ValueError("semantic checker source quote not locatable")
        anchors.append(located)
    verdict = value["verdict"]
    if verdict == "SUFFICIENT" and (
        not value["satisfied_relations"]
        or value["missing_relations"]
        or value["uncertainties"]
        or value["object_relevance"] != "RELEVANT"
    ):
        raise ValueError("semantic checker SUFFICIENT conflicts with evidence/coverage fields")
    if verdict == "INSUFFICIENT" and not value["missing_relations"]:
        raise ValueError("semantic checker INSUFFICIENT requires missing relations")
    if verdict == "UNCERTAIN" and not value["uncertainties"]:
        raise ValueError("semantic checker UNCERTAIN requires an explicit uncertainty")
    trace["result"] = {
        **value,
        "version": SEMANTIC_VERSION,
        "source_quote_anchors": anchors,
        "evidence_level": "MODEL_ASSISTED_NOT_GOLD_NOT_RENDERED",
    }
    return trace["result"]
