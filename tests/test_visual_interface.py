import json
from copy import deepcopy

import pytest

from textbook2video.research.visual_edits import apply_changes
from textbook2video.research.visual_interface import materialize_layout, planner_view
from textbook2video.research.visual_source_refs import materialize_source_refs
from textbook2video.research.visual_tools import dispatch


def relation():
    return {
        "visuals": [
            {
                "id": "r",
                "kind": "relationship",
                "title": "处理关系",
                "teaching_goal": "理解处理",
                "diagram": {
                    "version": "teaching-relationship-v1",
                    "layout": "auto",
                    "nodes": [
                        {"id": i, "label": label, "source_ref": "source-001"}
                        for i, label in zip("abc", ["输入", "处理", "输出"])
                    ],
                    "edges": [
                        {"source": "a", "target": "b", "source_ref": "source-001"},
                        {"source": "b", "target": "c", "source_ref": "source-001"},
                    ],
                },
            }
        ]
    }


def test_auto_layout_executes_without_model_columns_and_preserves_all_edges(tmp_path):
    args = relation()
    before = deepcopy(args)
    path = dispatch(
        "create", args, source="输入经过处理产生输出。", output_dir=tmp_path / "run", render=False
    )
    resolved = json.loads((path.parent / "request.json").read_text(encoding="utf-8"))["arguments"]
    diagram = resolved["visuals"][0]["diagram"]
    assert diagram["layout"] == "one_way"
    assert [n["column"] for n in diagram["nodes"]] == [0, 1, 2]
    assert [(e["source"], e["target"]) for e in diagram["edges"]] == [("a", "b"), ("b", "c")]
    view = planner_view(resolved)
    assert view["visuals"][0]["diagram"]["layout"] == "auto"
    assert "column" not in view["visuals"][0]["diagram"]["nodes"][0]
    assert "evidence" not in view["visuals"][0]["diagram"]["edges"][0]
    assert args == before


def test_automatic_relationship_template_follows_existing_columns_not_model_label():
    args = relation()
    diagram = args["visuals"][0]["diagram"]
    diagram.update(layout="one_way", columns=["输入", "处理", "输出"])
    diagram["nodes"].append({"id": "d", "label": "其他输入", "column": 0})
    for node, column in zip(diagram["nodes"], [0, 1, 2, 0]):
        node["column"] = column
    diagram["edges"].append({"source": "d", "target": "b", "source_ref": "source-001"})
    original = deepcopy(args)
    normalized, notes = materialize_layout(args, automatic_layout=True)
    fixed = normalized["visuals"][0]["diagram"]
    assert fixed["layout"] == "split_merge"
    assert fixed["nodes"] == original["visuals"][0]["diagram"]["nodes"]
    assert fixed["edges"] == original["visuals"][0]["diagram"]["edges"]
    assert any("template one_way -> split_merge" in note for note in notes)
    assert args == original
    untouched, _ = materialize_layout(args, automatic_layout=False)
    assert untouched["visuals"][0]["diagram"]["layout"] == "one_way"


@pytest.mark.parametrize("mode", ["cycle", "four_stages", "conflict"])
def test_auto_layout_does_not_invent_or_rewrite_invalid_topology(mode):
    args = relation()
    diagram = args["visuals"][0]["diagram"]
    if mode == "cycle":
        diagram["edges"].append({"source": "c", "target": "a"})
    elif mode == "four_stages":
        diagram["nodes"].append({"id": "d", "label": "额外节点"})
        diagram["edges"].append({"source": "c", "target": "d"})
    else:
        diagram["nodes"][0]["column"] = 2
    before = deepcopy(args)
    with pytest.raises(ValueError):
        materialize_layout(args)
    assert args == before


def test_agent_materializes_only_omitted_headings_for_explicit_three_stage_nodes():
    original = relation()
    diagram = original["visuals"][0]["diagram"]
    diagram["layout"] = "one_way"
    diagram.pop("columns", None)
    for index, node in enumerate(diagram["nodes"]):
        node["column"] = index
    before = deepcopy(original)
    effective, messages = materialize_layout(original, automatic_layout=True)
    result = effective["visuals"][0]["diagram"]
    assert result["columns"] == ["阶段一", "阶段二", "阶段三"]
    assert result["nodes"] == diagram["nodes"] and result["edges"] == diagram["edges"]
    assert original == before and messages
    manual, _ = materialize_layout(original, automatic_layout=False)
    assert "columns" not in manual["visuals"][0]["diagram"]


@pytest.mark.parametrize("columns", [None, [], ["one", "two"]])
def test_agent_never_replaces_explicit_invalid_column_headings(columns):
    original = relation()
    diagram = original["visuals"][0]["diagram"]
    diagram.update(layout="one_way", columns=columns)
    for index, node in enumerate(diagram["nodes"]):
        node["column"] = index
    effective, _ = materialize_layout(original, automatic_layout=True)
    assert effective["visuals"][0]["diagram"]["columns"] == columns


def test_pointer_reference_edit_refreshes_only_inherited_quote():
    base = {"visuals": [{"id": "v", "source_ref": "source-001", "evidence": "甲。"}]}
    result = apply_changes(
        base, {"changes": [{"op": "set", "path": "/visuals/@v/source_ref", "value": "source-002"}]}
    )
    resolved, _ = materialize_source_refs(result, "甲。乙。", None)
    assert resolved["visuals"][0]["evidence"] == "乙。"
    assert base["visuals"][0]["evidence"] == "甲。"
    assert result["derived_fields_cleared"][0]["old_value"] == "甲。"


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_contradictory_quote_is_never_silently_discarded(reverse):
    base = {"visuals": [{"id": "v", "source_ref": "source-001", "evidence": "甲。"}]}
    edits = [
        {"op": "set", "path": "/visuals/@v/source_ref", "value": "source-002"},
        {"op": "replace", "path": "/visuals/@v/evidence", "value": "甲。"},
    ]
    result = apply_changes(base, {"changes": edits[::-1] if reverse else edits})
    with pytest.raises(ValueError, match="conflicts"):
        materialize_source_refs(result, "甲。乙。", None)


def test_nested_replacement_quote_remains_explicit_in_same_batch():
    node = {"id": "n", "source_ref": "source-001", "evidence": "甲。"}
    base = {"visuals": [{"id": "v", "nodes": [node]}]}
    result = apply_changes(
        base,
        {
            "changes": [
                {"op": "replace", "path": "/visuals/@v/nodes/@n", "value": node},
                {"op": "set", "path": "/visuals/@v/nodes/@n/source_ref", "value": "source-002"},
            ]
        },
    )
    with pytest.raises(ValueError, match="conflicts"):
        materialize_source_refs(result, "甲。乙。", None)


def test_reference_array_member_edit_refreshes_inherited_quote():
    base = {"visuals": [{"id": "v", "source_ref": ["source-001"], "evidence": "甲。"}]}
    result = apply_changes(
        base,
        {
            "changes": [
                {"op": "set", "path": "/visuals/@v/source_ref/0", "value": "source-002"},
            ]
        },
    )
    result, _ = materialize_source_refs(result, "甲。乙。", None)
    assert result["visuals"][0]["evidence"] == "乙。"


def test_standalone_relationship_planner_uses_same_source_and_layout_interface(monkeypatch):
    from textbook2video.llm import client
    from textbook2video.research import relationship_visuals

    def planner(prompt, **kwargs):
        assert json.loads(prompt)["source_units"][0]["id"] == "source-001"
        return json.dumps(relation()["visuals"][0])

    monkeypatch.setattr(client, "chat_with_system", planner)
    spec, _ = relationship_visuals.plan_relationship(
        "输入经过处理产生输出。",
        teaching_goal="理解处理",
        model="test",
        layout_hint="auto",
    )
    assert spec["diagram"]["layout"] == "one_way"
    assert all(n["evidence"] == "输入经过处理产生输出。" for n in spec["diagram"]["nodes"])
