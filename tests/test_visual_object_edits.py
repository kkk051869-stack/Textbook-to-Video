from __future__ import annotations

import json
from copy import deepcopy

import pytest

from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_object_edits import (
    FIELDS,
    ObjectUpdateError,
    apply_object_updates,
    detail_repair_scope,
    editing_contract,
    label_repair_scope,
    validate_detail_repair,
    validate_label_repair,
)
from textbook2video.research.visual_panel_repair import (
    can_append_missing_panel,
    expand_missing_panel,
)

SOURCE = "采集数据。处理数据。显示结果。"


@pytest.mark.parametrize("relationship", [False, True])
def test_contract_uses_executor_permissions_and_exact_existing_targets(relationship):
    original = base(relationship)
    before = deepcopy(original)
    contract = editing_contract(original)
    assert original == before
    assert contract["allowed_fields"] == {k: sorted(v) for k, v in FIELDS.items()}
    assert {"kind": "node", "selector": {"visual_id": "main", "node_id": "a"}} in contract[
        "targets"
    ]
    assert "style" not in contract["allowed_fields"]["node"]
    assert "id" not in contract["allowed_fields"]["node"]
    assert any(t["kind"] == "constraint" for t in contract["targets"]) is relationship


@pytest.mark.parametrize("relationship", [False, True])
def test_single_label_review_grants_only_one_existing_target(relationship):
    original = base(relationship)
    container = (original["visuals"][0]["diagram"] if relationship
                 else original["visuals"][0])
    container["edges"][0]["label"] = "导致不一致"
    review = {"issues": [{
        "visual_id": "main", "category": "spacing",
        "issue": "连线标签‘导致不一致’换行，影响留白",
        "change": "把标签缩成‘不一致’",
    }], "reason": "仅处理标签"}
    scope = label_repair_scope(original, review)
    assert scope == {
        "mode": "label", "target": {"kind": "edge", "selector": {
            "visual_id": "main", "edge": {"source": "a", "target": "b"},
        }}, "field": "label", "old_value": "导致不一致",
    }
    valid = {"updates": [{**scope["target"]["selector"], "set": {"label": "不一致"}}]}
    validate_label_repair(valid, scope)
    changed = apply_object_updates(original, valid)
    expected = deepcopy(original)
    target = expected["visuals"][0]["diagram"] if relationship else expected["visuals"][0]
    target["edges"][0]["label"] = "不一致"
    assert changed["visuals"] == expected["visuals"]
    assert original["visuals"][0] != expected["visuals"][0]
    for invalid in [
        {"updates": valid["updates"] + valid["updates"]},
        {"updates": [{**valid["updates"][0], "set": {"label": "不一致", "kind": "flow"}}]},
        {"updates": [{"visual_id": "main", "node_id": "a", "set": {"label": "不一致"}}]},
        {"changes": [{"op": "replace", "path": "/visuals/0/kind", "value": "flow"}]},
        {"visuals": expected["visuals"]},
        {"updates": [{**scope["target"]["selector"], "delete": True}]},
    ]:
        with pytest.raises(ObjectUpdateError, match="label repair"):
            validate_label_repair(invalid, scope)


def test_label_scope_refuses_ambiguous_or_semantic_review():
    original = base(True)
    original["visuals"][0]["diagram"]["edges"][0]["label"] = "导致不一致"
    review = {"issues": [{"visual_id": "main", "category": "spacing",
                          "issue": "标签‘导致不一致’换行", "change": "缩短标签"}]}
    assert label_repair_scope(original, review)
    original["visuals"][0]["diagram"]["edges"][1]["label"] = "导致不一致"
    assert label_repair_scope(original, review) is None
    review["issues"][0]["category"] = "factual_error"
    assert label_repair_scope(original, review) is None


def test_single_node_detail_review_rejects_r60_unrelated_visual_update():
    original = base()
    original["visuals"][0]["nodes"][1]["detail"] = "输入数据经过校验后送入处理模块"
    review = {"issues": [{
        "visual_id": "main", "category": "unreadable",
        "issue": "节点‘处理’的正文说明换行拥挤，可读性差",
        "change": "精简该节点 detail 文本",
    }]}
    scope = detail_repair_scope(original, review)
    assert scope is not None
    valid_target = {**scope["target"]["selector"], "set": {
        "detail": "校验后送入处理模块",
    }}
    validate_detail_repair({"updates": [valid_target]}, scope)

    # r60 changed the reviewed node detail and an unrelated visual-level scale.
    with pytest.raises(ObjectUpdateError, match="detail repair"):
        validate_detail_repair({"updates": [valid_target,
            {"visual_id": "main", "set": {"text_scale": 1.25}}]}, scope)


def test_single_node_detail_review_allows_only_the_exact_target_detail():
    original = base()
    original["visuals"][0]["nodes"][1]["detail"] = "输入数据经过校验后送入处理模块"
    review = {"issues": [{
        "visual_id": "main", "category": "unreadable",
        "issue": "节点‘处理’的正文说明换行拥挤，可读性差",
        "change": "精简该节点 detail 文本",
    }]}
    scope = detail_repair_scope(original, review)
    assert scope == {
        "mode": "detail",
        "target": {"kind": "node", "selector": {"visual_id": "main", "node_id": "b"}},
        "field": "detail",
        "old_value": "输入数据经过校验后送入处理模块",
    }
    arguments = {"updates": [{
        "visual_id": "main", "node_id": "b",
        "set": {"detail": "校验后送入处理模块"},
    }]}
    validate_detail_repair(arguments, scope)
    changed = apply_object_updates(original, arguments)
    assert changed["visuals"][0]["nodes"][1]["detail"] == "校验后送入处理模块"
    assert original["visuals"][0]["nodes"][1]["detail"] == "输入数据经过校验后送入处理模块"


def test_detail_scope_refuses_ambiguous_or_unspecified_target():
    original = base()
    nodes = original["visuals"][0]["nodes"]
    nodes[0]["detail"] = "来源数据在此节点等待后续处理"
    nodes[1]["detail"] = "来源数据在此节点等待后续处理"
    ambiguous_review = {"issues": [{
        "visual_id": "main", "category": "unreadable",
        "issue": "节点正文说明换行拥挤，可读性差",
        "change": "精简该节点 detail 文本",
    }]}
    assert detail_repair_scope(original, ambiguous_review) is None

    unclear_review = {"issues": [{
        "visual_id": "main", "category": "unreadable",
        "issue": "节点正文说明换行拥挤，可读性差",
        "change": "精简正文",
    }]}
    assert detail_repair_scope(base(), unclear_review) is None
    semantic_review = deepcopy(unclear_review)
    semantic_review["issues"][0]["issue"] = "节点‘处理’正文断行"
    semantic_review["checks"] = {"accuracy": False}
    assert detail_repair_scope(base(), semantic_review) is None


def test_dispatch_enforces_label_scope_against_verified_parent(tmp_path):
    original = base()
    original["visuals"][0]["edges"][0]["label"] = "采集数据"
    parent = tmp_path / "parent"
    tools.dispatch("create", original, source=SOURCE, output_dir=parent, render=False)
    base_args = tools.revision_edit_base(parent)
    scope = label_repair_scope(base_args, {"issues": [{
        "visual_id": "main", "category": "spacing",
        "issue": "连线标签‘采集数据’换行", "change": "缩短标签",
    }]})
    assert scope is not None
    scope["base_sha256"] = tools.digest(base_args)
    tools._save_review(parent, json.dumps({
        "verdict": "REVISE",
        "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 3),
        "issues": [{"visual_id": "main", "category": "spacing",
                    "issue": "连线标签‘采集数据’换行", "change": "缩短标签"}],
        "reason": "缩短一处标签",
    }, ensure_ascii=False), [], model="fixture", has_images=True)
    for name, args in [
        ("extra", {"updates": [
            {"visual_id": "main", "edge": {"source": "a", "target": "b"},
             "set": {"label": "采集", "source_ref": "source-001"}},
        ]}),
        ("changes", {"changes": [{"op": "replace", "path": "/visuals/0/kind",
                                 "value": "comparison"}]}),
        ("replacement", {"visuals": deepcopy(base_args["visuals"])}),
    ]:
        with pytest.raises(ValueError, match="label repair|scoped label"):
            tools.dispatch("revise", {**args, "parent": str(parent), "reason": "label"},
                           source=SOURCE, output_dir=tmp_path / name,
                           render=False)
        assert (tmp_path / name / "failure.json").is_file()
        assert tools.revision_edit_base(parent)["visuals"] == base_args["visuals"]
    with pytest.raises(ValueError, match="scoped label"):
        tools.dispatch("revise", {
            "parent": str(tmp_path / "extra"), "reason": "bypass",
            "visuals": deepcopy(base_args["visuals"]),
        }, source=SOURCE, output_dir=tmp_path / "failed-parent-bypass", render=False)
    valid = {"parent": str(parent), "reason": "短标签", "updates": [{
        "visual_id": "main", "edge": {"source": "a", "target": "b"},
        "set": {"label": "采集"},
    }]}
    child = tmp_path / "valid"
    tools.dispatch("revise", valid, source=SOURCE, output_dir=child, render=False)
    tools.verify_revision(child)


def test_dispatch_rejects_unrelated_update_after_detail_review(tmp_path):
    original = base()
    original["visuals"][0]["nodes"][1]["detail"] = "处理数据"
    parent = tmp_path / "parent"
    tools.dispatch("create", original, source=SOURCE, output_dir=parent, render=False)
    review = {"verdict": "REVISE", "scores": dict.fromkeys(
        ("accuracy", "relevance", "readability", "composition"), 3),
        "issues": [{"visual_id": "main", "category": "unreadable",
                    "issue": "节点‘处理’正文断行", "change": "缩短节点正文说明"}],
        "reason": "仅一个节点的正文需要可读性修复"}
    tools._save_review(parent, json.dumps(review, ensure_ascii=False), [],
                       model="fixture", has_images=True)
    original_base = tools.revision_edit_base(parent)
    with pytest.raises(ObjectUpdateError, match="detail repair"):
        tools.dispatch("revise", {
            "parent": str(parent), "reason": "readability", "updates": [
                {"visual_id": "main", "node_id": "b", "set": {"detail": "处理"}},
                {"visual_id": "main", "set": {"text_scale": 1.25}},
            ],
        }, source=SOURCE, output_dir=tmp_path / "rejected", render=False)
    assert tools.revision_edit_base(parent)["visuals"] == original_base["visuals"]
    assert (tmp_path / "rejected" / "failure.json").is_file()


def test_late_invalid_update_reports_exact_error_and_leaves_original_untouched():
    original = base()
    before = deepcopy(original)
    with pytest.raises(ObjectUpdateError) as caught:
        apply_object_updates(
            original,
            {
                "updates": [
                    {"visual_id": "main", "node_id": "a", "set": {"label": "改写"}},
                    {"visual_id": "main", "node_id": "b", "set": {"style": "highlight"}},
                ]
            },
        )
    assert original == before
    assert caught.value.details == {
        "update_index": 1,
        "selector": {"visual_id": "main", "node_id": "b"},
        "kind": "node",
        "offending_fields": ["style"],
        "allowed_fields": sorted(FIELDS["node"]),
    }
    with pytest.raises(ObjectUpdateError) as unknown:
        apply_object_updates(
            original,
            {
                "updates": [
                    {"visual_id": "main", "node_id": "invented", "set": {"label": "不猜测"}},
                ]
            },
        )
    assert unknown.value.details["selector"]["node_id"] == "invented"


@pytest.mark.parametrize("nodes,edges", [
    ([{"label": "missing ID"}], [{"source": "a"}]),
    ([{"id": "a"}, {"id": "a"}], []),
    (None, None),
])
def test_contract_diagnoses_unaddressable_objects_without_inventing_selectors(nodes, edges):
    candidate = {"visuals": [{"id": "main", "kind": "flow", "nodes": nodes, "edges": edges}]}
    before = deepcopy(candidate)
    contract = editing_contract(candidate)
    assert contract["targets"] == [{"kind": "visual", "selector": {"visual_id": "main"}}]
    assert contract["unaddressable_targets"]
    assert candidate == before


def test_missing_relationship_diagram_does_not_advertise_constraint_target():
    contract = editing_contract({"visuals": [{"id": "main", "kind": "relationship"}]})
    assert contract["targets"] == [{"kind": "visual", "selector": {"visual_id": "main"}}]
    assert contract["unaddressable_targets"][0]["reason"] == "diagram missing or invalid"


def test_flat_explicit_fields_are_wrapped_without_changing_values_or_raw_audit():
    original = base()
    update = {"visual_id": "main", "node_id": "a", "label": "采集输入数据",
              "source_ref": "source-001"}
    changed = apply_object_updates(original, {"updates": [update]})
    assert changed["visuals"][0]["nodes"][0]["label"] == update["label"]
    assert changed["applied_updates"][0]["update"] == update
    assert changed["applied_updates"][0]["normalized_update"]["set"] == {
        "label": "采集输入数据", "source_ref": "source-001"
    }
    assert original == base()
    for invalid in [
        {**update, "set": {"label": "conflicting"}},
        {"visual_id": "main", "id": "new-identity"},
        {"visual_id": "main", "node_id": "a", "source_text": "forged"},
    ]:
        with pytest.raises(ValueError):
            apply_object_updates(original, {"updates": [invalid]})


def test_flat_fields_still_reject_forged_quotes_and_unknown_targets():
    changed = apply_object_updates(base(), {"updates": [
        {"visual_id": "main", "node_id": "a", "evidence": "FORGED",
         "source_ref": "source-001"}
    ]})
    with pytest.raises(ValueError, match="conflict"):
        tools.materialize_source_refs(changed, SOURCE, None)
    with pytest.raises(ValueError, match="existing"):
        apply_object_updates(base(), {"updates": [
            {"visual_id": "main", "node_id": "unknown", "label": "No guess"}
        ]})


def base(relationship=False):
    spec = {
        "id": "main", "kind": "flow", "schema_version": "teaching-visual-v2",
        "title": "数据处理", "teaching_goal": "理解完整处理过程",
        "nodes": [{"id": ident, "label": label, "source_ref": f"source-{i:03}"}
                  for i, (ident, label) in enumerate(zip("abc", ["采集", "处理", "显示"]), 1)],
        "edges": [{"source": "a", "target": "b", "source_ref": "source-001"},
                  {"source": "b", "target": "c", "source_ref": "source-002"}],
    }
    if relationship:
        spec["kind"] = "relationship"
        spec.pop("schema_version")
        spec["diagram"] = {"version": "teaching-relationship-v1", "layout": "one_way",
                           "columns": ["输入", "处理", "输出"],
                           "nodes": spec.pop("nodes"), "edges": spec.pop("edges")}
        for i, node in enumerate(spec["diagram"]["nodes"]):
            node["column"] = i
    return {"visuals": [spec]}


@pytest.mark.parametrize("relationship", [False, True])
def test_object_updates_locate_real_nodes_edges_and_audit_the_actual_path(relationship):
    original = base(relationship)
    before = deepcopy(original)
    updates = [{"visual_id": "main", "node_id": "b", "set": {"detail": "处理输入"}},
               {"visual_id": "main", "edge": {"source": "a", "target": "b"},
                "set": {"label": "输入"}}]
    result = apply_object_updates(original, {"updates": updates})
    spec = result["visuals"][0]
    diagram = spec["diagram"] if relationship else spec
    assert diagram["nodes"][1]["detail"] == "处理输入"
    assert diagram["edges"][0]["label"] == "输入"
    assert diagram["edges"][1] == (before["visuals"][0]["diagram"] if relationship
                                   else before["visuals"][0])["edges"][1]
    prefix = "/visuals/0/diagram" if relationship else "/visuals/0"
    assert result["applied_updates"][1]["resolved_path"] == prefix + "/edges/0"
    assert [item["update"] for item in result["applied_updates"]] == updates
    assert original == before


@pytest.mark.parametrize("selector", [
    {"visual_id": "absent"}, {"visual_id": "main", "node_id": "absent"},
    {"visual_id": "main", "edge": {"source": "b", "target": "a"}},
    {"visual_id": "main", "node_id": "a", "edge": {"source": "a", "target": "b"}},
    {"visual_id": "main", "element_id": "note"},
])
def test_unknown_reversed_or_ambiguous_object_selectors_never_guess(selector):
    with pytest.raises(ValueError):
        apply_object_updates(base(), {"updates": [{**selector, "set": {"label": "错目标"}}]})
    duplicate = base()
    duplicate["visuals"][0]["edges"] *= 2
    with pytest.raises(ValueError, match="exactly one"):
        apply_object_updates(duplicate, {"updates": [{
            "visual_id": "main", "edge": {"source": "a", "target": "b"},
            "set": {"label": "不猜"},
        }]})


def test_explicit_edge_retarget_and_delete_do_not_invent_other_relationships():
    result = apply_object_updates(base(), {"updates": [
        {"visual_id": "main", "edge": {"source": "a", "target": "b"},
         "set": {"target": "c"}},
        {"visual_id": "main", "edge": {"source": "b", "target": "c"}, "delete": True},
        {"visual_id": "main", "node_id": "b", "delete": True},
    ]})
    spec = result["visuals"][0]
    assert [n["id"] for n in spec["nodes"]] == ["a", "c"]
    assert spec["edges"] == [{"source": "a", "target": "c", "source_ref": "source-001"}]


@pytest.mark.parametrize("bad", [
    {"set": {"id": "other"}}, {"set": {"source_text": "fake"}},
    {"set": {"label": "x"}, "remove": ["label"]}, {"remove": ["missing"]},
    {"delete": True, "set": {"label": "x"}}, {"delete": 1},
])
def test_edits_cannot_change_identity_sources_or_hide_invalid_operations(bad):
    with pytest.raises(ValueError):
        apply_object_updates(base(), {"updates": [{"visual_id": "main", "node_id": "a", **bad}]})
    for key in ("changes", "visuals", "source_text", "review"):
        with pytest.raises(ValueError):
            apply_object_updates(base(), {key: [], "updates": [
                {"visual_id": "main", "set": {"title": "明确修改"}}
            ]})


def test_citation_refresh_is_explicit_audited_and_still_source_validated(tmp_path):
    parent = tmp_path / "parent"
    tools.dispatch("create", base(), source=SOURCE, output_dir=parent, render=False)
    args = {"parent": str(parent), "reason": "改用另一段真实依据", "updates": [
        {"visual_id": "main", "node_id": "b", "set": {"source_ref": "source-003"}},
    ]}
    child = tmp_path / "child"
    tools.dispatch("revise", args, source=SOURCE, output_dir=child, render=False)
    tools.verify_revision(child)
    request = json.loads((child / "request.json").read_text(encoding="utf-8"))["arguments"]
    assert request["visuals"][0]["nodes"][1]["evidence"] == "显示结果。"
    audit = request["applied_updates"][0]
    assert audit["update"] == args["updates"][0]
    assert audit["refreshed_evidence"] == {"evidence": "处理数据。"}
    assert json.loads((child / "raw_tool_request.json").read_text(encoding="utf-8"))[
        "arguments"] == args
    args["updates"][0]["set"]["evidence"] = "模型编造的依据。"
    with pytest.raises(ValueError, match="conflicts"):
        tools.dispatch("revise", args, source=SOURCE, output_dir=tmp_path / "bad", render=False)
    assert (tmp_path / "bad/failure.json").is_file()


def test_constraint_refresh_and_coverage_disposition_round_trip_keep_actual_facts():
    original = base(True)
    original["visuals"][0]["diagram"].update(
        constraint="处理数据", constraint_source_ref="source-002", constraint_evidence="处理数据。",
    )
    original["page_plan"] = {
        "reason": "教学关系", "support_element_ids": [], "replaces_element_ids": ["note"],
        "coverage": [{"element_id": "note", "decision": "represented", "source_ref": "source-001",
                      "source_evidence": "采集数据。", "reason": "对应输入",
                      "visual_refs": ["main:a"],
                      "fact_quotes": ["采集数据"]}],
    }
    result = apply_object_updates(original, {"updates": [
        {"visual_id": "main", "constraint": True, "set": {
            "constraint": "显示结果", "constraint_source_ref": "source-003",
        }},
        {"element_id": "note", "set": {"decision": "support", "reason": "保留短说明"}},
    ]})
    assert result["page_plan"]["support_element_ids"] == ["note"]
    assert result["page_plan"]["coverage"] == result["page_plan"]["replaces_element_ids"] == []
    result = apply_object_updates(result, {"updates": [{"element_id": "note", "set": {
        "decision": "represented", "source_ref": "source-001", "visual_refs": ["main:a"],
        "reason": "已明确表示输入",
    }}]})
    normalized, _ = tools.materialize_source_refs(
        result, SOURCE, [{"id": "note", "type": "text", "text": "采集数据"}],
    )
    assert normalized["page_plan"]["coverage"][0]["fact_quotes"] == ["采集数据"]
    assert normalized["visuals"][0]["diagram"]["constraint_evidence"] == "显示结果。"
    context = {"elements": [{"id": "note", "type": "text", "text": "采集数据"}]}
    apply_visual_page_plan(context, "primary", normalized["page_plan"],
                           visual_specs=normalized["visuals"], source_text=SOURCE)


def test_failed_object_updates_keep_a_recoverable_parent(tmp_path):
    parent = tmp_path / "parent"
    tools.dispatch("create", base(), source=SOURCE, output_dir=parent, render=False)
    args = {"parent": str(parent), "reason": "非法对象", "updates": [
        {"visual_id": "main", "node_id": "missing", "set": {"label": "处理"}},
    ]}
    failed = tmp_path / "failed"
    with pytest.raises(ValueError, match="exactly one"):
        tools.dispatch("revise", args, source=SOURCE, output_dir=failed, render=False)
    assert tools.revision_edit_base(failed)["visuals"] == (
        tools.revision_edit_base(parent)["visuals"]
    )
    args["parent"] = str(failed)
    args["updates"][0]["node_id"] = "b"
    child = tmp_path / "child"
    tools.dispatch("revise", args, source=SOURCE, output_dir=child, render=False)
    tools.verify_revision(child)
    assert json.loads((child / "revision.json").read_text(encoding="utf-8"))["parent"] == str(
        failed.resolve()
    )


def test_object_update_operation_budget_is_bounded():
    update = {"visual_id": "main", "set": {"title": "输入", "teaching_goal": "关系"}}
    with pytest.raises(ValueError, match="40-operation"):
        apply_object_updates(base(), {"updates": [update] * 21})


@pytest.mark.parametrize("selector,ref,quote,path", [
    ({"visual_id": "main", "node_id": "b"}, "source_ref", "evidence",
     ["visuals", 0, "diagram", "nodes", 1]),
    ({"visual_id": "main", "edge": {"source": "a", "target": "b"}}, "source_ref", "evidence",
     ["visuals", 0, "diagram", "edges", 0]),
    ({"element_id": "note"}, "source_ref", "source_evidence", ["page_plan", "coverage", 0]),
    ({"visual_id": "main", "constraint": True}, "constraint_source_ref", "constraint_evidence",
     ["visuals", 0, "diagram"]),
])
def test_separate_reference_update_never_discards_a_quote_explicit_in_this_batch(
    selector, ref, quote, path,
):
    original = base(True)
    original["visuals"][0]["diagram"]["constraint"] = "显示结果"
    original["page_plan"] = {"support_element_ids": [], "replaces_element_ids": ["note"],
                             "coverage": [{"element_id": "note", "decision": "represented",
                                           "source_ref": "source-001"}]}
    for explicit in ("FORGED", "显示结果"):
        changed = apply_object_updates(original, {"updates": [
            {**selector, "set": {quote: explicit}},
            {**selector, "set": {ref: "source-003"}},
        ]})
        if explicit == "FORGED":
            with pytest.raises(ValueError, match="conflicts"):
                tools.materialize_source_refs(changed, SOURCE, None)
        else:
            normalized, _ = tools.materialize_source_refs(changed, SOURCE, None)
            target = normalized
            for part in path:
                target = target[part]
            assert target[quote] == explicit


def test_quotes_nested_in_whole_object_replacement_are_explicit_not_parent_evidence():
    original = base(True)
    replacement = deepcopy(original["visuals"][0]["diagram"])
    replacement["nodes"][1]["evidence"] = "FORGED"
    changed = apply_object_updates(original, {"updates": [
        {"visual_id": "main", "set": {"diagram": replacement}},
        {"visual_id": "main", "node_id": "b", "set": {"source_ref": "source-003"}},
    ]})
    with pytest.raises(ValueError, match="conflicts"):
        tools.materialize_source_refs(changed, SOURCE, None)


def test_real_agent_dispatch_executes_object_update_and_seals_its_parent_chain(
    tmp_path, monkeypatch,
):
    responses = iter([
        {"tool": "create", "arguments": base(True)},
        {"tool": "revise", "arguments": {"updates": [
            {"visual_id": "main", "edge": {"source": "a", "target": "b"},
             "set": {"label": "输入数据"}},
        ]}},
    ])
    reports = iter([
        {"verdict": verdict, "issues": [], "reason": "Fixture review",
         "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), score)}
        for verdict, score in [("REVISE", 2), ("ACCEPT", 4)]
    ])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(responses)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: next(reports))
    path = tools.run_visual_agent(SOURCE, "理解输入关系", tmp_path / "run")
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert "visual_object_edits.py" in run["code_sha256"]
    assert len(run["history"]) == 2
    directory = path.parent / "revision-01"
    tools.verify_revision(directory)
    spec = json.loads((directory / "specs.json").read_text(encoding="utf-8"))[0]
    assert spec["diagram"]["edges"][0]["label"] == "输入数据"
    raw = json.loads((directory / "raw_tool_request.json").read_text(encoding="utf-8"))
    assert raw["arguments"]["updates"][0]["edge"] == {"source": "a", "target": "b"}


def test_agent_rejects_bulk_edit_after_one_label_review_and_preserves_parent(
    tmp_path, monkeypatch,
):
    candidate = base()
    candidate["visuals"][0]["edges"][0]["label"] = "采集数据"
    selector = {"visual_id": "main", "edge": {"source": "a", "target": "b"}}
    replies = iter([
        {"tool": "create", "arguments": candidate},
        {"tool": "revise", "arguments": {"updates": [
            {**selector, "set": {"label": "采集"}},
            {"visual_id": "main", "set": {"kind": "comparison"}},
        ]}},
        {"tool": "revise", "arguments": {"updates": [
            {**selector, "set": {"label": "采集"}},
        ]}},
    ])
    requests, reviews = [], []

    def planner(prompt, **kwargs):
        requests.append(json.loads(prompt))
        return json.dumps(next(replies), ensure_ascii=False)

    def review(directory, **kwargs):
        reviews.append(str(directory))
        return {
            "verdict": "REVISE" if len(reviews) == 1 else "ACCEPT",
            "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 4),
            "issues": ([{"visual_id": "main", "category": "spacing",
                         "issue": "连线标签‘采集数据’过长", "change": "将标签缩短"}]
                       if len(reviews) == 1 else []),
            "reason": "只调整一个标签",
        }

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", review)
    run_path = tools.run_visual_agent(SOURCE, "采集流程", tmp_path / "run", max_iterations=3)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(reviews) == 2
    assert requests[1]["repair_scope"]["target"] == requests[2]["repair_scope"]["target"]
    assert (requests[1]["repair_scope"]["review_sha256"]
            == requests[2]["repair_scope"]["review_sha256"])
    assert requests[1]["tools"][0]["arguments"] == {
        "updates": tools.TOOLS[1]["arguments"]["updates"]
    }
    assert run["history"][1]["status"] == "FAILED_PRESERVED"
    original = json.loads((run_path.parent / "revision-00/specs.json").read_text(encoding="utf-8"))
    revised = json.loads((run_path.parent / "revision-02/specs.json").read_text(encoding="utf-8"))
    original[0]["edges"][0]["label"] = "采集"
    assert revised == original
    from textbook2video.research.visual_interface import planner_view

    failed_base = tools.revision_edit_base(run_path.parent / "revision-01")
    assert failed_base == tools.revision_edit_base(run_path.parent / "revision-00")
    assert (planner_view(failed_base, unified_graphs=True)["visuals"]
            == requests[1]["previous_candidate"]["visuals"])


def test_semantic_review_offers_complete_replacement_with_full_validation(
    tmp_path, monkeypatch,
):
    original, replacement = base(), base()
    replacement["visuals"][0]["edges"][0]["label"] = "采集"
    replies = iter([
        {"tool": "create", "arguments": original},
        {"tool": "revise", "arguments": {**replacement, "updates": [{
            "visual_id": "main", "set": {"kind": "comparison"},
        }]}},
        {"tool": "revise", "arguments": replacement},
    ])
    requests, reviews = [], []

    def planner(prompt, **kwargs):
        requests.append(json.loads(prompt))
        return json.dumps(next(replies), ensure_ascii=False)

    def review(directory, **kwargs):
        reviews.append(directory)
        return {
            "verdict": "REVISE" if len(reviews) == 1 else "ACCEPT",
            "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 4),
            "checks": {"accuracy": len(reviews) > 1, "relevance": True,
                       "completeness": True, "readability": True},
            "issues": ([{"visual_id": "main", "category": "factual_error",
                         "issue": "边关系表述不准确", "change": "重设计关系"}]
                       if len(reviews) == 1 else []),
            "reason": "fixture",
        }

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", review)
    path = tools.run_visual_agent(SOURCE, "采集流程", tmp_path / "run", max_iterations=3)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert requests[1]["repair_mode"] == "structural_replacement"
    assert "visuals" in requests[1]["tools"][0]["arguments"]
    assert "updates" not in requests[1]["tools"][0]["arguments"]
    assert state["history"][1]["status"] == "FAILED_PRESERVED"
    assert json.loads((path.parent / "revision-02/specs.json").read_text(
        encoding="utf-8"
    ))[0]["edges"][0]["label"] == "采集"
    assert tools.revision_edit_base(path.parent / "revision-00")["visuals"][0][
        "edges"
    ][0].get("label") is None


def test_missing_fact_panel_preserves_reviewed_graph_and_exact_narration_partition():
    original = base()
    reviewed = deepcopy(original)
    review = {"issues": [{"category": "missing_content", "issue": "最后一步缺失"}],
              "checks": {"accuracy": True, "relevance": True, "completeness": False}}
    assert can_append_missing_panel(review, original, SOURCE)
    panel = deepcopy(original["visuals"][0])
    panel["id"] = "later"
    panel["title"] = "后续步骤"
    result = expand_missing_panel({
        "panel": panel,
        "existing_narration_refs": ["narration-001", "narration-002"],
        "panel_narration_refs": ["narration-003"],
    }, original, SOURCE)
    assert original == reviewed
    assert result["visuals"][0] == {
        **reviewed["visuals"][0],
        "narration_refs": ["narration-001", "narration-002"],
    }
    result, _ = tools.materialize_narration_refs(result, SOURCE)
    assert [v["narration_span"] for v in result["visuals"]] == [
        "采集数据。处理数据。", "显示结果。",
    ]
    for bad in [
        {"existing_narration_refs": ["narration-001"],
         "panel_narration_refs": ["narration-003"]},
        {"existing_narration_refs": ["narration-001", "narration-003"],
         "panel_narration_refs": ["narration-002"]},
        {"existing_narration_refs": ["narration-001", "narration-002"],
         "panel_narration_refs": ["narration-002", "narration-003"]},
    ]:
        with pytest.raises(ValueError, match="partition"):
            expand_missing_panel({"panel": panel, **bad}, original, SOURCE)
    with pytest.raises(ValueError, match="only panel"):
        expand_missing_panel({"panel": panel, "existing_narration_refs": ["narration-001"],
                              "panel_narration_refs": ["narration-002", "narration-003"],
                              "visuals": []}, original, SOURCE)
    with pytest.raises(ValueError, match="set only"):
        expand_missing_panel({"panel": {**panel, "narration_span": "伪造"},
                              "existing_narration_refs": ["narration-001"],
                              "panel_narration_refs": ["narration-002", "narration-003"]},
                             original, SOURCE)
    review["checks"]["accuracy"] = False
    assert not can_append_missing_panel(review, original, SOURCE)


@pytest.mark.parametrize("invalid_kind", ["split", "oversize"])
def test_agent_additive_repair_keeps_reviewed_visual_after_invalid_attempt(
    tmp_path, monkeypatch, invalid_kind,
):
    original = base()
    panel = deepcopy(original["visuals"][0])
    panel.update(id="later", title="后续步骤")
    common = {"panel": panel, "existing_narration_refs": ["narration-001", "narration-002"]}
    invalid_panel = deepcopy(panel)
    invalid_panel["nodes"] += [
        {"id": f"extra-{i}", "label": "补充", "source_ref": "source-003"}
        for i in range(6)
    ]
    invalid = ({**common, "panel_narration_refs": ["narration-002", "narration-003"]}
               if invalid_kind == "split" else
               {**common, "panel": invalid_panel, "panel_narration_refs": ["narration-003"]})
    replies = iter([
        {"tool": "create", "arguments": original},
        {"tool": "revise", "arguments": invalid},
        {"tool": "revise", "arguments": {**common,
            "panel_narration_refs": ["narration-003"]}},
    ])
    requests, reviews = [], []

    def planner(prompt, **kwargs):
        requests.append(json.loads(prompt))
        return json.dumps(next(replies), ensure_ascii=False)

    def review(directory, **kwargs):
        reviews.append(directory)
        return {
            "verdict": "REVISE" if len(reviews) == 1 else "ACCEPT",
            "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 4),
            "checks": {"accuracy": True, "relevance": True,
                       "completeness": len(reviews) > 1, "readability": True},
            "issues": ([{"visual_id": "main", "category": "missing_content",
                         "issue": "最后一步未绘出", "change": "增加独立的后续图"}]
                       if len(reviews) == 1 else []),
            "reason": "fixture",
        }

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", review)
    path = tools.run_visual_agent(
        SOURCE, "完整处理", tmp_path / "run", narration_text=SOURCE,
        page_context=[], max_iterations=3,
    )
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert state["history"][1]["status"] == "FAILED_PRESERVED"
    assert requests[1]["repair_mode"] == requests[2]["repair_mode"] == "append_missing_panel"
    assert "visuals" not in requests[2]["tools"][0]["arguments"]
    assert len(reviews) == 2
    first = json.loads((path.parent / "revision-00/specs.json").read_text(encoding="utf-8"))
    accepted = json.loads((path.parent / "revision-02/specs.json").read_text(encoding="utf-8"))
    assert [{k: v for k, v in item.items() if k not in {"narration_refs", "narration_span"}}
            for item in accepted[:1]] == first
    assert "".join(v["narration_span"] for v in accepted) == SOURCE
    assert [v["id"] for v in accepted] == ["main", "later"]
    accepted_args = json.loads((path.parent / "revision-02/request.json").read_text(
        encoding="utf-8"
    ))["arguments"]
    assert accepted_args["page_plan"]["coverage"] == []


def test_different_invalid_updates_do_not_collapse_into_one_repeated_state(tmp_path, monkeypatch):
    responses = iter([
        {"tool": "create", "arguments": base()},
        *[{"tool": "revise", "arguments": {"updates": [
            {"visual_id": "main", "node_id": ident, "set": {"label": "不可猜"}}
        ]}} for ident in ("unknown-a", "unknown-b")],
    ])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(responses)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: {
        "verdict": "REVISE", "scores": {"accuracy": 1},
    })
    path = tools.run_visual_agent(SOURCE, "输入关系", tmp_path / "run")
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["status"] == "STOPPED_ITERATION_BUDGET" and len(run["history"]) == 3
    assert run["history"][1]["state_sha256"] != run["history"][2]["state_sha256"]


def test_noop_object_update_still_stops_as_a_repeated_semantic_state(tmp_path, monkeypatch):
    responses = iter([
        {"tool": "create", "arguments": base()},
        {"tool": "revise", "arguments": {"updates": [
            {"visual_id": "main", "set": {"title": "数据处理"}}
        ]}},
    ])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(responses)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: {
        "verdict": "REVISE", "scores": {"accuracy": 1},
    })
    path = tools.run_visual_agent(SOURCE, "输入关系", tmp_path / "run")
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["status"] == "STOPPED_REPEATED_STATE" and run["accepted_revision"] is None


def test_revision_stage_rejects_recreation_but_preserves_the_base_for_next_update(
    tmp_path, monkeypatch,
):
    recreated = base()
    recreated["visuals"][0]["nodes"][0]["label"] = "错误重建，不应使用"
    replies = iter([
        {"tool": "create", "arguments": base()},
        {"tool": "create", "arguments": recreated},
        {"tool": "revise", "arguments": {"updates": [
            {"visual_id": "main", "node_id": "b", "set": {"label": "处理输入数据"}}
        ]}},
    ])
    reviews = iter([
        {"verdict": verdict, "issues": [], "reason": "Fixture review",
         "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), score)}
        for verdict, score in [("REVISE", 2), ("ACCEPT", 4)]
    ])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(replies)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: next(reviews))
    path = tools.run_visual_agent(SOURCE, "数据处理", tmp_path / "run")
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["status"] == "MODEL_REVIEWED_PENDING_HUMAN" and len(run["history"]) == 3
    assert "updates only" in run["history"][1]["error"]
    tools.verify_revision(path.parent / "revision-02")
    specs = json.loads((path.parent / "revision-02/specs.json").read_text(encoding="utf-8"))
    assert specs[0]["nodes"][0]["label"] == "采集"
    assert specs[0]["nodes"][1]["label"] == "处理输入数据"
