import json

import pytest

from textbook2video.pipeline.lesson_plan import (
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
