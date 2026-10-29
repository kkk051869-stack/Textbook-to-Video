"""Materialize explicitly declared semantic roles into the existing graph interface."""

import re
from collections import Counter, defaultdict
from copy import deepcopy

from textbook2video.research.visual_model_interface import GRAPH_TYPES

VALUES = {'data', 'value', 'state'}
ROLES = VALUES | {'entity', 'process', 'event'}
RELATIONS = {
    'input': (VALUES, {'process'}, '输入', 'input'),
    'produces': ({'process'}, VALUES, '生成', 'produces'),
    'stores': ({'entity'}, VALUES, '保存', 'stores'),
    'compares': (VALUES, VALUES, '比较', 'compares'),
    'detects': ({'entity', 'process'}, {'event', 'state'}, '发现', 'detects'),
    'changes': ({'entity', 'process', 'event'}, VALUES, '改变', 'changes'),
    'references': (ROLES, ROLES, '引用', 'references'),
    'precedes': (ROLES, ROLES, '随后', 'precedes'),
    'causes': (ROLES, ROLES, '导致', 'causes'),
    'association': (ROLES, ROLES, '关联', 'relates to'),
}
DIRECTIONAL_RELATIONS = set(RELATIONS) - {'association', 'compares'}

SEMANTIC_GRAPH_RULES = (
    'Plan each graph as explicit subjects, actions and objects in ONE nodes/edges response. '
    'Declare node role: entity|process|data|value|state|event. '
    'Declare each edge relation: input|produces|stores|compares|detects|changes|references|'
    'precedes|causes|association; omit label for typed edges, code renders the action. '
    'input means data/value/state -> process; produces means process -> value/data/state; '
    'stores means entity -> value/data/state; compares connects TWO values; detects means '
    'actor/process -> event/state. Edge endpoints are the actual subject and object, '
    'Directional actions render arrows from source to target; omit directed or set true. '
    'Use association for an explicitly undirected peer link. '
    'not a loose series of words. A property such as irreversibility belongs in node.detail, '
    'never in an action edge. For a stored value/reference, explicitly select '
    'stored_by:<existing entity node ID> and refers_to:<existing referenced node ID> '
    'on the value node when the source specifies them. Code makes BOTH identities visible '
    'in its detail. Include those owner/referent nodes in the same panel; prefer network '
    'for storage/reference mechanisms. Use source_ref to support every declared role/action; '
    'do not invent a missing actor, owner or mechanism. Use full replacement when changing '
    'semantic roles; ordinary label/detail updates retain the current editing contract.'
)


class SemanticGraphError(ValueError):
    """Collected deterministic errors; only uniquely addressable objects are patchable."""

    def __init__(self, issues):
        self.issues = deepcopy(issues)
        self.details = {'draft_issues': deepcopy(issues)}
        # Keep the original single-error diagnostic shape readable by old reports/tools.
        if len(issues) == 1 and issues[0].get('draft_target'):
            self.details.update({
                key: deepcopy(issues[0][key])
                for key in ('draft_target', 'draft_fields', 'draft_subgraph')
            })
        summary = '; '.join(
            f"{issue['path']}: {issue['message']}" for issue in issues
        )
        super().__init__(f"semantic graph validation found {len(issues)} issue(s): {summary}")


def _pointer(*parts):
    return '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def _collect_semantic_issues(arguments):
    issues = []

    def add(code, message, path, target=None, fields=(), subgraph=False):
        issue = {
            'code': code,
            'message': message,
            'path': path,
            'draft_target': deepcopy(target),
            'draft_fields': list(fields),
            'draft_subgraph': bool(subgraph),
        }
        issues.append(issue)

    if not isinstance(arguments, dict):
        return [{'code': 'arguments_type', 'message': 'arguments must be an object',
                 'path': '/', 'draft_target': None, 'draft_fields': [],
                 'draft_subgraph': False}]
    specs = arguments.get('visuals')
    if not isinstance(specs, list):
        if 'visuals' in arguments:
            add('visuals_type', 'visuals must be a list', '/visuals')
        return issues

    visual_ids = defaultdict(list)
    for index, spec in enumerate(specs):
        ident = spec.get('id') if isinstance(spec, dict) else None
        if isinstance(ident, str):
            visual_ids[ident].append(index)
        if (not isinstance(ident, str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ident)):
            add('visual_id', 'visual ID must be a safe nonempty identifier',
                _pointer('visuals', index, 'id'))
    for ident, indexes in visual_ids.items():
        if len(indexes) > 1:
            for index in indexes:
                add('duplicate_visual_id', f'duplicate visual ID {ident!r}',
                    _pointer('visuals', index, 'id'))

    for visual_index, spec in enumerate(specs):
        if not isinstance(spec, dict) or spec.get('kind') not in GRAPH_TYPES:
            continue
        graph = spec.get('diagram', spec) if spec['kind'] == 'relationship' else spec
        if not isinstance(graph, dict):
            add('graph_type', 'semantic graph must be an object',
                _pointer('visuals', visual_index, 'diagram'))
            continue
        if 'nodes' not in graph:
            continue
        nodes, edges = graph.get('nodes'), graph.get('edges', [])
        if not isinstance(nodes, list):
            add('nodes_type', 'semantic graph nodes must be a list',
                _pointer('visuals', visual_index, 'nodes'))
            continue
        if not isinstance(edges, list):
            add('edges_type', 'semantic graph edges must be a list',
                _pointer('visuals', visual_index, 'edges'))
            continue

        visual_id = spec.get('id')
        visual_addressable = (
            isinstance(visual_id, str)
            and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', visual_id)
            and visual_ids.get(visual_id) == [visual_index]
        )
        by_id = defaultdict(list)
        node_roles = {}
        node_addressable = {}
        for node_index, node in enumerate(nodes):
            node_id = node.get('id') if isinstance(node, dict) else None
            if isinstance(node_id, str):
                by_id[node_id].append((node_index, node))
            if (not isinstance(node_id, str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', node_id)):
                add('node_id', 'node ID must be a safe nonempty identifier',
                    _pointer('visuals', visual_index, 'nodes', node_index, 'id'))
        for node_id, entries in by_id.items():
            if len(entries) > 1:
                for node_index, _ in entries:
                    add('duplicate_node_id', f'duplicate node ID {node_id!r}',
                        _pointer('visuals', visual_index, 'nodes', node_index, 'id'))

        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                add('node_type', 'node must be an object',
                    _pointer('visuals', visual_index, 'nodes', node_index))
                continue
            node_id = node.get('id')
            unique_node = (isinstance(node_id, str) and len(by_id[node_id]) == 1
                           and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', node_id)))
            target = ({'visual_id': visual_id, 'node_id': node_id}
                      if visual_addressable and unique_node else None)
            node_addressable[node_index] = target
            role = node.get('role')
            if 'role' in node:
                if not isinstance(role, str) or role not in ROLES:
                    add('unknown_role', f'node {node_id}: unknown semantic role',
                        _pointer('visuals', visual_index, 'nodes', node_index, 'role'),
                        target, ('role',))
                else:
                    node_roles[node_id] = role

        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            node_id = node.get('id')
            unique_current = (isinstance(node_id, str) and len(by_id[node_id]) == 1)
            target = node_addressable.get(node_index)
            for field in ('stored_by', 'refers_to'):
                if field not in node:
                    continue
                selected = node[field]
                selected_entries = by_id.get(selected, []) if isinstance(selected, str) else []
                if (not isinstance(selected, str) or selected == node_id
                        or len(selected_entries) != 1):
                    add(f'{field}_reference',
                        f'node {node_id}: {field} must select another existing node',
                        _pointer('visuals', visual_index, 'nodes', node_index, field),
                        target, (field,))
                    continue
                selected_node = selected_entries[0][1]
                if field == 'stored_by':
                    owner_role = node_roles.get(selected)
                    value_role = node_roles.get(node_id) if unique_current else None
                    if not unique_current:
                        continue
                    if owner_role is None or value_role is None:
                        for role_node_id in (selected, node_id):
                            role_node = by_id[role_node_id][0][1]
                            if 'role' not in role_node:
                                role_index = by_id[role_node_id][0][0]
                                add('missing_role',
                                    f'node {role_node_id}: role is required for stored_by',
                                    _pointer('visuals', visual_index, 'nodes', role_index, 'role'),
                                    node_addressable.get(role_index), ('role',))
                        continue
                    if owner_role != 'entity' or value_role not in VALUES:
                        add('stored_by_role',
                            'stored_by must bind an entity owner to a data/value/state node',
                            _pointer('visuals', visual_index, 'nodes', node_index, field),
                            target, (field,))
                        continue
                if not isinstance(selected_node.get('label'), str):
                    selected_index = selected_entries[0][0]
                    selected_target = node_addressable.get(selected_index)
                    add('reference_label', 'referenced node needs a visible label',
                        _pointer('visuals', visual_index, 'nodes', selected_index, 'label'),
                        selected_target, ('label',))

        edge_pairs = Counter(
            (edge.get('source'), edge.get('target'))
            for edge in edges if isinstance(edge, dict)
            and isinstance(edge.get('source'), str) and isinstance(edge.get('target'), str)
        )
        for pair, count in edge_pairs.items():
            if count > 1:
                for edge_index, edge in enumerate(edges):
                    if isinstance(edge, dict) and (edge.get('source'), edge.get('target')) == pair:
                        add('duplicate_edge', f'duplicate directed edge {pair[0]}->{pair[1]}',
                            _pointer('visuals', visual_index, 'edges', edge_index))
        for edge_index, edge in enumerate(edges):
            if not isinstance(edge, dict):
                add('edge_type', 'edge must be an object',
                    _pointer('visuals', visual_index, 'edges', edge_index))
                continue
            source, target_id = edge.get('source'), edge.get('target')
            source_entries = by_id.get(source, []) if isinstance(source, str) else []
            target_entries = by_id.get(target_id, []) if isinstance(target_id, str) else []
            endpoints_valid = len(source_entries) == len(target_entries) == 1
            pair = (source, target_id)
            edge_target = (
                {'visual_id': visual_id, 'edge': {'source': source, 'target': target_id}}
                if visual_addressable and endpoints_valid and edge_pairs[pair] == 1 else None
            )
            if not endpoints_valid:
                for key, selected, entries in (
                    ('source', source, source_entries), ('target', target_id, target_entries),
                ):
                    if len(entries) != 1:
                        add('edge_endpoint',
                            f'{key} endpoint must select one existing node ID',
                            _pointer('visuals', visual_index, 'edges', edge_index, key))
            if 'relation' not in edge:
                continue
            relation = edge.get('relation')
            if not isinstance(relation, str) or relation not in RELATIONS:
                add('unknown_relation', 'unknown semantic relation',
                    _pointer('visuals', visual_index, 'edges', edge_index, 'relation'),
                    edge_target, ('relation',) if edge_target else ())
                continue
            if not endpoints_valid:
                continue
            source_role, target_role = node_roles.get(source), node_roles.get(target_id)
            for role_node_id, role_value in (
                (source, source_role), (target_id, target_role),
            ):
                if role_value is None:
                    role_node_index, role_node = by_id[role_node_id][0]
                    if 'role' not in role_node:
                        add('missing_role',
                            f'node {role_node_id}: role is required by relation {relation}',
                            _pointer('visuals', visual_index, 'nodes', role_node_index, 'role'),
                            node_addressable.get(role_node_index), ('role',))
            if source_role is None or target_role is None:
                continue
            allowed_source, allowed_target, zh, en = RELATIONS[relation]
            if (source_role not in allowed_source or target_role not in allowed_target):
                add('relation_role_pair',
                    f'{relation}: incompatible subject/object roles for {source}->{target_id}',
                    _pointer('visuals', visual_index, 'edges', edge_index, 'relation'),
                    edge_target, ('relation', 'source_ref'), True)
                continue
            if (relation in DIRECTIONAL_RELATIONS and 'directed' in edge
                    and edge['directed'] is not True):
                add('edge_direction', f'{relation}: directed must be true for this action edge',
                    _pointer('visuals', visual_index, 'edges', edge_index, 'directed'),
                    edge_target, ('directed',))
            chinese = bool(re.search(r'[\u3400-\u9fff]', str(spec.get('title', ''))))
            expected_label = zh if chinese else en
            if 'label' in edge and edge['label'] != expected_label:
                add('typed_edge_label',
                    f'typed edge {relation}: omit label; executor supplies {expected_label}',
                    _pointer('visuals', visual_index, 'edges', edge_index, 'label'),
                    edge_target, ('label',), True)
    unique, seen = [], set()
    for issue in issues:
        key = (issue['code'], issue['path'], issue['message'])
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def requires_semantic_replacement(arguments):
    """Raw semantic declarations are not editable renderer objects yet."""
    if not isinstance(arguments, dict):
        return False
    specs = arguments.get('visuals')
    for spec in specs if isinstance(specs, list) else []:
        if not isinstance(spec, dict):
            continue
        graph = spec.get('diagram', spec)
        if not isinstance(graph, dict):
            continue
        for key, fields in (('nodes', {'role', 'stored_by', 'refers_to'}),
                            ('edges', {'relation'})):
            objects = graph.get(key)
            if isinstance(objects, list) and any(
                    isinstance(obj, dict) and fields.intersection(obj) for obj in objects):
                return True
    return False


def materialize_semantic_graphs(arguments):
    issues = _collect_semantic_issues(arguments)
    if issues:
        raise SemanticGraphError(issues)
    result, messages = deepcopy(arguments), []
    for spec in result.get('visuals', []):
        if not isinstance(spec, dict) or spec.get('kind') not in GRAPH_TYPES:
            continue
        graph = spec.get('diagram', spec) if spec['kind'] == 'relationship' else spec
        if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list):
            continue
        nodes = {node.get('id'): node for node in graph['nodes'] if isinstance(node, dict)
                 and isinstance(node.get('id'), str)}
        chinese = bool(re.search(r'[\u3400-\u9fff]', str(spec.get('title', ''))))
        for ident, node in nodes.items():
            owner, referent = node.get('stored_by'), node.get('refers_to')
            detail = []
            for field, selected, zh, en in (
                ('stored_by', owner, '保存者', 'Stored by'),
                ('refers_to', referent, '所指对象', 'Refers to'),
            ):
                if field not in node:
                    continue
                detail.append(f'{zh if chinese else en}: {nodes[selected]["label"]}')
                node.pop(field)
            if detail:
                original = node.get('detail', '')
                if original and not isinstance(original, str):
                    raise ValueError('node detail must be text')
                node['detail'] = '；'.join(([original] if original else []) + detail)
                messages.append(f'Materialized declared ownership on {spec.get("id")}:{ident}')
        for edge in graph.get('edges', []):
            if not isinstance(edge, dict) or 'relation' not in edge:
                continue
            relation = edge['relation']
            source, target = edge.get('source'), edge.get('target')
            allowed_source, allowed_target, zh, en = RELATIONS[relation]
            if relation in DIRECTIONAL_RELATIONS:
                edge['directed'] = True
            label = zh if chinese else en
            edge['label'] = label
            edge.pop('relation')
            messages.append(
                f'Materialized {relation} action on {spec.get("id")}:{source}->{target}')
        for node in nodes.values():
            node.pop('role', None)
    return result, messages
