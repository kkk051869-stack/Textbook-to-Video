"""Model-facing evidence IDs for the ordinary course binding adapter."""

from copy import deepcopy

from jsonschema import Draft202012Validator


def evidence_catalog(proposition, evidence):
    from .binding_methods import _source_ids

    allowed = _source_ids(proposition["source_refs"])
    return {
        str(unit["id"]): unit["text"] for unit in evidence["source_units"]
        if str(unit["id"]) in allowed and unit.get("text", "").strip()
    }


def id_list(ids):
    return {"type": "array", "uniqueItems": True, "items": {"enum": list(ids)}}


def binding_request(request, catalog):
    """Expose one selection and reference IDs. Keep the existing validator behind it."""
    request = deepcopy(request)
    legacy_schema = request["output_json_schema"]
    schema = deepcopy(legacy_schema)
    for assessment in schema["properties"]["assessment_by_candidate"]["properties"].values():
        fields = assessment["properties"]
        for key in list(fields):
            if key.endswith("_quote") or key == "source_quotes":
                fields.pop(key)
        fields.update(source_ids=id_list(catalog), focus_source_id={
            "anyOf": [{"enum": list(catalog)}, {"type": "null"}],
        })
        assessment["required"] = list(fields)
    for field in ("joint_focus", "selected_candidate_ids", "selection_review"):
        schema["properties"].pop(field)
    text = {"type": "string", "minLength": 1}
    member = {
        "type": "object", "additionalProperties": False,
        "required": ["candidate_id", "contribution"],
        "properties": {
            "candidate_id": {"enum": [c["id"] for c in request["candidates"]]},
            "contribution": text,
        },
    }
    selection_fields = {
        "members": {"type": "array", "items": member},
        "source_ids": id_list(catalog),
        "coverage": {"enum": ["SUFFICIENT", "INSUFFICIENT", "UNCERTAIN"]},
        "minimal": {"type": "boolean"},
        "explanation": text,
    }
    schema["properties"]["selection"] = {
        "type": "object", "properties": selection_fields,
        "required": list(selection_fields), "additionalProperties": False,
    }
    schema["required"] = list(schema["properties"])
    request["output_json_schema"] = schema
    request["source_catalog"] = [{"id": key, "text": value} for key, value in catalog.items()]
    request.pop("source_context", None)
    request["evidence_protocol"] = "course-binding-source-ids-v1"
    request["rules"] = [
        "Assess every candidate once using the supplied source catalog and actual object pixels.",
        "Select evidence by ID only. SUPPORTED requires AFFIRMED polarity, a defined attention_role, "
        "and a focus_source_id from that candidate's source_ids. Explain which role or relation "
        "the candidate depicts and how the cited text supports it.",
        "Check context, negation, roles, direction and required relations. Topic similarity alone "
        "is insufficient. Distinguish the narrated target from rejected or historical alternatives.",
        "Use selection.members for the smallest sufficient set. Each member appears once, "
        "with its contribution. For a joint set cite the shared relation in selection.source_ids.",
        "If the selected pixels cannot express the required relation, use an empty members list "
        "and mark coverage INSUFFICIENT or UNCERTAIN.",
        "Return only the JSON instance for this schema.",
    ]
    return request


def resolve_binding_response(value, schema, catalog):
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise ValueError("Invalid binding reference IDs or selection: " + "; ".join(
            f"/{'/'.join(map(str, error.absolute_path))}: {error.message}" for error in errors
        ))
    selection = value["selection"]
    members = {m["candidate_id"]: m["contribution"] for m in selection["members"]}
    if len(members) != len(selection["members"]):
        raise ValueError("Each selected candidate ID must appear once")
    rows = {}
    for ident, row in value["assessment_by_candidate"].items():
        row = dict(row)
        focus = row.pop("focus_source_id")
        source_ids = row.pop("source_ids")
        if focus is not None and focus not in source_ids:
            raise ValueError(f"Candidate {ident} focus_source_id must belong to its source_ids")
        rows[ident] = {
            **row, "source_quotes": [catalog[ref] for ref in source_ids],
            "focus_quote": catalog[focus] if focus is not None else None,
            "actor_quote": None, "action_quote": None, "patient_quote": None,
            "candidate_label_quote": None,
        }
    quotes = [catalog[ref] for ref in selection["source_ids"]]
    result = {
        "assessment_by_candidate": rows,
        "selected_candidate_ids": list(members),
        "selection_review": {
            "source_quotes": quotes, "member_contributions": members,
            **{k: selection[k] for k in ("coverage", "minimal", "explanation")},
        },
    }
    if len(members) > 1:
        result["joint_focus"] = {
            "candidate_ids": list(members), "source_quotes": quotes,
            "explanation": selection["explanation"],
        }
    return result
