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
    "enrich_storyboard_with_lesson_plan",
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


def _text_features(text: Any) -> set[str]:
    text = re.sub(r"[\s\W_]+", "", str(text or "").lower(), flags=re.UNICODE)
    if not text:
        return set()
    return set(text) | {text[i : i + 2] for i in range(max(0, len(text) - 1))}


def _similarity(a: Any, b: Any) -> float:
    fa, fb = _text_features(a), _text_features(b)
    if not fa or not fb:
        return 0.0
    return len(fa & fb) / len(fa | fb)


def _segment_text(segment: dict[str, Any]) -> str:
    parts = [str(segment.get("narration") or "")]
    for element in segment.get("elements", []) or []:
        if not isinstance(element, dict):
            continue
        for key in ("text", "title", "label", "caption", "description"):
            if element.get(key):
                parts.append(str(element.get(key)))
        for key in ("items", "steps", "headers", "rows"):
            value = element.get(key)
            if isinstance(value, list):
                parts.append(json.dumps(value, ensure_ascii=False))
    return "\n".join(parts)


def _best_kp_ids_for_segment(
    segment: dict[str, Any],
    knowledge_points: list[dict[str, Any]],
) -> list[str]:
    if not knowledge_points:
        return []
    text = _segment_text(segment)
    scored: list[tuple[float, str]] = []
    for kp in knowledge_points:
        kid = str(kp.get("id") or "").strip()
        if not kid:
            continue
        kp_text = " ".join(
            str(kp.get(key) or "")
            for key in ("name", "description", "suggested_visual")
        )
        scored.append((_similarity(text, kp_text), kid))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.08:
        return [scored[0][1]]
    # 兜底：弱匹配时仍绑定一个知识点，避免完全失去教学追踪。
    first = str(knowledge_points[0].get("id") or "").strip()
    return [first] if first else []


def _next_segment_id(storyboard: dict[str, Any]) -> int:
    max_id = 0
    for segment in storyboard.get("segments", []) or []:
        try:
            max_id = max(max_id, int(segment.get("id", 0)))
        except (TypeError, ValueError):
            continue
    return max_id + 1


def _has_pedagogical_slide(storyboard: dict[str, Any], role: str) -> bool:
    for segment in storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        if segment.get("pedagogical_role") == role:
            return True
    return False


def _activity_slide(
    sid: int,
    activities: list[str],
    kp_ids: list[str],
) -> dict[str, Any]:
    steps = activities[:3] or ["请结合本页内容，举一个自己的例子。"]
    narration = "现在暂停一下，完成一个小活动：" + "；".join(steps)
    return {
        "id": sid,
        "visual_type": "activity",
        "render_mode": "template",
        "pedagogical_role": "reflection_activity",
        "knowledge_point_ids": kp_ids[:2],
        "narration": narration,
        "elements": [
            {"id": "e1", "type": "heading", "text": "想一想"},
            {"id": "e2", "type": "activity_step", "steps": steps},
            {"id": "e3", "type": "quote", "text": "先暂停思考，再继续观看。"},
        ],
        "animations": [],
    }


def _quiz_slide(
    sid: int,
    questions: list[dict[str, Any]],
    kp_ids: list[str],
) -> dict[str, Any]:
    picked = questions[:3]
    items = [str(q.get("question") or "").strip() for q in picked if q.get("question")]
    ids: list[str] = []
    for q in picked:
        for kid in q.get("knowledge_point_ids") or []:
            if kid not in ids:
                ids.append(str(kid))
    narration = "请完成这几个知识点检测题：" + "；".join(items)
    return {
        "id": sid,
        "visual_type": "activity",
        "render_mode": "template",
        "pedagogical_role": "knowledge_check",
        "knowledge_point_ids": ids or kp_ids[:3],
        "narration": narration,
        "elements": [
            {"id": "e1", "type": "heading", "text": "知识点检测"},
            {"id": "e2", "type": "icon_group", "items": items or ["说出本节课的一个关键概念"]},
            {"id": "e3", "type": "text", "text": "请先口头回答，再对照教材内容检查。"},
        ],
        "animations": [],
    }


def _summary_slide(
    sid: int,
    objectives: list[str],
    knowledge_points: list[dict[str, Any]],
) -> dict[str, Any]:
    names = [str(kp.get("name") or "").strip() for kp in knowledge_points if kp.get("name")]
    narration = "最后回顾本节课的关键内容：" + "；".join(names[:5])
    return {
        "id": sid,
        "visual_type": "definition",
        "render_mode": "template",
        "pedagogical_role": "lesson_summary",
        "knowledge_point_ids": [
            str(kp.get("id")) for kp in knowledge_points if kp.get("id")
        ][:5],
        "narration": narration,
        "elements": [
            {"id": "e1", "type": "heading", "text": "本节小结"},
            {"id": "e2", "type": "icon_group", "items": names[:5] or objectives[:4] or ["回顾核心概念"]},
            {"id": "e3", "type": "quote", "text": objectives[0] if objectives else "把概念、例子和应用联系起来。"},
        ],
        "animations": [],
    }


def enrich_storyboard_with_lesson_plan(
    storyboard: dict[str, Any],
    lesson_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Make lesson-plan activities/checks visible in storyboard pages.

    This deterministic post-pass is intentionally conservative: it does not
    rewrite LLM-produced pages, but it fills missing knowledge-point bindings
    and appends a small set of teaching pages when the lesson plan provides
    activities or assessment questions.
    """
    if not lesson_plan:
        return storyboard
    plan = normalize_lesson_plan(lesson_plan, lesson_title=str(storyboard.get("lesson_title") or ""))
    knowledge_points = plan.get("knowledge_points") or []
    kp_ids = [str(kp.get("id")) for kp in knowledge_points if kp.get("id")]

    for segment in storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        ids = segment.get("knowledge_point_ids")
        if isinstance(ids, list) and ids:
            continue
        matched = _best_kp_ids_for_segment(segment, knowledge_points)
        if matched:
            segment["knowledge_point_ids"] = matched

    added: list[str] = []
    sid = _next_segment_id(storyboard)
    segments = storyboard.setdefault("segments", [])

    activities = plan.get("activities") or []
    if activities and not _has_pedagogical_slide(storyboard, "reflection_activity"):
        segments.append(_activity_slide(sid, activities, kp_ids))
        added.append("reflection_activity")
        sid += 1

    questions = plan.get("assessment_questions") or []
    if questions and not _has_pedagogical_slide(storyboard, "knowledge_check"):
        segments.append(_quiz_slide(sid, questions, kp_ids))
        added.append("knowledge_check")
        sid += 1

    if knowledge_points and not _has_pedagogical_slide(storyboard, "lesson_summary"):
        segments.append(_summary_slide(sid, plan.get("objectives") or [], knowledge_points))
        added.append("lesson_summary")

    metadata = storyboard.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["total_slides"] = len(storyboard.get("segments", []) or [])
        if added:
            metadata["pedagogical_slides_added"] = added
    return storyboard


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
