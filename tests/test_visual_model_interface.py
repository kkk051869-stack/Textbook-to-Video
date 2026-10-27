import json
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_interface import planner_view
from textbook2video.research.visual_model_interface import (
    renderer_graphs,
    renderer_updates,
)
from textbook2video.research.visual_object_edits import apply_object_updates, editing_contract

SOURCE = "输入经过处理产生输出。输出不能反推输入。"


def flat(kind="flow"):
    return {"visuals": [{"id": "main", "kind": kind, "title": "处理关系",
                         "teaching_goal": "理解输入和输出",
                         "nodes": [{"id": ident, "label": label, "source_ref": "source-001"}
                                   for ident, label in zip("abc", ["输入", "处理", "输出"])],
                         "edges": [{"source": "a", "target": "b", "source_ref": "source-001"},
                                   {"source": "b", "target": "c", "source_ref": "source-001"}]}]}


@pytest.mark.parametrize("kind", ["flow", "relationship"])
def test_same_flat_graph_content_reaches_each_renderer_and_model_targets(tmp_path, kind):
    original = flat(kind)
    before = deepcopy(original)
    path = tools.dispatch("create", original, source=SOURCE, output_dir=tmp_path/kind,
                          automatic_layout=True, render=False)
    effective = tools.revision_edit_base(path.parent)
    view = planner_view(effective, unified_graphs=True)
    spec = view["visuals"][0]
    assert "diagram" not in spec and "schema_version" not in spec
    assert spec["nodes"] == original["visuals"][0]["nodes"]
    assert spec["edges"] == original["visuals"][0]["edges"]
    assert original == before
    contract = editing_contract(view)
    assert {"kind": "node", "selector": {"visual_id": "main", "node_id": "a"}} in contract[
        "targets"]
    assert any(item["kind"] == "edge" for item in contract["targets"])


def test_wrong_citation_retains_addressable_sealed_base_for_real_next_node_update(tmp_path):
    wrapped = flat()
    spec = wrapped["visuals"][0]
    spec["nodes"][1]["source_ref"] = "narration-001"
    spec["diagram"] = {"type": "flow", "layout": "auto",
                       "nodes": spec.pop("nodes"), "edges": spec.pop("edges")}
    before = deepcopy(wrapped)
    parent = tmp_path/"failed-source"
    with pytest.raises(ValueError, match="existing source IDs"):
        tools.dispatch("create", wrapped, source=SOURCE, output_dir=parent,
                       automatic_layout=True, render=False)
    base = tools.revision_edit_base(parent)
    assert "diagram" not in base["visuals"][0]
    assert base["visuals"][0]["nodes"][1]["source_ref"] == "narration-001"
    tools.verify_failure(parent)
    snapshot = (parent/"structural-base.json").read_bytes()
    child = tools.dispatch("revise", {"parent": str(parent), "reason": "Fix explicit citation",
        "updates": [
        {"visual_id": "main", "node_id": "b", "set": {"source_ref": "source-001"}}]},
        source=SOURCE, output_dir=tmp_path/"fixed-source", automatic_layout=True, render=False)
    tools.verify_revision(child.parent)
    assert wrapped == before and (parent/"structural-base.json").read_bytes() == snapshot
    corrupted = json.loads(snapshot)
    corrupted["visuals"][0]["nodes"][0]["label"] = "tampered"
    (parent/"structural-base.json").write_text(json.dumps(corrupted), encoding="utf-8")
    with pytest.raises(tools.RevisionIntegrityError, match="structural base hash drift"):
        tools.revision_edit_base(parent)


@pytest.mark.parametrize("wrapper", [
    {"nodes": [], "edges": [], "unsupported_fact": "must not disappear"},
    {"type": "network", "nodes": [], "edges": []},
])
def test_ambiguous_or_unknown_wrappers_are_rejected_before_source_ids(tmp_path, wrapper):
    args = flat()
    spec = args["visuals"][0]
    spec.pop("nodes")
    spec.pop("edges")
    spec["diagram"] = wrapper
    with pytest.raises(ValueError, match="wrapper"):
        tools.dispatch("create", args, source=SOURCE, output_dir=tmp_path/"bad",
                       automatic_layout=True, render=False)


def test_conflicting_containers_are_never_chosen_by_guessing():
    args = flat()
    args["visuals"][0]["diagram"] = {"type": "flow", "nodes": [], "edges": []}
    with pytest.raises(ValueError, match="conflicting graph containers"):
        renderer_graphs(args)


@pytest.mark.parametrize("first_kind", ["nodes", "node_selector"])
def test_sequential_relationship_updates_never_restore_an_earlier_field(first_kind):
    base, _ = renderer_graphs(flat("relationship"))
    new_nodes = deepcopy(base["visuals"][0]["diagram"]["nodes"])
    new_nodes[0]["label"] = "新输入"
    new_edges = deepcopy(base["visuals"][0]["diagram"]["edges"])
    new_edges[0]["label"] = "新关系"
    first = ({"visual_id": "main", "set": {"nodes": new_nodes}} if first_kind == "nodes"
             else {"visual_id": "main", "node_id": "a", "set": {"label": "新输入"}})
    original = {"updates": [first, {"visual_id": "main", "set": {"edges": new_edges}}]}
    before = deepcopy((base, original))
    result = apply_object_updates(base, renderer_updates(base, original))
    assert result["visuals"][0]["diagram"]["nodes"][0]["label"] == "新输入"
    assert result["visuals"][0]["diagram"]["edges"][0]["label"] == "新关系"
    assert (base, original) == before


@pytest.mark.parametrize("nodes", [None, 7, "invalid"])
def test_malformed_candidate_view_preserves_input_for_bounded_repair(nodes):
    args = flat()
    args["visuals"][0]["nodes"] = nodes
    view = planner_view(args, unified_graphs=True)
    assert view["visuals"][0]["nodes"] == nodes and args["visuals"][0]["nodes"] == nodes


@pytest.mark.parametrize("nodes", [None, [None]])
def test_malformed_legacy_auto_layout_wrapper_cannot_crash_next_request(nodes):
    args = {"visuals": [{"id": "broken", "kind": "relationship", "diagram": {
        "version": "teaching-relationship-v1", "layout": "auto", "auto_layout": True,
        "nodes": nodes, "edges": []}}]}
    before = deepcopy(args)
    view = planner_view(args, unified_graphs=True)
    assert view["visuals"][0]["nodes"] == nodes and args == before


@pytest.mark.parametrize("directed", [False, None, "false", 1])
def test_relationship_never_ignores_explicit_unsupported_direction(directed):
    args = flat("relationship")
    args["visuals"][0]["edges"][0]["directed"] = directed
    with pytest.raises(ValueError, match="directed edges only"):
        renderer_graphs(args)


@pytest.mark.parametrize("malformed_reply", [False, True])
def test_real_agent_revision_view_has_same_selectors_as_internal_relationship_base(
    tmp_path, monkeypatch, malformed_reply,
):
    from test_visual_tools import review

    replies = iter([{"tool": "create", "arguments": flat("relationship")},
                    *([{}] if malformed_reply else []),
                    {"tool": "revise", "arguments": {"updates": [
                        {"visual_id": "main", "node_id": "a", "set": {"label": "输入项"}}]}}])
    requests, reviews = [], []

    def planner(prompt, **kwargs):
        requests.append(json.loads(prompt))
        return json.dumps(next(replies))

    def preview(directory, **kwargs):
        tools._save(directory/"geometry.json", [])
        return []

    def reviewer(directory, **kwargs):
        reviews.append(directory)
        result = review()
        if len(reviews) == 1:
            result.update(verdict="REVISE", issues=[{"visual_id": "main", "category": "spacing",
                "issue": "调整标签‘输入’", "change": "调整标签‘输入’",
                "target_selector": {"visual_id": "main", "node_id": "a"}}])
        return tools._save_review(directory, json.dumps(result), [], model="test", has_images=True)

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", preview)
    monkeypatch.setattr(tools, "review_revision", reviewer)
    run = tools.run_visual_agent(SOURCE, "处理关系", tmp_path/"agent",
                                 max_iterations=3 if malformed_reply else 2)
    state = json.loads(run.read_text(encoding="utf-8"))
    assert state["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    view = requests[1]["previous_candidate"]["visuals"][0]
    assert "diagram" not in view and view["nodes"][0]["id"] == "a"
    assert {"kind": "node", "selector": {"visual_id": "main", "node_id": "a"}} in requests[1][
        "edit_contract"]["targets"]
    assert "changes" not in requests[1]["tools"][0]["arguments"]
    assert not {"diagram", "schema_version", "layout_direction", "kind"}.intersection(
        requests[1]["edit_contract"]["allowed_fields"]["visual"])
    assert "column" not in requests[1]["edit_contract"]["allowed_fields"]["node"]
    assert all("optional_relationship_schema" not in req for req in requests)
