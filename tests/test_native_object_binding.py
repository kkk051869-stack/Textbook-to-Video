from textbook2video.animation_ids import native_object_targets, resolve_element_targets
from textbook2video.variants import VARIANTS
from textbook2video.pipeline.course_binding import apply_course_bindings
from textbook2video.pipeline.timing import apply_timing


def test_all_table_variants_expose_semantic_rows_with_headers():
    e={'id':'table','type':'table','headers':['Input','Output'],'rows':[['a','b'],['c','d']]}
    targets=native_object_targets(e)
    assert targets['table--row-0']['description']=='Input: a; Output: b'
    for variant in VARIANTS['table']:
        html=variant.fn(e,'','1',set())
        assert all(html.count(f'data-anim-id="{target}"')==1 for target in targets)
    assert resolve_element_targets('table--row-1',[e])==['table--row-1']


def test_native_selections_replan_without_stale_bindings_and_keep_content():
    text='First action. Second action.'
    e={'id':'flow','type':'flow_step','steps':['First action','Second action']}
    board={'segments':[{'id':'s','narration':text,'audio_duration_sec':6,'elements':[e],
                        'timeline':[{'target':'flow','action':'show','at_sec':0}]}]}
    rows=[{'segment_id':'s','element_id':'flow','proposition_id':f'p{i}',
           'text':part,'span':{'start':a,'end':b},'focus_scope':'local',
           'result':{'status':'BOUND','selected_candidate_ids':[f'flow--step-{i}'],
                     'semantic_check':{'verdict':'SUFFICIENT'}}}
          for i,part,a,b in [(0,'First action.',0,13),(1,'Second action.',14,len(text))]]
    report={'method':'v1.3','results':rows}
    apply_course_bindings(board,report)
    apply_course_bindings(board,report)
    assert len(board['segments'][0]['course_visual_bindings'])==2
    cues=[{'text':'First action.','start_sec':0,'end_sec':3},
          {'text':'Second action.','start_sec':3,'end_sec':6}]
    timed=apply_timing(board,cues,timing_mode='semantic')
    assert timed['segments'][0]['elements']==[e]
    assert timed['segments'][0]['narration']==text
    focused=[e['target'] for e in timed['segments'][0]['timeline'] if e.get('action')=='focus']
    assert focused==['flow--step-0','flow--step-1']
    assert apply_timing(timed,cues,timing_mode='semantic')['segments']==timed['segments']
