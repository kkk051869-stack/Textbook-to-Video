"""One model-facing graph shape; renderer dialects stay behind this adapter."""

from copy import deepcopy

from textbook2video.research.visual_grammar import GRAPH_KINDS

GRAPH_TYPES = GRAPH_KINDS | {"comparison", "relationship"}
RELATION_FIELDS = {"nodes", "edges", "constraint", "constraint_source_ref", "constraint_evidence"}


def common_graphs(arguments):
    """Copy explicit graph content to one container; refuse ambiguous/unknown wrappers."""
    result, changes = deepcopy(arguments), []
    specs = result.get("visuals")
    for spec in specs if isinstance(specs, list) else []:
        if (not isinstance(spec, dict) or not isinstance(spec.get("kind"), str)
                or spec["kind"] not in GRAPH_TYPES):
            continue
        diagram = spec.get("diagram")
        if "diagram" not in spec:
            continue
        if not isinstance(diagram, dict):
            raise ValueError("graph diagram must be an object; use top-level nodes/edges")
        if "nodes" in spec or "edges" in spec:
            raise ValueError("conflicting graph containers; supply nodes/edges only at visual root")
        if spec["kind"] == "relationship":
            allowed = RELATION_FIELDS | {
                "version", "layout", "columns", "column_titles", "auto_layout"}
            if diagram.get("version", "teaching-relationship-v1") != "teaching-relationship-v1":
                raise ValueError("unsupported relationship version; no conversion was performed")
        else:
            allowed = {"type", "layout", "nodes", "edges"}
            if diagram.get("type", spec["kind"]) != spec["kind"]:
                raise ValueError("graph wrapper type conflicts with explicit visual kind")
            if diagram.get("layout", "auto") != "auto":
                raise ValueError("legacy graph wrapper must use automatic layout")
        if set(diagram) - allowed:
            raise ValueError(
                f"unknown graph wrapper fields {sorted(set(diagram) - allowed)}; "
                "send a complete visual using top-level nodes/edges; no fields were discarded"
            )
        for key in RELATION_FIELDS if spec["kind"] == "relationship" else ("nodes", "edges"):
            if key in diagram:
                if key in spec:
                    raise ValueError(f"conflicting graph field {key}")
                spec[key] = deepcopy(diagram[key])
        spec.pop("diagram")
        changes.append(f"Unified explicit graph container for {spec.get('id')}; content unchanged")
    return result, changes


def renderer_graphs(arguments):
    """Wrap only the legacy three-stage renderer; infer no nodes, edges or citations."""
    result, changes = deepcopy(arguments), []
    specs = result.get("visuals")
    for index, original in enumerate(specs if isinstance(specs, list) else []):
        if isinstance(original, dict) and original.get("kind") == "relationship":
            graph = original.get("diagram", original)
            edges = graph.get("edges") if isinstance(graph, dict) else None
            for edge in edges if isinstance(edges, list) else []:
                if isinstance(edge, dict) and "directed" in edge and edge["directed"] is not True:
                    raise ValueError(
                        "relationship supports directed edges only; use network for peer links"
                    )
        normalized, messages = common_graphs({"visuals": [original]})
        if (isinstance(original, dict) and original.get("kind") == "relationship"
                and "diagram" in original):
            continue  # Existing renderer metadata/manual dialect remains authoritative.
        spec = normalized["visuals"][0]
        specs[index] = spec
        changes.extend(messages)
        if not isinstance(spec, dict) or spec.get("kind") != "relationship":
            continue
        if spec.get("schema_version"):
            raise ValueError("relationship may not declare a general graph schema_version")
        diagram = {"version": "teaching-relationship-v1", "layout": "auto"}
        for key in RELATION_FIELDS:
            if key in spec:
                diagram[key] = spec.pop(key)
        # Placement metadata does not belong to the model-facing graph contract.
        nodes = diagram.get("nodes")
        for node in nodes if isinstance(nodes, list) else []:
            if isinstance(node, dict):
                node.pop("column", None)
        spec["diagram"] = diagram
        changes.append(f"Adapted unified relationship {spec.get('id')} to renderer container")
    return result, changes


def renderer_updates(base, arguments):
    """Resolve common visual-level graph fields to an existing renderer container."""
    from textbook2video.research.visual_object_edits import apply_object_updates

    result = deepcopy(arguments)
    updates = result.get("updates")
    if isinstance(updates, list) and (len(updates) > 40 or sum(
        len(u.get("set", {})) + len(u.get("remove", [])) + int(u.get("delete") is True)
        for u in updates if isinstance(u, dict)
        and isinstance(u.get("set", {}), dict) and isinstance(u.get("remove", []), list)
    ) > 40):
        raise ValueError("object updates exceed the 40-operation budget")
    working = deepcopy(base)
    for update in updates if isinstance(updates, list) else []:
        if not isinstance(update, dict):
            continue
        if set(update) & {"node_id", "edge", "constraint", "element_id"}:
            working = apply_object_updates(working, {"updates": [update]})
            continue
        visuals = [v for v in working.get("visuals", [])
                   if isinstance(v, dict) and v.get("id") == update.get("visual_id")]
        fields = update.get("set")
        if (len(visuals) == 1 and visuals[0].get("kind") == "relationship"
                and isinstance(visuals[0].get("diagram"), dict) and isinstance(fields, dict)):
            selected = set(fields) & {"nodes", "edges"}
            if selected:
                if ("diagram" in fields or "kind" in fields
                        or update.get("remove") or update.get("delete")):
                    raise ValueError("ambiguous graph update; use complete replacement visuals")
                diagram = deepcopy(visuals[0]["diagram"])
                for key in selected:
                    diagram[key] = fields.pop(key)
                fields["diagram"] = diagram
        working = apply_object_updates(working, {"updates": [update]})
    return result


def model_edit_contract(base):
    """Advertise only common semantic fields, not renderer version/container controls."""
    from textbook2video.research.visual_object_edits import editing_contract

    contract = editing_contract(base)
    hidden = {"kind", "diagram", "schema_version", "layout_direction"}
    contract["allowed_fields"]["visual"] = [
        key for key in contract["allowed_fields"]["visual"] if key not in hidden]
    contract["allowed_fields"]["node"] = [
        key for key in contract["allowed_fields"]["node"] if key != "column"]
    contract["rules"].append(
        "Renderer containers, versions and placement are executor-owned; "
        "changing diagram kind requires complete replacement visuals."
    )
    return contract


def check_structure(arguments):
    """Check addressable objects before source validation, not semantic entailment."""
    specs = arguments.get("visuals")
    if not isinstance(specs, list) or not 1 <= len(specs) <= 6:
        raise ValueError("visuals must contain 1-6 objects; send a complete replacement")
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError("visual must be an object; send a complete replacement")
        if not isinstance(spec.get("kind"), str) or spec["kind"] not in GRAPH_TYPES:
            continue
        graph = spec.get("diagram") if spec.get("kind") == "relationship" else spec
        if not isinstance(graph, dict):
            raise ValueError("relationship requires a graph object")
        nodes, edges = graph.get("nodes"), graph.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError(
                f"visual {spec.get('id')}: nodes/edges must be object lists at the graph root; "
                "send complete replacement visuals before editing source IDs"
            )
        ids = [node.get("id") for node in nodes if isinstance(node, dict)]
        if (len(ids) != len(nodes) or any(not isinstance(i, str) or not i for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("graph nodes need unique IDs; send complete replacement visuals")
        for edge in edges:
            if (not isinstance(edge, dict) or not isinstance(edge.get("source"), str)
                    or not isinstance(edge.get("target"), str)
                    or edge["source"] not in ids or edge["target"] not in ids):
                raise ValueError("edge endpoints must name existing nodes; replace the structure")
