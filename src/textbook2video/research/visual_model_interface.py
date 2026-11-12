"""One model-facing graph shape; renderer dialects stay behind this adapter."""

import json
import re
from copy import deepcopy

from jsonschema import Draft202012Validator

from textbook2video.research.visual_grammar import GRAPH_KINDS

GRAPH_TYPES = GRAPH_KINDS | {"comparison", "relationship"}
RELATION_FIELDS = {"nodes", "edges", "constraint", "constraint_source_ref", "constraint_evidence"}

VISUAL_PLAN_VERSION = "visual-plan-v1"
_PLAN_FIELDS = {
    "full_candidate": {"visuals", "content_map", "composition", "page_plan"},
    "updates": {"updates"},
    "draft_updates": {"updates"},
    "scoped_label": {"updates"},
    "scoped_detail": {"updates"},
    "structural_replacement": {"visuals", "content_map", "composition", "page_plan"},
    "append_missing_panel": {
        "panel", "existing_narration_refs", "panel_narration_refs",
    },
}
_PLAN_REQUIRED = {
    "full_candidate": {"visuals"},
    "updates": {"updates"},
    "draft_updates": {"updates"},
    "scoped_label": {"updates"},
    "scoped_detail": {"updates"},
    "structural_replacement": {"visuals"},
    "append_missing_panel": {
        "panel", "existing_narration_refs", "panel_narration_refs",
    },
}

# One source for model-visible JSON types and the local envelope validator.
# Nested visual/operation semantics remain the existing executor's responsibility.
_PLAN_TYPES = {
    "visuals": list, "content_map": dict, "composition": dict, "page_plan": dict,
    "updates": list, "panel": dict, "existing_narration_refs": list,
    "panel_narration_refs": list,
}

_COMPOSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "visual_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                       "items": {"type": "string", "minLength": 1}},
        "axis": {"enum": ["single", "horizontal", "vertical"]},
        "horizontal_free": {"type": "boolean"},
        "vertical_free": {"type": "boolean"},
    },
    "required": ["visual_ids"],
    "additionalProperties": False,
}


def visual_plan_contract(mode: str, *, asset_only: bool = False) -> dict:
    """Describe the one response shape, narrowed by executor-selected mode."""
    if mode not in _PLAN_FIELDS:
        raise ValueError(f"unsupported VisualPlanV1 mode: {mode}")
    fields = _PLAN_FIELDS[mode] - ({'content_map', 'page_plan', 'composition'} if asset_only else set())
    required = sorted(_PLAN_REQUIRED[mode])
    return {
        "version": VISUAL_PLAN_VERSION,
        "mode": mode,
        "required_fields": required if asset_only else ["plan_version", *required],
        "allowed_fields": ["plan_version", *sorted(fields)],
        "asset_only": asset_only,
        "executor_owned": ["mode", "operation", "parent", "reason", "layout", "references"]
        + (["plan_version", "content_map", "page_plan", "composition"] if asset_only else []),
        "response_schema": {
            "type": "object",
            "properties": {
                "plan_version": {"type": "string", "const": VISUAL_PLAN_VERSION},
                **{key: deepcopy(_COMPOSITION_SCHEMA) if key == "composition"
                   else {"type": "array" if _PLAN_TYPES[key] is list else "object"}
                   for key in sorted(fields)},
            },
            "required": required if asset_only else ["plan_version", *required],
            "additionalProperties": False,
        },
        "rules": [
            "Return one JSON object, not a tool/name/arguments envelope.",
            *( ["Asset-only execution: omit plan_version; the executor supplies this fixed metadata. "
                "A supplied version must still be exact. Do not emit content_map, page_plan or composition; "
                "the original page and asset ordering are executor-owned."] if asset_only else []),
            f'Any emitted plan_version must be exactly the fixed protocol string "{VISUAL_PLAN_VERSION}"; '
            'it is not a revision number, model choice or editable content.',
            "response_schema describes the response envelope; nested visual content must also "
            "satisfy the supplied catalog, source and semantic contracts.",
            "Emit only allowed_fields; the executor selected this mode.",
            "For local edits, updates must use existing object selectors and edit_contract.",
            "Use source_ref and narration_refs from the supplied inventories only.",
        ],
    }


def parse_visual_plan_response(raw: str, mode: str, *, asset_only: bool = False) -> tuple[dict, list[str]]:
    """Parse model-only VisualPlanV1; this deliberately does not use tool dispatch."""
    contract = visual_plan_contract(mode, asset_only=asset_only)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        plan = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        if not exc.msg.startswith("Invalid control character"):
            raise ValueError(f"invalid VisualPlanV1 JSON: {exc.msg}") from exc
        plan = json.loads(cleaned, strict=False)
    if not isinstance(plan, dict):
        raise ValueError("VisualPlanV1 response must be a JSON object")

    changes = []
    if "plan_version" not in plan and asset_only:
        plan['plan_version'] = VISUAL_PLAN_VERSION
        changes.append('Executor supplied fixed VisualPlan protocol version for asset-only payload')
    issues = []
    def add(path, message):
        issues.append({'stage': 'envelope', 'path': path, 'message': message})
    if 'plan_version' not in plan:
        add('/plan_version', 'VisualPlanV1 response is missing required plan_version')
    elif plan['plan_version'] != VISUAL_PLAN_VERSION:
        add('/plan_version', f'plan_version must be {VISUAL_PLAN_VERSION}')
    for field in sorted(set(plan) - set(contract['allowed_fields'])):
        add('/' + field, f'VisualPlanV1 {mode} has disallowed fields: {field}')
    for field in sorted(set(contract['required_fields']) - set(plan)):
        if field != 'plan_version':
            add('/' + field, f'VisualPlanV1 {mode} is missing required fields: {field}')
    payload = {key: value for key, value in plan.items() if key != 'plan_version'}
    for key, value in payload.items():
        expected_type = _PLAN_TYPES.get(key)
        if expected_type is not None and not isinstance(value, expected_type):
            add('/' + key, f'VisualPlanV1 {mode}.{key} must be {expected_type.__name__}')
        elif key == 'composition' and key in contract['response_schema']['properties']:
            for error in Draft202012Validator(_COMPOSITION_SCHEMA).iter_errors(value):
                path = '/composition' + ''.join('/' + str(p) for p in error.absolute_path)
                add(path, error.message)
    if issues:
        error = ValueError('; '.join(i['message'] for i in issues))
        error.details = {'validation_issues': issues}
        raise error
    return payload, changes


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


def _route_relationship_renderer(spec):
    """Choose a renderer from explicit DAG topology, never repair teaching content."""
    nodes, edges = spec.get("nodes"), spec.get("edges")
    if (
        not isinstance(nodes, list)
        or not nodes
        or not isinstance(edges, list)
        or not edges
        or any(not isinstance(n, dict) for n in nodes)
        or any(not isinstance(e, dict) for e in edges)
    ):
        raise ValueError("relationship routing requires explicit node and edge objects")
    ids = [n.get("id") for n in nodes]
    if any(
        not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", i) for i in ids
    ) or len(set(ids)) != len(ids):
        raise ValueError("relationship routing requires unique safe node IDs")
    incoming, pairs = {i: [] for i in ids}, set()
    for edge in edges:
        a, b = edge.get("source"), edge.get("target")
        if (
            not isinstance(a, str)
            or not isinstance(b, str)
            or a not in incoming
            or b not in incoming
        ):
            raise ValueError("relationship routing edge endpoint is missing")
        if a == b or (a, b) in pairs:
            raise ValueError("relationship routing rejects self or duplicate edges")
        pairs.add((a, b))
        incoming[b].append(a)
    levels = {}
    while len(levels) < len(ids):
        ready = [i for i in ids if i not in levels and all(a in levels for a in incoming[i])]
        if not ready:
            raise ValueError("relationship routing requires a DAG; cycles are not rewritten")
        for ident in ready:
            levels[ident] = max((levels[a] + 1 for a in incoming[ident]), default=0)
    counts = [sum(v == i for v in levels.values()) for i in range(3)]
    if max(levels.values()) == 2 and all(1 <= c <= 3 for c in counts) and counts[1] == 1:
        return False  # Keep the existing compatible three-stage renderer.
    from textbook2video.research.visual_semantic_graph import DIRECTIONAL_RELATIONS

    if any(
        "relation" in e
        and (not isinstance(e["relation"], str) or e["relation"] not in DIRECTIONAL_RELATIONS)
        for e in edges
    ):
        raise ValueError("relationship flow routing requires directional actions, not peer links")
    if spec.get("constraint") and not (
        spec.get("constraint_source_ref") or spec.get("constraint_evidence")
    ):
        raise ValueError("flow constraint requires source evidence")
    # Unknown fields are not discarded or silently rendered as plain labels.
    shared = {
        "id",
        "kind",
        "title",
        "teaching_goal",
        "nodes",
        "edges",
        "narration_refs",
        "narration_span",
        "text_scale",
        "constraint",
        "constraint_source_ref",
        "constraint_evidence",
    }
    node_fields = {
        "id",
        "label",
        "detail",
        "role",
        "source_ref",
        "evidence",
        "stored_by",
        "refers_to",
    }
    edge_fields = {"source", "target", "relation", "label", "directed", "source_ref", "evidence"}
    if (
        set(spec) - shared
        or any(set(n) - node_fields for n in nodes)
        or any(set(e) - edge_fields for e in edges)
    ):
        raise ValueError("relationship cannot route to flow without unsupported field loss")
    return True



def renderer_graphs(arguments):
    """Select compatible renderers; preserve explicit topology, text and provenance."""
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
        if (
            isinstance(original, dict)
            and original.get("kind") == "relationship"
            and "diagram" in original
        ):
            continue  # Existing renderer metadata/manual dialect remains authoritative.
        spec = normalized["visuals"][0]
        specs[index] = spec
        changes.extend(messages)
        if not isinstance(spec, dict) or spec.get("kind") != "relationship":
            continue
        if spec.get("schema_version"):
            raise ValueError("relationship may not declare a general graph schema_version")
        if _route_relationship_renderer(spec):
            spec["kind"] = "flow"
            changes.append(
                f"Executor routed {spec.get('id')} relationship -> flow "
                "from explicit DAG topology; "
                "node IDs, nodes, edges, directions, text and source refs unchanged; "
                "renderer selection is not semantic approval"
            )
            continue
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
        graph = spec.get("diagram", spec) if spec.get("kind") == "relationship" else spec
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
            invalid = [index for index, node in enumerate(nodes)
                       if not isinstance(node, dict) or not isinstance(node.get("id"), str)
                       or not node.get("id")]
            duplicate = sorted({ident for ident in ids if ids.count(ident) > 1})
            raise ValueError(
                f"visual {spec.get('id')}: graph nodes need unique nonempty IDs; "
                f"invalid_node_indexes={invalid}, duplicate_node_ids={duplicate}; "
                "send complete replacement visuals"
            )
        for index, edge in enumerate(edges):
            if (not isinstance(edge, dict) or not isinstance(edge.get("source"), str)
                    or not isinstance(edge.get("target"), str)
                    or edge["source"] not in ids or edge["target"] not in ids):
                source = edge.get("source") if isinstance(edge, dict) else None
                target = edge.get("target") if isinstance(edge, dict) else None
                raise ValueError(
                    f"visual {spec.get('id')}: edge[{index}] endpoints must name existing "
                    f"nodes; source={source!r}, target={target!r}, node_ids={ids}; "
                    "replace the structure"
                )


def diagnose_visual_plan_response(raw, mode, *, source=None, narration=None, page_context=None, asset_only=False):
    """Collect independent offline diagnostics using existing gates; never repair or admit.

    This supplements fail-closed execution, it is not an alternate acceptance path.
    Envelope failures do not hide independently inspectable semantic/source failures.
    """
    from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
    from textbook2video.research.relationship_visuals import validate_relationship
    from textbook2video.research.visual_content_map import materialize_content_map
    from textbook2video.research.visual_grammar import KINDS, validate_visual
    from textbook2video.research.visual_narration_refs import materialize_narration_refs
    from textbook2video.research.visual_semantic_graph import materialize_semantic_graphs
    from textbook2video.research.visual_source_refs import materialize_source_refs
    from textbook2video.research.visual_tools import compose, normalize_visual_arguments
    issues = []
    try:
        parse_visual_plan_response(raw, mode, asset_only=asset_only)
    except (ValueError, TypeError) as exc:
        issues.extend((getattr(exc, 'details', None) or {}).get('validation_issues', [
            {'stage': 'envelope', 'path': '/', 'message': str(exc)}]))
    try:
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.I)
        value = json.loads(cleaned)
        if not isinstance(value, dict):
            return issues
        # Edits need their verified parent and scope. Do not diagnose a patch
        # as if it were a complete graph; dispatch validates the resolved base.
        if mode not in {'full_candidate', 'structural_replacement'}:
            return issues
        args = {key: deepcopy(value[key]) for key in _PLAN_TYPES if key in value}
        args, _ = common_graphs(args)
    except (ValueError, TypeError) as exc:
        return issues + [{'stage': 'structure', 'path': '/', 'message': str(exc)}]
    def check(stage, fn, path='/'):
        try:
            return fn()
        except (ValueError, TypeError, KeyError) as exc:
            details = getattr(exc, 'issues', None)
            if details:
                issues.extend({'stage': stage, 'path': i['path'], 'message': i['message']} for i in details)
            else:
                issues.append({'stage': stage, 'path': path, 'message': str(exc)})
    check('structure', lambda: check_structure(deepcopy(args)))
    normalized = check('semantics', lambda: materialize_semantic_graphs(deepcopy(args)))
    semantic_args = normalized[0] if normalized else args
    if source is not None:
        check('source', lambda: materialize_source_refs(deepcopy(semantic_args), source, page_context))
    if narration is not None:
        check('narration', lambda: materialize_narration_refs(deepcopy(args), narration))
    # Reuse renderer validation on independent panels. A failed panel must not
    # hide another panel's malformed grammar. No compiler/image API runs here.
    specs = args.get('visuals')
    for index, spec in enumerate(specs if isinstance(specs, list) else []):
        if not isinstance(spec, dict):
            continue
        def grammar_check(spec=spec):
            candidate, _ = normalize_visual_arguments({'visuals': [spec]}, automatic_layout=True)
            if source is not None:
                candidate, _ = materialize_source_refs(candidate, source, None)
            resolved = candidate['visuals'][0]
            if resolved.get('kind') == 'relationship':
                validate_relationship(resolved, source)
            elif resolved.get('kind') in KINDS:
                validate_visual(resolved, source)
        # Dependent role/source failures are already reported with their own
        # stage; do not relabel those failures as renderer grammar errors.
        if not any(i['stage'] in {'semantics', 'source'} for i in issues):
            check('grammar', grammar_check, f'/visuals/{index}')
    if isinstance(args.get('composition'), dict):
        def composition_check():
            result = compose(**args['composition'])
            flattened = [ident for group in result['pages'] for ident in group]
            ids = [spec.get('id') for spec in specs if isinstance(spec, dict)]
            if set(flattened) != set(ids) or len(flattened) != len(ids):
                raise ValueError('composition must include every visual exactly once')
        check('composition', composition_check, '/composition')
    if page_context is not None and ('content_map' in args or 'page_plan' in args):
        def page_check():
            candidate, _ = materialize_content_map(deepcopy(semantic_args), page_context)
            if source is not None:
                candidate, _ = materialize_source_refs(candidate, source, page_context)
            apply_visual_page_plan({'elements': deepcopy(page_context)}, '__diagnostic__',
                                   candidate.get('page_plan'), visual_specs=candidate.get('visuals'), source_text=source)
        check('page_plan', page_check)
    return issues
