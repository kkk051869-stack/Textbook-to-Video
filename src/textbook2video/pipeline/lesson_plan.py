"""Lesson-plan generation and validation helpers.

The lesson plan is a teaching-semantic layer between raw textbook text and
script/storyboard generation. It captures objectives, knowledge points,
source hints, images, activities, and assessment questions without deciding
slide layout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__all__ = [
    "generate_lesson_plan",
    "load_lesson_plan",
    "lesson_plan_prompt_section",
    "normalize_lesson_plan",
]


def _strip_code_fence(raw: str) -> str:
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    return (m.group(1) if m else raw).strip()


def _extract_json(raw: str) -> dict[str, Any]:
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("lesson plan output does not contain a JSON object") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("lesson plan must be a JSON object")
    return data


def normalize_lesson_plan(data: dict[str, Any], *, lesson_title: str = "") -> dict[str, Any]:
    """Normalize an LLM-produced lesson plan into a stable minimal schema."""
    plan = dict(data)
    plan["lesson_title"] = str(plan.get("lesson_title") or lesson_title or "")

    def _list(key: str) -> list:
        value = plan.get(key)
        return value if isinstance(value, list) else []

    plan["objectives"] = [str(x).strip() for x in _list("objectives") if str(x).strip()]

    kps: list[dict[str, Any]] = []
    for i, kp in enumerate(_list("knowledge_points"), 1):
        if not isinstance(kp, dict):
            continue
        kid = str(kp.get("id") or f"kp{i}").strip()
        name = str(kp.get("name") or kp.get("title") or "").strip()
        if not name:
            continue
        kps.append({
            "id": kid,
            "name": name,
            "description": str(kp.get("description") or "").strip(),
            "source_refs": kp.get("source_refs") if isinstance(kp.get("source_refs"), list) else [],
            "suggested_visual": str(kp.get("suggested_visual") or "").strip(),
            "required_images": kp.get("required_images") if isinstance(kp.get("required_images"), list) else [],
        })
    plan["knowledge_points"] = kps
    plan["activities"] = [str(x).strip() for x in _list("activities") if str(x).strip()]

    questions: list[dict[str, Any]] = []
    for i, q in enumerate(_list("assessment_questions"), 1):
        if isinstance(q, dict) and q.get("question"):
            questions.append({
                "id": str(q.get("id") or f"q{i}"),
                "question": str(q.get("question")),
                "answer": str(q.get("answer") or ""),
                "knowledge_point_ids": q.get("knowledge_point_ids")
                if isinstance(q.get("knowledge_point_ids"), list) else [],
            })
        elif isinstance(q, str) and q.strip():
            questions.append({"id": f"q{i}", "question": q.strip(), "answer": "", "knowledge_point_ids": []})
    plan["assessment_questions"] = questions
    return plan


def _images_section(available_images: list[dict] | None) -> str:
    if not available_images:
        return "无教材原图。"
    lines = ["| ID | 文件 | 描述 |", "|---|---|---|"]
    for img in available_images:
        lines.append(
            f"| {img.get('id', '')} | {img.get('filename', '')} | {img.get('description', '')} |"
        )
    return "\n".join(lines)


def lesson_plan_prompt_section(plan: dict[str, Any] | None) -> str:
    """Compact lesson-plan summary for script/storyboard prompts."""
    if not plan:
        return ""
    lines = ["\n## 教学计划约束（必须优先满足）"]
    objectives = plan.get("objectives") or []
    if objectives:
        lines.append("### 学习目标")
        lines.extend(f"- {obj}" for obj in objectives)
    kps = plan.get("knowledge_points") or []
    if kps:
        lines.append("### 知识点")
        for kp in kps:
            if not isinstance(kp, dict):
                continue
            desc = f"：{kp.get('description')}" if kp.get("description") else ""
            visual = f"，建议视觉：{kp.get('suggested_visual')}" if kp.get("suggested_visual") else ""
            lines.append(f"- {kp.get('id')}: {kp.get('name')}{desc}{visual}")
    activities = plan.get("activities") or []
    if activities:
        lines.append("### 可用学习活动")
        lines.extend(f"- {act}" for act in activities)
    return "\n".join(lines)


def generate_lesson_plan(
    lesson_text: str,
    *,
    lesson_title: str = "",
    available_images: list[dict] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Generate a lesson plan from textbook text using the configured LLM."""
    from textbook2video.llm.client import chat_with_system, load_prompt

    prompt_template = load_prompt("lesson_plan.md")
    prompt = (
        prompt_template
        .replace("{lesson_title}", lesson_title or "")
        .replace("{lesson_text}", lesson_text)
        .replace("{available_images}", _images_section(available_images))
    )
    raw = chat_with_system(
        user_content=prompt,
        system_prompt="你是一位教学设计专家。只输出 JSON，不要解释。",
        model=model,
        temperature=0.4,
        max_tokens=4096,
    )
    return normalize_lesson_plan(_extract_json(raw), lesson_title=lesson_title)


def load_lesson_plan(path: str | Path) -> dict[str, Any]:
    """Load and normalize a lesson-plan JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("lesson plan JSON must be an object")
    return normalize_lesson_plan(data, lesson_title=str(data.get("lesson_title") or ""))
