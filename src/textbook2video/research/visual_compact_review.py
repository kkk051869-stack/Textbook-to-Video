"""Model judgments select executor-owned objects; they never retype graph structure."""

from copy import deepcopy

from textbook2video.research.visual_relation_semantics import RELATION_QUESTIONS

COMPACT_RULES = (
    'Return JSON {verdict:ACCEPT|REVISE|REJECT,scores:{accuracy:0..4,relevance:0..4,'
    'readability:0..4,composition:0..4},reason:"short overall reason",'
    'items:[{id,status,reason,panel_id?:ID,evidence_ids?:[ID],source_ids?:[source-ID]}],'
    'notes?:[{id,category,reason,change}]}. Answer EVERY review_contract.targets ID once. '
    'Do not repeat endpoints, labels, visual IDs, quotes, selectors, relation_audit or fact_audit. '
    'Unit statuses: ok|missing|wrong|unsupported; edge: ok|wrong|unsupported; '
    'relation: ok|missing|wrong|na|unspecified; coverage: covered|unsupported|irrelevant|missing. '
    'For ok unit and ok/wrong relation select evidence_ids from the same panel. '
    'For a panel-bound target use only its allowed_evidence_ids; never copy evidence '
    'from another panel. A global relation may cite several panels: omit panel_id and '
    'select evidence_ids from each; code retains separate per-visual evidence groups. '
    'Relation ok/wrong MUST include evidence_ids, not only a reason. '
    'Sources attached to evidence/targets are copied by code; provide source_ids only when '
    'additional source grounding is needed (especially a missing relation). '
    'For missing relation choose panel_id from review_contract.panels and source_ids. '
    'Use na only outside the FULL narration scope; unspecified only if SOURCE lacks that role. '
    'Unit unsupported means the source supports none of its facts; mixed units must retain '
    'all supported facts. For a scene, observation may replace evidence_ids. '
    'Use only review_contract.allowed_note_ids as notes.id; never use a raw node ID '
    'or visual_id as notes.id. '
    'notes may point to a panel, target or evidence ID; categories factual_error, missing_content, '
    'irrelevant_content, unreadable, spacing, color, hierarchy, styling. '
    'Judge actual screenshots, ALL supported facts in each assigned unit, and every edge\'s '
    'actual subject/action/object. A label property is not an action. Check explicit owners '
    'and referenced entities, not just similar vocabulary. No title/narration/hidden-text proof. '
    'Known content or readability defects require REVISE, even with high scores. '
    'Only source_text is factual authority: narration and old page elements may be unsupported. '
    'Check the full source-supported narration, including applications, and every replaced '
    'element; omit only unsupported details in a mixed claim. Never narrow scope to a title '
    'or diagram goal, invent missing mechanisms, or restore unsupported old steps. '
    'Cosmetic categories apply only when meaning, completeness and readability are intact. '
    'Do not assert human approval.'
)


def _list(value):
    return value if isinstance(value, list) else [value] if value is not None else []


def _citations(objects):
    refs, quotes = [], []
    for obj in objects:
        for ref in _list(obj.get('source_ref')):
            if ref not in refs:
                refs.append(ref)
        for quote in _list(obj.get('evidence', obj.get('source_evidence',
                                                     obj.get('constraint_evidence')))):
            if quote not in quotes:
                quotes.append(quote)
    if refs:
        return {'source_ref': refs}
    return {'source_evidence': quotes} if quotes else {}


def build_review_contract(specs, fact_targets, page_plan=None):
    panels, targets, evidence = [], [], []
    by_id = {spec['id']: spec for spec in specs}
    facts = (fact_targets or {}).get('panels', [])
    for index, spec in enumerate(specs, 1):
        pid = f'p{index}'
        panels.append({'id': pid, 'visual_id': spec['id']})
        graph = spec.get('diagram', spec) if spec.get('kind') == 'relationship' else spec
        objects = [obj for key in ('nodes', 'edges', 'series')
                   for obj in graph.get(key, []) if isinstance(obj, dict)]
        fact = next((p for p in facts if p['visual_id'] == spec['id']), None)
        texts = (fact or {}).get('visible_texts', []) + (fact or {}).get('retained_page_texts', [])
        for number, text in enumerate(dict.fromkeys(texts), 1):
            matched = [obj for obj in objects if text in (obj.get('label'), obj.get('detail'))]
            if text == graph.get('constraint'):
                matched.append({'source_ref': graph.get('constraint_source_ref'),
                                'evidence': graph.get('constraint_evidence')})
            item = {'id': f'{pid}.t{number}', 'panel_id': pid, 'text': text,
                    **_citations(matched or [spec])}
            if len(matched) == 1 and matched[0].get('id'):
                item['selector'] = {'visual_id': spec['id'], 'node_id': matched[0]['id']}
                item['field'] = 'label' if text == matched[0].get('label') else 'detail'
            evidence.append(item)
        if fact is None:
            continue
        for number, ref in enumerate(fact['narration_refs'], 1):
            unit = next(u for u in fact_targets['narration_units'] if u['id'] == ref)
            targets.append({'id': f'{pid}.u{number}', 'kind': 'unit', 'panel_id': pid,
                            'narration_ref': ref, 'text': unit['text']})
        for number, edge in enumerate(fact['edges'], 1):
            actual = [e for e in graph.get('edges', [])
                      if e.get('source') == edge['source'] and e.get('target') == edge['target']]
            targets.append({'id': f'{pid}.e{number}', 'kind': 'edge', 'panel_id': pid,
                            'edge': deepcopy(edge), **_citations(actual)})
    for key, question in RELATION_QUESTIONS.items():
        targets.append({'id': f'relation.{key}', 'kind': 'relation', 'question': question})
    for item in (page_plan or {}).get('coverage', []):
        targets.append({'id': f'coverage.{item["element_id"]}', 'kind': 'coverage',
                        'element_id': item['element_id'], 'proof': deepcopy(item)})
    for target in targets:
        if target.get('panel_id'):
            target['allowed_evidence_ids'] = [item['id'] for item in evidence
                                              if item['panel_id'] == target['panel_id']]
    return {'panels': panels, 'targets': targets, 'evidence': evidence,
            'allowed_note_ids': [item['id'] for item in [*panels, *targets, *evidence]],
            'scene_panels': [p['id'] for p in panels if by_id[p['visual_id']]['kind'] == 'scene']}


def expand_review(report, contract, *, partial=False):
    """Expand selected IDs to canonical audits, preserving the raw reply separately."""
    if 'items' not in report:
        return deepcopy(report)  # Legacy/manual API remains valid under existing validators.
    targets = {item['id']: item for item in contract['targets']}
    evidence = {item['id']: item for item in contract['evidence']}
    panels = {p['id']: p['visual_id'] for p in contract['panels']}
    items = report['items']
    if not isinstance(items, list):
        raise ValueError('compact review items must be a list')
    if partial:
        items = [item for item in items if isinstance(item, dict)
                 and isinstance(item.get('id'), str) and item['id'] in targets]
    ids = [item.get('id') for item in items if isinstance(item, dict)]
    if (len(ids) != len(items) or any(not isinstance(i, str) for i in ids)
            or (not partial and len(set(ids)) != len(ids)) or set(ids) - set(targets)
            or (not partial and set(ids) != set(targets))):
        raise ValueError('compact review must answer each known target ID exactly once')
    rewritten = {'items', 'notes', 'relation_audit', 'fact_audit', 'coverage', 'issues'}
    result = {key: deepcopy(value) for key, value in report.items() if key not in rewritten}
    result.update(relation_audit={}, fact_audit={'panels': []}, coverage=[], issues=[])
    result.setdefault('checks', dict.fromkeys(
        ('accuracy', 'relevance', 'completeness', 'readability'), True))
    scoped = {pid: {'visual_id': visual, 'units': [], 'edges': []}
              for pid, visual in panels.items()
              if any(t.get('panel_id') == pid for t in targets.values())}
    statuses = {
        'unit': {'ok': 'visible', 'missing': 'missing', 'wrong': 'incorrect',
                 'unsupported': 'unsupported'},
        'edge': {'ok': 'supported', 'wrong': 'incorrect', 'unsupported': 'unsupported'},
        'relation': {'ok': 'visible', 'missing': 'missing', 'wrong': 'incorrect',
                     'na': 'not_applicable', 'unspecified': 'not_specified'},
        'coverage': {x: x for x in ('covered', 'missing', 'unsupported', 'irrelevant')},
    }
    for item in items:
        target = targets[item['id']]
        kind, status = target['kind'], item.get('status')
        if not isinstance(status, str) or status not in statuses[kind]:
            if partial:
                continue
            raise ValueError(f'compact review {item["id"]}: invalid status')
        if partial and kind != 'coverage' and status not in {'missing', 'wrong', 'unsupported'}:
            continue
        reason = item.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            if not partial:
                raise ValueError('compact review requires a short reason per item')
            reason = 'Negative judgment retained pending protocol completion'
        selected = item.get('evidence_ids', [])
        if partial:
            selected = [i for i in (selected if isinstance(selected, list) else [])
                        if isinstance(i, str) and i in evidence]
        if (not isinstance(selected, list) or any(not isinstance(i, str) or i not in evidence
                                                 for i in selected)):
            raise ValueError('compact review contains unknown evidence ID')
        selected = [evidence[i] for i in selected]
        pid = target.get('panel_id') or item.get('panel_id')
        if pid is not None and not isinstance(pid, str):
            if not partial:
                raise ValueError('compact review contains unknown panel ID')
            pid = None
        selected_panels = {e['panel_id'] for e in selected}
        if pid is None and len(selected_panels) == 1:
            pid = next(iter(selected_panels))
        global_relation = kind == 'relation' and pid is None and len(selected_panels) > 1
        if selected_panels and selected_panels != {pid} and not global_relation:
            if partial:
                selected = []
            else:
                raise ValueError('compact review evidence must belong to its own panel')
        if pid is not None and (not isinstance(pid, str) or pid not in panels):
            if partial:
                pid = None
            else:
                raise ValueError('compact review contains unknown panel ID')
        value = {'status': statuses[kind][status], 'reason': reason}
        if kind == 'unit':
            value.update(narration_ref=target['narration_ref'],
                         visible_evidence=[e['text'] for e in selected])
            if pid in contract['scene_panels'] and isinstance(item.get('observation'), str):
                value['visible_evidence'] = [item['observation']]
            scoped[pid]['units'].append(value)
        elif kind == 'edge':
            scoped[pid]['edges'].append({**target['edge'], **value})
        elif kind == 'relation':
            if pid is not None:
                value['visual_id'] = panels[pid]
            value['visible_evidence'] = [e['text'] for e in selected]
            value.update(_citations(selected))
            if 'source_ids' in item:
                value.pop('source_evidence', None)
                value['source_ref'] = deepcopy(item['source_ids'])
            if global_relation:
                value['evidence_by_visual'] = [
                    {'visual_id': panels[panel],
                     'visible_evidence': [e['text'] for e in selected if e['panel_id'] == panel],
                     **_citations([e for e in selected if e['panel_id'] == panel])}
                    for panel in panels if panel in selected_panels
                ]
            result['relation_audit'][target['id'].split('.', 1)[1]] = value
        else:
            result['coverage'].append({'element_id': target['element_id'],
                                       'verdict': value['status'], 'reason': reason})
    result['fact_audit']['panels'] = list(scoped.values())
    locations = {**{p['id']: p for p in contract['panels']}, **targets, **evidence}
    notes = report.get('notes', [])
    if not isinstance(notes, list):
        if partial:
            return result
        raise ValueError('compact review notes must be a list')
    for note in notes:
        if (not isinstance(note, dict) or not isinstance(note.get('id'), str)
                or note['id'] not in locations):
            if partial:
                continue
            raise ValueError('compact review note requires an existing target ID')
        location = locations[note['id']]
        pid = location.get('panel_id', note['id'] if note['id'] in panels else None)
        selector = location.get('selector')
        issue = note.get('reason', '')
        if location.get('field') in {'label', 'detail'}:
            issue = f"node {location['field']} '{location['text']}': {issue}"
        if location.get('kind') == 'edge':
            selector = {'visual_id': panels[pid], 'edge': {
                k: location['edge'][k] for k in ('source', 'target')}}
            if location['edge'].get('label'):
                issue = f"edge label '{location['edge']['label']}': {issue}"
        result['issues'].append({
            'visual_id': panels.get(pid, ''), 'category': note.get('category', 'unknown'),
            'issue': issue, 'change': note.get('change', note.get('reason', '')),
            **({'target_selector': deepcopy(selector)} if selector else {}),
        })
    return result
