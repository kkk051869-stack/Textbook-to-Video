from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_grammar import GRAMMAR_VERSION, render_visual, validate_visual

SOURCE = "传感器采集数据，处理器分析数据，屏幕显示结果。"


def graph(kind="flow", count=3):
    nodes = [
        {"id": f"n{i}", "label": label, "evidence": SOURCE}
        for i, label in enumerate(
            ["采集", "分析", "显示", "反馈", "存储", "检索", "使用", "检查"][:count]
        )
    ]
    edges = [
        {"source": nodes[i - 1]["id"], "target": nodes[i]["id"], "evidence": SOURCE}
        for i in range(1, count)
    ]
    if kind == "cycle":
        edges.append({"source": nodes[-1]["id"], "target": nodes[0]["id"], "evidence": SOURCE})
    return {
        "id": "main",
        "schema_version": GRAMMAR_VERSION,
        "kind": kind,
        "title": "数据处理",
        "teaching_goal": "理解信息处理关系",
        "nodes": nodes,
        "edges": edges,
    }


def test_protocol_normalization_defaults_metadata_but_never_rewrites_semantics():
    spec = graph()
    del spec["schema_version"]
    args = {"visuals": [spec]}
    normalized, messages = tools.normalize_visual_arguments(args)
    assert normalized["visuals"][0]["schema_version"] == GRAMMAR_VERSION
    assert normalized["visuals"][0]["nodes"] == spec["nodes"]
    assert normalized["visuals"][0]["edges"] == spec["edges"]
    assert "schema_version" not in args["visuals"][0] and messages
    args["visuals"][0]["schema_version"] = "unsupported-explicit-version"
    explicit, _ = tools.normalize_visual_arguments(args)
    with pytest.raises(ValueError, match="version"):
        validate_visual(explicit["visuals"][0], SOURCE)
    nested = {"visuals": [{"id": "x", "kind": "relationship", "diagram": {"title": "明确标题"}}]}
    moved, _ = tools.normalize_visual_arguments(nested)
    assert moved["visuals"][0]["title"] == "明确标题"
    assert "title" in nested["visuals"][0]["diagram"]
    empty, _ = tools.normalize_visual_arguments({"visuals": [{"id": "x", "kind": "relationship"}]})
    assert "title" not in empty["visuals"][0]


def review(verdict="ACCEPT", score=4):
    return {
        "verdict": verdict,
        "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], score),
        "issues": [],
        "reason": "checked source and rendered pixels",
    }


def reviewable_revision(tmp_path, monkeypatch):
    directory = tmp_path / "reviewable"

    def preview(output_dir, **kwargs):
        (output_dir / "geometry.json").write_text("[]", encoding="utf-8")
        return []

    monkeypatch.setattr(tools, "preview_revision", preview)
    plan = {
        "support_element_ids": [], "replaces_element_ids": ["note"],
        "reason": "Processing shown in the diagram",
        "coverage": [{"element_id": "note", "decision": "represented",
                      "reason": "Same processing", "source_evidence": SOURCE,
                      "visual_refs": ["main"], "fact_quotes": ["采集和分析"]}],
    }
    tools.dispatch("create", {"visuals": [graph()], "page_plan": plan},
                   source=SOURCE, output_dir=directory,
                   page_context=[{"id": "note", "type": "text", "text": "采集和分析"}],
                   teaching_goal="理解采集、分析与显示的完整关系", narration_text=SOURCE)
    return directory


def test_review_protocol_repair_keeps_same_diagram_and_complete_coverage(tmp_path, monkeypatch):
    directory = reviewable_revision(tmp_path, monkeypatch)
    before = (directory / "specs.json").read_bytes()
    fixed = review()
    fixed["coverage"] = [{"element_id": "note", "verdict": "covered", "reason": "Visible"}]
    replies = iter([review(), fixed])
    calls = []

    def chat(request, **kwargs):
        calls.append((json.loads(request), kwargs["timeout"]))
        return json.dumps(next(replies))

    monkeypatch.setattr(tools, "chat_with_system", chat)
    result = tools.review_revision(directory, model="test", timeout=120)
    assert result["verdict"] == "ACCEPT" and result["protocol_repairs"] == 1
    assert len(calls) == 2 and calls[1][1] <= calls[0][1] <= 120
    assert calls[0][0]["specs"] == calls[1][0]["specs"]
    assert calls[0][0]["required_coverage_element_ids"] == ["note"]
    assert calls[0][0]["teaching_goal"] == "理解采集、分析与显示的完整关系"
    assert calls[0][0]["narration_text"] == SOURCE
    assert (directory / "specs.json").read_bytes() == before
    assert (directory / "review-response.txt").is_file()
    assert (directory / "review-response-retry-1.txt").is_file()
    tools.verify_revision(directory)


@pytest.mark.parametrize("prior_verdict", ["REJECT", "REVISE"])
def test_review_protocol_repair_never_erases_semantic_refusal(tmp_path, monkeypatch, prior_verdict):
    directory = reviewable_revision(tmp_path, monkeypatch)
    invalid = review(prior_verdict)
    invalid["issues"] = [{"visual_id": "main", "issue": "Wrong direction", "change": "Fix edge"}]
    fixed = review()
    fixed["coverage"] = [{"element_id": "note", "verdict": "covered", "reason": "Visible"}]
    replies = iter([invalid, fixed])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(replies)))
    result = tools.review_revision(directory, model="test")
    assert result["verdict"] == prior_verdict
    assert result["issues"] == invalid["issues"]


def test_exhausted_review_protocol_stops_without_asking_planner_to_change_art(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    planner_calls = []

    def plan(*args, **kwargs):
        planner_calls.append(args)
        return json.dumps({"tool": "create", "arguments": {"visuals": [graph()]}})

    monkeypatch.setattr(tools, "chat_with_system", plan)

    def bad_review(*args, **kwargs):
        raise tools.ReviewResponseError("review response invalid after one repair")

    monkeypatch.setattr(tools, "review_revision", bad_review)
    path = tools.run_visual_agent(SOURCE, "理解数据处理", tmp_path / "run")
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "STOPPED_REVIEW_PROTOCOL"
    assert len(planner_calls) == 1 and state["accepted_revision"] is None


def test_review_protocol_retry_is_bounded_and_preserves_both_failures(tmp_path, monkeypatch):
    directory = reviewable_revision(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: calls.append(a) or "{}")
    with pytest.raises(tools.ReviewResponseError, match="after one repair"):
        tools.review_revision(directory, model="test")
    assert len(calls) == 2 and not (directory / "review.json").exists()
    assert (directory / "review-protocol-error-0.json").exists()
    assert (directory / "review-protocol-error-1.json").exists()


@pytest.mark.parametrize("problem", ["low_score", "reject_missing", "bad_verdict", "late"])
def test_review_protocol_negative_evidence_and_deadline_are_not_erased(
    tmp_path, monkeypatch, problem,
):
    directory = reviewable_revision(tmp_path, monkeypatch)
    first, second = review(), review()
    second["coverage"] = [{"element_id": "note", "verdict": "covered", "reason": "Visible"}]
    if problem == "low_score":
        first["scores"]["accuracy"] = 1
    elif problem == "reject_missing":
        first["verdict"] = "REJECT"
        second["coverage"][0]["verdict"] = "missing"
    elif problem == "bad_verdict":
        first["verdict"] = []
    clock = [0.0]
    monkeypatch.setattr(tools.time, "monotonic", lambda: clock[0])
    replies = iter([first, second])

    def chat(*args, **kwargs):
        if problem == "late":
            clock[0] = 121.0
        return json.dumps(next(replies))

    monkeypatch.setattr(tools, "chat_with_system", chat)
    if problem == "late":
        with pytest.raises(tools.ReviewResponseError, match="deadline"):
            tools.review_revision(directory, model="test", timeout=120)
        assert not (directory / "review.json").exists()
        assert (directory / "review-response.txt").exists()
        return
    result = tools.review_revision(directory, model="test", timeout=120)
    assert (directory / "review-protocol-error-0.json").exists()
    if problem == "low_score":
        assert result["verdict"] == "REVISE" and result["scores"]["accuracy"] == 1
    elif problem == "reject_missing":
        assert result["verdict"] == "REJECT"
    else:
        assert result["verdict"] == "ACCEPT"


def test_single_visual_cannot_trim_the_page_narration_scope(tmp_path):
    spec = graph()
    spec["narration_span"] = "处理器分析数据"
    with pytest.raises(ValueError, match="entire narration_text"):
        tools.dispatch(
            "create", {"visuals": [spec]}, source=SOURCE, output_dir=tmp_path / "partial",
            narration_text=SOURCE, teaching_goal="理解完整信息处理过程", render=False,
        )
    assert (tmp_path / "partial/failure.json").is_file()
    spec["narration_span"] = SOURCE
    tools.dispatch(
        "create", {"visuals": [spec]}, source=SOURCE, output_dir=tmp_path / "whole",
        narration_text=SOURCE, teaching_goal="理解完整信息处理过程", render=False,
    )


def test_sparse_graph_can_enlarge_and_turn_without_changing_teaching_relations():
    spec = graph()
    spec["edges"][0]["label"] = "传递"
    spec["nodes"][0]["detail"] = "输入信息"
    normal = ET.fromstring(render_visual({**spec, "text_scale": 1}))
    enlarged = ET.fromstring(render_visual(spec))
    vertical = ET.fromstring(render_visual({**spec, "layout_direction": "vertical"}))
    ns = {"s": "http://www.w3.org/2000/svg"}
    def font(svg):
        return float(svg.find("s:g[@data-node-id]/s:text", ns).get("font-size"))
    assert font(enlarged) == font(vertical) == font(normal) * 1.5
    for svg in (normal, enlarged, vertical):
        assert {p.get("data-edge") for p in svg.findall("s:path[@data-edge]", ns)} == {
            "n0:n1", "n1:n2",
        }
        boxes = [tuple(float(g.find("s:rect", ns).get(k))
                       for k in ("x", "y", "width", "height"))
                 for g in svg.findall("s:g[@data-node-id]", ns)]
        assert len(boxes) == 3
        assert all(x >= 10 and y >= 10 and x + w <= 1590 and y + h <= 670
                   for x, y, w, h in boxes)
    rows = [float(g.find("s:rect", ns).get("y"))
            for g in vertical.findall("s:g[@data-node-id]", ns)]
    assert rows == sorted(rows) and len(set(rows)) == 3


@pytest.mark.parametrize("scale", [0.5, True, float("nan"), 2])
def test_graph_presentation_rejects_unreadable_or_undefined_scale(scale):
    with pytest.raises(ValueError, match="text_scale"):
        validate_visual({**graph(), "text_scale": scale}, SOURCE)


@pytest.mark.parametrize("count", range(4, 9))
def test_long_linear_chain_wraps_without_rewriting_steps_or_edges(count):
    spec = graph(count=count)
    svg = ET.fromstring(render_visual(spec))
    ns = {"s": "http://www.w3.org/2000/svg"}
    nodes = svg.findall("s:g[@data-node-id]", ns)
    assert [node.get("data-node-id") for node in nodes] == [n["id"] for n in spec["nodes"]]
    assert len({node.find("s:rect", ns).get("y") for node in nodes}) >= 2
    assert {e.get("data-edge") for e in svg.findall("s:path[@data-edge]", ns)} == {
        f"{e['source']}:{e['target']}" for e in spec["edges"]
    }
    for node in nodes:
        box = node.find("s:rect", ns)
        x, y, w, h = [float(box.get(k)) for k in ("x", "y", "width", "height")]
        assert 10 <= x < x + w <= 1590 and 10 <= y < y + h <= 670
        assert float(node.find("s:text", ns).get("font-size")) >= 29 * 1.25


def test_wrapped_presentation_does_not_flatten_a_branch_or_skip_edge():
    spec = graph(count=4)
    spec["layout_direction"] = "wrapped"
    spec["edges"].append({"source": "n0", "target": "n2", "evidence": SOURCE})
    with pytest.raises(ValueError, match="linear chain"):
        render_visual(spec)


def test_graph_preserves_explicit_edges_and_arbitrary_node_count():
    spec = graph("network", 7)
    spec["edges"] = [
        spec["edges"][0],
        spec["edges"][2],
        spec["edges"][4],
        {"source": "n0", "target": "n6", "evidence": SOURCE},
    ]
    svg = ET.fromstring(render_visual(spec))
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert len(svg.findall("s:g", ns)) == 7
    actual = [p.attrib["data-edge"] for p in svg.findall("s:path", ns)]
    assert actual == ["n0:n1", "n2:n3", "n4:n5", "n0:n6"]
    rectangles = [g.find("s:rect", ns) for g in svg.findall("s:g", ns)]
    assert len({(r.get("x"), r.get("y")) for r in rectangles}) == 7


def test_cycle_closes_on_actual_first_node_and_rejects_disconnected_cycles():
    spec = graph("cycle", 3)
    assert 'data-edge="n2:n0"' in render_visual(spec)
    spec = graph("cycle", 4)
    spec["edges"] = [
        {"source": f"n{a}", "target": f"n{b}", "evidence": SOURCE}
        for a, b in [(0, 1), (1, 0), (2, 3), (3, 2)]
    ]
    with pytest.raises(ValueError, match="connected loop"):
        validate_visual(spec, SOURCE)


@pytest.mark.parametrize("kind", ["hierarchy", "part_whole"])
def test_tree_preserves_grandchild_and_rejects_multiple_parents(kind):
    spec = graph(kind)
    assert 'data-edge="n1:n2"' in render_visual(spec)
    spec["edges"].append({"source": "n0", "target": "n2", "evidence": SOURCE})
    with pytest.raises(ValueError, match="tree"):
        validate_visual(spec, SOURCE)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "3"])
def test_numeric_contract_rejects_nonfinite_and_non_numeric(bad):
    spec = {
        "schema_version": GRAMMAR_VERSION,
        "kind": "chart",
        "title": "温度",
        "teaching_goal": "观察变化",
        "unit": "摄氏度",
        "series": [{"label": "甲", "value": bad, "evidence": SOURCE}],
    }
    with pytest.raises(ValueError, match="finite"):
        validate_visual(spec, SOURCE)


def test_source_quote_is_never_taken_from_generation_instructions(tmp_path):
    spec = graph()
    spec["nodes"][0]["evidence"] = "不存在的事实"
    with pytest.raises(ValueError, match="exact source"):
        tools.dispatch(
            "create", {"visuals": [spec]}, source=SOURCE, output_dir=tmp_path / "bad", render=False
        )
    assert (tmp_path / "bad/failure.json").exists()
    assert not (tmp_path / "bad/revision.json").exists()


def test_revision_from_failed_validation_is_traceable_and_cannot_change_source(tmp_path):
    spec = graph()
    broken = deepcopy(spec)
    broken["edges"][0]["target"] = "missing"
    old = tmp_path / "r0"
    with pytest.raises(ValueError):
        tools.dispatch("create", {"visuals": [broken]}, source=SOURCE, output_dir=old, render=False)
    request = {"visuals": [spec], "parent": str(old), "reason": "repair missing target"}
    new = tools.dispatch("revise", request, source=SOURCE, output_dir=tmp_path / "r1", render=False)
    record = json.loads(new.read_text(encoding="utf-8"))
    assert record["parent"] == str(old.resolve())
    assert record["parent_sha256"]
    assert (old / "failure.json").exists()
    with pytest.raises(ValueError, match="source"):
        tools.dispatch(
            "revise", request, source="不同原文", output_dir=tmp_path / "drift", render=False
        )


def test_immutable_revision_and_safe_asset_id(tmp_path):
    tools.dispatch(
        "create", {"visuals": [graph()]}, source=SOURCE, output_dir=tmp_path / "r0", render=False
    )
    with pytest.raises(FileExistsError):
        tools.dispatch(
            "create",
            {"visuals": [graph()]},
            source=SOURCE,
            output_dir=tmp_path / "r0",
            render=False,
        )
    spec = graph()
    spec["id"] = "../../escape"
    with pytest.raises(ValueError, match="safe"):
        tools.dispatch(
            "create",
            {"visuals": [spec]},
            source=SOURCE,
            output_dir=tmp_path / "unsafe",
            render=False,
        )


def test_composition_requires_free_axis_and_splits_more_than_two():
    assert tools.compose(["a", "b", "c"])["pages"] == [["a"], ["b"], ["c"]]
    with pytest.raises(ValueError, match="free space"):
        tools.compose(["a", "b"], axis="horizontal", vertical_free=True)
    with pytest.raises(ValueError, match="free space"):
        tools.compose(["a", "b"], axis="vertical", horizontal_free=True)
    assert tools.compose(["a", "b"], axis="horizontal", horizontal_free=True)["pages"] == [
        ["a", "b"]
    ]


def test_agent_uses_review_feedback_and_preserves_all_revisions(monkeypatch, tmp_path):
    replies = iter([
        {"tool": "create", "arguments": {"visuals": [graph()]}},
        {"tool": "revise", "arguments": {"updates": [
            {"visual_id": "main", "node_id": "n0", "set": {"label": "数据采集"}}
        ]}},
    ])
    reviews = iter([review("REVISE", 2), review()])
    calls = []

    def planner(prompt, **kwargs):
        assert kwargs["extra_body"] == {"response_format": {"type": "json_object"}}
        calls.append(json.loads(prompt))
        return json.dumps(next(replies))

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: next(reviews))
    path = tools.run_visual_agent(SOURCE, "理解信息处理", tmp_path / "run")
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(result["history"]) == 2
    assert result["planning_response_format"] == "json_object"
    assert calls[1]["feedback"]["verdict"] == "REVISE"
    assert calls[1]["phase"] == "revise_existing_visual"
    assert [tool["name"] for tool in calls[1]["tools"]] == ["revise"]
    assert "optional_relationship_schema" not in calls[1]
    assert (tmp_path / "run/revision-00/revision.json").exists()
    assert result["history"][1]["review"]["scores"]["accuracy"] == 4


def test_agent_detects_repeat_and_never_promotes_rejected_graph(monkeypatch, tmp_path):
    def planner(prompt, **kwargs):
        request = json.loads(prompt)
        if request.get("phase") == "revise_existing_visual":
            return json.dumps({"tool": "revise", "arguments": {"updates": [
                {"visual_id": "main", "set": {"title": "数据处理"}}
            ]}})
        return json.dumps({"tool": "create", "arguments": {"visuals": [graph()]}})

    monkeypatch.setattr(
        tools,
        "chat_with_system",
        planner,
    )
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: review("REVISE", 2))
    path = tools.run_visual_agent(SOURCE, "理解信息处理", tmp_path / "run")
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["status"] == "STOPPED_REPEATED_STATE"
    assert result["accepted_revision"] is None


def test_five_round_budget_preserves_attempts_and_still_rejects_six(monkeypatch, tmp_path):
    revisions = [graph() for _ in range(5)]
    for i, spec in enumerate(revisions):
        spec["nodes"][0]["label"] = f"数据采集{i}"
    replies = iter([
        {"tool": "create", "arguments": {"visuals": [revisions[0]]}},
        *[{"tool": "revise", "arguments": {"updates": [
            {"visual_id": "main", "node_id": "n0", "set": {"label": spec["nodes"][0]["label"]}}
        ]}} for spec in revisions[1:]],
    ])
    reports = iter([review("REVISE", i) for i in range(1, 5)] + [review()])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(replies)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: next(reports))
    path = tools.run_visual_agent(SOURCE, "完整数据处理", tmp_path / "five", max_iterations=5)
    result = json.loads(path.read_text(encoding="utf-8"))
    assert len(result["history"]) == result["max_iterations"] == 5
    assert result["accepted_revision"].endswith("revision-04")
    assert all((tmp_path / "five" / f"revision-{i:02}" / "revision.json").is_file()
               for i in range(5))
    with pytest.raises(ValueError, match="1-5 iterations"):
        tools.run_visual_agent(SOURCE, "完整数据处理", tmp_path / "six", max_iterations=6)


def test_course_adapter_consumes_only_reviewed_asset_and_preserves_timing(monkeypatch, tmp_path):
    from textbook2video.pipeline import course_visuals

    spec = graph()
    revision = tmp_path / "compiled"
    plan = {
        "support_element_ids": [],
        "replaces_element_ids": ["image"],
        "reason": "Replace diagram intent",
        "coverage": [
            {
                "element_id": "image",
                "fact_quotes": ["图示"],
                "decision": "represented",
                "visual_refs": ["main"],
                "source_evidence": SOURCE,
                "reason": "Shows the source processing steps",
            }
        ],
    }
    tools.dispatch(
        "create",
        {"visuals": [spec], "page_plan": plan},
        source=SOURCE,
        output_dir=revision,
        render=False,
    )
    report = review()
    report["coverage"] = [
        {"element_id": "image", "verdict": "covered", "reason": "The processing diagram is present"}
    ]
    saved_review = tools._save_review(
        revision, json.dumps(report), [], model="test", has_images=True
    )
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "accepted_revision": str(revision),
                "status": "MODEL_REVIEWED_PENDING_HUMAN",
                "history": [
                    {"revision": str(revision), "review_sha256": tools.digest(saved_review)}
                ],
            }
        ),
        encoding="utf-8",
    )
    budgets = []

    def plan(*args, **kwargs):
        budgets.append(kwargs["max_iterations"])
        return run_path

    monkeypatch.setattr(course_visuals, "run_visual_agent", plan)
    segment = {
        "id": "s1",
        "narration": SOURCE,
        "audio_duration_sec": 15,
        "timeline": [{"target": "image", "at_sec": 2}],
        "elements": [{"id": "image", "type": "image", "description": "图示"}],
    }
    original = deepcopy(segment)
    results = course_visuals.generate_course_visuals(
        [segment], output_dir=tmp_path, model="ecnu-plus", theme="bright"
    )
    assert results["s1:visual-primary-1"].endswith("main.svg")
    assert budgets == [5]
    for key in ("id", "narration", "audio_duration_sec"):
        assert segment[key] == original[key]
    assert segment["timeline"] == [{"target": "visual-primary-1", "at_sec": 2}]
    assert segment["elements"][0]["visual_brief_role"] == "EXPLANATORY_DIAGRAM"


def test_browser_checks_all_graph_nodes_at_final_viewports(tmp_path):
    path = tools.dispatch(
        "create",
        {"visuals": [graph("network", 7)]},
        source=SOURCE,
        output_dir=tmp_path / "network",
        theme="bright",
    )
    revision = json.loads(path.read_text(encoding="utf-8"))
    assert len(revision["geometry"]) == 2
    assert all(not r["issues"] for r in revision["geometry"])
    assert all(r["sha256"] for r in revision["geometry"])


def test_page_plan_keeps_event_times_and_records_replaced_targets():
    from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan

    segment = {
        "id": 1,
        "narration": SOURCE,
        "audio_duration_sec": 15,
        "elements": [
            {"id": "image", "type": "image"},
            {"id": "steps", "type": "flow_step", "steps": ["采集", "处理"]},
            {"id": "note", "type": "text", "text": "信息处理"},
        ],
        "timeline": [{"target": "steps,note", "start_ms": 4200}],
    }
    plan = {
        "support_element_ids": ["note"],
        "replaces_element_ids": ["steps"],
        "reason": "Main visual expresses the same processing steps",
        "coverage": [
            {
                "element_id": "steps",
                "fact_quotes": ["采集", "处理"],
                "decision": "represented",
                "visual_refs": ["main"],
                "source_evidence": SOURCE,
                "reason": "Same source processing steps",
            }
        ],
    }
    record = apply_visual_page_plan(segment, "image", plan)
    assert segment["timeline"] == [{"target": "image,note", "start_ms": 4200}]
    assert record["retargeted_events"][0]["before"]["target"] == "steps,note"
    assert segment["narration"] == SOURCE and segment["audio_duration_sec"] == 15


def test_page_plan_cannot_silently_drop_content_or_keep_a_second_main_visual():
    from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan

    segment = {
        "elements": [{"id": "primary", "type": "image"}, {"id": "chart", "type": "chart_line"}]
    }
    with pytest.raises(ValueError, match="partition"):
        apply_visual_page_plan(
            segment,
            "primary",
            {"support_element_ids": [], "replaces_element_ids": [], "reason": "make room"},
        )
    with pytest.raises(ValueError, match="explanatory text"):
        apply_visual_page_plan(
            segment,
            "primary",
            {"support_element_ids": ["chart"], "replaces_element_ids": [], "reason": "make room"},
        )


def test_page_plan_reports_all_missing_visual_targets_together():
    from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan

    segment = {"elements": [{"id": ident, "type": "text", "text": ident}
                            for ident in ("e2", "e4")]}
    plan = {"reason": "Diagram represents original facts", "support_element_ids": [],
            "replaces_element_ids": ["e2", "e4"], "coverage": [
                {"element_id": ident, "decision": "represented", "reason": "Same fact",
                 "fact_quotes": [ident], "visual_refs": [f"main:missing-{ident}"],
                 "source_evidence": SOURCE} for ident in ("e2", "e4")
            ]}
    with pytest.raises(ValueError) as error:
        apply_visual_page_plan(segment, "primary", plan, visual_specs=[graph()], source_text=SOURCE)
    assert "missing-e2" in str(error.value) and "missing-e4" in str(error.value)
