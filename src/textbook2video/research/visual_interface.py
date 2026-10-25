"""Keep mechanical provenance and layout fields out of model editing tasks."""

from copy import deepcopy


def planner_view(arguments):
    value = deepcopy(arguments)

    def visit(item):
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            for ref, field in (
                ("source_ref", "source_evidence" if "element_id" in item else "evidence"),
                ("constraint_source_ref", "constraint_evidence"),
                ("narration_refs", "narration_span"),
            ):
                if ref in item:
                    item.pop(field, None)
            if item.get("auto_layout") is True:
                item["layout"] = "auto"
                item.pop("columns", None)
                for node in item.get("nodes", []):
                    node.pop("column", None)
            for key in ("applied_updates", "applied_changes", "derived_fields_cleared"):
                item.pop(key, None)
            for child in item.values():
                visit(child)

    visit(value)
    return value


def materialize_layout(arguments, *, automatic_layout=False):
    result = deepcopy(arguments)
    changes = []
    for spec in result.get("visuals", []):
        if not isinstance(spec, dict):
            continue
        layered = spec.get("kind") in {"flow", "causal", "timeline", "hierarchy", "part_whole"}
        direction = spec.get("layout_direction")
        if "layout_direction" in spec and not isinstance(direction, str):
            raise ValueError("layout_direction must be a supported direction string")
        if automatic_layout and direction in {"horizontal", "vertical", "wrapped", "auto"}:
            if layered:
                spec["layout_direction"] = "auto"
            else:
                spec.pop("layout_direction")
            if direction != spec.get("layout_direction"):
                changes.append(
                    f"Executor owns placement for {spec.get('id')}: "
                    f"proposed direction={direction!r}, "
                    f"effective={spec.get('layout_direction')!r}; "
                    "nodes, edges and text unchanged"
                )
        if layered:
            if "layout_direction" not in spec:
                spec["layout_direction"] = "auto"
                changes.append("Defaulted omitted graph placement to deterministic auto layout")
        if spec.get("layout_direction") == "auto":
            changes.append("Delegated graph placement to the deterministic renderer")
        diagram = spec.get("diagram")
        if spec.get("kind") != "relationship" or not isinstance(diagram, dict):
            continue
        if diagram.get("layout") != "auto" and diagram.get("auto_layout") is not True:
            continue
        nodes, edges = diagram.get("nodes", []), diagram.get("edges", [])
        if (
            not isinstance(nodes, list)
            or not isinstance(edges, list)
            or any(not isinstance(n, dict) for n in nodes)
            or any(not isinstance(e, dict) for e in edges)
        ):
            raise ValueError("auto layout requires node and edge objects")
        ids = [n.get("id") for n in nodes]
        if not ids or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("auto relationship layout requires unique node IDs")
        incoming = {i: [] for i in ids}
        for edge in edges:
            a, b = edge.get("source"), edge.get("target")
            if a not in incoming or b not in incoming or a == b:
                raise ValueError("auto layout edge endpoints must exist and differ")
            incoming[b].append(a)
        levels = {}
        while len(levels) < len(ids):
            ready = [i for i in ids if i not in levels and all(a in levels for a in incoming[i])]
            if not ready:
                raise ValueError(
                    "auto relationship needs a DAG; use network for peer/cyclic relations"
                )
            for ident in ready:
                levels[ident] = max((levels[a] + 1 for a in incoming[ident]), default=0)
        counts = [sum(v == i for v in levels.values()) for i in range(3)]
        if max(levels.values()) != 2 or any(c < 1 or c > 3 for c in counts) or counts[1] != 1:
            raise ValueError(
                "auto relationship needs three stages with one middle node; "
                "use kind=flow/network for other topology; no nodes/edges were changed"
            )
        layout = "one_way" if counts == [1, 1, 1] else "split_merge"
        was_auto = diagram.get("auto_layout") is True
        titles = diagram.get("column_titles", ["阶段一", "阶段二", "阶段三"])
        if not was_auto and "columns" in diagram and diagram["columns"] != titles:
            raise ValueError("explicit columns conflict with auto layout headings")
        diagram.update(layout=layout, columns=deepcopy(titles), auto_layout=True)
        for node in nodes:
            column = levels[node["id"]]
            if not was_auto and "column" in node and node["column"] != column:
                raise ValueError("explicit node column conflicts with graph-derived stage")
            node["column"] = column
        changes.append(
            "Computed relationship stages from explicit directed edges; topology unchanged"
        )
    return result, changes
