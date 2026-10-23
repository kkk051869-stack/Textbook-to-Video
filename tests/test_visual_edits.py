from __future__ import annotations

import json
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_edits import apply_changes

SOURCE = "数据经过采集和分析。"


def arguments():
    return {
        "visuals": [
            {
                "id": "main",
                "schema_version": "teaching-visual-v2",
                "kind": "flow",
                "title": "数据处理",
                "teaching_goal": "理解处理过程",
                "nodes": [
                    {"id": "a", "label": "采集", "evidence": SOURCE},
                    {"id": "b", "label": "分析", "evidence": SOURCE},
                ],
                "edges": [{"source": "a", "target": "b", "evidence": SOURCE}],
            }
        ]
    }


def test_local_change_preserves_other_content_and_never_mutates_parent():
    base = arguments()
    original = deepcopy(base)
    changed = apply_changes(
        base,
        {"changes": [{"op": "replace", "path": "/visuals/0/nodes/1/label", "value": "分析数据"}]},
    )
    assert changed["visuals"][0]["nodes"][1]["label"] == "分析数据"
    assert changed["visuals"][0]["edges"] == original["visuals"][0]["edges"]
    assert base == original


@pytest.mark.parametrize(
    "path",
    [
        "/source_text",
        "/source_sha256",
        "/page_context/0/text",
        "/parent",
        "/review/verdict",
        "/visuals/-1",
        "/visuals/01",
        "/visuals/9999",
        "/visuals/0/nodes/0/~2label",
    ],
)
def test_edits_cannot_change_sources_reviews_or_use_ambiguous_indices(path):
    with pytest.raises(ValueError):
        apply_changes(arguments(), {"changes": [{"op": "replace", "path": path, "value": "x"}]})


def test_add_remove_and_escaped_keys_are_exact():
    base = {"visuals": [], "page_plan": {"a/b": 1}}
    changed = apply_changes(
        base,
        {
            "changes": [
                {"op": "add", "path": "/visuals/-", "value": {"id": "a"}},
                {"op": "replace", "path": "/page_plan/a~1b", "value": 2},
                {"op": "remove", "path": "/visuals/0"},
            ]
        },
    )
    assert changed["visuals"] == [] and changed["page_plan"]["a/b"] == 2


def test_revise_dispatch_seals_expanded_state_and_keeps_raw_patch(tmp_path):
    parent, child = tmp_path / "r0", tmp_path / "r1"
    tools.dispatch("create", arguments(), source=SOURCE, output_dir=parent, render=False)
    patch = {
        "parent": str(parent),
        "reason": "clarify label",
        "changes": [{"op": "replace", "path": "/visuals/0/nodes/1/label", "value": "分析数据"}],
    }
    tools.dispatch("revise", patch, source=SOURCE, output_dir=child, render=False)
    tools.verify_revision(child)
    raw = json.loads((child / "raw_tool_request.json").read_text(encoding="utf-8"))
    effective = json.loads((child / "request.json").read_text(encoding="utf-8"))
    assert raw["arguments"] == patch
    assert effective["arguments"]["visuals"][0]["nodes"][1]["label"] == "分析数据"
    assert json.loads((parent / "specs.json").read_text(encoding="utf-8")) == arguments()["visuals"]


def test_local_edit_does_not_bypass_source_validation(tmp_path):
    parent = tmp_path / "r0"
    tools.dispatch("create", arguments(), source=SOURCE, output_dir=parent, render=False)
    with pytest.raises(ValueError, match="exact source"):
        tools.dispatch(
            "revise",
            {
                "parent": str(parent),
                "reason": "bad quote",
                "changes": [
                    {"op": "replace", "path": "/visuals/0/nodes/1/evidence", "value": "伪造依据"}
                ],
            },
            source=SOURCE,
            output_dir=tmp_path / "bad",
            render=False,
        )
    assert (tmp_path / "bad/failure.json").exists()


def test_agent_repairs_a_label_using_only_local_changes(monkeypatch, tmp_path):
    replies = iter(
        [
            {"tool": "create", "arguments": arguments()},
            {
                "tool": "revise",
                "arguments": {
                    "changes": [
                        {"op": "replace", "path": "/visuals/0/nodes/1/label", "value": "分析数据"}
                    ]
                },
            },
        ]
    )
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(replies)))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    verdicts = iter(["REVISE", "ACCEPT"])
    monkeypatch.setattr(
        tools,
        "review_revision",
        lambda *a, **kw: {
            "verdict": next(verdicts),
            "scores": dict.fromkeys(("accuracy", "relevance", "readability", "composition"), 4),
            "issues": [],
            "reason": "fixture screenshot review",
        },
    )
    result = tools.run_visual_agent(SOURCE, "理解过程", tmp_path / "agent")
    record = json.loads(result.read_text(encoding="utf-8"))
    assert record["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(record["history"]) == 2
    assert (
        record["history"][1]["resolved_arguments"]["visuals"][0]["nodes"][1]["label"] == "分析数据"
    )
