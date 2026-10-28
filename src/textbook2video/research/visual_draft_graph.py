"""Immutable pre-materialization evidence and scoped edits for the existing VisualPlan."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

from textbook2video.research.visual_model_interface import GRAPH_TYPES, common_graphs
from textbook2video.research.visual_narration_refs import (
    materialize_narration_refs,
    narration_units,
)
from textbook2video.research.visual_source_refs import materialize_source_refs, source_units

PLAN_FIELDS = {"visuals", "content_map", "composition", "page_plan"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def _objects(candidate):
    """Index only unambiguous IDs; capacity and semantic typing are later gates."""
    result, visual_ids = {}, set()
    specs = candidate.get("visuals")
    if not isinstance(specs, list):
        raise ValueError("draft visuals must be a list")
    for visual in specs:
        ident = visual.get("id") if isinstance(visual, dict) else None
        if (
            not isinstance(ident, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident)
            or ident in visual_ids
        ):
            raise ValueError("draft visuals need unique safe IDs")
        visual_ids.add(ident)
        result[("visual", ident)] = ({"visual_id": ident}, visual)
        if visual.get("kind") not in GRAPH_TYPES:
            continue
        nodes, edges = visual.get("nodes"), visual.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError(f"draft {ident}: nodes/edges must be lists")
        ids = set()
        for node in nodes:
            nid = node.get("id") if isinstance(node, dict) else None
            if (
                not isinstance(nid, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nid)
                or nid in ids
            ):
                raise ValueError(f"draft {ident}: nodes need unique safe IDs")
            ids.add(nid)
            result[("node", ident, nid)] = ({"visual_id": ident, "node_id": nid}, node)
        pairs = set()
        for edge in edges:
            pair = (edge.get("source"), edge.get("target")) if isinstance(edge, dict) else ()
            if len(pair) != 2 or any(not isinstance(p, str) or p not in ids for p in pair):
                raise ValueError(f"draft {ident}: edge endpoints must exist")
            if pair in pairs:
                raise ValueError(f"draft {ident}: duplicate directed edge")
            pairs.add(pair)
            result[("edge", ident, *pair)] = (
                {"visual_id": ident, "edge": dict(zip(("source", "target"), pair))},
                edge,
            )
    return result


def _refs(value):
    refs = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_ref", "constraint_source_ref"}:
                values = child if isinstance(child, list) else [child]
                refs.update(p.strip() for v in values if isinstance(v, str) for p in v.split(","))
            else:
                refs.update(_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_refs(child))
    return refs


def read_draft(directory, seen=None):
    directory = Path(directory).resolve()
    seen = set() if seen is None else seen
    if directory in seen:
        raise ValueError("cyclic draft ancestry")
    seen.add(directory)
    draft = json.loads((directory / "draft-graph.json").read_text(encoding="utf-8"))
    if digest({k: v for k, v in draft.items() if k != "sha256"}) != draft.get("sha256"):
        raise ValueError("draft graph hash drift")
    if (
        hashlib.sha256(Path(draft["raw_response"]["path"]).read_bytes()).hexdigest()
        != draft["raw_response"]["sha256"]
    ):
        raise ValueError("draft raw response hash drift")
    raw_request = json.loads((directory / "raw_tool_request.json").read_text(encoding="utf-8"))
    if digest(raw_request) != draft["raw_request_sha256"]:
        raise ValueError("draft raw tool request hash drift")
    if draft["parent"]:
        if draft["parent"]["sha256"] is not None:
            parent = read_draft(draft["parent"]["directory"], seen)
            if parent["sha256"] != draft["parent"]["sha256"]:
                raise ValueError("draft parent hash drift")
        record = draft["parent"]["revision_record"]
        if hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("draft parent revision record hash drift")
    return draft


def save_draft(
    directory,
    arguments,
    *,
    source,
    narration,
    parent_dir=None,
    raw_response_path=None,
    inherited=None,
):
    """Persist before role/renderer materialization, including failed coverage responsibility."""
    directory = Path(directory)
    candidate = {key: deepcopy(arguments[key]) for key in PLAN_FIELDS if key in arguments}
    diagnostics, indexed = [], {}
    try:
        candidate, _ = common_graphs(candidate)
        indexed = _objects(candidate)
    except ValueError as exc:
        diagnostics.append({"stage": "identity", "error": str(exc)})
    specs = candidate.get("visuals")
    specs = specs if isinstance(specs, list) else []
    for visual in specs:
        if (
            isinstance(visual, dict)
            and isinstance(visual.get("nodes"), list)
            and len(visual["nodes"]) > 8
        ):
            diagnostics.append(
                {
                    "stage": "capacity",
                    "visual_id": visual.get("id"),
                    "actual": len(visual["nodes"]),
                    "maximum": 8,
                }
            )
    excerpts = None
    try:
        excerpts, _ = materialize_source_refs(candidate, source, None)
    except ValueError as exc:
        diagnostics.append({"stage": "source", "error": str(exc)})
    try:
        materialized, _ = materialize_narration_refs(candidate, narration)
        panels = materialized.get("visuals", [])
        if (
            narration is not None
            and len(panels) > 1
            and "".join(p.get("narration_span", "") for p in panels) != narration
        ):
            raise ValueError("draft panels must cover full immutable narration")
    except (ValueError, TypeError) as exc:
        diagnostics.append({"stage": "narration", "error": str(exc)})
    parent = (
        read_draft(parent_dir)
        if parent_dir is not None and (Path(parent_dir) / "draft-graph.json").exists()
        else None
    )
    if parent and (
        parent["source_sha256"] != digest(source) or parent["narration_sha256"] != digest(narration)
    ):
        raise ValueError("draft revision cannot change source or narration")
    old = parent["objects"] if parent else []
    run_id = parent["run_id"] if parent else str(directory.parent.resolve())
    objects, mappings, used = [], [], set()
    for key, (selector, value) in indexed.items():
        content_hash = digest(value)
        matches = [
            o
            for o in old
            if o["kind"] == key[0]
            and o["local_key"] == list(key[2:])
            and o["content_sha256"] == content_hash
        ]
        inherited_id = (inherited or {}).get(json.dumps(selector, sort_keys=True))
        if inherited_id:
            matches = [o for o in old if o["stable_id"] == inherited_id]
            if len(matches) != 1:
                raise ValueError("draft patch lineage is not an existing parent object")
        if len(matches) == 1 and matches[0]["stable_id"] not in used:
            stable = matches[0]["stable_id"]
            mappings.append(
                {
                    "parent": matches[0]["selector"],
                    "child": selector,
                    "stable_id": stable,
                    "content_unchanged": not inherited_id,
                }
            )
        else:
            stable = key[0] + "-" + digest([run_id, parent["sha256"] if parent else None, *key])
        if stable in used:
            raise ValueError("draft stable ID collision")
        used.add(stable)
        objects.append(
            {
                "stable_id": stable,
                "kind": key[0],
                "local_key": list(key[2:]),
                "selector": selector,
                "content_sha256": content_hash,
            }
        )
    replacement_errors, preservation = [], None
    if parent and any(d["stage"] == "capacity" for d in parent["diagnostics"]):
        from textbook2video.research.visual_semantic_graph import materialize_semantic_graphs

        protected = [o for o in old if o["kind"] != "visual"]
        invalid_selector = None
        try:
            materialize_semantic_graphs(parent["candidate"])
        except ValueError as exc:
            invalid_selector = (getattr(exc, "details", None) or {}).get("draft_target")
            # A known wrong relation is repairable while splitting. An unlocated
            # semantic/source failure needs full revalidation, not blind conservation.
            protected = (
                [o for o in protected if o["selector"] != invalid_selector]
                if invalid_selector
                else []
            )
        if any(d["stage"] in {"identity", "source"} for d in parent["diagnostics"]):
            protected = []
        preservation = {
            "protected_parent_ids": [o["stable_id"] for o in protected],
            "known_invalid_selector": invalid_selector,
        }
        counts = Counter((k[0], digest(v)) for k, (_, v) in indexed.items() if k[0] != "visual")
        expected = Counter((o["kind"], o["content_sha256"]) for o in protected)
        if expected - counts:
            replacement_errors.append("capacity split lost or changed parent nodes/edges")
    diagnostics.extend({"stage": "replacement", "error": e} for e in replacement_errors)
    raw = Path(raw_response_path or directory / "raw_tool_request.json").resolve()
    parent_record = None
    if parent_dir is not None:
        parent_path = Path(parent_dir) / "revision.json"
        if not parent_path.exists():
            parent_path = Path(parent_dir) / "failure.json"
        parent_record = {
            "path": str(parent_path.resolve()),
            "sha256": hashlib.sha256(parent_path.read_bytes()).hexdigest(),
        }
    draft = {
        "version": "visual-draft-v1",
        "run_id": run_id,
        "candidate": candidate,
        "source_sha256": digest(source),
        "narration_sha256": digest(narration),
        "narration_text": narration,
        "source_units": source_units(source),
        "selected_source_refs": sorted(_refs(candidate)),
        "source_reference_delta": {
            "added": sorted(_refs(candidate) - (_refs(parent["candidate"]) if parent else set())),
            "removed": sorted((_refs(parent["candidate"]) if parent else set()) - _refs(candidate)),
        },
        "preservation": preservation,
        "materialized_source_snapshot": excerpts,
        "expected_narration_units": narration_units(narration) if narration is not None else [],
        "panel_narration": [
            {
                "visual_id": v.get("id"),
                "narration_refs": v.get("narration_refs"),
                "narration_span": v.get("narration_span"),
            }
            for v in specs
            if isinstance(v, dict)
        ],
        "raw_response": {"path": str(raw), "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()},
        "raw_request_sha256": digest(
            json.loads((directory / "raw_tool_request.json").read_text(encoding="utf-8"))
        ),
        "parent": {
            "directory": str(Path(parent_dir).resolve()),
            "sha256": parent["sha256"] if parent else None,
            "revision_record": parent_record,
        }
        if parent_dir is not None
        else None,
        "objects": objects,
        "lineage": mappings,
        "added_ids": sorted(used - {o["stable_id"] for o in old}),
        "removed_ids": sorted({o["stable_id"] for o in old} - used),
        "diagnostics": diagnostics,
        "semantic_status": "UNCONFIRMED",
    }
    draft["sha256"] = digest(draft)
    _write(directory / "draft-graph.json", draft)
    return draft


def save_draft_result(directory, draft, error=None):
    result = {
        "draft_sha256": draft["sha256"],
        "status": "FAILED" if error else "COMPILED",
        "error": str(error) if error else None,
        "details": deepcopy(getattr(error, "details", None)),
        "semantic_status": "UNCONFIRMED",
    }
    _write(Path(directory) / "draft-result.json", result)
    return digest(result)


def verify_draft_artifacts(directory, record):
    exists = (Path(directory) / "draft-graph.json").exists()
    if bool(record.get("draft_sha256")) != exists:
        raise ValueError("draft evidence missing or unexpectedly present")
    if exists:
        draft = read_draft(directory)
        result = json.loads((Path(directory) / "draft-result.json").read_text(encoding="utf-8"))
        if (
            draft["sha256"] != record["draft_sha256"]
            or result["draft_sha256"] != draft["sha256"]
            or digest(result) != record.get("draft_result_sha256")
        ):
            raise ValueError("draft execution result hash drift")


def draft_edit_contract(directory):
    """The executor selects the one failing object; model output cannot enlarge the scope."""
    draft = read_draft(directory)
    record_path = Path(directory) / "failure.json"
    if not record_path.exists():
        return None
    record = json.loads(record_path.read_text(encoding="utf-8"))
    verify_draft_artifacts(directory, record)
    result_path = Path(directory) / "draft-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    details = result.get("details") or {}
    if draft["diagnostics"] or not details.get("draft_target") or not details.get("draft_fields"):
        return None
    # Reuse the deterministic validator to authorize scope, rather than trusting
    # editable diagnostic text or a model's claim about which object was wrong.
    from textbook2video.research.visual_semantic_graph import materialize_semantic_graphs

    try:
        materialize_semantic_graphs(draft["candidate"])
    except ValueError as exc:
        actual = getattr(exc, "details", None) or {}
    else:
        actual = {}
    if details != actual:
        raise ValueError("draft diagnostic scope binding drift")
    selected = details.get("draft_target")
    targets = [o for o in draft["objects"] if o["selector"] == selected]
    if len(targets) != 1:
        return None
    selected_object = next(
        value for selector, value in _objects(draft["candidate"]).values() if selector == selected
    )
    source_refs = sorted(_refs(selected_object))
    if not source_refs:
        return None
    return {
        "parent_sha256": draft["sha256"],
        "target_id": targets[0]["stable_id"],
        "selector": selected,
        "allowed_fields": details["draft_fields"],
        "allow_subgraph": bool(details.get("draft_subgraph")),
        "source_refs": source_refs,
    }


def apply_draft_updates(directory, arguments):
    draft, contract = read_draft(directory), draft_edit_contract(directory)
    if not contract or set(arguments) - {"updates", "parent", "reason"}:
        raise ValueError(
            "draft update has no authorized local repair scope; "
            "complete replacement visuals required"
        )
    if contract["parent_sha256"] != draft["sha256"] or (
        arguments.get("parent") and Path(arguments["parent"]).resolve() != Path(directory).resolve()
    ):
        raise ValueError("draft update parent binding changed")
    updates = arguments.get("updates")
    if (
        not isinstance(updates, list)
        or len(updates) != 1
        or not isinstance(updates[0], dict)
        or set(updates[0]) != {"target_id", "set"}
        or updates[0]["target_id"] != contract["target_id"]
    ):
        raise ValueError("draft updates must select exactly the authorized stable target_id")
    fields = updates[0]["set"]
    if not isinstance(fields, dict) or not fields:
        raise ValueError("draft update requires nonempty set fields")
    result = deepcopy(draft["candidate"])
    selector = contract["selector"]
    visual = next(v for v in result["visuals"] if v["id"] == selector["visual_id"])
    target = (
        next(n for n in visual["nodes"] if n["id"] == selector["node_id"])
        if "node_id" in selector
        else next(e for e in visual["edges"] if all(e[k] == v for k, v in selector["edge"].items()))
    )
    inherited = {}
    if set(fields) == {"nodes", "edges"} and contract["allow_subgraph"]:
        nodes, edges = fields["nodes"], fields["edges"]
        if (
            not isinstance(nodes, list)
            or not isinstance(edges, list)
            or not edges
            or len(nodes) + len(edges) > 40
        ):
            raise ValueError("draft subgraph needs explicit nodes/edges within operation budget")
        old_ids = {n["id"] for n in visual["nodes"]}
        if any(
            not isinstance(n, dict) or not isinstance(n.get("id"), str) or n["id"] in old_ids
            for n in nodes
        ):
            raise ValueError("draft subgraph cannot replace existing nodes")
        for value in [*nodes, *edges]:
            if (
                not isinstance(value, dict)
                or not _refs(value)
                or not _refs(value).issubset(contract["source_refs"])
            ):
                raise ValueError("draft subgraph must retain the target's existing sources")
        node_fields = {"id", "label", "detail", "role", "source_ref"}
        edge_fields = {"source", "target", "relation", "label", "source_ref", "directed"}
        if any(set(n) - node_fields for n in nodes) or any(set(e) - edge_fields for e in edges):
            raise ValueError("draft subgraph additions contain unauthorized fields")
        allowed_ids = (
            set(selector["edge"].values())
            | {
                n["id"]
                for n in visual["nodes"]
                if _refs(n) and _refs(n).issubset(contract["source_refs"])
            }
            | {n["id"] for n in nodes}
        )
        if any(e.get(key) not in allowed_ids for e in edges for key in ("source", "target")):
            raise ValueError("draft subgraph endpoints exceed the authorized source bindings")
        visual["edges"].remove(target)
        visual["nodes"].extend(deepcopy(nodes))
        visual["edges"].extend(deepcopy(edges))
        _objects(result)
        reachable = {target["source"]}
        for _ in range(len(nodes) + len(old_ids)):
            for edge in edges:
                if edge["source"] in reachable:
                    reachable.add(edge["target"])
                if edge["target"] in reachable:
                    reachable.add(edge["source"])
        if not {n["id"] for n in nodes}.union(
            {x for e in edges for x in (e["source"], e["target"])}
        ).issubset(reachable):
            raise ValueError("draft subgraph must stay connected to the selected relation")
    else:
        if set(fields) - set(contract["allowed_fields"]):
            raise ValueError("draft update touches unauthorized fields")
        if "source_ref" in fields and (
            not _refs(fields) or not _refs(fields).issubset(contract["source_refs"])
        ):
            raise ValueError("draft update may select only existing target source bindings")
        for key, value in fields.items():
            if key != "source_ref" and (not isinstance(value, str) or not value.strip()):
                raise ValueError("draft semantic text fields must be nonempty strings")
        target.update(deepcopy(fields))
        inherited[json.dumps(selector, sort_keys=True)] = contract["target_id"]
    result.update({key: arguments[key] for key in ("parent", "reason") if key in arguments})
    return result, inherited
