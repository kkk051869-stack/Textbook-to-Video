"""Offline engineering checks; none of these tests certifies model semantic truth."""

import json
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_draft_graph import (
    apply_draft_updates,
    draft_edit_contract,
    read_draft,
)

SOURCE = "根部保存水分。叶片释放水汽。"


def candidate():
    return {
        "visuals": [
            {
                "id": "water",
                "kind": "network",
                "title": "水分保存",
                "teaching_goal": "理解水分保存",
                "narration_refs": ["narration-001", "narration-002"],
                "nodes": [
                    {"id": "root", "label": "根部", "role": "entity", "source_ref": ["source-001"]},
                    {"id": "water", "label": "水分", "role": "data", "source_ref": ["source-001"]},
                ],
                "edges": [
                    {
                        "source": "root",
                        "target": "water",
                        "relation": "produces",
                        "source_ref": ["source-001"],
                    }
                ],
            }
        ]
    }


def failed(tmp_path, args=None, **kwargs):
    parent = tmp_path / "parent"
    with pytest.raises(ValueError):
        tools.dispatch(
            "create",
            args or candidate(),
            source=SOURCE,
            output_dir=parent,
            narration_text=SOURCE,
            automatic_layout=True,
            render=False,
            **kwargs,
        )
    tools.verify_failure(parent)
    return parent


def patch(parent, fields, target_id=None):
    contract = draft_edit_contract(parent)
    return {
        "parent": str(parent),
        "reason": "Repair exactly the located relation",
        "updates": [{"target_id": target_id or contract["target_id"], "set": fields}],
    }


def test_failed_semantics_retains_draft_then_local_patch_preserves_other_objects(tmp_path):
    parent = failed(tmp_path)
    original_bytes = (parent / "draft-graph.json").read_bytes()
    before = read_draft(parent)
    assert before["candidate"] == candidate()
    assert len(before["expected_narration_units"]) == 2
    assert (
        before["materialized_source_snapshot"]["visuals"][0]["nodes"][0]["evidence"]
        == "根部保存水分。"
    )
    contract = draft_edit_contract(parent)
    assert contract["selector"] == {
        "visual_id": "water",
        "edge": {"source": "root", "target": "water"},
    }
    child = tools.dispatch(
        "revise",
        patch(parent, {"relation": "stores"}),
        source=SOURCE,
        output_dir=tmp_path / "child",
        render=False,
        automatic_layout=True,
    )
    tools.verify_revision(child.parent)
    after = read_draft(child.parent)
    assert (parent / "draft-graph.json").read_bytes() == original_bytes
    assert after["parent"]["sha256"] == before["sha256"]
    assert after["narration_text"] == SOURCE
    assert after["candidate"]["visuals"][0]["nodes"] == before["candidate"]["visuals"][0]["nodes"]
    for node in (o for o in before["objects"] if o["kind"] == "node"):
        assert node in after["objects"]
    assert any(o["stable_id"] == contract["target_id"] for o in after["objects"])
    assert after["semantic_status"] == "UNCONFIRMED"


@pytest.mark.parametrize(
    "fields",
    [
        {"role": "process"},
        {"stored_by": "root"},
        {"refers_to": "root"},
        {"source": "water"},
        {"narration_refs": ["narration-001"]},
        {"source_ref": ["source-002"]},
    ],
)
def test_local_patch_rejects_unauthorized_fields_and_new_source_bindings(tmp_path, fields):
    parent = failed(tmp_path)
    with pytest.raises(ValueError):
        apply_draft_updates(parent, patch(parent, fields))
    tools.verify_failure(parent)


def test_patch_target_and_parent_result_are_sealed(tmp_path):
    parent = failed(tmp_path)
    authorized_patch = patch(parent, {"relation": "stores"})
    with pytest.raises(ValueError, match="stable target_id"):
        apply_draft_updates(parent, patch(parent, {"relation": "stores"}, "node-unreviewed"))
    result_path = parent / "draft-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["details"]["draft_fields"].append("role")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="hash drift"):
        apply_draft_updates(parent, patch(parent, {"relation": "stores"}))
    failure_path = parent / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["draft_result_sha256"] = tools.digest(result)
    failure_path.write_text(json.dumps(failure), encoding="utf-8")
    with pytest.raises(ValueError, match="scope binding drift"):
        apply_draft_updates(parent, authorized_patch)


def test_raw_response_hash_and_invalid_narration_responsibility_survive_failure(tmp_path):
    raw = tmp_path / "response.txt"
    raw.write_text(json.dumps(candidate()), encoding="utf-8")
    parent = failed(tmp_path, model_response_path=raw)
    raw.write_text("changed model response", encoding="utf-8")
    with pytest.raises(tools.RevisionIntegrityError, match="raw response hash drift"):
        tools.verify_failure(parent)
    incomplete = candidate()
    incomplete["visuals"][0]["narration_refs"] = ["narration-001"]
    other = tmp_path / "other"
    other.mkdir()
    parent = failed(other, incomplete)
    draft = read_draft(parent)
    assert len(draft["expected_narration_units"]) == 2
    assert any(d["stage"] == "narration" for d in draft["diagnostics"])
    assert draft_edit_contract(parent) is None


def test_duplicate_local_ids_preserve_raw_without_fabricating_stable_ids(tmp_path):
    bad = candidate()
    bad["visuals"][0]["nodes"][1]["id"] = "root"
    parent = failed(tmp_path, bad)
    draft = read_draft(parent)
    assert draft["objects"] == []
    assert draft["candidate"] == bad
    assert any(d["stage"] == "identity" for d in draft["diagnostics"])


def capacity_candidate():
    args = candidate()
    visual = args["visuals"][0]
    visual["nodes"] = [
        {"id": f"n{i}", "label": f"位置{i}", "source_ref": ["source-001"]} for i in range(10)
    ]
    visual["edges"] = [
        {"source": f"n{i}", "target": f"n{i + 1}", "source_ref": ["source-001"]} for i in range(9)
    ]
    return args


def test_missing_visual_id_and_capacity_preserve_draft_evidence(tmp_path):
    from textbook2video.research.visual_draft_graph import save_draft

    args = capacity_candidate()
    del args["visuals"][0]["id"]
    (tmp_path / "raw_tool_request.json").write_text(json.dumps(args), encoding="utf-8")
    draft = save_draft(tmp_path, args, source=SOURCE, narration=SOURCE)
    assert read_draft(tmp_path) == draft
    assert draft["candidate"] == args
    assert draft["objects"] == []
    assert {d["stage"] for d in draft["diagnostics"]} == {"identity", "capacity"}
    capacity = next(d for d in draft["diagnostics"] if d["stage"] == "capacity")
    assert capacity == {"stage": "capacity", "visual_id": None, "actual": 10, "maximum": 8}


def test_agent_feedback_keeps_capacity_and_role_error(tmp_path, monkeypatch):
    wrong = capacity_candidate()
    for node in wrong["visuals"][0]["nodes"]:
        node["role"] = "entity"
    wrong["visuals"][0]["edges"][0]["relation"] = "changes"
    requests = []

    def planner(payload, **kwargs):
        request = json.loads(payload)
        requests.append(request)
        if len(requests) == 2:
            assert request["visual_plan_contract"]["mode"] == "structural_replacement"
            assert "representation_rules" not in request
            assert tools.REPRESENTATION_RULES in kwargs["system_prompt"]
            assert "complete VisualPlanV1 replacement" in request["recovery_contract"]
            assert "incompatible subject/object roles" in request["feedback"]["validation_error"]
            assert request["feedback"]["draft_diagnostics"] == [
                {"stage": "capacity", "visual_id": "water", "actual": 10, "maximum": 8}
            ]
        return json.dumps({"plan_version": "visual-plan-v1", **wrong})

    monkeypatch.setattr(tools, "chat_with_system", planner)
    tools.run_visual_agent(SOURCE, "保存水分", tmp_path / "agent",
                           narration_text=SOURCE, max_iterations=2)
    assert len(requests) == 2


def test_compile_failure_uses_sealed_renderer_updates_before_first_review(tmp_path, monkeypatch):
    from test_visual_tools import review

    args = candidate()
    args["visuals"][0]["edges"][0]["relation"] = "stores"
    args["visuals"][0]["nodes"][1]["stored_by"] = "root"
    requests = []
    original_compile = tools.compile_visuals
    compile_calls = []

    def compile_once(*a, **kw):
        compile_calls.append(a)
        if len(compile_calls) == 1:
            raise ValueError("offline simulated geometry failure")
        return original_compile(*a, **kw)

    def planner(payload, **kwargs):
        request = json.loads(payload)
        requests.append(request)
        if len(requests) == 1:
            return json.dumps({"plan_version": "visual-plan-v1", **args})
        assert request["visual_plan_contract"]["mode"] == "updates"
        assert request["phase"] == "revise_existing_visual"
        assert "draft_edit_contract" not in request
        node = request["previous_candidate"]["visuals"][0]["nodes"][1]
        assert "保存者: 根部" in node["detail"]
        assert "stored_by" not in node and "role" not in node
        return json.dumps({"plan_version": "visual-plan-v1", "updates": [
            {"visual_id": "water", "node_id": "root", "set": {"label": "根部保存者"}}]})

    monkeypatch.setattr(tools, "compile_visuals", compile_once)
    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: review("REJECT", 0))
    output = tmp_path / "agent"
    tools.run_visual_agent(SOURCE, "保存水分", output, narration_text=SOURCE, max_iterations=2)
    assert len(requests) == len(compile_calls) == 2
    tools.verify_failure(output / "revision-00")
    tools.verify_revision(output / "revision-01")
    old = read_draft(output / "revision-00")
    assert old["candidate"] == args
    new = json.loads((output / "revision-01/specs.json").read_text(encoding="utf-8"))[0]
    assert new["nodes"][0]["label"] == "根部保存者"
    assert "保存者: 根部" in new["nodes"][1]["detail"]


def split_candidate():
    original = capacity_candidate()["visuals"][0]
    left, right = deepcopy(original), deepcopy(original)
    left.update(
        id="left",
        nodes=left["nodes"][:5],
        edges=left["edges"][:4],
        narration_refs=["narration-001"],
    )
    right.update(
        id="right",
        nodes=right["nodes"][4:],
        edges=right["edges"][4:],
        narration_refs=["narration-002"],
    )
    return {"visuals": [left, right]}


def test_ten_node_split_preserves_nodes_edges_sources_and_full_narration(tmp_path):
    parent = failed(tmp_path, capacity_candidate())
    assert draft_edit_contract(parent) is None
    replacement = {**split_candidate(), "parent": str(parent), "reason": "Split oversized panel"}
    child = tools.dispatch(
        "revise",
        replacement,
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "split",
        render=False,
        automatic_layout=True,
    )
    tools.verify_revision(child.parent)
    draft = read_draft(child.parent)
    old = read_draft(parent)
    assert len(draft["lineage"]) >= 19  # Every old node/edge has a retained exact mapping.
    assert draft["source_sha256"] == old["source_sha256"]
    assert draft["narration_sha256"] == old["narration_sha256"]
    assert not draft["diagnostics"]
    bad = split_candidate()
    bad["visuals"][0]["nodes"].pop(0)
    bad["visuals"][0]["edges"].pop(0)
    with pytest.raises(ValueError, match="split lost"):
        tools.dispatch(
            "revise",
            {**bad, "parent": str(parent), "reason": "Drop a fact"},
            source=SOURCE,
            narration_text=SOURCE,
            output_dir=tmp_path / "loss",
            automatic_layout=True,
            render=False,
        )


def test_source_and_narration_cannot_drift_during_replacement(tmp_path):
    parent = failed(tmp_path)
    replacement = candidate()
    replacement.update(parent=str(parent), reason="Replacement")
    with pytest.raises(ValueError, match="cannot change.*narration"):
        tools.dispatch(
            "revise",
            replacement,
            source=SOURCE,
            narration_text="改写的旁白。",
            output_dir=tmp_path / "drift",
            automatic_layout=True,
            render=False,
        )


def test_connected_intermediate_subgraph_only_replaces_selected_relation(tmp_path):
    parent = failed(tmp_path)
    fields = {
        "nodes": [
            {"id": "storage", "label": "保存过程", "role": "process", "source_ref": ["source-001"]}
        ],
        "edges": [
            {
                "source": "root",
                "target": "storage",
                "relation": "association",
                "source_ref": ["source-001"],
            },
            {
                "source": "storage",
                "target": "water",
                "relation": "produces",
                "source_ref": ["source-001"],
            },
        ],
    }
    result, _ = apply_draft_updates(parent, patch(parent, fields))
    visual = result["visuals"][0]
    assert visual["nodes"][:2] == candidate()["visuals"][0]["nodes"]
    assert visual["edges"] == fields["edges"]
    # This checks authorized graph operations only; it does not certify the new explanation.
    assert read_draft(parent)["semantic_status"] == "UNCONFIRMED"
    fields["nodes"][0]["narration_refs"] = ["narration-001"]
    with pytest.raises(ValueError, match="unauthorized fields"):
        apply_draft_updates(parent, patch(parent, fields))


def test_ownership_fields_remain_in_draft_and_materialize_visible_owner_and_referent(tmp_path):
    args = candidate()
    visual = args["visuals"][0]
    visual["edges"][0]["relation"] = "stores"
    visual["nodes"][1].update(stored_by="root", refers_to="root")
    result = tools.dispatch(
        "create",
        args,
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "owner",
        automatic_layout=True,
        render=False,
    )
    raw = read_draft(result.parent)["candidate"]["visuals"][0]["nodes"][1]
    assert raw["stored_by"] == raw["refers_to"] == "root"
    specs = json.loads((result.parent / "specs.json").read_text(encoding="utf-8"))
    assert "保存者: 根部" in specs[0]["nodes"][1]["detail"]
    assert "所指对象: 根部" in specs[0]["nodes"][1]["detail"]


def test_role_legal_wrong_direction_is_never_marked_semantically_confirmed(tmp_path):
    args = candidate()
    args["visuals"][0]["edges"][0].update(source="water", target="root", relation="causes")
    path = tools.dispatch(
        "create",
        args,
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "wrong-direction",
        automatic_layout=True,
        render=False,
    )
    # An exact quotation and a legal role pair do not entail this reversed causal claim.
    assert read_draft(path.parent)["semantic_status"] == "UNCONFIRMED"
    assert json.loads(path.read_text(encoding="utf-8"))["human_review"] == "NOT_REVIEWED"


def test_legacy_revision_without_draft_remains_readable_and_manually_editable(tmp_path):
    args = candidate()
    args["visuals"][0]["edges"][0]["relation"] = "stores"
    path = tools.dispatch(
        "create",
        args,
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "legacy",
        render=False,
        automatic_layout=True,
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    for key in ("draft_sha256", "draft_result_sha256", "execution_sha256"):
        record.pop(key)
    record["execution_sha256"] = tools.digest(record)
    path.write_text(json.dumps(record), encoding="utf-8")
    (path.parent / "draft-graph.json").unlink()
    (path.parent / "draft-result.json").unlink()
    tools.verify_revision(path.parent)
    child = tools.dispatch(
        "revise",
        {
            "parent": str(path.parent),
            "reason": "Manual old interface",
            "updates": [{"visual_id": "water", "node_id": "root", "set": {"detail": "保存水分"}}],
        },
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "new-child",
        render=False,
        automatic_layout=True,
    )
    tools.verify_revision(child.parent)
    assert read_draft(child.parent)["parent"]["sha256"] is None
    assert read_draft(child.parent)["parent"]["revision_record"]["path"] == str(path.resolve())


def test_agent_selects_draft_updates_and_binds_model_raw_before_materialization(
    tmp_path, monkeypatch
):
    from test_visual_tools import review

    output = tmp_path / "agent"
    requests = []
    original_materialize = tools.materialize_semantic_graphs

    def materialize(arguments):
        assert list(output.glob("revision-*/draft-graph.json"))
        return original_materialize(arguments)

    def planner(payload, **kwargs):
        request = json.loads(payload)
        requests.append(request)
        if len(requests) == 1:
            return json.dumps({"plan_version": "visual-plan-v1", **candidate()})
        assert request["repair_mode"] == request["visual_plan_contract"]["mode"] == "draft_updates"
        assert "edit_contract" not in request
        assert request["recovery_contract"] == tools.DRAFT_UPDATE_RULES
        assert tools.DRAFT_UPDATE_RULES in kwargs["system_prompt"]
        assert "complete VisualPlanV1 replacement" not in payload
        return json.dumps(
            {
                "plan_version": "visual-plan-v1",
                "updates": [
                    {
                        "target_id": request["draft_edit_contract"]["target_id"],
                        "set": {"relation": "stores"},
                    }
                ],
            }
        )

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "materialize_semantic_graphs", materialize)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: review("REJECT", 0))
    run = tools.run_visual_agent(
        SOURCE, "保存水分", output, narration_text=SOURCE, max_iterations=2
    )
    state = json.loads(run.read_text(encoding="utf-8"))
    assert len(requests) == len(state["history"]) == 2
    assert state["status"] == "STOPPED_REVIEW_REJECTED"
    assert state["accepted_revision"] is None
    draft = read_draft(output / "revision-01")
    assert draft["raw_response"]["path"] == str((output / "model-response-1.txt").resolve())
    assert draft["semantic_status"] == "UNCONFIRMED"


def test_full_replacement_can_correct_a_wrong_existing_citation_without_changing_source(tmp_path):
    wrong = candidate()
    for value in wrong["visuals"][0]["nodes"] + wrong["visuals"][0]["edges"]:
        value["source_ref"] = ["source-002"]
    parent = failed(tmp_path, wrong)
    corrected = candidate()
    corrected["visuals"][0]["edges"][0]["relation"] = "stores"
    path = tools.dispatch(
        "revise",
        {**corrected, "parent": str(parent), "reason": "Correct citation"},
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "corrected",
        automatic_layout=True,
        render=False,
    )
    draft = read_draft(path.parent)
    assert draft["source_sha256"] == read_draft(parent)["source_sha256"]
    assert draft["source_reference_delta"] == {"added": ["source-001"], "removed": ["source-002"]}
    assert read_draft(parent)["selected_source_refs"] == ["source-002"]


def test_capacity_split_can_repair_located_invalid_edge_while_preserving_other_objects(tmp_path):
    wrong = capacity_candidate()
    visual = wrong["visuals"][0]
    for i, node in enumerate(visual["nodes"]):
        node["role"] = "entity" if i == 0 else "data"
    visual["edges"][0]["relation"] = "produces"
    parent = failed(tmp_path, wrong)
    left, right = deepcopy(visual), deepcopy(visual)
    left.update(
        id="left",
        nodes=left["nodes"][:5],
        edges=left["edges"][:4],
        narration_refs=["narration-001"],
    )
    right.update(
        id="right",
        nodes=right["nodes"][4:],
        edges=right["edges"][4:],
        narration_refs=["narration-002"],
    )
    left["edges"][0]["relation"] = "stores"
    path = tools.dispatch(
        "revise",
        {
            "visuals": [left, right],
            "parent": str(parent),
            "reason": "Split and repair the located edge",
        },
        source=SOURCE,
        narration_text=SOURCE,
        output_dir=tmp_path / "fixed-split",
        render=False,
        automatic_layout=True,
    )
    draft = read_draft(path.parent)
    assert len(draft["preservation"]["protected_parent_ids"]) == 18
    assert draft["preservation"]["known_invalid_selector"] == {
        "visual_id": "water",
        "edge": {"source": "n0", "target": "n1"},
    }
    assert not draft["diagnostics"]
