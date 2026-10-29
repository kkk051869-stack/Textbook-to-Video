import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_grammar import render_visual
from textbook2video.research.visual_graph_layout import layered_positions, overlaps
from textbook2video.research.visual_interface import materialize_layout

SOURCE = "输入经过处理，生成输出并验证。"


def dag():
    pairs = [("a", "b"), ("b", "c"), ("c", "d"), ("c", "e"), ("d", "f"), ("e", "f")]
    return {
        "id": "dag",
        "schema_version": "teaching-visual-v2",
        "kind": "flow",
        "title": "五层关系",
        "teaching_goal": "保持显式关系",
        "layout_direction": "auto",
        "nodes": [
            {
                "id": ident,
                "label": f"节点{ident}",
                "detail": "输入微小变动\n导致输出显著变化",
                "evidence": SOURCE,
            }
            for ident in "abcdef"
        ],
        "edges": [
            {"source": a, "target": b, "label": "关系", "evidence": SOURCE} for a, b in pairs
        ],
    }


def test_auto_dag_keeps_all_semantics_and_readable_type_without_overlap():
    spec = dag()
    before = deepcopy(spec)
    svg = ET.fromstring(render_visual(spec))
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert svg.get("data-auto-layout") in {"grid2", "grid3"}
    assert spec == before
    assert {p.get("data-edge") for p in svg.findall("s:path[@data-edge]", ns)} == {
        f"{e['source']}:{e['target']}" for e in spec["edges"]
    }
    boxes = []
    for group in svg.findall("s:g[@data-node-id]", ns):
        rect = group.find("s:rect", ns)
        box = tuple(float(rect.get(k)) for k in ("x", "y", "width", "height"))
        x, y, width, height = box
        assert 10 <= x and x + width <= 1590 and 10 <= y and y + height <= 670
        boxes.append(box)
        assert min(float(t.get("font-size")) for t in group.findall("s:text", ns)) >= 24
    assert len(boxes) == 6
    assert not any(overlaps(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])


def test_auto_does_not_relax_manual_stage_limit_or_silently_shrink_text():
    spec = dag()
    with pytest.raises(ValueError, match="four relationship stages"):
        render_visual({**spec, "layout_direction": "horizontal"})
    for node in spec["nodes"]:
        node.update(label="宽" * 48, detail="长" * 96)
    with pytest.raises(ValueError, match="auto geometry could not fit"):
        render_visual(spec)


def test_auto_fits_complete_multiline_nodes_with_bounded_body_font():
    spec = dag()
    spec.update(nodes=spec["nodes"][:3], edges=spec["edges"][:2], text_scale=1.5)
    spec["nodes"][1]["detail"] = "基础信息：\n上一区块哈希\n随机数\n交易执行记录"
    before = deepcopy(spec)
    with pytest.raises(ValueError, match="node text needs a separate panel"):
        render_visual({**spec, "layout_direction": "horizontal"})
    svg = ET.fromstring(render_visual(spec))
    ns = {"s": "http://www.w3.org/2000/svg"}
    boxes = []
    for group in svg.findall("s:g[@data-node-id]", ns):
        rect = group.find("s:rect", ns)
        x, y, w, h = (float(rect.get(k)) for k in ("x", "y", "width", "height"))
        assert 10 <= x and x + w <= 1590 and 10 <= y and y + h <= 670
        # The approved body policy is 24 -> 23 -> 22 times text_scale;
        # titles stay at 29 times text_scale and short bodies do not shrink.
        body_size = float(group.get("data-detail-font-size"))
        assert body_size in {33, 34.5, 36}
        texts = group.findall("s:text", ns)
        assert float(texts[0].get("font-size")) == 43.5
        assert min(float(t.get("font-size")) for t in texts) == body_size
        if group.get("data-node-id") != "b":
            assert body_size == 36
        else:
            assert body_size < 36
        boxes.append((x, y, w, h))
        if group.get("data-node-id") == "b":
            assert h > 247.5
            for original_line in spec["nodes"][1]["detail"].splitlines():
                assert original_line in "".join(group.itertext())
    assert not any(overlaps(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    assert spec == before


def test_horizontal_auto_column_uses_measured_heights_and_rejects_overfull_column():
    nodes = [{"id": ident} for ident in "abc"]
    edges = [{"source": "a", "target": ident} for ident in "bc"]
    ranks = {"a": 0, "b": 1, "c": 1}
    dimensions = {ident: (310, 280) for ident in "abc"}
    placed = layered_positions(nodes, edges, ranks, dimensions=dimensions, adaptive_height=True)
    assert placed["c"][1] - placed["b"][1] >= 280 + 50
    dimensions.update(b=(310, 300), c=(310, 300))
    with pytest.raises(ValueError, match="measured layer heights"):
        layered_positions(nodes, edges, ranks, dimensions=dimensions, adaptive_height=True)


def test_new_candidate_defaults_to_auto_but_explicit_manual_layout_is_preserved():
    spec = dag()
    spec.pop("layout_direction")
    original = deepcopy(spec)
    normalized, changes = materialize_layout({"visuals": [spec]})
    result = normalized["visuals"][0]
    assert spec == original
    assert result == {**original, "layout_direction": "auto"}
    assert changes
    assert "data-auto-layout" in render_visual(result)
    explicit, _ = materialize_layout({"visuals": [{**spec, "layout_direction": "horizontal"}]})
    with pytest.raises(ValueError, match="four relationship stages"):
        render_visual(explicit["visuals"][0])


def test_executor_layout_policy_preserves_semantics_and_audits_model_proposal(tmp_path):
    wrapped = {"visuals": [{**dag(), "layout_direction": "wrapped"}]}
    before = deepcopy(wrapped)
    horizontal = deepcopy(wrapped)
    horizontal["visuals"][0]["layout_direction"] = "horizontal"
    effective, changes = materialize_layout(wrapped, automatic_layout=True)
    other, _ = materialize_layout(horizontal, automatic_layout=True)
    assert effective == other
    assert effective["visuals"][0] == {**wrapped["visuals"][0], "layout_direction": "auto"}
    assert any("proposed direction='wrapped'" in change for change in changes)
    assert wrapped == before
    revision = tools.dispatch(
        "create",
        wrapped,
        source=SOURCE,
        output_dir=tmp_path / "auto",
        render=False,
        automatic_layout=True,
    )
    tools.verify_revision(revision.parent)
    raw = json.loads((revision.parent / "raw_tool_request.json").read_text(encoding="utf-8"))
    request = json.loads((revision.parent / "request.json").read_text(encoding="utf-8"))
    assert raw["arguments"] == wrapped
    assert request["layout_policy"] == "automatic"
    assert request["arguments"]["visuals"][0]["layout_direction"] == "auto"
    with pytest.raises(ValueError):
        tools.dispatch(
            "create", wrapped, source=SOURCE, output_dir=tmp_path / "manual", render=False
        )


def test_nonlayered_generated_proposal_is_removed_but_unknown_direction_is_rejected():
    candidate = {"visuals": [{**dag(), "kind": "network", "layout_direction": "horizontal"}]}
    normalized, changes = materialize_layout(candidate, automatic_layout=True)
    assert "layout_direction" not in normalized["visuals"][0]
    assert candidate["visuals"][0]["layout_direction"] == "horizontal"
    assert any("effective=None" in change for change in changes)
    for invalid in ("diagonal", [], None):
        with pytest.raises(ValueError, match="direction"):
            spec, _ = materialize_layout(
                {"visuals": [{**dag(), "layout_direction": invalid}]}, automatic_layout=True
            )
            render_visual(spec["visuals"][0])


@pytest.mark.parametrize("repair_partition", [False, True])
@pytest.mark.parametrize("explicit_composition", [False, True])
def test_explicit_panel_delete_still_requires_complete_narration(
    tmp_path, repair_partition, explicit_composition
):
    source = "输入。处理。输出。"
    args = {"visuals": []}
    for ident, refs in [
        ("first", ["narration-001"]),
        ("second", ["narration-002", "narration-003"]),
    ]:
        spec = dag()
        spec.update(id=ident, narration_refs=refs)
        for node in spec["nodes"]:
            node["evidence"] = source
        for edge in spec["edges"]:
            edge["evidence"] = source
        args["visuals"].append(spec)
    if explicit_composition:
        args["composition"] = {"visual_ids": ["first", "second"], "axis": "single"}
    parent = tools.dispatch(
        "create",
        args,
        source=source,
        narration_text=source,
        output_dir=tmp_path / "parent",
        render=False,
    ).parent
    edits = [{"visual_id": "second", "delete": True}]
    if repair_partition:
        edits.append(
            {
                "visual_id": "first",
                "set": {"narration_refs": ["narration-001", "narration-002", "narration-003"]},
            }
        )
    request = {"parent": str(parent), "reason": "explicit panel merge", "updates": edits}
    if not repair_partition:
        with pytest.raises(ValueError, match="partition narration_text exactly"):
            tools.dispatch(
                "revise",
                request,
                source=source,
                narration_text=source,
                output_dir=tmp_path / "bad",
                render=False,
            )
    else:
        path = tools.dispatch(
            "revise",
            request,
            source=source,
            narration_text=source,
            output_dir=tmp_path / "merged",
            render=False,
        )
        tools.verify_revision(path.parent)
        specs = json.loads((path.parent / "specs.json").read_text(encoding="utf-8"))
        assert len(specs) == 1 and specs[0]["narration_span"] == source
        assert specs[0]["nodes"] == args["visuals"][0]["nodes"]
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["composition"]["pages"] == [["first"]]
