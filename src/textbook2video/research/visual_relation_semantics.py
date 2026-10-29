"""Shared semantic planning checks; these rules never infer facts for the model."""

from copy import deepcopy

RELATION_QUESTIONS = {
    "state_ownership": "Who stores/owns which object's state or reference? "
                       "Distinguish the entities.",
    "change_effect": "Which object's state changes and which separately stored state "
                     "stays unchanged?",
    "comparison_operands": "Which TWO values of the same quantity/representation are compared? "
                           "A derived value and raw data are not equivalent comparison operands.",
    "detection_actor": "Who detects/acts on the discrepancy? "
                       "Distinguish that actor from the changer.",
    "edge_meaning": "Do visible edge labels/directions express the source's actual "
                    "subject/action/object?",
}


def relation_audit_contract():
    return {
        "questions": deepcopy(RELATION_QUESTIONS),
        "response": "Return relation_audit as an object with EVERY question ID exactly once. "
                    "Each value: {status:visible|missing|incorrect|not_applicable|not_specified, "
                    "reason:string, visual_id?:string, source_ref?:source ID(s), "
                    "source_evidence?:exact source excerpt, "
                    "visible_evidence?:[exact node label/detail, edge label or table cell,...]}. "
                    "visible/missing/incorrect require visual_id and source evidence. "
                    "PREFER source_ref IDs from source_units and OMIT source_evidence: "
                    "the executor copies exact selected excerpts. Never copy narration as source. "
                    "visible and incorrect require visible_evidence from the actual spec AND "
                    "screenshots. Do not use titles/goals/narration as visible proof. "
                    "Use not_applicable only when that role is outside the explanation's scope; "
                    "use not_specified when the SOURCE does not specify it, never to excuse "
                    "an omission in the diagram. Explain both decisions. A visible generic "
                    "chain does not prove ownership or the comparison operands. "
                    "missing/incorrect force REVISE even with scores=4.",
    }


def materialize_relation_audit(report, source):
    """Use the existing ID/exact-excerpt contract; never infer a missing citation."""
    from textbook2video.research.visual_source_refs import materialize_source_refs

    result = deepcopy(report)
    changes = []
    audit = result.get("relation_audit")
    for key, item in audit.items() if isinstance(audit, dict) else []:
        if not isinstance(item, dict) or "source_ref" not in item:
            continue
        citation = {"source_ref": item["source_ref"]}
        if "source_evidence" in item:
            citation["evidence"] = item["source_evidence"]
        resolved, messages = materialize_source_refs(citation, source, None)
        item["source_evidence"] = resolved["evidence"]
        changes.extend(f"relation_audit/{key}: {message}" for message in messages)
    for key, item in audit.items() if isinstance(audit, dict) else []:
        for group in item.get('evidence_by_visual', []) if isinstance(item, dict) else []:
            if not isinstance(group, dict) or 'source_ref' not in group:
                continue
            citation = {'source_ref': group['source_ref']}
            if 'source_evidence' in group:
                citation['evidence'] = group['source_evidence']
            resolved, messages = materialize_source_refs(citation, source, None)
            group['source_evidence'] = resolved['evidence']
            changes.extend(f'relation_audit/{key}/{group.get("visual_id")}: {m}' for m in messages)
    return result, changes


def relation_findings(report):
    """Retain negative audit findings even when a protocol repair is needed."""
    audit = report.get("relation_audit")
    findings = []
    for question, item in audit.items() if isinstance(audit, dict) else []:
        if (question in RELATION_QUESTIONS and isinstance(item, dict)
                and isinstance(item.get("status"), str)
                and item["status"] in {"missing", "incorrect"}):
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                reason = "Reviewer flagged this relation; explanation pending protocol completion."
            groups = item.get('evidence_by_visual')
            locations = groups if isinstance(groups, list) and groups else [item]
            for location in locations:
                if not isinstance(location, dict):
                    continue
                findings.append({
                    "visual_id": location.get("visual_id", ""),
                    "category": "missing_content" if item["status"] == "missing" else "factual_error",
                    "issue": f"{question}: {reason}",
                    "change": "Resolve this source-grounded relationship in the visible diagram.",
                })
    return findings


def validate_relation_audit(report, specs, source):
    audit = report.get("relation_audit")
    if not isinstance(audit, dict) or set(audit) != set(RELATION_QUESTIONS):
        raise ValueError("relation_audit must answer every relationship question exactly once")
    by_id = {spec["id"]: spec for spec in specs}
    for question, item in audit.items():
        if (not isinstance(item, dict)
                or not isinstance(item.get("status"), str) or item["status"] not in {
                    "visible", "missing", "incorrect", "not_applicable", "not_specified"}
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()):
            raise ValueError(f"relation_audit {question} requires status and reason")
        if item["status"] in {"not_applicable", "not_specified"}:
            continue
        if 'evidence_by_visual' in item:
            groups = item['evidence_by_visual']
            if (not isinstance(groups, list) or not groups
                    or any(not isinstance(g, dict)
                           or set(g) - {'visual_id', 'visible_evidence', 'source_ref', 'source_evidence'}
                           or not isinstance(g.get('visual_id'), str) for g in groups)
                    or len({g.get('visual_id') for g in groups}) != len(groups)):
                raise ValueError(f'relation_audit {question} requires unique per-visual evidence')
            for group in groups:
                # Reuse the exact single-visual gate for every selected panel.
                # No cross-panel label/citation pooling may satisfy it.
                single = {'status': item['status'], 'reason': item['reason'], **group}
                other = {key: {'status': 'not_applicable', 'reason': 'Validated separately'}
                         for key in RELATION_QUESTIONS if key != question}
                validate_relation_audit({'relation_audit': {**other, question: single}}, specs, source)
            continue
        visual_id, quote = item.get("visual_id"), item.get("source_evidence")
        quotes = [quote] if isinstance(quote, str) else quote
        if (not isinstance(visual_id, str) or visual_id not in by_id
                or not isinstance(quotes, list) or not quotes
                or any(not isinstance(text, str) or not text.strip() or text not in source
                       for text in quotes)):
            raise ValueError(
                f"relation_audit {question} requires actual visual and exact source evidence"
            )
        spec = by_id[visual_id]
        diagram = spec.get("diagram") if spec.get("kind") == "relationship" else spec
        texts = []
        for obj in [*diagram.get("nodes", []), *diagram.get("edges", [])]:
            texts.extend(obj[key] for key in ("label", "detail") if obj.get(key))
        if diagram.get("constraint"):
            texts.append(diagram["constraint"])
        texts.extend(cell for row in spec.get("rows", []) for cell in row)
        visible = item.get("visible_evidence")
        if item["status"] in {"visible", "incorrect"} and (
            not isinstance(visible, list) or not visible
            or any(not isinstance(text, str) or text not in texts for text in visible)
        ):
            raise ValueError(f"relation_audit {question} requires exact visible evidence")

RELATION_RULES = """For cross-entity or cross-stage explanations, distinguish the entity,
the state/value it owns or stores, and the action performed on that state. A box named
"saved value" is insufficient if its owner and the referenced object's identity are
unclear. Show ownership/reference with explicit node wording or a labelled edge.
Keep earlier/stored and later/recomputed values distinct: name whose state each is,
what changes, and which TWO values are compared. A change to one entity does not
silently update a copy/reference stored by another entity. Make the comparison result
and the actor who detects or acts on it visible when supported by source_text.
Every action edge must have unambiguous subject, object, direction and source support;
spatial adjacency or a generic arrow does not explain storage, comparison or detection.
Use kind=flow for supported order and kind=network for references/ownership that do
not form a sequence. Do not force these roles into a three-column transformation.
Alternatively use a table with explicit entity/state/action columns when it explains
the same source facts more clearly. Use separate full-size panels for distinct facts,
and repeat explicit entity names across panels rather than relying on hidden links.
These are questions to resolve from the source, NOT a required five-step mechanism:
include only applicable, source-supported roles. Do not invent a storage location,
comparison algorithm, detector or temporal order absent from the source. If the
source leaves a role unspecified, keep that limit explicit instead of filling it in.
Preserve the full narration and source-grounded applications when choosing panels.
"""

RELATION_REVIEW_RULES = """Check cross-entity/state relationships against BOTH source_text
and actual visible labels/edges/table cells. Identify who stores whose state, whether
a stored reference and a recomputed/current value are distinguished, which two values
are compared, what a change affects, and who detects the discrepancy, WHERE the source
supports those roles. Verify direction and ownership, not just the presence of words.
Do not infer a missing relationship from the title, narration or background knowledge.
A technically correct generic chain can still omit the source's cross-entity mechanism.
Report wrong ownership/direction or invented mechanics as factual_error, and missing
source-supported roles as missing_content; neither is a cosmetic/readability issue.
Do not demand a mechanism or actor the source does not specify. These checks do not
establish truth mechanically; the screenshot and source review must still decide.
"""
