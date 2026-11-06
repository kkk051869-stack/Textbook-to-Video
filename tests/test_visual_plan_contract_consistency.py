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
