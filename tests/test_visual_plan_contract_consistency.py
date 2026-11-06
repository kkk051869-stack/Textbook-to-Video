"""Offline envelope checks only; no visual generation or semantic relaxation."""
import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from textbook2video.research.visual_model_interface import (
    VISUAL_PLAN_VERSION, visual_plan_contract, parse_visual_plan_response, check_structure,
)


@pytest.mark.parametrize('mode,body', [
    ('full_candidate', {'visuals': []}),
    ('structural_replacement', {'visuals': []}),
    ('updates', {'updates': []}),
    ('draft_updates', {'updates': []}),
    ('scoped_label', {'updates': []}),
    ('scoped_detail', {'updates': []}),
    ('append_missing_panel', {'panel': {}, 'existing_narration_refs': [], 'panel_narration_refs': []}),
])
def test_advertised_envelope_and_strict_parser_agree(mode, body):
    contract = visual_plan_contract(mode)
    schema = contract['response_schema']
    assert schema['properties']['plan_version'] == {'type': 'string', 'const': VISUAL_PLAN_VERSION}
    assert set(schema['required']) == set(contract['required_fields'])
    assert set(schema['properties']) == set(contract['allowed_fields'])
    Draft202012Validator.check_schema(schema)
    good = {'plan_version': VISUAL_PLAN_VERSION, **body}
    Draft202012Validator(schema).validate(good)
    assert parse_visual_plan_response(json.dumps(good), mode) == (body, [])
    # Fixed version and field requirements cannot be silently supplied or coerced.
    invalid = [dict(good, plan_version='1'), dict(good, plan_version=1),
               dict(good, plan_version=None), dict(good, plan_version='visual-plan-v2'),
               dict(good, arbitrary='not allowed')]
    for required in schema['required']:
        missing = deepcopy(good); missing.pop(required); invalid.append(missing)
    for key in body:
        invalid.append({**good, key: ''})
    for bad in invalid:
        before = deepcopy(bad)
        assert list(Draft202012Validator(schema).iter_errors(bad))
        with pytest.raises(ValueError):
            parse_visual_plan_response(json.dumps(bad), mode)
        assert bad == before


def test_envelope_schema_does_not_bypass_nested_graph_checks():
    # A valid envelope never implies that its visual content is legal.
    plan = {'plan_version': VISUAL_PLAN_VERSION, 'visuals': [
        {'id': 'bad', 'kind': 'flow', 'nodes': [{'label': 'missing object ID'}], 'edges': []}]}
    Draft202012Validator(visual_plan_contract('full_candidate')['response_schema']).validate(plan)
    payload, changes = parse_visual_plan_response(json.dumps(plan), 'full_candidate')
    assert not changes
    with pytest.raises(ValueError):
        check_structure(payload)


@pytest.mark.parametrize('mode,body', [
    ('full_candidate', {'visuals': []}), ('structural_replacement', {'visuals': []}),
    ('updates', {'updates': []}), ('draft_updates', {'updates': []}),
    ('scoped_label', {'updates': []}), ('scoped_detail', {'updates': []}),
    ('append_missing_panel', {'panel': {}, 'existing_narration_refs': [], 'panel_narration_refs': []}),
])
def test_asset_contract_owns_metadata_but_never_repairs_explicit_errors(mode, body):
    contract = visual_plan_contract(mode, asset_only=True)
    schema = contract['response_schema']
    Draft202012Validator(schema).validate(body)
    raw = json.dumps(body)
    payload, changes = parse_visual_plan_response(raw, mode, asset_only=True)
    assert payload == body and changes
    assert raw == json.dumps(body)
    for bad in [dict(body, plan_version='1'), dict(body, plan_version=None),
                dict(body, content_map={}), dict(body, page_plan={}), dict(body, composition={})]:
        assert list(Draft202012Validator(schema).iter_errors(bad))
        with pytest.raises(ValueError):
            parse_visual_plan_response(json.dumps(bad), mode, asset_only=True)
    good = dict(body, plan_version=VISUAL_PLAN_VERSION)
    assert parse_visual_plan_response(json.dumps(good), mode, asset_only=True) == (body, [])


def test_all_independent_envelope_errors_have_field_paths():
    with pytest.raises(ValueError) as caught:
        parse_visual_plan_response(json.dumps({'plan_version': '1', 'visuals': {}, 'unknown': 1}), 'full_candidate')
    issues = caught.value.details['validation_issues']
    assert {i['path'] for i in issues} == {'/plan_version', '/visuals', '/unknown'}
    with pytest.raises(ValueError) as missing:
        parse_visual_plan_response('{}', 'full_candidate')
    assert {i['path'] for i in missing.value.details['validation_issues']} == {'/plan_version', '/visuals'}


def test_diagnostics_keep_semantic_and_source_errors_despite_invalid_version():
    from textbook2video.research.visual_model_interface import diagnose_visual_plan_response
    plan = {'plan_version': '1', 'visuals': [{
        'id': 'hierarchy', 'kind': 'hierarchy', 'title': 'fixture', 'teaching_goal': 'fixture',
        'nodes': [{'id': 'a', 'label': 'A', 'role': 'data', 'source_ref': 'source-999'},
                  {'id': 'b', 'label': 'B', 'role': 'data', 'source_ref': 'source-999'},
                  {'id': 'c', 'label': 'C', 'role': 'data', 'source_ref': 'source-999'}],
        'edges': [{'source': 'a', 'target': 'b', 'relation': 'produces'},
                  {'source': 'b', 'target': 'c', 'relation': 'produces'}],
    }]}
    before = deepcopy(plan)
    issues = diagnose_visual_plan_response(json.dumps(plan), 'full_candidate', source='A contains B and C.')
    assert {'envelope', 'semantics', 'source'} <= {i['stage'] for i in issues}
    semantic_paths = {i['path'] for i in issues if i['stage'] == 'semantics'}
    assert '/visuals/0/edges/0/relation' in semantic_paths
    assert '/visuals/0/edges/1/relation' in semantic_paths
    assert plan == before


def test_patch_diagnostics_do_not_invent_missing_full_graph():
    from textbook2video.research.visual_model_interface import diagnose_visual_plan_response
    assert diagnose_visual_plan_response('{"updates": []}', 'updates', asset_only=True) == []


@pytest.mark.parametrize('value', [None, [], 3, {'visuals': None}, {'visuals': {}}, {'visuals': [None]},
                                  {'visuals': [{'kind': 'flow', 'nodes': None, 'edges': None}]}])
def test_diagnostics_handle_malformed_shapes_without_transport(value):
    from textbook2video.research.visual_model_interface import diagnose_visual_plan_response
    assert diagnose_visual_plan_response(json.dumps(value), 'full_candidate', source='fixture', narration='fixture')


def test_composition_schema_reports_multiple_errors_before_compilation():
    bad = {'plan_version': VISUAL_PLAN_VERSION, 'visuals': [],
           'composition': {'axis': 'diagonal', 'vertical_free': 'yes'}}
    assert len(list(Draft202012Validator(visual_plan_contract('full_candidate')['response_schema']).iter_errors(bad))) == 3
    with pytest.raises(ValueError) as caught:
        parse_visual_plan_response(json.dumps(bad), 'full_candidate')
    assert len(caught.value.details['validation_issues']) == 3
    good = dict(bad, composition={'visual_ids': ['main'], 'axis': 'single'})
    parse_visual_plan_response(json.dumps(good), 'full_candidate')


def test_flat_and_renderer_relationship_have_same_addressable_structure():
    graph = {'nodes': [{'id': 'a'}, {'id': 'b'}], 'edges': [{'source': 'a', 'target': 'b'}]}
    check_structure({'visuals': [{'id': 'main', 'kind': 'relationship', **deepcopy(graph)}]})
    check_structure({'visuals': [{'id': 'main', 'kind': 'relationship', 'diagram': deepcopy(graph)}]})
    graph['edges'][0]['target'] = 'missing'
    with pytest.raises(ValueError, match='endpoints'):
        check_structure({'visuals': [{'id': 'main', 'kind': 'relationship', **graph}]})


def test_composition_executor_rejects_schema_type_errors_without_coercion():
    from textbook2video.research.visual_tools import compose
    for bad in [{'visual_ids': 'ab'}, {'visual_ids': [['a']]},
                {'visual_ids': ['a'], 'axis': []},
                {'visual_ids': ['a', 'b'], 'axis': 'vertical', 'vertical_free': 'true'}]:
        with pytest.raises(ValueError):
            compose(**bad)
