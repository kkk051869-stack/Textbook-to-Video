"""Object-addressed visual edits, resolved against one immutable parent only."""

from __future__ import annotations

from copy import deepcopy

from textbook2video.research.visual_edits import EDIT_ROOTS

FIELDS = {
    "visual": {"kind", "schema_version", "title", "teaching_goal",
               "narration_span", "narration_refs",
               "layout_direction", "text_scale", "nodes", "edges", "diagram", "rows",
               "series", "unit", "chart_type", "content", "prompt", "source_ref", "evidence"},
    "node": {"label", "detail", "value", "accent", "column", "source_ref", "evidence"},
    "edge": {"source", "target", "label", "directed", "source_ref", "evidence"},
    "constraint": {"constraint", "constraint_source_ref", "constraint_evidence"},
    "coverage": {"decision", "reason", "visual_refs", "source_ref", "source_evidence"},
}


def _unique(items, predicate, label):
    if not isinstance(items, list):
        raise ValueError(f"{label} needs an existing object list")
    matches = [(i, obj) for i, obj in enumerate(items) if isinstance(obj, dict) and predicate(obj)]
    if len(matches) != 1:
        raise ValueError(f"{label} must identify exactly one existing object")
    return matches[0]


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty stable ID")
    return value


def _coverage(base, ident, fields):
    """Move an explicitly reclassified element without inventing a disposition."""
    if "content_map" in base:
        if "page_plan" in base:
            raise ValueError("ambiguous coverage: both content_map and page_plan exist")
        mapping = base["content_map"]
        if not isinstance(mapping, dict) or not isinstance(mapping.get(ident), dict):
            raise ValueError("coverage element_id must identify an existing content_map entry")
        return mapping[ident], f"/content_map/{ident}"
    plan = base.get("page_plan")
    if not isinstance(plan, dict):
        raise ValueError("coverage update needs an existing page plan")
    support, replaced, proofs = (plan.get(k) for k in (
        "support_element_ids", "replaces_element_ids", "coverage",
    ))
    if not all(isinstance(value, list) for value in (support, replaced, proofs)):
        raise ValueError("coverage update needs explicit support/replacement lists")
    if support.count(ident) + replaced.count(ident) != 1:
        raise ValueError("coverage element_id must identify exactly one existing page element")
    if ident in support:
        if fields.get("decision") in {"represented", "unsupported_in_source", "irrelevant_to_goal"}:
            if any(isinstance(p, dict) and p.get("element_id") == ident for p in proofs):
                raise ValueError("ambiguous coverage entry for supported element")
            support.remove(ident)
            replaced.append(ident)
            proofs.append({"element_id": ident})
            return proofs[-1], f"/page_plan/coverage/{len(proofs) - 1}"
        raise ValueError(
            "a retained support needs an explicit replacement disposition to change it"
        )
    index, proof = _unique(proofs, lambda p: p.get("element_id") == ident, "coverage element_id")
    if fields.get("decision") == "support":
        proofs.pop(index)
        replaced.remove(ident)
        support.append(ident)
    return proof, f"/page_plan/coverage/{index}"


def apply_object_updates(base: dict, arguments: dict) -> dict:
    """Set/remove fields or delete a node/edge; never guess or create a target.

    Explicitly setting source_ref refreshes its derived quote unless the model
    supplies a quote too. Both the citation intent and removed old quote are
    audited, and all results still pass ordinary source/coverage/render gates.
    """
    updates = arguments.get("updates")
    if not isinstance(updates, list) or not 1 <= len(updates) <= 40:
        raise ValueError("revise updates requires 1-40 object updates")
    if "changes" in arguments or EDIT_ROOTS.intersection(arguments):
        raise ValueError("use updates, changes or replacement arguments, never mix them")
    if set(arguments) - {"updates", "parent", "reason"}:
        raise ValueError("updates may not change source, context, review or audit parameters")
    result = {key: deepcopy(base[key]) for key in EDIT_ROOTS if key in base}
    audit, operations = [], 0
    # Hold actual object references: array indices can shift after deletes,
    # and a whole-object replacement can supply explicit nested quotes too.
    explicit_quotes = []

    def remember_quotes(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"evidence", "source_evidence", "constraint_evidence", "narration_span"}:
                    explicit_quotes.append((value, key))
                remember_quotes(child)
        elif isinstance(value, list):
            for child in value:
                remember_quotes(child)

    for raw_update in updates:
        update = deepcopy(raw_update)
        controls = {"visual_id", "node_id", "edge", "constraint", "element_id",
                    "set", "remove", "delete"}
        if isinstance(update, dict):
            kind_hint = (
                "coverage" if "element_id" in update else "node" if "node_id" in update
                else "edge" if "edge" in update else "constraint" if "constraint" in update
                else "visual"
            )
            flat_fields = set(update) - controls
            if flat_fields and not flat_fields - FIELDS[kind_hint]:
                if "set" in update:
                    raise ValueError("use flat fields or set, never both in one object update")
                update["set"] = {key: update.pop(key) for key in sorted(flat_fields)}
        if not isinstance(update, dict) or set(update) - {
            "visual_id", "node_id", "edge", "constraint", "element_id", "set", "remove", "delete",
        }:
            unknown = sorted(set(update) - controls) if isinstance(update, dict) else []
            raise ValueError(
                f"object update contains an unknown selector or operation: {unknown}; "
                "select visual_id/node_id/edge or element_id, then put editable fields inside set"
            )
        fields, removed = update.get("set", {}), update.get("remove", [])
        delete = update.get("delete", False)
        if (not isinstance(fields, dict) or not isinstance(removed, list)
                or any(not isinstance(key, str) for key in removed)
                or len(set(removed)) != len(removed) or set(fields).intersection(removed)
                or type(delete) is not bool or not (fields or removed or delete)
                or (delete and (fields or removed))):
            raise ValueError("use explicit set fields, unique remove fields, or delete:true")
        operations += len(fields) + len(removed) + int(delete)
        if operations > 40:
            raise ValueError("object updates exceed the 40-operation budget")
        parent, index = None, None
        if "element_id" in update:
            if any(key in update for key in ("visual_id", "node_id", "edge", "constraint")):
                raise ValueError("coverage selector cannot also select a visual object")
            ident = _identifier(update["element_id"], "element_id")
            if fields.get("decision") == "support" and (
                set(fields) != {"decision", "reason"} or removed or delete
                or not isinstance(fields["reason"], str) or not fields["reason"].strip()
            ):
                raise ValueError(
                    "retaining a support requires only decision=support and reason; "
                    f"remove extra fields {sorted(set(fields) - {'decision', 'reason'})}. "
                    "Use represented with source_ref/visual_refs only when replacing an element."
                )
            target, path = _coverage(result, ident, fields)
            kind = "coverage"
        else:
            ident = _identifier(update.get("visual_id"), "visual_id")
            vi, visual = _unique(result.get("visuals"), lambda v: v.get("id") == ident, "visual_id")
            target, path, kind = visual, f"/visuals/{vi}", "visual"
            parent, index = result['visuals'], vi
            selectors = [key for key in ("node_id", "edge", "constraint") if key in update]
            if len(selectors) > 1:
                raise ValueError("select a node, edge or constraint, never multiple objects")
            if selectors:
                container, prefix = visual, path
                if visual.get("kind") == "relationship":
                    if "nodes" in visual or "edges" in visual:
                        raise ValueError("ambiguous relationship containers; use full replacement")
                    container, prefix = visual.get("diagram"), path + "/diagram"
                    if not isinstance(container, dict):
                        raise ValueError("relationship update needs an existing diagram")
                if "constraint" in update:
                    if update["constraint"] is not True or visual.get("kind") != "relationship":
                        raise ValueError("constraint:true selects an existing relationship diagram")
                    target, path, kind = container, prefix, "constraint"
                elif "node_id" in update:
                    node = _identifier(update["node_id"], "node_id")
                    parent = container.get("nodes")
                    index, target = _unique(parent, lambda n: n.get("id") == node, "node_id")
                    path, kind = prefix + f"/nodes/{index}", "node"
                else:
                    edge = update["edge"]
                    if not isinstance(edge, dict) or set(edge) != {"source", "target"}:
                        raise ValueError("edge must specify source and target IDs exactly")
                    a, b = (_identifier(edge[k], f"edge.{k}") for k in ("source", "target"))
                    parent = container.get("edges")
                    index, target = _unique(
                        parent, lambda e: e.get("source") == a and e.get("target") == b,
                        "directed edge endpoints",
                    )
                    path, kind = prefix + f"/edges/{index}", "edge"
        if set(fields).union(removed) - FIELDS[kind]:
            raise ValueError(f"unsupported {kind} fields; allowed={sorted(FIELDS[kind])}")
        record = {"update": deepcopy(raw_update), "resolved_path": path}
        if update != raw_update:
            record["normalized_update"] = deepcopy(update)
        if delete:
            if kind not in {"visual", "node", "edge"}:
                raise ValueError(
                    "delete:true only deletes an explicitly selected visual, node or edge"
                )
            parent.pop(index)
            composition = result.get('composition')
            if kind == 'visual' and isinstance(composition, dict) and isinstance(
                composition.get('visual_ids'), list
            ):
                old_composition = deepcopy(composition)
                composition['visual_ids'] = [v for v in composition['visual_ids'] if v != ident]
                if len(composition['visual_ids']) == 1:
                    composition['axis'] = 'single'
                if composition != old_composition:
                    record['updated_composition_after_explicit_delete'] = {
                        'before': old_composition, 'after': deepcopy(composition),
                    }
        else:
            for key in removed:
                if key not in target:
                    raise ValueError(f"cannot remove absent field {path}/{key}")
                target.pop(key)
            cleared = {}
            quote_field = "source_evidence" if kind == "coverage" else "evidence"
            for ref, quote in (("source_ref", quote_field),
                               ("constraint_source_ref", "constraint_evidence"),
                               ("narration_refs", "narration_span")):
                explicitly_set = any(
                    obj is target and key == quote for obj, key in explicit_quotes
                )
                if ref in fields and quote not in fields and quote in target and not explicitly_set:
                    cleared[quote] = target.pop(quote)
            if cleared:
                record["refreshed_evidence"] = cleared
            target.update(deepcopy(fields))
            for key in fields:
                if key in {"evidence", "source_evidence", "constraint_evidence", "narration_span"}:
                    explicit_quotes.append((target, key))
                remember_quotes(target[key])
        audit.append(record)
    result.update({key: deepcopy(value) for key, value in arguments.items() if key != "updates"})
    result["applied_updates"] = audit
    return result
