import json

import pytest

from textbook2video.pipeline.lesson_plan import (
    enrich_storyboard_with_lesson_plan,
    lesson_plan_prompt_section,
    load_lesson_plan,
    normalize_lesson_plan,
)


def test_normalize_lesson_plan_keeps_stable_fields():
    raw = {
        "lesson_title": "算法",
        "objectives": ["解释算法", ""],
        "knowledge_points": [
            {"name": "算法定义", "description": "有限步骤", "suggested_visual": "definition"},
            "bad",
        ],
        "activities": ["描述刷牙步骤"],
        "assessment_questions": ["什么是算法？"],
    }

    plan = normalize_lesson_plan(raw)

    assert plan["lesson_title"] == "算法"
    assert plan["objectives"] == ["解释算法"]
    assert plan["knowledge_points"][0]["id"] == "kp1"
    assert plan["knowledge_points"][0]["name"] == "算法定义"
    assert plan["assessment_questions"][0]["id"] == "q1"


def test_lesson_plan_prompt_section_mentions_objectives_and_kps():
    plan = normalize_lesson_plan({
        "objectives": ["区分算法和程序"],
        "knowledge_points": [{"id": "kp1", "name": "算法", "description": "解决问题的步骤"}],
    })

    section = lesson_plan_prompt_section(plan)

    assert "教学计划约束" in section
    assert "区分算法和程序" in section
    assert "kp1: 算法" in section


def test_load_lesson_plan_requires_object(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ValueError):
        load_lesson_plan(p)


def test_enrich_storyboard_adds_activity_quiz_and_summary_pages():
    storyboard = {
        "lesson_title": "算法",
        "segments": [
            {
                "id": 1,
                "narration": "算法是一组明确步骤。",
                "visual_type": "definition",
                "elements": [{"id": "e1", "type": "heading", "text": "算法"}],
                "animations": [],
            }
        ],
        "metadata": {"total_slides": 1},
    }
    plan = normalize_lesson_plan({
        "objectives": ["理解算法的含义"],
        "knowledge_points": [{"id": "kp1", "name": "算法定义", "description": "明确步骤"}],
        "activities": ["举一个生活中的算法例子"],
        "assessment_questions": [{"id": "q1", "question": "什么是算法？", "knowledge_point_ids": ["kp1"]}],
    })

    enriched = enrich_storyboard_with_lesson_plan(storyboard, plan)

    roles = [seg.get("pedagogical_role") for seg in enriched["segments"]]
    assert "reflection_activity" in roles
    assert "knowledge_check" in roles
    assert "lesson_summary" in roles
    assert enriched["segments"][0]["knowledge_point_ids"] == ["kp1"]
    assert enriched["metadata"]["total_slides"] == 4
    assert enriched["metadata"]["pedagogical_slides_added"] == [
        "reflection_activity",
        "knowledge_check",
        "lesson_summary",
    ]


def test_enrich_storyboard_does_not_duplicate_existing_teaching_pages():
    storyboard = {
        "segments": [
            {
                "id": 1,
                "pedagogical_role": "knowledge_check",
                "narration": "检测题",
                "elements": [],
            }
        ],
        "metadata": {"total_slides": 1},
    }
    plan = normalize_lesson_plan({
        "knowledge_points": [{"id": "kp1", "name": "算法"}],
        "assessment_questions": ["什么是算法？"],
    })

    enriched = enrich_storyboard_with_lesson_plan(storyboard, plan)

    assert [seg.get("pedagogical_role") for seg in enriched["segments"]].count("knowledge_check") == 1
