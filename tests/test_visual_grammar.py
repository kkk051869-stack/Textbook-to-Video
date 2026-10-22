from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from textbook2video.research.visual_grammar import GRAMMAR_VERSION, KINDS, render_visual


def specimen(kind):
    spec = {
        "id": "diagram",
        "schema_version": GRAMMAR_VERSION,
        "kind": kind,
        "title": "教学示例",
        "teaching_goal": "理解关系而非记忆孤立标签",
    }
    nodes = [
        {"id": f"n{i}", "label": text, "evidence": "教学来源"}
        for i, text in enumerate(["输入", "处理", "输出"])
    ]
    edges = [
        {"source": "n0", "target": "n1", "evidence": "教学来源"},
        {"source": "n1", "target": "n2", "evidence": "教学来源"},
    ]
    if kind in {"flow", "hierarchy", "network", "timeline", "cycle", "causal", "part_whole"}:
        if kind == "cycle":
            edges.append({"source": "n2", "target": "n0", "evidence": "教学来源"})
        spec.update(nodes=nodes, edges=edges)
    elif kind == "comparison":
        spec.update(nodes=nodes[:2], edges=[])
    elif kind in {"chart", "proportion"}:
        spec.update(
            series=[
                {"label": "甲", "value": 3, "evidence": "教学来源"},
                {"label": "乙", "value": 2, "evidence": "教学来源"},
            ],
            unit="件",
        )
    elif kind == "table":
        spec.update(rows=[["类别", "特征"], ["甲", "示例"]], evidence="教学来源")
    else:
        spec.update(content="x = 1\n    y = x + 2", evidence="教学来源")
    return spec


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("theme", ["bright", "dark-blue-academic", "3b1b-math"])
def test_all_general_kinds_are_well_formed_and_inherit_theme(kind, theme):
    svg = ET.fromstring(render_visual(specimen(kind), theme_id=theme))
    assert svg.get("data-theme") == theme
    assert svg.get("data-renderer") == GRAMMAR_VERSION
    assert svg.get("viewBox") == "0 0 1600 680"
    if kind in {"code", "formula"}:
        lines = svg.findall("{http://www.w3.org/2000/svg}text")
        assert [t.text for t in lines] == ["x = 1", "    y = x + 2"]


def test_final_course_surface_has_minimum_size_with_real_css_in_both_viewports(tmp_path):
    from playwright.sync_api import sync_playwright

    from textbook2video.pipeline.visual_page_render import course_page_html

    segment = {
        "id": 1,
        "visual_type": "illustration",
        "narration": "教学来源",
        "visual_page_plan": {"primary_visual_id": "main"},
        "elements": [
            {"id": "heading", "type": "heading", "text": "教学关系"},
            {
                "id": "main",
                "type": "image",
                "description": "教学关系图",
                "visual_brief_role": "EXPLANATORY_DIAGRAM",
                "visual_tools_run": "development-run.json",
            },
            {
                "id": "support",
                "type": "quote",
                "text": "由多个参与者共同维护，每个参与者持有一份完整的账本副本。",
            },
        ],
    }
    asset = tmp_path / "flow.svg"
    asset.write_text(render_visual(specimen("flow")), encoding="utf-8")
    markup = course_page_html(segment, {"1:main": str(asset)}, theme="dark-blue-academic")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            for width, height in ((1600, 900), (1366, 768)):
                page.set_viewport_size({"width": width, "height": height})
                page.set_content(markup)
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                assert page.evaluate("typeof window.__fitAll") == "function"
                bounds = page.locator(".t2v-image-surface img").bounding_box()
                assert bounds["width"] >= 780
                assert bounds["height"] >= 480
                assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height
                content = page.locator(".t2v-content-box").bounding_box()
                assert bounds["y"] >= content["y"] - 1
                assert bounds["y"] + bounds["height"] <= content["y"] + content["height"] + 1
        finally:
            browser.close()
