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


def review(verdict="ACCEPT", score=4):
    return {
        "verdict": verdict,
        "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], score),
        "issues": [],
        "reason": "checked source and rendered pixels",
    }


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
    a, b = graph(), graph()
    b["nodes"][0]["label"] = "数据采集"
    replies = iter([a, b])
    reviews = iter([review("REVISE", 2), review()])
    calls = []

    def planner(prompt, **kwargs):
        calls.append(json.loads(prompt))
        return json.dumps({"tool": "create", "arguments": {"visuals": [next(replies)]}})

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: next(reviews))
    path = tools.run_visual_agent(SOURCE, "理解信息处理", tmp_path / "run")
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(result["history"]) == 2
    assert calls[1]["feedback"]["verdict"] == "REVISE"
    assert (tmp_path / "run/revision-00/revision.json").exists()
    assert result["history"][1]["review"]["scores"]["accuracy"] == 4


def test_agent_detects_repeat_and_never_promotes_rejected_graph(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tools,
        "chat_with_system",
        lambda *a, **kw: json.dumps({"tool": "create", "arguments": {"visuals": [graph()]}}),
    )
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: review("REVISE", 2))
    path = tools.run_visual_agent(SOURCE, "理解信息处理", tmp_path / "run")
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["status"] == "STOPPED_REPEATED_STATE"
    assert result["accepted_revision"] is None


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
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run_path)
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
