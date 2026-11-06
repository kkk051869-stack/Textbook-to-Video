"""SVG transparent padding is not drawn content; true close artwork still fails."""
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize('art_height,expected_failure', [(200, False), (500, True)])
def test_svg_gap_uses_drawn_bounds(tmp_path, art_height, expected_failure):
    spec = importlib.util.spec_from_file_location(
        'layout_gap_check', Path(__file__).resolve().parents[1] / 'scripts/check_layout.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
