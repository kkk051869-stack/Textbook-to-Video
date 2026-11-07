import pytest

from textbook2video.research.visual_compact_review import (
    COMPACT_RULES,
    build_review_contract,
    compact_response_format,
    expand_review,
)
from textbook2video.research.visual_fact_audit import build_review_targets

NARRATION = "传感器读取温度。控制器保存阈值。"
SPECS = [
    {
        "id": "sensor",
        "kind": "relationship",
        "title": "温度采集",
        "narration_refs": ["narration-001"],
        "diagram": {
            "nodes": [
                {"id": "probe", "label": "传感器", "detail": "读取温度",
                 "source_ref": ["src-sensor"]},
                {"id": "controller", "label": "控制器"},
            ],
            "edges": [{"source": "probe", "target": "controller", "label": "发送读数"}],
        },
    },
    {
        "id": "threshold",
        "kind": "relationship",
        "title": "阈值保存",
        "narration_refs": ["narration-002"],
        "diagram": {
            "nodes": [
                {"id": "controller", "label": "控制器", "detail": "保存阈值",
                 "source_ref": ["src-threshold"]},
                {"id": "threshold", "label": "阈值"},
            ],
            "edges": [{"source": "controller", "target": "threshold", "label": "保存"}],
        },
    },
]


@pytest.fixture
def contract():
    facts = build_review_targets(SPECS, NARRATION)
    return build_review_contract(SPECS, facts)


def compact(contract, overrides=None):
    overrides = overrides or {}
    items = []
    for target in contract["targets"]:
        item = {"id": target["id"], "status": "ok", "reason": "可见且正确"}
        if target["kind"] == "unit":
            local = [e for e in contract["evidence"] if e["panel_id"] == target["panel_id"]]
            item["evidence_ids"] = [local[0]["id"]] if local else []
        if target["kind"] == "relation":
            item["status"] = "unspecified"
        item.update(overrides.get(target["id"], {}))
        items.append(item)
    return {"verdict": "ACCEPT", "scores": {"accuracy": 4}, "reason": "整体清晰", "items": items}


def test_expands_ids_to_executor_owned_endpoints_and_labels(contract):
    report = compact(contract)
    expanded = expand_review(report, contract)
    edges = [edge for panel in expanded["fact_audit"]["panels"] for edge in panel["edges"]]
    assert edges == [
        {"source": "probe", "target": "controller", "label": "发送读数",
         "status": "supported", "reason": "可见且正确"},
        {"source": "controller", "target": "threshold", "label": "保存",
         "status": "supported", "reason": "可见且正确"},
    ]


def test_relation_reuses_selected_evidence_source_refs(contract):
    report = compact(contract)
    relation = next(t for t in contract["targets"] if t["kind"] == "relation")
    evidence = next(e for e in contract["evidence"] if e.get("source_ref"))
    # Replace the default unspecified answer for this relation.
    report["items"] = [item for item in report["items"] if item["id"] != relation["id"]]
    report["items"].append({"id": relation["id"], "status": "ok", "reason": "屏幕可见",
                            "evidence_ids": [evidence["id"]], "panel_id": evidence["panel_id"]})
    expanded = expand_review(report, contract)
    canonical = expanded["relation_audit"][relation["id"].split(".", 1)[1]]
    assert canonical["source_ref"] == evidence["source_ref"]


def test_rejects_evidence_from_another_panel(contract):
    report = compact(contract)
    target = next(t for t in contract["targets"] if t["kind"] == "unit")
    foreign = next(e for e in contract["evidence"] if e["panel_id"] != target["panel_id"])
    next(i for i in report["items"] if i["id"] == target["id"])["evidence_ids"] = [foreign["id"]]
    with pytest.raises(ValueError, match="own panel"):
        expand_review(report, contract)


def test_model_receives_exact_local_evidence_and_note_choices(contract):
    assert set(contract['allowed_note_ids']) == {
        item['id'] for key in ('panels', 'targets', 'evidence') for item in contract[key]
    }
    for target in contract['targets']:
        if target.get('panel_id'):
            assert target['allowed_evidence_ids'] == [
                e['id'] for e in contract['evidence'] if e['panel_id'] == target['panel_id']
            ]
        elif target['kind'] == 'relation':
            assert target['allowed_evidence_ids'] == [e['id'] for e in contract['evidence']]


def test_prompt_distinguishes_answer_ids_and_requires_unit_proof():
    assert 'evidence_ids selects ONLY review_contract.evidence[].id' in COMPACT_RULES
    assert 'EVERY non-scene ok unit MUST include a nonempty evidence_ids list' in COMPACT_RULES


def test_edge_answer_cannot_be_reused_as_relation_evidence(contract):
    edge = next(t for t in contract['targets'] if t['kind'] == 'edge')
    report = compact(contract, {'relation.edge_meaning': {
        'status': 'ok', 'evidence_ids': [edge['id']]}})
    with pytest.raises(ValueError, match='unknown evidence ID'):
        expand_review(report, contract)


def test_unit_reason_does_not_replace_missing_visible_proof(contract):
    from textbook2video.research.visual_fact_audit import validate_fact_audit

    unit = next(t for t in contract['targets'] if t['kind'] == 'unit')
    report = compact(contract, {unit['id']: {'evidence_ids': []}})
    expanded = expand_review(report, contract)
    with pytest.raises(ValueError, match='visible proof must be exact text'):
        validate_fact_audit(expanded, build_review_targets(SPECS, NARRATION), SPECS)


def schema_reply(contract):
    report = compact(contract)
    report['scores'] = dict.fromkeys(('accuracy', 'relevance', 'readability', 'composition'), 4)
    report['checks'] = dict.fromkeys(('accuracy', 'relevance', 'completeness', 'readability'), True)
    report['notes'] = []
    return report


def test_existing_compact_schema_keeps_negative_judgments_and_scene_observation(contract):
    from jsonschema import Draft202012Validator

    schema = compact_response_format(contract, ['source-001'])['json_schema']['schema']
    Draft202012Validator.check_schema(schema)
    report = schema_reply(contract)
    report.update(verdict='REVISE', notes=[{'id': 'p1.t1', 'category': 'unreadable',
                                          'reason': 'Too small', 'change': 'Enlarge'}])
    report['checks']['readability'] = False
    report['items'][0].update(status='wrong', observation='Wrong subject visible')
    Draft202012Validator(schema).validate(report)


@pytest.mark.parametrize('mutation', ['reason', 'check', 'score', 'evidence', 'source', 'note'])
def test_transport_schema_rejects_known_missing_fields_and_wrong_id_namespaces(contract, mutation):
    from jsonschema import Draft202012Validator

    schema = compact_response_format(contract, ['source-001'])['json_schema']['schema']
    report = schema_reply(contract)
    if mutation == 'reason':
        report['items'][0].pop('reason')
    elif mutation == 'check':
        report['checks'].pop('completeness')
    elif mutation == 'score':
        report['scores'].pop('accuracy')
    elif mutation == 'evidence':
        report['items'][0]['evidence_ids'] = ['p1.e1']
    elif mutation == 'source':
        report['items'][0]['source_ids'] = ['source-999']
    else:
        report['notes'] = [{'id': 'p1', 'category': 'styling', 'reason': 'Defect'}]
    assert list(Draft202012Validator(schema).iter_errors(report))


def test_global_relation_preserves_separate_panel_evidence(contract):
    selected = [next(e for e in contract['evidence']
                     if e['panel_id'] == panel and e.get('source_ref'))['id']
                for panel in ('p1', 'p2')]
    report = compact(contract, {'relation.edge_meaning': {
        'status': 'ok', 'reason': '逐图检查全部连线', 'evidence_ids': selected}})
    result = expand_review(report, contract)['relation_audit']['edge_meaning']
    assert [g['visual_id'] for g in result['evidence_by_visual']] == ['sensor', 'threshold']
    assert result['evidence_by_visual'][0]['source_ref'] == ['src-sensor']
    assert result['evidence_by_visual'][1]['source_ref'] == ['src-threshold']


def test_invalid_panel_type_is_protocol_error_not_type_error(contract):
    report = compact(contract)
    relation = next(item for item in report['items'] if item['id'].startswith('relation.'))
    relation['panel_id'] = []
    with pytest.raises(ValueError, match='unknown panel ID'):
        expand_review(report, contract)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_rejects_incomplete_or_ambiguous_target_ids(contract, mutation):
    report = compact(contract)
    if mutation == "missing":
        report["items"].pop()
    elif mutation == "duplicate":
        report["items"].append(dict(report["items"][0]))
    else:
        report["items"][0]["id"] = "not-a-target"
    with pytest.raises(ValueError, match="each known target ID exactly once"):
        expand_review(report, contract)


def test_partial_keeps_known_negative_and_does_not_fabricate_missing_answers(contract):
    report = compact(contract)
    negative = report["items"][0]
    negative.update(status="wrong", reason="标签错误")
    report["items"] = [negative]
    expanded = expand_review(report, contract, partial=True)
    first_unit = expanded["fact_audit"]["panels"][0]["units"][0]
    assert first_unit["status"] == "incorrect"
    assert first_unit["reason"] == "标签错误"
    assert len(expanded["fact_audit"]["panels"][0]["units"]) == 1
    assert len(expanded["fact_audit"]["panels"][1]["units"]) == 0
