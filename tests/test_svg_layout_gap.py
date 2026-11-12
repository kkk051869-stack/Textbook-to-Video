"""SVG transparent padding is not drawn content; true close artwork still fails."""
import importlib.util
from pathlib import Path

import pytest

from textbook2video.animation_gen import build_slide_timelines, merge_html


def _layout_checker():
    spec = importlib.util.spec_from_file_location(
        'layout_gap_check', Path(__file__).resolve().parents[1] / 'scripts/check_layout.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('art_height,expected_failure', [(200, False), (500, True)])
def test_svg_gap_uses_drawn_bounds(tmp_path, art_height, expected_failure):
    module = _layout_checker()
    html = tmp_path / 'gap.html'
    html.write_text(
        '<style>body{margin:0}.slide{position:absolute;inset:0}</style>'
        '<div class="slide active"><svg width="800" height="500" viewBox="0 0 800 500">'
        f'<rect width="800" height="{art_height}" fill="blue"/></svg>'
        '<p style="margin:28px 0 0;font-size:24px">Visible supporting explanation</p></div>',
        encoding='utf-8')
    report = module.run_browser_check(html, 1600, 900, 0, 'msedge')
    failures = [issue for slide in report['slides'] for issue in slide['issues']
                if issue['type'] == 'visual_text_gap_too_small']
    assert bool(failures) == expected_failure


def test_layout_checks_late_highlight_without_moving_text(tmp_path):
    templates = Path(__file__).resolve().parents[1] / "src/textbook2video/templates"
    css = (templates / "base.css").read_text(encoding="utf-8")
    original = css.replace("    transform: none;\n    animation: eventHighlight", "    animation: eventHighlight")
    assert original != css
    slide = (
        '<div class="slide">'
        '<div class="anim anim-up" data-anim-id="list" '
        'style="position:absolute;top:200px;left:100px;font-size:20px">Practice list</div>'
        '<p style="position:absolute;top:241px;left:100px;margin:0;font-size:20px">Practice notes</p>'
        '</div>'
    )
    timelines = build_slide_timelines([{
        "id": 1, "audio_duration_sec": 8,
        "elements": [{"id": "list", "type": "text"}],
        "timeline": [
            {"target": "list", "action": "show", "effect": "fadeInUp", "at_sec": 0},
            {"target": "list", "action": "highlight", "effect": "highlight", "at_sec": 5},
        ],
    }])
    checker = _layout_checker()
    for name, framework in (("original", original), ("fixed", css)):
        html = tmp_path / f"{name}.html"
        html.write_text(merge_html(
            [slide], [], (templates / "base-template.html").read_text(encoding="utf-8"),
            framework, (templates / "slide-controller.js").read_text(encoding="utf-8"),
            "", [8000], "Layout check", timelines=timelines,
        ), encoding="utf-8")
        report = checker.run_browser_check(html, 1920, 1080, 2200, "msedge")["slides"][0]
        overlaps = [issue["time_ms"] for issue in report["issues"] if issue["type"] == "text_overlap"]
        assert overlaps == ([5001] if name == "original" else [])
