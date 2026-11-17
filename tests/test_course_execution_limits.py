import json

from textbook2video.pipeline import course_visuals
from textbook2video.pipeline.timing import _apply_course_binding_timing


def test_all_seven_generate_tasks_are_attempted_without_retries(tmp_path, monkeypatch):
    def save(name, data):
        p = tmp_path / name
        p.write_text(json.dumps(data), encoding='utf-8')
        return p
    board = save('board.json', {'segments': [{'id': 's', 'elements': [], 'narration': 'Input becomes output.'}]})
    source = tmp_path / 'source.txt'
    source.write_text('Input becomes output.', encoding='utf-8')
    props = [{'id': f'p{i}', 'segment_id': 's', 'text': 'Input becomes output.'} for i in range(7)]
    graph = save('graph.json', {'narration_propositions': props})
    decisions = [{'narration_proposition_id': p['id'], 'action': 'generate',
                  'decision_state': 'DECIDED', 'abstain': False, 'uncertain': False} for p in props]
    path = save('decisions.json', {'decisions': decisions})
    selection = {'pages': {'s': {'assets': [], 'decisions': decisions}}}
    calls = []
    monkeypatch.setenv('T2V_VISUAL_AGENT_MAX_ITERATIONS', '3')
    monkeypatch.setattr(course_visuals, '_measure_generation_capacity', lambda *a, **kw: {})
    def failed_agent(*a, **kw):
        calls.append(kw['max_iterations'])
        raise ValueError('offline synthetic compile failure')
    monkeypatch.setattr(course_visuals, 'run_visual_agent', failed_agent)
    course_visuals._materialize_decided_visuals(selection=selection, storyboard_path=board,
        source_path=source, graph_path=graph, decisions_path=path, output_dir=tmp_path,
        model='offline', review_model='offline', max_generated_visuals=0)
    assert calls == [3] * 7
    assert selection['generated_visual_budget']['deferred_proposition_ids'] == []
    assert selection['generated_visual_budget']['unlimited_tasks'] is True


def test_production_focus_budget_and_duration_respect_measured_windows(monkeypatch):
    monkeypatch.setenv('T2V_MIN_FOCUS_BUDGET_PER_SEGMENT', '3')
    monkeypatch.setenv('T2V_MAX_FOCUS_DURATION_SEC', '4')
    sentences = ['First input.', 'Second input.', 'Final output.']
    text = ' '.join(sentences)
    bindings = []
    for i, sentence in enumerate(sentences):
        a = text.index(sentence)
        bindings.append({'proposition_id': f'p{i}', 'parent_id': 'figure', 'text': sentence,
                         'span': {'start': a, 'end': a + len(sentence)}, 'targets': [f'n{i}']})
    segment = {'id': 's', 'narration': text, 'audio_duration_sec': 14,
               'elements': [{'id': 'figure', 'type': 'image'}],
               'timeline': [{'target': 'figure', 'action': 'show', 'at_sec': 0}],
               'course_visual_bindings': bindings}
    cues = [{'text': sentence, 'start_sec': i * 5, 'end_sec': min(14, (i + 1) * 5)}
            for i, sentence in enumerate(sentences)]
    _apply_course_binding_timing(segment, cues)
    events = [e for e in segment['course_dynamic_plan']['events'] if e['action'] == 'focus']
    assert [e['target_element_id'] for e in events] == ['n0', 'n1', 'n2']
    assert all(e['duration_sec'] == 4 for e in events)
    assert all(e['at_sec'] + e['duration_sec'] <= cue['end_sec'] for e, cue in zip(events, cues))

def test_production_binding_receives_three_repair_rounds_and_300_seconds(tmp_path, monkeypatch):
    from textbook2video.pipeline import course_binding
    monkeypatch.setenv('T2V_RQ2_MAX_REPAIR_ROUNDS', '3')
    monkeypatch.setenv('T2V_RQ2_REPAIR_DEADLINE_SEC', '300')
    evidence = tmp_path / 'evidence.json'
    evidence.write_text(json.dumps({'source_units': [{'id': 'u', 'text': 'Input becomes output.'}]}))
    graph = tmp_path / 'graph.json'
    graph.write_text(json.dumps({'source_evidence_path': str(evidence), 'narration_propositions': [
        {'id': 'p', 'segment_id': 's', 'text': 'Input becomes output.',
         'span': {'start': 0, 'end': 21}, 'source_refs': ['u']}]}))
    board = {'segments': [{'id': 's', 'narration': 'Input becomes output.',
                          'elements': [{'id': 'e', 'type': 'flow_step', 'steps': []}]}]}
    monkeypatch.setattr(course_binding, '_object_evidence',
                        lambda *a, **kw: ([{'id': 'e', 'local_path': 'offline.png'}], {}))
    calls = []
    def bind(*a, **kw):
        calls.append(kw)
        return {'status': 'ABSTAINED', 'selected_candidate_ids': []}
    monkeypatch.setattr(course_binding, 'bind_source_conditioned', bind)
    report = course_binding.bind_course_visuals(board, graph, tmp_path, tmp_path / 'audit',
                                               review_model='offline', browser=None)
    assert len(calls) == 1
    assert calls[0]['max_repair_rounds'] == report['max_repair_rounds'] == 3
    assert calls[0]['repair_deadline_sec'] == report['repair_deadline_sec'] == 300
