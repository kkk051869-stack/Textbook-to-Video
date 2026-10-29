"""Hash-bound SVG nodes execute on the existing renderer/controller clock."""

import hashlib
from pathlib import Path

import pytest

from textbook2video.animation_gen import _inline_reviewed_visual_objects
from textbook2video.animation_ids import visual_node_animation_id
from textbook2video.pipeline.timing import apply_timing
from textbook2video.pipeline.visual_page_render import course_page_html


SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 350">
<defs><marker id="arrow"><path d="M0 0L8 4L0 8"/></marker></defs>
<g data-node-id="input"><rect x="80" y="120" width="220" height="100" fill="#247"/>
<text x="100" y="180" fill="white">传感器采集温度</text></g>
<path d="M300 170H480" stroke="white" marker-end="url(#arrow)"/>
<g data-node-id="output"><rect x="480" y="120" width="240" height="100" fill="#247"/>
<text x="500" y="180" fill="white">控制器保存阈值</text></g></svg>'''


def example(tmp_path):
    path = tmp_path / 'visual.svg'
    path.write_text(SVG, encoding='utf-8')
    targets = {visual_node_animation_id('diagram', node): {
        'node_id': node, 'description': text}
        for node, text in [('input', '传感器采集温度'), ('output', '控制器保存阈值')]}
    element = {'id': 'diagram', 'type': 'image', 'src': path.name,
               'description': '温度采集与阈值保存',
               'visual_asset_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
               'visual_object_targets': targets}
    segment = {'id': 's1', 'visual_type': 'image', 'audio_duration_sec': 4,
               'narration': '传感器采集温度。控制器保存阈值。',
               'elements': [{'id': 'heading', 'type': 'heading', 'text': '温度监测'}, element]}
    cues = [{'sentence_id': 'one', 'text': '传感器采集温度。', 'start_sec': 0, 'end_sec': 2},
            {'sentence_id': 'two', 'text': '控制器保存阈值。', 'start_sec': 2, 'end_sec': 4}]
    return path, element, segment, cues


def test_inline_svg_preserves_source_and_namespaces_marker_ids(tmp_path):
    path, element, _, _ = example(tmp_path)
    before = path.read_bytes()
    result = _inline_reviewed_visual_objects(path, element)
    for target in element['visual_object_targets']:
        assert f'data-anim-id="{target}"' in result
    assert f"url(#--diagram--{element['visual_asset_sha256'][:16]}--svg-arrow)" in result
    assert _inline_reviewed_visual_objects(path, element, scope='other-slide') != result
    assert path.read_bytes() == before
    path.write_text(SVG + ' ', encoding='utf-8')
    with pytest.raises(ValueError, match='exact compiled SVG hash'):
        _inline_reviewed_visual_objects(path, element)


@pytest.mark.parametrize('payload', [
    '<script>alert(1)</script>', '<foreignObject/>',
    '<g onclick="alert(1)"/>', '<path fill="URL(https://example.com/x)"/>',
    r'<path style="fill:u\72l(https://example.com/x.svg#x)"/>'])
def test_inline_svg_rejects_active_or_external_content(tmp_path, payload):
    path, element, _, _ = example(tmp_path)
    path.write_text(SVG.replace('</svg>', payload + '</svg>'), encoding='utf-8')
    element['visual_asset_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        _inline_reviewed_visual_objects(path, element)


def test_node_signals_reuse_measured_sentence_anchors_without_changing_narration(tmp_path):
    _, _, segment, cues = example(tmp_path)
    result = apply_timing({'segments': [segment]}, cues, timing_mode='semantic')['segments'][0]
    signals = result['visual_object_timing']['signals']
    assert len(signals) == 2
    assert [s['sentence_start_sec'] for s in signals] == [0, 2]
    assert {s['target'] for s in signals} == set(segment['elements'][1]['visual_object_targets'])
    assert all(s['action'] == 'focus' and s['trigger_source'] == 'text_match' for s in signals)
    assert result['narration'] == segment['narration']
    assert 'timeline' not in segment
    again = apply_timing({'segments': [result]}, cues, timing_mode='semantic')['segments'][0]
    assert len(again['visual_object_timing']['signals']) == 2
    assert len(again['timeline']) == len(result['timeline'])


def test_node_focus_never_finishes_behind_a_delayed_parent(tmp_path):
    _, _, segment, cues = example(tmp_path)
    segment['timeline'] = [
        {'target': 'diagram', 'action': 'show', 'effect': 'fadeIn',
         'start_ms': 3000, 'duration_ms': 200}]
    result = apply_timing({'segments': [segment]}, cues, timing_mode='semantic')['segments'][0]
    signals = result['visual_object_timing']['signals']
    assert all(s['trigger_at_sec'] >= 3.2 for s in signals)
    assert all(s['matched_sentence_id'] != 'one' for s in signals)
    assert len(signals) == 1
    assert signals[0]['trigger_at_sec'] + signals[0]['hold_sec'] <= 4


def test_real_browser_executes_node_focus_on_inline_svg(tmp_path):
    from playwright.sync_api import sync_playwright

    path, element, segment, _ = example(tmp_path)
    target = visual_node_animation_id('diagram', 'output')
    segment['timeline'] = [
        {'id': 'show-parent', 'target': 'diagram', 'action': 'show', 'effect': 'fadeIn',
         'start_ms': 0, 'duration_ms': 1},
        {'id': 'focus-node', 'target': target, 'action': 'focus', 'effect': 'fadeIn',
         'start_ms': 150, 'duration_ms': 0, 'hold_sec': 2},
    ]
    page_path = tmp_path/'runtime.html'
    page_path.write_text(course_page_html(segment, {'s1:diagram': str(path)},
                                         theme='dark-blue-academic', static=False), encoding='utf-8')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        try:
            page = browser.new_page(viewport={'width': 1600, 'height': 900})
            page.goto(page_path.resolve().as_uri())
            node = page.locator(f'[data-anim-id="{target}"]')
            assert node.count() == 1
            page.wait_for_function('''id => {
                const e = document.querySelector('[data-anim-id="'+id+'"]');
                return e && e.classList.contains('event-focus');
            }''', arg=target, timeout=5000)
            assert node.evaluate('e => getComputedStyle(e).opacity') == '1'
            assert node.evaluate('e => getComputedStyle(e).filter') != 'none'
            traces = page.evaluate('window.exportAnimationTrace()')
            assert any(t.get('target') == target and t.get('status') == 'executed'
                       for t in traces)
        finally:
            browser.close()
