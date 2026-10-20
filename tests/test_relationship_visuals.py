from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET

import pytest

from textbook2video.research.relationship_visuals import (
    plan_relationship,
    render_relationship,
    validate_relationship,
)
from textbook2video.research.visual_synthesis import compile_visuals


def sample(layout="split_merge"):
    source = "已有0.5和0.3，合并为0.8，支付0.6，找零0.2。"
    nodes = [
        {"id": "a", "column": 0, "label": "输入甲", "value": "0.5 BTC"},
        {"id": "b", "column": 0, "label": "输入乙", "value": "0.3 BTC"},
        {"id": "c", "column": 1, "label": "合并输入", "value": "0.8 BTC"},
        {"id": "d", "column": 2, "label": "支付", "value": "0.6 BTC"},
        {"id": "e", "column": 2, "label": "找零", "value": "0.2 BTC", "accent": True},
    ]
    edges = [("a", "c"), ("b", "c"), ("c", "d"), ("c", "e")]
    if layout == "one_way":
        nodes = [nodes[0], nodes[2], nodes[3]]
        edges = [("a", "c"), ("c", "d")]
    if layout == "peer_network":
        nodes[1]["column"] = 1
        edges = [("a", "b"), ("a", "c"), ("b", "c"), ("b", "d"), ("c", "e")]
    for node in nodes:
        node["evidence"] = source
    return {
        "id": "example",
        "kind": "relationship",
        "title": "教学关系",
        "diagram": {
            "version": "teaching-relationship-v1",
            "layout": layout,
            "columns": ["输入", "处理", "输出"],
            "nodes": nodes,
            "edges": [{"source": a, "target": b} for a, b in edges],
        },
    }, source


@pytest.mark.parametrize("layout", ["peer_network", "split_merge", "one_way"])
def test_all_relationship_families_compile_preserving_nodes_and_edges(layout, tmp_path):
    spec, source = sample(layout)
    validate_relationship(spec, source)
    path = compile_visuals([spec], tmp_path / layout)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["assets"][0]["theme_id"] == "dark-blue-academic"
    svg = ET.fromstring((path.parent / "assets/example.svg").read_text(encoding="utf-8"))
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert len(svg.findall("s:g", ns)) == len(spec["diagram"]["nodes"])
    assert len(svg.findall("s:path", ns)) == len(spec["diagram"]["edges"])
    if layout == "split_merge":
        assert "0.6 BTC" in ET.tostring(svg, encoding="unicode")
        assert "0.2 BTC" in ET.tostring(svg, encoding="unicode")


@pytest.mark.parametrize(
    "problem", ["duplicate_id", "dangling_edge", "unconnected", "bad_quote", "bad_column"]
)
def test_bad_relationships_fail_closed(problem):
    spec, source = sample()
    diagram = spec["diagram"]
    if problem == "duplicate_id":
        diagram["nodes"][1]["id"] = "a"
    elif problem == "dangling_edge":
        diagram["edges"][0]["target"] = "missing"
    elif problem == "unconnected":
        diagram["edges"].pop()
    elif problem == "bad_quote":
        diagram["nodes"][0]["evidence"] = "教材没有说过的话"
    elif problem == "bad_column":
        diagram["nodes"][0]["column"] = True
    with pytest.raises(ValueError):
        validate_relationship(spec, source)


def test_theme_wrapping_and_xml_escaping():
    spec, _ = sample()
    spec["diagram"]["nodes"][0]["label"] = "包含中文和英文的较长教学输入标签"
    spec["diagram"]["nodes"][0]["detail"] = "<script> & 数据"
    dark = render_relationship(spec)
    bright = render_relationship(spec, theme_id="bright")
    assert dark != bright
    assert "<script>" not in dark
    assert "&lt;script&gt;" in dark
    svg = ET.fromstring(dark)
    texts = svg.findall(".//{http://www.w3.org/2000/svg}g")[0].findall(
        "{http://www.w3.org/2000/svg}text"
    )
    assert len(texts) >= 4


def test_overfull_column_requires_splitting_instead_of_truncating():
    spec, _ = sample("peer_network")
    extra = copy.deepcopy(spec["diagram"]["nodes"][1])
    extra["id"] = "extra"
    spec["diagram"]["nodes"].append(extra)
    spec["diagram"]["edges"].append({"source": "a", "target": "extra"})
    for node in spec["diagram"]["nodes"]:
        node["label"] = "较长的标签需要自动换行才能正确阅读"
        node["detail"] = "这段详细解释需要占用多行空间以验证高度限制"
    with pytest.raises(ValueError, match="budget"):
        render_relationship(spec)


def test_planner_preserves_raw_response_before_rejecting_bad_evidence(monkeypatch, tmp_path):
    spec, _ = sample()
    raw = json.dumps(spec, ensure_ascii=False)
    monkeypatch.setattr("textbook2video.llm.client.chat_with_system", lambda *a, **kw: raw)
    response = tmp_path / "raw.txt"
    with pytest.raises(ValueError, match="evidence"):
        plan_relationship("不同的原文", response_path=response)
    assert response.read_text(encoding="utf-8") == raw


def test_planner_rejects_drift_from_predeclared_layout(monkeypatch):
    spec, source = sample()
    monkeypatch.setattr(
        "textbook2video.llm.client.chat_with_system",
        lambda *a, **kw: json.dumps(spec, ensure_ascii=False),
    )
    with pytest.raises(ValueError, match="requested relationship layout"):
        plan_relationship(source, layout_hint="one_way")


def test_p0_auto_planner_accepts_relationship_without_legacy_items(tmp_path, monkeypatch):
    from textbook2video.research.auto_visual_plan import build_auto_visual_plan

    spec, source = sample()
    spec["proposition_id"] = "p1"
    graph = tmp_path / "graph.json"
    graph.write_text(
        json.dumps(
            {
                "narration_propositions": [
                    {"id": "p1", "segment_id": "s1", "text": source},
                ]
            }
        ),
        encoding="utf-8",
    )
    decisions = tmp_path / "decisions.json"
    decisions.write_text(
        json.dumps(
            {
                "decisions": [
                    {"narration_proposition_id": "p1", "action": "generate"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "textbook2video.research.auto_visual_plan.chat_with_system",
        lambda *a, **kw: json.dumps({"visuals": [spec]}, ensure_ascii=False),
    )
    result = build_auto_visual_plan(
        proposition_graph_path=graph,
        visual_decision_path=decisions,
        output_path=tmp_path / "plan.json",
    )
    plan = json.loads(result.read_text(encoding="utf-8"))
    assert plan["visuals"][0]["diagram"]["layout"] == "split_merge"
    manifest = compile_visuals(plan["visuals"], tmp_path / "compiled", theme_id="bright")
    assert json.loads(manifest.read_text(encoding="utf-8"))["assets"][0]["theme_id"] == "bright"


def test_same_column_edge_label_is_kept_outside_node_rectangles():
    spec, _ = sample("peer_network")
    peer_edge = next(e for e in spec["diagram"]["edges"] if e["source"] == "b")
    peer_edge["label"] = "比对副本"
    svg = ET.fromstring(render_relationship(spec))
    ns = {"s": "http://www.w3.org/2000/svg"}
    nodes = [g.find("s:rect", ns) for g in svg.findall("s:g", ns) if g.get("data-node-id")]
    for group in svg.findall("s:g", ns):
        if not group.get("data-edge-label"):
            continue
        for label in group.findall("s:text", ns):
            x, y = float(label.attrib["x"]), float(label.attrib["y"])
            for node in nodes:
                bx, by, w, h = (float(node.attrib[k]) for k in ("x", "y", "width", "height"))
                assert x + 90 <= bx or x >= bx + w or y + 6 <= by or y - 21 >= by + h


@pytest.mark.parametrize("value", ["12345678901234 BTC", "W" * 18])
def test_long_display_value_stays_inside_node_and_svg_in_browser(value):
    from playwright.sync_api import Error, sync_playwright

    spec, _ = sample("one_way")
    spec["diagram"]["nodes"][-1]["value"] = value
    spec["diagram"]["columns"][-1] = "较长的列标题也应换行而不能越过整个画布"
    svg = render_relationship(spec)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge", headless=True)
        except Error:
            pytest.skip("Microsoft Edge is unavailable")
        page = browser.new_page(viewport={"width": 1600, "height": 650})
        page.set_content("<style>body{margin:0}</style>" + svg)
        page.evaluate("document.fonts.ready")
        issues = page.evaluate("""() => {
            const issues=[];
            for(const text of document.querySelectorAll('svg text')) {
                const r=text.getBoundingClientRect();
                if(r.left<0||r.right>1600||r.top<0||r.bottom>650)
                    issues.push(text.textContent);
            }
            for(const node of document.querySelectorAll('[data-node-id]')) {
                const b=node.querySelector('rect').getBoundingClientRect();
                for(const text of node.querySelectorAll('text')) {
                    const r=text.getBoundingClientRect();
                    if(r.right>b.right||r.left<b.left||r.top<b.top||r.bottom>b.bottom
                        ||r.right>1600) issues.push(text.textContent);
                }
            }
            return issues;
        }""")
        browser.close()
    assert issues == []


def test_generated_prompt_cannot_supply_relationship_source_evidence(tmp_path, monkeypatch):
    from textbook2video.research.auto_visual_plan import build_auto_visual_plan

    spec, false_claim = sample()
    spec["proposition_id"] = "p1"
    graph = tmp_path / "graph.json"
    graph.write_text(
        json.dumps(
            {
                "narration_propositions": [
                    {"id": "p1", "segment_id": "s1", "text": "节点共同保存副本。"},
                ]
            }
        ),
        encoding="utf-8",
    )
    decisions = tmp_path / "decisions.json"
    decisions.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "narration_proposition_id": "p1",
                        "action": "generate",
                        "generation_prompt": false_claim,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "textbook2video.research.auto_visual_plan.chat_with_system",
        lambda *a, **kw: json.dumps({"visuals": [spec]}, ensure_ascii=False),
    )
    with pytest.raises(ValueError, match="evidence"):
        build_auto_visual_plan(
            proposition_graph_path=graph,
            visual_decision_path=decisions,
            output_path=tmp_path / "plan.json",
        )
    assert not (tmp_path / "plan.json").exists()
