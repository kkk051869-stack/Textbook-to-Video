from __future__ import annotations

import itertools
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from textbook2video.research.visual_grammar import render_visual
from textbook2video.research.visual_graph_layout import (
    bridge_path,
    intersection,
    layered_positions,
    line_hits_box,
    network_positions,
    overlaps,
)

NS = {"s": "http://www.w3.org/2000/svg"}


def test_layered_layout_reorders_crossed_input_lanes_without_new_edges():
    nodes = [{"id": ident} for ident in ("a", "b", "c", "d")]
    edges = [{"source": "a", "target": "d"}, {"source": "b", "target": "c"}]
    positions = layered_positions(nodes, edges, {"a": 0, "b": 0, "c": 1, "d": 1})
    assert intersection(positions["a"], positions["d"], positions["b"], positions["c"]) is None
    assert positions["a"][1] == positions["d"][1]
    assert positions["b"][1] == positions["c"][1]


def communication_spec():
    source = "甲、乙、丙相互通信，并均向网关提交状态。"
    return {
        "id": "network",
        "schema_version": "teaching-visual-v2",
        "kind": "network",
        "title": "通信与状态汇聚",
        "teaching_goal": "区分对等通信与状态汇聚",
        "nodes": [
            {"id": ident, "label": label, "detail": "保有本地状态", "evidence": source}
            for ident, label in (("a", "甲"), ("b", "乙"), ("c", "丙"), ("hub", "网关"))
        ],
        "edges": [
            {"source": a, "target": b, "label": "相互通信", "directed": False, "evidence": source}
            for a, b in itertools.combinations(("a", "b", "c"), 2)
        ]
        + [
            {
                "source": a,
                "target": "hub",
                "label": "提交状态",
                "directed": True,
                "evidence": source,
            }
            for a in ("a", "b", "c")
        ],
    }


def test_k4_placement_removes_crossing_without_changing_topology():
    spec = communication_spec()
    before = deepcopy(spec)
    positions = network_positions(spec["nodes"], spec["edges"])
    assert positions["hub"] == (800, 340)
    for e, f in itertools.combinations(spec["edges"], 2):
        if {e["source"], e["target"]} & {f["source"], f["target"]}:
            continue
        assert (
            intersection(
                positions[e["source"]],
                positions[e["target"]],
                positions[f["source"]],
                positions[f["target"]],
            )
            is None
        )
    svg = ET.fromstring(render_visual(spec))
    assert len(svg.findall("s:path[@data-edge]", NS)) == 6
    assert spec == before
    assert network_positions(spec["nodes"], spec["edges"]) == positions


def test_equal_peers_do_not_gain_a_false_central_manager():
    spec = communication_spec()
    for edge in spec["edges"]:
        edge["directed"] = False
    assert (800, 340) not in network_positions(spec["nodes"], spec["edges"]).values()


def test_cycle_layout_uses_successors_not_input_array_order():
    spec = communication_spec()
    spec["kind"] = "cycle"
    spec["edges"] = [
        {"source": a, "target": b, "evidence": "教学来源"}
        for a, b in (("a", "c"), ("c", "b"), ("b", "hub"), ("hub", "a"))
    ]
    svg = ET.fromstring(render_visual(spec))
    boxes = {
        group.get("data-node-id"): group.find("s:rect", NS)
        for group in svg.findall("s:g[@data-node-id]", NS)
    }
    assert float(boxes["c"].get("x")) > float(boxes["b"].get("x"))
    assert float(boxes["b"].get("y")) > float(boxes["c"].get("y"))


def test_short_node_labels_are_centered_not_top_aligned():
    spec = communication_spec()
    for node in spec["nodes"]:
        node.pop("detail")
    svg = ET.fromstring(render_visual(spec))
    for group in svg.findall("s:g[@data-node-id]", NS):
        rectangle, label = group.find("s:rect", NS), group.find("s:text", NS)
        assert float(rectangle.get("height")) == 80
        assert label.get("text-anchor") == "middle"
        assert float(label.get("y")) - float(rectangle.get("y")) < 55


def test_edge_labels_do_not_cover_other_labels_nodes_or_unrelated_lines():
    svg = ET.fromstring(render_visual(communication_spec()))
    node_boxes = [
        tuple(float(rect.get(k)) for k in ("x", "y", "width", "height"))
        for rect in svg.findall("s:g[@data-node-id]/s:rect", NS)
    ]
    labels = []
    for group in svg.findall("s:g[@data-edge-label]", NS):
        rect = group.find("s:rect", NS)
        box = tuple(float(rect.get(k)) for k in ("x", "y", "width", "height"))
        assert not any(overlaps(box, other) for other in node_boxes + labels)
        labels.append(box)
    assert len(labels) == 6
    for path in svg.findall("s:path[@data-edge]", NS):
        points = path.get("d").replace("M", "").replace("L", " ").split()
        start, end = (tuple(float(v) for v in point.split(",")) for point in points)
        own = path.get("data-edge")
        for group, box in zip(svg.findall("s:g[@data-edge-label]", NS), labels, strict=True):
            if group.get("data-edge-label") != own:
                assert not line_hits_box(start, end, box)


@pytest.mark.parametrize(
    "a,b,box,expected",
    [
        ((0, 0), (10, 10), (4, 4, 2, 2), True),
        ((0, 0), (10, 0), (4, 4, 2, 2), False),
        ((4.5, 4.5), (5, 5), (4, 4, 2, 2), True),
        ((0, 5), (10, 5), (4, 4, 2, 2), True),
    ],
)
def test_segment_box_intersections(a, b, box, expected):
    assert line_hits_box(a, b, box) is expected


def test_unavoidable_crossing_is_rendered_as_overpass_not_junction():
    assert "Q" in bridge_path((0, 100), (200, 100), [((100, 0), (100, 200))])
    assert "Q" not in bridge_path((0, 0), (200, 0), [((200, 0), (200, 200))])


def routing_spec(kind, ids, pairs):
    return {
        "schema_version": "teaching-visual-v2",
        "kind": kind,
        "title": "路由反例",
        "teaching_goal": "保持不同关系可区分",
        "nodes": [{"id": ident, "label": ident, "evidence": "教学来源"} for ident in ids],
        "edges": [{"source": a, "target": b, "evidence": "教学来源"} for a, b in pairs],
    }


def test_crossing_lower_path_has_real_transparent_gap_mask():
    spec = routing_spec("causal", "abcd", ["ac", "ad", "bc", "bd"])
    svg = ET.fromstring(render_visual(spec))
    masks = svg.findall("s:defs/s:mask", NS)
    assert masks and any(mask.findall("s:circle", NS) for mask in masks)
    masked = [p for p in svg.findall("s:path[@data-edge]", NS) if p.get("mask")]
    assert masked
    assert all(mask.find("s:rect", NS).get("fill") == "white" for mask in masks)
    assert all(
        circle.get("fill") == "black" for mask in masks for circle in mask.findall("s:circle", NS)
    )


def test_browser_actual_routed_paths_avoid_nodes_and_labels():
    from playwright.sync_api import sync_playwright

    cases = [
        routing_spec("causal", "abc", ["ab", "bc", "ac"]),
        routing_spec("causal", "abcd", ["ac", "ad", "bc", "bd"]),
    ]
    dense = routing_spec(
        "network",
        "abcdefg",
        ["bf", "fg", "ae", "cg", "bg", "bc", "be", "ag", "df", "ce", "ac", "cd"],
    )
    for node in dense["nodes"]:
        node["detail"] = {"b": "long detail of node", "c": "测试说明文字较长"}.get(node["id"], "")
    dense["edges"][5]["label"] = "edge"
    cases.append(dense)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            for spec in cases:
                page.set_content(render_visual(spec))
                issues = page.evaluate("""() => {
                    const nodes=[...document.querySelectorAll('[data-node-id]')].map(g=>({
                        id:g.dataset.nodeId, b:g.querySelector('rect').getBBox()}));
                    const labels=[...document.querySelectorAll('[data-edge-label]')].map(g=>({
                        id:g.dataset.edgeLabel, b:g.querySelector('rect').getBBox()}));
                    const issues=[];
                    for(const path of document.querySelectorAll('path[data-edge]')){
                        const ends=path.dataset.edge.split(':'), length=path.getTotalLength();
                        for(let t=0;t<=length;t+=1){
                            const p=path.getPointAtLength(t);
                            const inside=b=>p.x>b.x+.75&&p.x<b.x+b.width-.75&&
                                             p.y>b.y+.75&&p.y<b.y+b.height-.75;
                            for(const n of nodes)if(!ends.includes(n.id)&&inside(n.b))
                                issues.push({edge:path.dataset.edge,node:n.id});
                            for(const label of labels)
                                if(label.id!==path.dataset.edge&&inside(label.b))
                                    issues.push({edge:path.dataset.edge,label:label.id});
                        }
                    }
                    return issues;
                }""")
                assert not issues, issues[:5]
        finally:
            browser.close()
