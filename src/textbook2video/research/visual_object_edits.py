"""Object-addressed visual edits, resolved against one immutable parent only."""

from __future__ import annotations

import re
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


class ObjectUpdateError(ValueError):
    """An atomic rejected update with executor-owned diagnostic coordinates."""

    def __init__(self, message, details):
        super().__init__(message)
        self.details = deepcopy(details)


def label_repair_requested(review: dict) -> bool:
    """Identify a cosmetic label request without authorizing a target."""
    issues = review.get("issues") if isinstance(review, dict) else None
    return bool(isinstance(issues, list) and issues and all(
        isinstance(issue, dict)
        and issue.get("category") in {"spacing", "styling", "hierarchy", "unreadable"}
        and any(word in " ".join(str(issue.get(key) or "") for key in
                    ("issue", "change")).lower()
                for word in ("label", "标签", "标注", "字样"))
        for issue in issues
    ))


def label_repair_scope(base: dict, review: dict) -> dict | None:
    """Resolve a single screenshot label complaint to one existing object.

    The reviewer may name an exact selector, or quote the old label. A vague or
    ambiguous complaint never grants permission to edit a guessed object.
    """
    issues = review.get("issues") if isinstance(review, dict) else None
    if not label_repair_requested(review) or len(issues) != 1:
        return None
    issue = issues[0]
    description = " ".join(str(issue.get(key) or "") for key in ("issue", "change"))
    def compact(value):
        return re.sub(r"\s+", "", value).casefold()
    mentioned = compact(description)
    quoted = {
        compact(value) for value in re.findall(r"[“‘\"']([^”’\"']+)[”’\"']", description)
    }
    declared = issue.get("target_selector")
    matches = []
    visuals = base.get("visuals")
    if not isinstance(visuals, list):
        return None
    for visual in visuals:
        if not isinstance(visual, dict) or not isinstance(visual.get("id"), str):
            continue
        if issue.get("visual_id") not in (None, visual["id"]):
            continue
        container = visual.get("diagram") if visual.get("kind") == "relationship" else visual
        if not isinstance(container, dict):
            continue
        for kind, entries in (("node", container.get("nodes", [])),
                              ("edge", container.get("edges", []))):
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("label"), str):
                    continue
                label = compact(entry["label"])
                if not label:
                    continue
                if kind == "node":
                    ident = entry.get("id")
                    if not isinstance(ident, str) or not ident:
                        continue
                    selector = {"visual_id": visual["id"], "node_id": ident}
                else:
                    if any(not isinstance(entry.get(k), str) or not entry[k]
                           for k in ("source", "target")):
                        continue
                    selector = {"visual_id": visual["id"], "edge": {
                        "source": entry["source"], "target": entry["target"],
                    }}
                if declared is not None:
                    selected = declared == selector
                elif quoted:
                    selected = label in quoted
                else:
                    selected = label in mentioned
                if selected:
                    matches.append((kind, selector, entry["label"]))
    if declared is None and not quoted and matches:
        longest = max(len(compact(item[2])) for item in matches)
        matches = [item for item in matches if len(compact(item[2])) == longest]
    if len(matches) != 1:
        return None
    kind, selector, old_label = matches[0]
    target = {"kind": kind, "selector": selector}
    if target not in editing_contract(base)["targets"]:
        return None
    return {"mode": "label", "target": target, "field": "label", "old_value": old_label}


def validate_label_repair(arguments: dict, scope: dict) -> None:
    """Reject any incidental mutation before applying a scoped repair."""
    updates = arguments.get("updates")
    first = updates[0] if isinstance(updates, list) and updates else None
    supplied = first.get("set") if isinstance(first, dict) else None
    details = {"allowed_target": scope["target"], "allowed_field": "label",
               "update_index": 0 if first is not None else None}
    if isinstance(first, dict):
        details["selector"] = {key: deepcopy(first[key]) for key in
                               ("visual_id", "node_id", "edge", "constraint", "element_id")
                               if key in first}
    if isinstance(supplied, dict):
        details["offending_fields"] = sorted(set(supplied) - {"label"})
    if (set(arguments) - {"updates", "parent", "reason"}
            or not isinstance(updates, list) or len(updates) != 1):
        raise ObjectUpdateError("label repair requires exactly one object update", details)
    update = updates[0]
    expected = scope["target"]["selector"]
    if (not isinstance(update, dict) or set(update) != set(expected) | {"set"}
            or any(update.get(key) != value for key, value in expected.items())
            or not isinstance(update.get("set"), dict)
            or set(update["set"]) != {"label"}
            or not isinstance(update["set"]["label"], str)
            or not update["set"]["label"].strip()
            or update["set"]["label"] == scope["old_value"]):
        raise ObjectUpdateError("label repair may change only the reviewed label", details)


def detail_repair_requested(review: dict) -> bool:
    """Identify a single-node body-text readability complaint, not a redesign."""
    issues = review.get("issues") if isinstance(review, dict) else None
    checks = review.get("checks") if isinstance(review, dict) else None
    if isinstance(checks, dict) and any(
        checks.get(key) is False for key in ("accuracy", "relevance", "completeness")
    ):
        return False
    if not isinstance(issues, list) or len(issues) != 1:
        return False
    issue = issues[0]
    if not isinstance(issue, dict) or issue.get("category") != "unreadable":
        return False
    description = " ".join(str(issue.get(key) or "") for key in ("issue", "change"))
    return (any(word in description for word in ("节点", "node"))
            and any(word in description for word in ("正文", "说明", "detail", "文本")))


def detail_repair_scope(base: dict, review: dict) -> dict | None:
    """Authorize only one existing node detail when review uniquely identifies it."""
    if not detail_repair_requested(review):
        return None
    issue = review["issues"][0]
    description = " ".join(str(issue.get(key) or "") for key in ("issue", "change"))
    def compact(value):
        return re.sub(r"\s+", "", str(value)).casefold()
    mentioned = compact(description)
    declared = issue.get("target_selector")
    matches = []
    visuals = base.get("visuals") if isinstance(base, dict) else None
    if not isinstance(visuals, list):
        return None
    for visual in visuals:
        if not isinstance(visual, dict) or not isinstance(visual.get("id"), str):
            continue
        if issue.get("visual_id") not in (None, visual["id"]):
            continue
        container = visual.get("diagram") if visual.get("kind") == "relationship" else visual
        if not isinstance(container, dict) or not isinstance(container.get("nodes"), list):
            continue
        for node in container["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                continue
            old_detail = node.get("detail")
            if not isinstance(old_detail, str) or not old_detail.strip():
                continue
            selector = {"visual_id": visual["id"], "node_id": node["id"]}
            if declared is not None:
                selected = declared == selector
            else:
                label = compact(node.get("label", ""))
                detail = compact(old_detail)
                selected = bool((label and label in mentioned) or (detail and detail in mentioned))
            if selected:
                matches.append((selector, old_detail))
    if len(matches) != 1:
        return None
    selector, old_detail = matches[0]
    target = {"kind": "node", "selector": selector}
    if target not in editing_contract(base)["targets"]:
        return None
    return {"mode": "detail", "target": target, "field": "detail", "old_value": old_detail}


def validate_detail_repair(arguments: dict, scope: dict) -> None:
    """Reject incidental edits during one reviewed node-detail correction."""
    updates = arguments.get("updates")
    details = {"allowed_target": scope["target"], "allowed_field": "detail"}
    if (set(arguments) - {"updates", "parent", "reason"}
            or not isinstance(updates, list) or len(updates) != 1):
        raise ObjectUpdateError("detail repair requires exactly one object update", details)
    update = updates[0]
    expected = scope["target"]["selector"]
    if (not isinstance(update, dict) or set(update) != set(expected) | {"set"}
            or any(update.get(key) != value for key, value in expected.items())
            or not isinstance(update.get("set"), dict)
            or set(update["set"]) != {"detail"}
            or not isinstance(update["set"]["detail"], str)
            or not update["set"]["detail"].strip()
            or update["set"]["detail"] == scope["old_value"]):
        details["selector"] = (
            {key: update.get(key) for key in expected} if isinstance(update, dict) else None
        )
        raise ObjectUpdateError("detail repair may change only the reviewed node detail", details)


def editing_contract(base):
    """Describe existing targets and actual field permissions, without proposing edits."""
    targets, unaddressable = [], []

    def unique_objects(items, keys, scope):
        if not isinstance(items, list):
            unaddressable.append({"scope": scope, "reason": "object list missing or invalid"})
            return []
        indexed, counts = [], {}
        for index, item in enumerate(items):
            if not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key].strip() for key in keys
            ):
                unaddressable.append({"scope": scope, "index": index,
                                      "reason": "missing or invalid stable selector"})
                continue
            identity = tuple(item[key] for key in keys)
            counts[identity] = counts.get(identity, 0) + 1
            indexed.append((index, identity, item))
        valid = []
        for index, identity, item in indexed:
            if counts[identity] != 1:
                unaddressable.append({"scope": scope, "index": index,
                                      "reason": "ambiguous duplicate selector"})
            else:
                valid.append(item)
        return valid

    for visual in unique_objects(base.get("visuals"), ("id",), "visuals"):
        selector = {"visual_id": visual.get("id")}
        targets.append({"kind": "visual", "selector": selector})
        container = visual.get("diagram") if visual.get("kind") == "relationship" else visual
        if not isinstance(container, dict):
            unaddressable.append({"scope": selector, "reason": "diagram missing or invalid"})
            continue
        if visual.get("kind") == "relationship" and ("nodes" in visual or "edges" in visual):
            unaddressable.append({"scope": selector, "reason": "ambiguous relationship containers"})
            continue
        for node in unique_objects(container.get("nodes", []), ("id",), selector):
            targets.append({"kind": "node", "selector": {**selector, "node_id": node["id"]}})
        for edge in unique_objects(container.get("edges", []), ("source", "target"), selector):
            targets.append({"kind": "edge", "selector": {
                **selector, "edge": {key: edge[key] for key in ("source", "target")},
            }})
        if visual.get("kind") == "relationship":
            targets.append({"kind": "constraint", "selector": {**selector, "constraint": True}})
    mapping = base.get("content_map")
    coverage = {key for key, value in mapping.items() if isinstance(value, dict)} \
        if isinstance(mapping, dict) else set()
    plan = base.get("page_plan", {})
    if isinstance(plan, dict):
        for key in ("support_element_ids", "replaces_element_ids"):
            values = plan.get(key, [])
            if isinstance(values, list):
                coverage.update(v for v in values if isinstance(v, str))
    targets.extend({"kind": "coverage", "selector": {"element_id": ident}}
                   for ident in sorted(coverage))
    return {
        "targets": targets,
        "unaddressable_targets": unaddressable,
        "allowed_fields": {kind: sorted(fields) for kind, fields in FIELDS.items()},
        "operations": {"set": "field:value mapping", "remove": "existing field names",
                       "delete": ["visual", "node", "edge"]},
        "max_updates": 40,
        "max_operations": 40,
        "rules": [
            "Use only an exact existing selector; IDs cannot be set or renamed",
            "Use set, remove or delete:true; never combine delete with set/remove",
            "Unsupported style/coordinates are rejected, never automatically translated",
            "Structural node/edge replacement must preserve source and full narration coverage",
            "All results still require source, narration, geometry and screenshot checks",
        ],
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
    context = {"update_index": None, "selector": None}
    try:
        return _apply_object_updates(base, arguments, context)
    except ObjectUpdateError:
        raise
    except ValueError as exc:
        raise ObjectUpdateError(str(exc), context) from exc


def _apply_object_updates(base: dict, arguments: dict, context: dict) -> dict:
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

    for update_index, raw_update in enumerate(updates):
        context.clear()
        context.update(update_index=update_index, selector={
            key: deepcopy(raw_update[key])
            for key in ("visual_id", "node_id", "edge", "constraint", "element_id")
            if isinstance(raw_update, dict) and key in raw_update
        })
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
            context.update(offending_fields=unknown, allowed_controls=sorted(controls))
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
            context.update(
                kind=kind, offending_fields=sorted(set(fields).union(removed) - FIELDS[kind]),
                allowed_fields=sorted(FIELDS[kind]),
            )
            misplaced = set(fields).union(removed) & FIELDS["constraint"]
            if kind == "visual" and misplaced and target.get("kind") == "relationship":
                context["suggested_selector"] = {"visual_id": target["id"], "constraint": True}
                context["suggested_fields"] = sorted(misplaced)
                raise ValueError(
                    "relationship constraint fields require selector "
                    f"visual_id={target['id']!r}, constraint:true; "
                    "use set/remove on that selector, never the visual root; "
                    "constraint text must remain an exact source excerpt"
                )
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
