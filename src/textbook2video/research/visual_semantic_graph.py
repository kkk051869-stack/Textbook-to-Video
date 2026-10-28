"""Materialize explicitly declared semantic roles into the existing graph interface."""

import re
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

SEMANTIC_GRAPH_RULES = (
    'Plan each graph as explicit subjects, actions and objects in ONE nodes/edges response. '
    'Declare node role: entity|process|data|value|state|event. '
    'Declare each edge relation: input|produces|stores|compares|detects|changes|references|'
    'precedes|causes|association; omit label for typed edges, code renders the action. '
    'input means data/value/state -> process; produces means process -> value/data/state; '
    'stores means entity -> value/data/state; compares connects TWO values; detects means '
    'actor/process -> event/state. Edge endpoints are the actual subject and object, '
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
    """A located failure authorizes only the executor-selected draft object."""

    def __init__(self, message, visual_id, edge, fields, subgraph=False):
        super().__init__(message)
        self.details = {
            'draft_target': {'visual_id': visual_id, 'edge': {
                key: edge[key] for key in ('source', 'target')}},
            'draft_fields': fields, 'draft_subgraph': subgraph,
        }


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
    result, messages = deepcopy(arguments), []
    for spec in result.get('visuals', []):
        if not isinstance(spec, dict) or spec.get('kind') not in GRAPH_TYPES:
            continue
        graph = spec.get('diagram', spec) if spec['kind'] == 'relationship' else spec
        if not isinstance(graph, dict) or not isinstance(graph.get('nodes'), list):
            continue
        nodes = {node.get('id'): node for node in graph['nodes'] if isinstance(node, dict)
                 and isinstance(node.get('id'), str)}
        roles = {ident: node.get('role') for ident, node in nodes.items()}
        chinese = bool(re.search(r'[\u3400-\u9fff]', str(spec.get('title', ''))))
        for ident, node in nodes.items():
            if 'role' in node and (not isinstance(node['role'], str) or node['role'] not in ROLES):
                raise ValueError(
                    f'node {ident}: unknown semantic role; properties belong in detail')
            owner, referent = node.get('stored_by'), node.get('refers_to')
            detail = []
            for field, selected, zh, en in (
                ('stored_by', owner, '保存者', 'Stored by'),
                ('refers_to', referent, '所指对象', 'Refers to'),
            ):
                if field not in node:
                    continue
                if not isinstance(selected, str) or selected not in nodes or selected == ident:
                    raise ValueError(f'node {ident}: {field} must select another existing node')
                if field == 'stored_by' and (roles.get(selected) != 'entity'
                                             or roles.get(ident) not in VALUES):
                    raise ValueError(
                        'stored_by must bind an entity owner to a data/value/state node')
                if not isinstance(nodes[selected].get('label'), str):
                    raise ValueError('ownership target needs a visible node label')
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
            if not isinstance(relation, str) or relation not in RELATIONS:
                raise ValueError('unknown semantic relation; properties belong in node.detail')
            source, target = edge.get('source'), edge.get('target')
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValueError('semantic relation endpoints must select existing node IDs')
            allowed_source, allowed_target, zh, en = RELATIONS[relation]
            if roles.get(source) not in allowed_source or roles.get(target) not in allowed_target:
                raise SemanticGraphError(
                    f'{relation}: incompatible subject/object roles for {source}->{target}',
                    spec.get('id'), edge, ['relation', 'source_ref'], subgraph=True)
            label = zh if chinese else en
            if 'label' in edge and edge['label'] != label:
                raise SemanticGraphError(
                    f'typed edge {relation}: omit label; executor supplies {label}',
                    spec.get('id'), edge, ['label'])
            edge['label'] = label
            edge.pop('relation')
            messages.append(
                f'Materialized {relation} action on {spec.get("id")}:{source}->{target}')
        for node in nodes.values():
            node.pop('role', None)
    return result, messages
