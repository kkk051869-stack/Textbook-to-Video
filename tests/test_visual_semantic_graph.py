import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from textbook2video.research.visual_semantic_graph import (
    materialize_semantic_graphs,
    requires_semantic_replacement,
)


def sample():
    return {'visuals': [{'id': 'monitor', 'kind': 'network', 'title': '监测设备',
                         'nodes': [
                             {'id': 'instrument', 'label': '监测仪', 'role': 'entity'},
                             {'id': 'equipment', 'label': '设备', 'role': 'entity'},
                             {'id': 'measure', 'label': '测量过程', 'role': 'process'},
                             {'id': 'value', 'label': '温度基准', 'role': 'value',
                              'stored_by': 'instrument', 'refers_to': 'equipment',
                              'source_ref': 'source-001'}],
                         'edges': [
                             {'source': 'measure', 'target': 'value', 'relation': 'produces',
                              'source_ref': 'source-001'},
                             {'source': 'instrument', 'target': 'value', 'relation': 'stores',
                              'source_ref': 'source-001'}]}]}


def test_semantic_replacement_required_only_for_unmaterialized_semantic_graphs():
    args = sample()
    assert requires_semantic_replacement(args) is True

    materialized, _ = materialize_semantic_graphs(args)
    assert requires_semantic_replacement(materialized) is False

    ordinary_graph = {'visuals': [{'id': 'legacy', 'kind': 'network', 'nodes': [
        {'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}],
        'edges': [{'source': 'a', 'target': 'b', 'label': '连接'}]}]}
    assert requires_semantic_replacement(ordinary_graph) is False
    assert requires_semantic_replacement({}) is False


def test_declared_owners_and_actions_become_visible_without_mutating_source_intent():
    args = sample()
    before = deepcopy(args)
    rendered, changes = materialize_semantic_graphs(args)
    graph = rendered['visuals'][0]
    assert graph['nodes'][-1]['detail'] == '保存者: 监测仪；所指对象: 设备'
    assert [e['label'] for e in graph['edges']] == ['生成', '保存']
    assert graph['nodes'][-1]['source_ref'] == 'source-001'
    assert args == before and changes
    assert materialize_semantic_graphs(rendered)[0] == rendered


@pytest.mark.parametrize('relation,source,target', [
    ('produces', 'value', 'measure'), ('stores', 'measure', 'value'),
    ('input', 'instrument', 'measure'), ('irreversible', 'measure', 'value'),
])
def test_incompatible_subject_action_object_or_property_edge_is_rejected(relation, source, target):
    args = sample()
    args['visuals'][0]['edges'][0].update(relation=relation, source=source, target=target)
    with pytest.raises(ValueError, match='semantic relation|incompatible subject'):
        materialize_semantic_graphs(args)


def test_conflicting_action_label_is_rejected_instead_of_silently_rewritten():
    args = sample()
    args['visuals'][0]['edges'][0]['label'] = '无法反推'
    with pytest.raises(ValueError, match='omit label'):
        materialize_semantic_graphs(args)


def test_ownership_requires_explicit_existing_entity_and_does_not_infer_unspecified_roles():
    args = sample()
    args['visuals'][0]['nodes'][-1]['stored_by'] = 'unknown'
    with pytest.raises(ValueError, match='another existing node'):
        materialize_semantic_graphs(args)
    args = sample()
    for key in ('stored_by', 'refers_to'):
        args['visuals'][0]['nodes'][-1].pop(key)
    result, _ = materialize_semantic_graphs(args)
    assert 'detail' not in result['visuals'][0]['nodes'][-1]


def test_english_graph_uses_english_relation_labels():
    args = sample()
    args['visuals'][0]['title'] = 'Measurement'
    result, _ = materialize_semantic_graphs(args)
    assert result['visuals'][0]['edges'][0]['label'] == 'produces'


def test_typed_graph_runs_through_real_dispatch_and_svg_without_losing_raw_intent(tmp_path):
    from textbook2video.research.visual_tools import dispatch, verify_revision

    source = '监测仪通过测量过程生成温度基准并保存，温度基准所指对象为设备。'
    args = sample()
    args['visuals'][0]['teaching_goal'] = '理解温度基准的生成、保存及所指设备'
    args['visuals'][0]['edges'].append({
        'source': 'value', 'target': 'equipment', 'relation': 'references',
        'source_ref': 'source-001',
    })
    for node in args['visuals'][0]['nodes']:
        node['source_ref'] = 'source-001'
    output = dispatch('create', args, source=source, output_dir=tmp_path / 'candidate',
                      page_context=[], narration_text=source, render=False)
    directory = output.parent
    verify_revision(directory)
    raw = json.loads((directory / 'raw_tool_request.json').read_text(encoding='utf-8'))
    effective = json.loads((directory / 'request.json').read_text(encoding='utf-8'))
    assert raw['arguments']['visuals'][0]['nodes'][-1]['stored_by'] == 'instrument'
    assert effective['arguments']['visuals'][0]['edges'][0]['label'] == '生成'
    svg = next(directory.rglob('*.svg')).read_text(encoding='utf-8')
    visible_text = ''.join(ET.fromstring(svg).itertext())
    assert '保存者: 监测仪' in visible_text and '所指对象: 设备' in visible_text
    root = ET.fromstring(svg)
    paths = {p.get('data-edge'): p for p in root.iter() if p.get('data-edge')}
    for edge in args['visuals'][0]['edges']:
        path = paths[f"{edge['source']}:{edge['target']}"]
        assert path.get('marker-end') == 'url(#grammar-arrow)'


@pytest.mark.parametrize('relation,source_role,target_role', [
    ('input', 'data', 'process'), ('produces', 'process', 'value'),
    ('stores', 'entity', 'value'), ('detects', 'entity', 'event'),
    ('changes', 'process', 'state'), ('references', 'value', 'entity'),
    ('precedes', 'event', 'event'), ('causes', 'event', 'state'),
])
def test_directional_action_materializes_arrow_without_changing_endpoints_or_sources(
    relation, source_role, target_role,
):
    args = {'visuals': [{'id': 'test', 'kind': 'network', 'title': '方向检查',
                        'nodes': [{'id': 'a', 'role': source_role},
                                  {'id': 'b', 'role': target_role}],
                        'edges': [{'source': 'a', 'target': 'b', 'relation': relation,
                                   'source_ref': 'source-001'}]}]}
    before = deepcopy(args)
    result, _ = materialize_semantic_graphs(args)
    edge = result['visuals'][0]['edges'][0]
    assert edge['directed'] is True
    assert (edge['source'], edge['target'], edge['source_ref']) == ('a', 'b', 'source-001')
    assert args == before


@pytest.mark.parametrize('directed', [False, None, 'true', 1])
def test_explicit_direction_conflict_is_rejected_instead_of_silently_overwritten(directed):
    args = sample()
    args['visuals'][0]['edges'][0]['directed'] = directed
    before = deepcopy(args)
    with pytest.raises(ValueError, match='directed must be true'):
        materialize_semantic_graphs(args)
    assert args == before


def test_peer_association_and_legacy_network_are_not_forced_directional():
    args = sample()
    args['visuals'][0]['edges'][0].update(relation='association', directed=False)
    args['visuals'][0]['edges'][1].pop('relation')
    result, _ = materialize_semantic_graphs(args)
    assert result['visuals'][0]['edges'][0]['directed'] is False
    assert 'directed' not in result['visuals'][0]['edges'][1]
