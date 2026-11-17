"""Engineering fixtures: degraded rendering is not semantic approval."""

from copy import deepcopy
import json

import pytest

from textbook2video.pipeline import course_binding
from textbook2video.research import visual_tools
from textbook2video.research.visual_review_policy import review_disposition


def arguments():
    return {'visuals': [{
        'id': 'graph', 'kind': 'flow', 'title': 'Fixture', 'teaching_goal': 'Explain inputs.',
        'nodes': [
            {'id': 'a', 'label': 'Input', 'role': 'data', 'source_ref': 'source-001'},
            {'id': 'b', 'label': 'Process', 'role': 'process', 'source_ref': 'source-001'},
            {'id': 'c', 'label': 'Context', 'role': 'entity', 'source_ref': 'source-001'},
        ],
        'edges': [
            {'source': 'a', 'target': 'b', 'relation': 'input', 'source_ref': 'source-001'},
            {'source': 'b', 'target': 'c', 'relation': 'input', 'source_ref': 'source-001'},
        ],
    }]}


def test_development_retains_nodes_without_inventing_replacement_relations(tmp_path):
    raw = arguments()
    visual_tools.dispatch('create', raw, source='Input enters process.', output_dir=tmp_path/'dev',
                          automatic_layout=True, development=True, render=False)
    visual_tools.verify_revision(tmp_path/'dev')
    record = json.loads((tmp_path/'dev/revision.json').read_text(encoding='utf-8'))
    specs = json.loads((tmp_path/'dev/specs.json').read_text(encoding='utf-8'))
    assert [n['id'] for n in specs[0]['nodes']] == ['a', 'b', 'c']
    assert [(e['source'], e['target']) for e in specs[0]['edges']] == [('a', 'b')]
    assert any('Omitted invalid' in s for s in record['development_warnings'])
    assert record['quality_status'] == 'USED_WITH_WARNING'
    assert json.loads((tmp_path/'dev/raw_tool_request.json').read_text())['arguments'] == raw
    assert raw == arguments()
    with pytest.raises(ValueError, match='incompatible subject/object roles'):
        visual_tools.dispatch('create', raw, source='Input enters process.',
                              output_dir=tmp_path/'strict', automatic_layout=True, render=False)


def test_unresolved_evidence_remains_unresolved_in_rendered_draft(tmp_path):
    raw = arguments()
    raw['visuals'][0]['nodes'][0]['source_ref'] = 'source-does-not-exist'
    visual_tools.dispatch('create', raw, source='Input enters process.', output_dir=tmp_path/'dev',
                          automatic_layout=True, development=True, render=False)
    visual_tools.verify_revision(tmp_path/'dev')
    spec = json.loads((tmp_path/'dev/specs.json').read_text())
    assert spec[0]['nodes'][0]['source_ref'] == 'source-does-not-exist'
    assert 'evidence' not in spec[0]['nodes'][0]  # No fabricated quote.
    record = json.loads((tmp_path/'dev/revision.json').read_text())
    assert any('source_ref must select existing' in w for w in record['development_warnings'])


def test_unknown_role_is_not_reinterpreted_as_a_valid_typed_relation(tmp_path):
    raw = arguments()
    raw['visuals'][0]['nodes'][0]['role'] = 'unknown-semantic-role'
    visual_tools.dispatch('create', raw, source='Input enters process.', output_dir=tmp_path/'dev',
                          automatic_layout=True, development=True, render=False)
    spec = json.loads((tmp_path/'dev/specs.json').read_text())
    assert [n['id'] for n in spec[0]['nodes']] == ['a', 'b', 'c']
    assert spec[0]['edges'] == []  # Neither typed claim can safely be retained.
    assert len(json.loads((tmp_path/'dev/raw_tool_request.json').read_text())
               ['arguments']['visuals'][0]['edges']) == 2


@pytest.mark.parametrize('mutation', ['unsafe_id', 'duplicate_node', 'invalid_label'])
def test_core_nonrenderable_structure_still_fails(tmp_path, mutation):
    raw = arguments()
    if mutation == 'unsafe_id':
        raw['visuals'][0]['id'] = '../escape'
    elif mutation == 'duplicate_node':
        raw['visuals'][0]['nodes'][1]['id'] = 'a'
    else:
        raw['visuals'][0]['nodes'][0]['label'] = None
    with pytest.raises(ValueError):
        visual_tools.dispatch('create', raw, source='Input enters process.',
                              output_dir=tmp_path/'bad', automatic_layout=True,
                              development=True, render=False)
    assert not (tmp_path/'bad/revision.json').exists()


def test_degraded_execution_never_promoted_by_accepting_reviewer():
    report = {'verdict': 'ACCEPT', 'scores': dict.fromkeys(
        ['accuracy', 'relevance', 'readability', 'composition'], 4), 'issues': []}
    before = deepcopy(report)
    for policy in ('development', 'strict'):
        d = review_disposition(report, [], policy=policy,
                               execution_warnings=['Omitted invalid edge'])
        assert d['strict_approved'] is False
        assert d['draft_usable'] is (policy == 'development')
    assert report == before


def test_binding_reservation_does_not_allow_overwriting_evidence(tmp_path):
    tmp_path.joinpath('existing.json').write_text('original', encoding='utf-8')
    with pytest.raises(FileExistsError, match='not empty'):
        course_binding.bind_course_visuals({'segments': []}, None, tmp_path, tmp_path,
                                          review_model='offline', browser='msedge')
    assert tmp_path.joinpath('existing.json').read_text() == 'original'
