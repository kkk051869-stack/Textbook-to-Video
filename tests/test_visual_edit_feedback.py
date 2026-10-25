import json

import pytest

from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
from textbook2video.research import visual_tools as tools

SOURCE = "输入经过处理。输出显示结果。"


@pytest.mark.parametrize("bad", [{"diagram": "table"}, {"nodes": "not objects"}, {"nodes": [{}]}])
def test_malformed_visual_shape_is_a_recoverable_validation_error(bad):
    segment = {"id": 1, "narration": SOURCE, "elements": []}
    with pytest.raises(ValueError, match="diagram must|nodes must"):
        apply_visual_page_plan(
            segment,
            "main",
            {
                "reason": "new page",
                "support_element_ids": [],
                "replaces_element_ids": [],
                "coverage": [],
            },
            visual_specs=[{"id": "main", "kind": "comparison", **bad}],
        )
    assert segment == {"id": 1, "narration": SOURCE, "elements": []}


def arguments():
    return {
        "visuals": [
            {
                "id": "main",
                "kind": "flow",
                "title": "处理流程",
                "teaching_goal": "理解处理",
                "nodes": [
                    {"id": "a", "label": "输入", "source_ref": "source-001"},
                    {"id": "b", "label": "输出", "source_ref": "source-002"},
                ],
                "edges": [{"source": "a", "target": "b", "source_ref": "source-001"}],
            }
        ]
    }


def test_malformed_candidate_can_reach_next_repair_request(monkeypatch, tmp_path):
    malformed = arguments()
    malformed["visuals"][0]["nodes"][0].pop("id")
    calls = []

    def planner(prompt, **kwargs):
        calls.append(json.loads(prompt))
        return json.dumps(
            {"tool": "create", "arguments": malformed if len(calls) == 1 else arguments()}
        )

    def preview(directory, **kwargs):
        tools._save(directory / "geometry.json", [])
        return []

    def review(directory, **kwargs):
        return {
            "verdict": "ACCEPT",
            "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
            "issues": [],
        }

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", preview)
    monkeypatch.setattr(tools, "review_revision", review)
    path = tools.run_visual_agent(SOURCE, "理解处理", tmp_path / "run", max_iterations=2)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(calls) == 2
    assert calls[1]["edit_contract"]["unaddressable_targets"]
    assert {"kind": "node", "selector": {"visual_id": "main", "node_id": "b"}} in calls[1][
        "edit_contract"
    ]["targets"]


def test_review_goal_and_executor_diagnostics_survive_invalid_edit_and_resume(
    monkeypatch, tmp_path
):
    replies = iter(
        [
            {"tool": "create", "arguments": arguments()},
            {
                "tool": "revise",
                "arguments": {
                    "updates": [
                        {"visual_id": "main", "node_id": "a", "set": {"style": "highlight"}}
                    ]
                },
            },
            {
                "tool": "revise",
                "arguments": {
                    "updates": [
                        {"visual_id": "main", "node_id": "invented", "set": {"label": "不存在"}}
                    ]
                },
            },
            {"tool": "revise", "arguments": {}},
            {
                "tool": "revise",
                "arguments": {
                    "updates": [{"visual_id": "main", "node_id": "a", "set": {"label": "输入数据"}}]
                },
            },
        ]
    )
    requests, reviews = [], []

    def planner(prompt, **kwargs):
        requests.append(json.loads(prompt))
        return json.dumps(next(replies))

    def preview(directory, **kwargs):
        tools._save(directory / "geometry.json", [])
        return []

    def review(directory, **kwargs):
        reviews.append(str(directory))
        report = {
            "verdict": "REVISE" if len(reviews) == 1 else "ACCEPT",
            "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
            "issues": (
                [
                    {
                        "visual_id": "main",
                        "category": "spacing",
                        "issue": "Improve label separation",
                        "change": "Separate labels",
                    }
                ]
                if len(reviews) == 1
                else []
            ),
            "reason": "fixture",
        }
        return tools._save_review(
            directory, json.dumps(report), [], model=kwargs["model"], has_images=True
        )

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", preview)
    monkeypatch.setattr(tools, "review_revision", review)
    old = tools.run_visual_agent(SOURCE, "理解处理", tmp_path / "first", max_iterations=2)
    before = old.read_bytes()
    resumed = tools.run_visual_agent(
        SOURCE, "理解处理", tmp_path / "resumed", resume_from=old, max_iterations=3
    )
    result = json.loads(resumed.read_text(encoding="utf-8"))
    assert result["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(reviews) == 2  # No review of any failed or unchanged edit.
    assert old.read_bytes() == before
    assert requests[2]["feedback"]["edit_error"]["offending_fields"] == ["style"]
    assert requests[3]["feedback"]["edit_error"]["selector"]["node_id"] == "invented"
    assert "Return valid tool JSON" in requests[4]["feedback"]["validation_error"]
    for request in requests[1:]:
        assert request["representation_rules"] == tools.REPRESENTATION_RULES
        assert "comparison has exactly two nodes" in request["representation_rules"]
        assert 'tool:"create"' not in request["representation_rules"]
        assert request["latest_screenshot_review"]["review"]["verdict"] == "REVISE"
        assert request["latest_screenshot_review"]["revision"] == reviews[0]
        assert request["previous_candidate"]["visuals"][0]["nodes"][0]["label"] == "输入"
        assert {"kind": "node", "selector": {"visual_id": "main", "node_id": "a"}} in request[
            "edit_contract"
        ]["targets"]
    assert (
        result["history"][-1]["resolved_arguments"]["visuals"][0]["nodes"][0]["label"] == "输入数据"
    )
