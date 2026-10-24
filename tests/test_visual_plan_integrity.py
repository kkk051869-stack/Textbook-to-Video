from __future__ import annotations

import json
from copy import deepcopy

import pytest

from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
from textbook2video.research import visual_tools as tools

SOURCE = "数据采集后进入处理器。"


def spec():
    return {
        "id": "main",
        "schema_version": "teaching-visual-v2",
        "kind": "flow",
        "title": "数据处理",
        "teaching_goal": "理解采集与处理的关系",
        "nodes": [
            {"id": "a", "label": "采集", "evidence": SOURCE},
            {"id": "b", "label": "处理", "evidence": SOURCE},
        ],
        "edges": [{"source": "a", "target": "b", "evidence": SOURCE}],
    }


def plan():
    return {
        "support_element_ids": ["note"],
        "replaces_element_ids": ["old"],
        "reason": "The main diagram represents the processing fact",
        "coverage": [
            {
                "element_id": "old",
                "fact_quotes": ["数据采集"],
                "decision": "represented",
                "visual_refs": ["main:a"],
                "source_evidence": SOURCE,
                "reason": "The sampling node expresses this fact",
            }
        ],
    }


def segment():
    return {
        "id": 1,
        "narration": SOURCE,
        "audio_duration_sec": 10,
        "elements": [
            {"id": "image", "type": "image"},
            {"id": "old", "type": "text", "text": "数据采集"},
            {"id": "note", "type": "text", "text": "结果"},
        ],
    }


def test_deleting_an_earlier_element_freezes_later_positional_target():
    from textbook2video.animation_gen import build_slide_timelines

    page = segment()
    page["timeline"] = [{"target": "e3", "at_sec": 2}]
    apply_visual_page_plan(page, "image", plan(), visual_specs=[spec()], source_text=SOURCE)
    assert page["timeline"][0]["target"] == "note"
    compiled = build_slide_timelines([page])[0]
    assert compiled[0]["target"] == "note" and compiled[0]["start_ms"] == 2000


def test_non_equivalent_emphasis_cannot_silently_move_to_later_primary_show():
    page = segment()
    page["timeline"] = [
        {"target": "image", "action": "show", "at_sec": 5},
        {"target": "old", "action": "highlight", "at_sec": 1},
    ]
    original = deepcopy(page)
    with pytest.raises(ValueError, match="object-level"):
        apply_visual_page_plan(page, "image", plan(), visual_specs=[spec()], source_text=SOURCE)
    assert page == original


def test_multiple_independently_timed_objects_cannot_collapse_into_whole_diagram():
    page = segment()
    page["elements"].append({"id": "old2", "type": "text", "text": "处理器"})
    page["timeline"] = [{"target": "old", "at_sec": 1}, {"target": "old2", "at_sec": 3}]
    proposal = plan()
    proposal["replaces_element_ids"].append("old2")
    proposal["coverage"].append(
        {
            "element_id": "old2",
            "fact_quotes": ["处理器"],
            "decision": "represented",
            "visual_refs": ["main:b"],
            "source_evidence": SOURCE,
            "reason": "Processing node",
        }
    )
    with pytest.raises(ValueError, match="cannot collapse"):
        apply_visual_page_plan(page, "image", proposal, visual_specs=[spec()], source_text=SOURCE)


def test_a_generic_reason_does_not_prove_unique_content_is_preserved():
    proposal = plan()
    proposal.pop("coverage")
    with pytest.raises(ValueError, match="coverage"):
        apply_visual_page_plan(segment(), "image", proposal)
    proposal = plan()
    proposal["coverage"][0]["fact_quotes"] = []
    with pytest.raises(ValueError, match="all original visible facts"):
        apply_visual_page_plan(segment(), "image", proposal)


@pytest.mark.parametrize("change", ["page_plan", "parent_sha256", "request"])
def test_execution_seal_detects_page_plan_parent_or_context_drift(change, tmp_path):
    directory = tmp_path / "revision"
    path = tools.dispatch(
        "create", {"visuals": [spec()]}, source=SOURCE, output_dir=directory, render=False
    )
    if change == "request":
        file = directory / "request.json"
        data = json.loads(file.read_text(encoding="utf-8"))
        data["page_context"] = [{"id": "injected"}]
    else:
        file = path
        data = json.loads(file.read_text(encoding="utf-8"))
        data[change] = "changed"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="hash drift"):
        tools.verify_revision(directory)


def test_fixing_only_page_plan_is_not_a_repeated_visual_state(monkeypatch, tmp_path):
    first, second = plan(), plan()
    first["support_element_ids"] = []
    first["reason"] = "invalid coverage partition"
    responses = iter([first, second])
    monkeypatch.setattr(
        tools,
        "chat_with_system",
        lambda *a, **kw: json.dumps(
            {"tool": "create", "arguments": {"visuals": [spec()], "page_plan": next(responses)}}
        ),
    )
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(
        tools,
        "review_revision",
        lambda *a, **kw: {
            "verdict": "ACCEPT",
            "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
            "reason": "reviewed",
            "issues": [],
            "coverage": [
                {"element_id": "old", "verdict": "covered", "reason": "Sampling node visible"}
            ],
        },
    )
    context = segment()["elements"][1:]
    path = tools.run_visual_agent(SOURCE, "数据处理", tmp_path / "run", page_context=context)
    run = json.loads(path.read_text(encoding="utf-8"))
    assert run["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert len(run["history"]) == 2
    assert run["history"][0]["status"] == "FAILED_PRESERVED"


def test_replacing_an_existing_image_requires_its_pixels():
    page = segment()
    page["elements"][1].update(type="image", src="missing.png")
    with pytest.raises(ValueError, match="pixels"):
        apply_visual_page_plan(page, "image", plan(), visual_specs=[spec()], source_text=SOURCE)
