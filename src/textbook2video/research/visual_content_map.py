"""Compile compact, model-chosen element dispositions into an auditable page plan."""

from __future__ import annotations

from copy import deepcopy


def materialize_content_map(arguments: dict, page_context: list[dict] | None) -> tuple[dict, list]:
    if "content_map" not in arguments:
        return deepcopy(arguments), []
    if "page_plan" in arguments or page_context is None:
        raise ValueError("content_map needs page_context and must not also supply page_plan")
    mapping = arguments["content_map"]
    expected = {str(element["id"]) for element in page_context}
    if not isinstance(mapping, dict) or set(mapping) != expected:
        supplied = set(mapping) if isinstance(mapping, dict) else set()
        raise ValueError(
            f"content_map must classify every element exactly once; "
            f"missing={sorted(expected - supplied)}, extra={sorted(supplied - expected)}"
        )
    support, replaced, coverage = [], [], []
    for ident, decision in mapping.items():
        if (
            not isinstance(decision, dict)
            or not isinstance(decision.get("reason"), str)
            or not decision["reason"].strip()
        ):
            raise ValueError(f"content_map {ident} needs a decision object and reason")
        action = decision.get("decision")
        if action == "support":
            support.append(ident)
            continue
        if action not in {"represented", "unsupported_in_source", "irrelevant_to_goal"}:
            raise ValueError(f"content_map {ident} has unsupported decision")
        if any(key in decision for key in ("evidence", "source_evidence", "fact_quotes")):
            raise ValueError("content_map uses source_ref IDs, never retyped evidence or facts")
        proof = {
            "element_id": ident,
            "decision": action,
            "reason": decision["reason"],
            "visual_refs": deepcopy(decision.get("visual_refs", [])),
        }
        if isinstance(proof["visual_refs"], str):
            proof["visual_refs"] = [proof["visual_refs"]]
        reference = decision.get("source_ref")
        no_reference = reference is None or reference == "" or reference == []
        if no_reference and action == "represented":
            raise ValueError(f"content_map {ident} represented facts need source_ref IDs")
        if not no_reference:
            proof["source_ref"] = deepcopy(reference)
        replaced.append(ident)
        coverage.append(proof)
    result = deepcopy(arguments)
    result.pop("content_map")
    result["page_plan"] = {
        "support_element_ids": support,
        "replaces_element_ids": replaced,
        "coverage": coverage,
        "reason": "Compiled from model element decisions; all facts inventoried",
    }
    return result, ["Compiled content_map without inventing decisions, references or source quotes"]
