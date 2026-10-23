from __future__ import annotations

import json
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_content_map import materialize_content_map

SOURCE = "传感器采集数据，处理器分析数据。"
CONTEXT = [
    {"id": "e2", "type": "text", "text": "采集和分析"},
    {"id": "e8", "type": "text", "text": "不属于教学目标的口号"},
]


def request():
    return {
        "visuals": [
            {
                "id": "main",
                "schema_version": "teaching-visual-v2",
                "kind": "flow",
                "title": "数据处理",
                "teaching_goal": "理解两个处理阶段",
                "nodes": [
                    {"id": "a", "label": "采集", "source_ref": "source-001"},
                    {"id": "b", "label": "分析", "source_ref": "source-001"},
                ],
                "edges": [{"source": "a", "target": "b", "source_ref": "source-001"}],
            }
        ],
        "content_map": {
            "e2": {
                "decision": "represented",
                "source_ref": "source-001",
                "visual_refs": "main",
                "reason": "两个节点保留采集和分析",
            },
            "e8": {"decision": "unsupported_in_source", "reason": "原文没有该口号"},
        },
    }


def test_compact_map_inventories_every_fact_and_preserves_explicit_choices(tmp_path):
    args = request()
    original = deepcopy(args)
    tools.dispatch(
        "create",
        args,
        source=SOURCE,
        output_dir=tmp_path / "r0",
        page_context=CONTEXT,
        render=False,
    )
    effective = json.loads((tmp_path / "r0/request.json").read_text(encoding="utf-8"))
    plan = effective["arguments"]["page_plan"]
    assert plan["replaces_element_ids"] == ["e2", "e8"]
    assert plan["coverage"][0]["source_evidence"] == SOURCE
    assert plan["coverage"][0]["fact_quotes"] == ["采集和分析"]
    assert plan["coverage"][0]["visual_refs"] == ["main"]
    assert plan["coverage"][1]["decision"] == "unsupported_in_source"
    assert args == original
    tools.verify_revision(tmp_path / "r0")
    args["content_map"]["e8"]["source_ref"] = []
    compiled, _ = materialize_content_map(args, CONTEXT)
    assert "source_ref" not in compiled["page_plan"]["coverage"][1]


def test_map_never_infers_missing_dispositions_or_sources():
    args = request()
    del args["content_map"]["e8"]
    with pytest.raises(ValueError, match="missing=.*e8"):
        materialize_content_map(args, CONTEXT)
    args = request()
    del args["content_map"]["e2"]["source_ref"]
    with pytest.raises(ValueError, match="need source_ref"):
        materialize_content_map(args, CONTEXT)
    args = request()
    args["content_map"]["e2"]["source_evidence"] = "编造引文"
    with pytest.raises(ValueError, match="never retyped"):
        materialize_content_map(args, CONTEXT)


def test_course_visual_missing_title_is_bounded_validation_not_keyerror(tmp_path):
    args = request()
    del args["visuals"][0]["title"]
    with pytest.raises(ValueError, match="top-level title"):
        tools.dispatch(
            "create", args, source=SOURCE, page_context=CONTEXT,
            output_dir=tmp_path / "missing-title", render=False,
        )
    assert (tmp_path / "missing-title/failure.json").is_file()


def test_flat_tool_parameters_are_wrapped_without_editing_values():
    raw = {
        "tool": "revise",
        "changes": [{"op": "replace", "path": "/visuals/@main/title", "value": "新标题"}],
        "reason": "修改标题",
    }
    envelope, normalizations = tools.parse_tool_envelope(json.dumps(raw))
    assert envelope["arguments"] == {key: value for key, value in raw.items() if key != "tool"}
    assert normalizations
    for malformed in [
        {"tool": "revise"},
        {"tool": "revise", "arguments": []},
        {"tool": "unknown", "arguments": {}},
    ]:
        with pytest.raises(ValueError):
            tools.parse_tool_envelope(json.dumps(malformed))


def test_invalid_envelope_is_bounded_feedback_not_keyerror(monkeypatch, tmp_path):
    replies = iter([{"tool": "revise"}, {"tool": "create", "visuals": request()["visuals"]}])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(replies)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(
        tools,
        "review_revision",
        lambda *a, **kw: {
            "verdict": "ACCEPT",
            "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 4),
            "issues": [],
            "reason": "fixture screenshot review",
        },
    )
    path = tools.run_visual_agent(SOURCE, "理解两个阶段", tmp_path / "run")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert record["history"][0]["status"] == "FAILED_PRESERVED"
    assert (tmp_path / "run/model-envelope-1.json").exists()


def test_failed_compact_source_can_be_patched_without_losing_dispositions(tmp_path):
    args = request()
    args["visuals"][0]["nodes"][0]["source_ref"] = "source-999"
    parent = tmp_path / "bad"
    with pytest.raises(ValueError, match="existing source IDs"):
        tools.dispatch(
            "create", args, source=SOURCE, output_dir=parent, page_context=CONTEXT, render=False
        )
    result = tools.dispatch(
        "revise",
        {
            "parent": str(parent),
            "reason": "correct selected source ID",
            "changes": [
                {
                    "op": "replace",
                    "path": "/visuals/@main/nodes/@a/source_ref",
                    "value": "source-001",
                }
            ],
        },
        source=SOURCE,
        output_dir=tmp_path / "repaired",
        page_context=CONTEXT,
        render=False,
    )
    tools.verify_revision(result.parent)
    effective = json.loads((result.parent / "request.json").read_text(encoding="utf-8"))
    assert effective["arguments"]["page_plan"]["replaces_element_ids"] == ["e2", "e8"]


def test_distinct_invalid_content_maps_do_not_stop_before_valid_third_attempt(
    monkeypatch, tmp_path
):
    missing, invalid, valid = request(), request(), request()
    del missing["content_map"]["e2"]["source_ref"]
    invalid["content_map"]["e2"]["source_ref"] = "source-999"
    replies = iter([missing, invalid, valid])
    monkeypatch.setattr(
        tools,
        "chat_with_system",
        lambda *a, **kw: json.dumps(
            {
                "tool": "create",
                "arguments": next(replies),
            }
        ),
    )
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(
        tools,
        "review_revision",
        lambda *a, **kw: {
            "verdict": "ACCEPT",
            "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 4),
            "issues": [],
            "reason": "fixture screenshot review",
        },
    )
    path = tools.run_visual_agent(SOURCE, "理解两个阶段", tmp_path / "run", page_context=CONTEXT)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(record["history"]) == 3
    assert "need source_ref" in record["history"][0]["error"]
    assert "existing source IDs" in record["history"][1]["error"]
