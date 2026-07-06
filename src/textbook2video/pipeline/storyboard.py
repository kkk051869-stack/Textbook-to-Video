"""
画面大纲生成器：讲稿文本 → 画面大纲 JSON

用法：
  from textbook2video.pipeline.storyboard import generate_storyboard
  storyboard = generate_storyboard(script_segments, lesson_title="第4课")
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# 每批最多处理的讲稿段数，避免单次 LLM 输出被 max_tokens 截断
_BATCH_SIZE = 3


def load_prompt(name: str) -> str:
    prompts_dir = Path(__file__).resolve().parents[1] / "llm" / "prompts"
    return (prompts_dir / name).read_text(encoding="utf-8")


def chat_with_system(*args: Any, **kwargs: Any) -> str:
    from textbook2video.llm.client import chat_with_system as _chat_with_system

    return _chat_with_system(*args, **kwargs)


def generate_storyboard(
    script_segments: list[str],
    *,
    lesson_title: str = "",
    model: str | None = None,
    available_images: list[dict] | None = None,
    lesson_plan: dict[str, Any] | None = None,
    agent_review: bool = False,
    agent_review_rounds: int = 2,
    agent_review_strict: bool = False,
) -> dict[str, Any]:
    """
    根据讲稿分段生成画面大纲 JSON。

    讲稿超过 _BATCH_SIZE 段时自动分批调用 LLM，每次只生成若干段的
    storyboard segments，最后合并为完整 storyboard。

    Args:
        script_segments: 讲稿分段列表
        lesson_title: 课程标题
        model: 可选，指定模型名
        available_images: 可用的教材原图列表，每项含 id, filename, description

    Returns:
        画面大纲 dict,符合 storyboard JSON schema
    """
    all_segments: list[dict] = []
    global_idx = 0

    for batch_start in range(0, len(script_segments), _BATCH_SIZE):
        batch = script_segments[batch_start : batch_start + _BATCH_SIZE]
        # 编号保持与全局一致，让 LLM 知道这些段在整个课程中的位置
        script_text = ""
        for i, seg in enumerate(batch):
            global_idx = batch_start + i + 1
            script_text += f"第{global_idx}段讲稿：\n{seg}\n\n"

        if lesson_plan:
            from textbook2video.pipeline.lesson_plan import lesson_plan_prompt_section

            script_text += lesson_plan_prompt_section(lesson_plan) + "\n\n"

        if available_images:
            script_text += _build_images_section(available_images)

        prompt_template = load_prompt("storyboard.md")
        prompt = prompt_template.replace("{script_text}", script_text)

        batch_hint = ""
        if len(script_segments) > _BATCH_SIZE:
            batch_hint = (
                f"本次只需生成第 {batch_start + 1}-{batch_start + len(batch)} 段讲稿"
                f"对应的 segments（共 {len(script_segments)} 段中的这一批）。"
            )

        result = chat_with_system(
            user_content=prompt,
            system_prompt=(
                "你是一位教学动画设计师。根据讲稿内容输出 JSON 格式的画面大纲。"
                "只输出 JSON,不要额外文字。"
                + batch_hint
            ),
            model=model,
            temperature=0.7,
            max_tokens=8192,
        )

        batch_sb = _parse_storyboard(result, lesson_title)
        all_segments.extend(batch_sb.get("segments", []))

    # 类型重叠在生成阶段（TTS 之前）就拆段：保信息 + 每页干净，且不破坏"段=页=音频"对齐
    if os.environ.get("T2V_NO_SPLIT") != "1":
        all_segments = split_overlapping_segments(all_segments, model)

    storyboard: dict[str, Any] = {
        "lesson_title": lesson_title,
        "segments": all_segments,
        "metadata": {"total_slides": len(all_segments)},
    }

    _sanitize_image_paths(storyboard, available_images)

    if lesson_plan:
        from textbook2video.pipeline.lesson_plan import enrich_storyboard_with_lesson_plan

        storyboard = enrich_storyboard_with_lesson_plan(storyboard, lesson_plan)

    if os.environ.get("T2V_DISABLE_STORYBOARD_ENHANCER") != "1":
        enhance_storyboard_quality(storyboard, lesson_plan)

    if agent_review or os.environ.get("T2V_STORYBOARD_AGENT_REVIEW") == "1":
        storyboard = run_storyboard_agent_review(
            storyboard,
            lesson_plan=lesson_plan,
            model=model,
            max_rounds=agent_review_rounds,
            strict=agent_review_strict,
        )
        _sanitize_image_paths(storyboard, available_images)

    return storyboard


_HERO_ELEMENT_TYPES = {"image", "comparison_panel", "table", "flow_step", "activity_step", "quiz_card"}


def _compact_text(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def _text_similarity(a: Any, b: Any) -> float:
    aa, bb = _compact_text(a), _compact_text(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    if aa in bb or bb in aa:
        return min(len(aa), len(bb)) / max(len(aa), len(bb))
    aset = set(aa) | {aa[i : i + 2] for i in range(max(0, len(aa) - 1))}
    bset = set(bb) | {bb[i : i + 2] for i in range(max(0, len(bb) - 1))}
    return len(aset & bset) / len(aset | bset) if aset and bset else 0.0


def _flatten_element_text(element: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("text", "title", "label", "caption", "description"):
        if element.get(key):
            parts.append(str(element.get(key)))
    for key in ("items", "steps", "headers", "rows", "questions"):
        value = element.get(key)
        if isinstance(value, list):
            parts.append(json.dumps(value, ensure_ascii=False))
    return " ".join(parts)


def _first_sentence(text: Any, *, fallback: str = "") -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return fallback
    pieces = re.split(r"(?<=[。！？!?；;])", raw)
    for piece in pieces:
        piece = piece.strip()
        if 8 <= len(piece) <= 90:
            return piece
    return raw[:90].strip() or fallback


def _lesson_plan_lookup(lesson_plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not lesson_plan:
        return {}
    points = lesson_plan.get("knowledge_points") if isinstance(lesson_plan, dict) else []
    lookup: dict[str, dict[str, Any]] = {}
    for point in points or []:
        if not isinstance(point, dict):
            continue
        kid = str(point.get("id") or "").strip()
        if kid:
            lookup[kid] = point
    return lookup


def _best_point_for_segment(
    segment: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    ids = segment.get("knowledge_point_ids")
    if isinstance(ids, list):
        for kid in ids:
            point = lookup.get(str(kid))
            if point:
                return point
    return None


def _next_element_id(elements: list[dict[str, Any]]) -> str:
    used = {str(e.get("id")) for e in elements if isinstance(e, dict) and e.get("id")}
    i = 1
    while f"e{i}" in used:
        i += 1
    return f"e{i}"


def _remove_title_echoes(segment: dict[str, Any]) -> bool:
    elements = segment.get("elements")
    if not isinstance(elements, list) or not elements:
        return False
    heading = next(
        (e for e in elements if isinstance(e, dict) and e.get("type") == "heading"),
        None,
    )
    if not heading:
        return False
    heading_text = str(heading.get("text") or "").strip()
    if not heading_text:
        return False

    changed = False
    kept: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        if element is heading:
            kept.append(element)
            continue
        body_text = _flatten_element_text(element)
        if element.get("type") in {"text", "quote", "label", "subheading"}:
            if _text_similarity(heading_text, body_text) >= 0.82:
                changed = True
                continue
        if element.get("type") == "icon_group":
            items = element.get("items") if isinstance(element.get("items"), list) else []
            filtered = [it for it in items if _text_similarity(heading_text, it) < 0.82]
            if len(filtered) != len(items):
                changed = True
                if filtered:
                    element = {**element, "items": filtered}
                else:
                    continue
        kept.append(element)
    if len(kept) != len(elements):
        segment["elements"] = kept
    return changed


def _ensure_body_text(segment: dict[str, Any], point: dict[str, Any] | None) -> bool:
    elements = segment.get("elements")
    if not isinstance(elements, list) or not elements:
        return False
    has_body_text = any(
        isinstance(e, dict)
        and e.get("type") in {"text", "quote", "subheading"}
        and str(e.get("text") or "").strip()
        for e in elements
    )
    if has_body_text:
        return False
    desc = str((point or {}).get("description") or "").strip()
    text = desc or _first_sentence(segment.get("narration"), fallback="本页先抓住核心概念，再看它如何用于解释教材内容。")
    if not text:
        return False
    insert_at = 1 if elements and isinstance(elements[0], dict) and elements[0].get("type") == "heading" else 0
    elements.insert(insert_at, {"id": _next_element_id(elements), "type": "text", "text": text})
    return True


def _ensure_hero_element(segment: dict[str, Any], point: dict[str, Any] | None) -> bool:
    elements = segment.get("elements")
    if not isinstance(elements, list) or not elements:
        return False
    if any(isinstance(e, dict) and e.get("type") in _HERO_ELEMENT_TYPES for e in elements):
        return False
    if str(segment.get("visual_type") or "") in {"title", "closing", "section_divider"}:
        return False

    concept = str((point or {}).get("name") or "").strip()
    desc = str((point or {}).get("description") or "").strip()
    narration_hint = _first_sentence(segment.get("narration"), fallback=desc or concept)
    left = concept or "核心概念"
    left_content = desc or narration_hint
    right_content = narration_hint
    if _text_similarity(left_content, right_content) >= 0.82:
        right_content = "判断它是否真正改变了学习过程、教学活动或问题解决方式。"
    panel = {
        "id": _next_element_id(elements),
        "type": "comparison_panel",
        "items": [
            {"title": left, "content": left_content},
            {"title": "学习判断", "content": right_content},
        ],
    }
    insert_at = min(2, len(elements))
    elements.insert(insert_at, panel)
    return True


def _ensure_explanatory_quote(segment: dict[str, Any]) -> bool:
    elements = segment.get("elements")
    if not isinstance(elements, list):
        return False
    if any(isinstance(e, dict) and e.get("type") == "quote" for e in elements):
        return False
    text = _first_sentence(segment.get("narration"), fallback="")
    if not text:
        return False
    elements.append({
        "id": _next_element_id(elements),
        "type": "quote",
        "text": f"判断标准：{text}",
    })
    return True


def _refresh_segment_animations(segment: dict[str, Any]) -> None:
    elements = segment.get("elements")
    if not isinstance(elements, list):
        return
    known = {str(e.get("id")) for e in elements if isinstance(e, dict) and e.get("id")}
    animations = [
        a for a in segment.get("animations", []) or []
        if isinstance(a, dict) and str(a.get("target")) in known
    ]
    existing = {str(a.get("target")) for a in animations if isinstance(a, dict)}
    for element in elements:
        if not isinstance(element, dict) or not element.get("id"):
            continue
        eid = str(element["id"])
        if eid not in existing:
            animations.append({"target": eid, "effect": "fadeInUp"})
    segment["animations"] = animations


def enhance_storyboard_quality(
    storyboard: dict[str, Any],
    lesson_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministically repair common low-quality storyboard pages."""
    lookup = _lesson_plan_lookup(lesson_plan)
    changed_segments = 0
    for segment in storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        elements = segment.get("elements")
        if not isinstance(elements, list) or not elements:
            continue
        point = _best_point_for_segment(segment, lookup)
        changed = False
        changed |= _remove_title_echoes(segment)
        changed |= _ensure_body_text(segment, point)
        changed |= _ensure_hero_element(segment, point)
        if str(segment.get("visual_type") or "") not in {"title", "closing", "section_divider"}:
            changed |= _ensure_explanatory_quote(segment)
        if changed:
            _refresh_segment_animations(segment)
            changed_segments += 1

    metadata = storyboard.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["total_slides"] = len(storyboard.get("segments", []) or [])
        if changed_segments:
            metadata["storyboard_quality_enhanced"] = changed_segments
    return storyboard


def _strip_json_fence(raw: str) -> str:
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    return (m.group(1) if m else raw).strip()


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = _strip_json_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("agent output does not contain a JSON object") from None
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("agent output must be a JSON object")
    return data


def _storyboard_review_prompt(
    storyboard: dict[str, Any],
    lesson_plan: dict[str, Any] | None,
) -> str:
    compact = {
        "lesson_title": storyboard.get("lesson_title"),
        "metadata": storyboard.get("metadata", {}),
        "segments": storyboard.get("segments", []),
    }
    plan = lesson_plan or {}
    return (
        "你是 Storyboard Review Agent，负责审核教材视频 storyboard 是否可以进入 HTML 动画渲染。\n"
        "请严格检查：标题正文是否重复、每页是否有主视觉、图片 src 是否合理、quiz 是否有题干/答案/解析、"
        "教学活动/小结是否存在、页面是否过空或过满。\n"
        "只输出 JSON，不要输出解释文字。格式：\n"
        "{\n"
        '  "pass": true,\n'
        '  "severity": "pass|minor|major|blocker",\n'
        '  "issues": [{"slide": 1, "type": "title_echo|thin_page|missing_hero|bad_image|quiz_incomplete|overcrowded|other", "message": "...", "suggestion": "..."}],\n'
        '  "summary": "..."\n'
        "}\n\n"
        f"## Lesson Plan\n{json.dumps(plan, ensure_ascii=False)[:6000]}\n\n"
        f"## Storyboard\n{json.dumps(compact, ensure_ascii=False)[:18000]}"
    )


def _storyboard_repair_prompt(
    storyboard: dict[str, Any],
    review: dict[str, Any],
    lesson_plan: dict[str, Any] | None,
) -> str:
    compact = {
        "lesson_title": storyboard.get("lesson_title"),
        "metadata": storyboard.get("metadata", {}),
        "segments": storyboard.get("segments", []),
    }
    return (
        "你是 Storyboard Repair Agent。请根据 Review Agent 的问题清单修复 storyboard JSON。\n"
        "要求：\n"
        "1. 保持 segments 数量和 narration 主体不大改，除非问题要求拆分或补全。\n"
        "2. 修复标题正文重复、缺主视觉、图片幻觉、quiz 缺答案/解析、页面过空等问题。\n"
        "3. 只使用支持的 element 类型：heading, subheading, text, quote, icon_group, flow_step, "
        "activity_step, comparison_panel, table, image, focus_box, callout, quiz_card。\n"
        "4. 不要编造本地图片 src；没有真实图片时保留 image.description 即可。\n"
        "5. 输出完整 storyboard JSON object，不要 markdown，不要解释。\n\n"
        f"## Review Issues\n{json.dumps(review, ensure_ascii=False)}\n\n"
        f"## Lesson Plan\n{json.dumps(lesson_plan or {}, ensure_ascii=False)[:6000]}\n\n"
        f"## Storyboard\n{json.dumps(compact, ensure_ascii=False)[:18000]}"
    )


def _call_review_agent(
    storyboard: dict[str, Any],
    lesson_plan: dict[str, Any] | None,
    model: str | None,
) -> dict[str, Any]:
    raw = chat_with_system(
        user_content=_storyboard_review_prompt(storyboard, lesson_plan),
        system_prompt="你是严谨的教学视频 storyboard 审核 agent。只输出 JSON。",
        model=model,
        temperature=0.2,
        max_tokens=3000,
        timeout=360,
    )
    data = _extract_json_object(raw)
    data["pass"] = bool(data.get("pass"))
    issues = data.get("issues")
    data["issues"] = issues if isinstance(issues, list) else []
    data["severity"] = str(data.get("severity") or ("pass" if data["pass"] else "major"))
    data["summary"] = str(data.get("summary") or "")
    return data


def _call_repair_agent(
    storyboard: dict[str, Any],
    review: dict[str, Any],
    lesson_plan: dict[str, Any] | None,
    model: str | None,
) -> dict[str, Any]:
    raw = chat_with_system(
        user_content=_storyboard_repair_prompt(storyboard, review, lesson_plan),
        system_prompt="你是 storyboard JSON 修复 agent。只输出完整 JSON object。",
        model=model,
        temperature=0.35,
        max_tokens=8192,
        timeout=420,
    )
    repaired = _extract_json_object(raw)
    if not isinstance(repaired.get("segments"), list):
        raise ValueError("repair agent output missing segments")
    repaired.setdefault("lesson_title", storyboard.get("lesson_title", ""))
    repaired.setdefault("metadata", {})
    if isinstance(storyboard.get("metadata"), dict) and isinstance(repaired["metadata"], dict):
        repaired["metadata"] = {**storyboard["metadata"], **repaired["metadata"]}
    repaired["metadata"]["total_slides"] = len(repaired.get("segments", []) or [])
    return repaired


def run_storyboard_agent_review(
    storyboard: dict[str, Any],
    *,
    lesson_plan: dict[str, Any] | None = None,
    model: str | None = None,
    max_rounds: int = 2,
    strict: bool = False,
) -> dict[str, Any]:
    """Run a reviewer-agent / repair-agent loop before HTML generation."""
    max_rounds = max(1, int(max_rounds or 1))
    reviews: list[dict[str, Any]] = []
    current = storyboard
    for round_index in range(1, max_rounds + 1):
        review = _call_review_agent(current, lesson_plan, model)
        review["round"] = round_index
        reviews.append(review)
        if review.get("pass"):
            metadata = current.setdefault("metadata", {})
            metadata["agent_review"] = {
                "status": "passed",
                "rounds": round_index,
                "reviews": reviews,
            }
            return current
        if round_index >= max_rounds:
            break
        current = _call_repair_agent(current, review, lesson_plan, model)
        enhance_storyboard_quality(current, lesson_plan)

    metadata = current.setdefault("metadata", {})
    metadata["agent_review"] = {
        "status": "failed",
        "rounds": len(reviews),
        "reviews": reviews,
    }
    if strict:
        raise RuntimeError("Storyboard agent review failed; HTML generation is blocked.")
    return current


# 同组内多个 widget = 功能重叠（重复啰嗦）→ 触发拆段，每段各留 1 个
_SPLIT_GROUPS: list[set[str]] = [
    {"icon_group", "flow_step", "activity_step"},          # 列举组
    {"comparison_panel", "table", "bar", "chart_line"},    # 数据展示组
]
_SENT_END = re.compile(r"[。！？!?；;]")


def _first_overlap_index(elements: list[dict]) -> int | None:
    """返回第一个造成"同组第二个 widget"的元素下标；无重叠返回 None。"""
    seen = [False] * len(_SPLIT_GROUPS)
    for i, el in enumerate(elements):
        t = el.get("type", "")
        for gi, g in enumerate(_SPLIT_GROUPS):
            if t in g:
                if seen[gi]:
                    return i
                seen[gi] = True
    return None


def _split_narration(narration: str, ratio: float) -> tuple[str, str]:
    """按 ratio 在最近的句子边界切分旁白，保证两段都非空。"""
    narr = (narration or "").strip()
    if len(narr) < 8:
        return narr, narr
    target = max(1, int(len(narr) * ratio))
    ends = [m.end() for m in _SENT_END.finditer(narr)]
    cuts = [e for e in ends if e < len(narr)]  # 不取末尾整句
    if not cuts:
        return narr, narr
    cut = min(cuts, key=lambda e: abs(e - target))
    a, b = narr[:cut].strip(), narr[cut:].strip()
    return (a or narr), (b or narr)


# 拆出来的每一半至少要有这么多"空间权重"，否则不拆（避免拆出寡淡页）。
# 宁可一页满 + 轻微重叠，也不要一页只剩一个孤零零的小 widget。
_MIN_HALF_WEIGHT = 3.0


def _split_one(seg: dict, model: str | None = None, _depth: int = 0) -> list[dict]:
    """把一个含同组重叠的 segment 拆成多个各自无重叠的 segment。

    策略：
    - 位置拆分若两半都"够实"（权重 ≥ _MIN_HALF_WEIGHT）→ 直接确定性拆（免 LLM）。
    - 否则（会拆出寡淡页）→ 让 LLM 把这段改写成两页，各配相关正文填实（保信息+不重叠）。
    - LLM 不可用/失败 → 回退为不拆（保持一页满 + 轻微重叠，绝不出寡淡页）。
    """
    from textbook2video.pipeline.checks import segment_weight

    elements = seg.get("elements", [])
    idx = _first_overlap_index(elements)
    if idx is None or idx <= 0 or _depth >= 3:  # 深度上限：防 LLM 改写仍重叠时无限递归
        return [seg]

    heading = next((e for e in elements if e.get("type") == "heading"), None)
    a_elems = elements[:idx]
    b_elems = elements[idx:]
    if heading is not None and heading not in b_elems:  # 续页保留标题做上下文
        b_elems = [heading, *b_elems]

    if min(segment_weight(a_elems), segment_weight(b_elems)) >= _MIN_HALF_WEIGHT:
        # 两半都够实 → 确定性拆
        ratio = len(a_elems) / max(1, len(a_elems) + len(b_elems))
        na, nb = _split_narration(seg.get("narration", ""), ratio)
        seg_a = {**seg, "elements": a_elems, "narration": na}
        seg_b = {**seg, "elements": b_elems, "narration": nb}
        return _split_one(seg_a, model, _depth + 1) + _split_one(seg_b, model, _depth + 1)

    # 会拆出寡淡页 → LLM 改写成两页（补相关正文填实）
    rewritten = _llm_resplit(seg, model)
    if rewritten:
        out: list[dict] = []
        for s in rewritten:
            out.extend(_split_one(s, model, _depth + 1))  # 改写结果若仍重叠，继续处理
        return out
    return [seg]  # LLM 失败 → 不拆


def _llm_resplit(seg: dict, model: str | None) -> list[dict] | None:
    """让 LLM 把一个"重叠且偏大"的 segment 改写成两页，各配相关正文填实。

    返回 2 个 segment 的列表；解析失败 / LLM 不可用时返回 None（调用方回退不拆）。
    """
    seg_json = json.dumps(
        {k: seg.get(k) for k in ("narration", "visual_type", "elements")},
        ensure_ascii=False,
    )
    prompt = (
        "下面这页教学画面大纲同时用了功能重叠的元素（列举类 icon_group/flow_step/"
        "activity_step 之间，或数据类 comparison_panel/table 之间），信息量偏大。\n"
        "请把它改写成【正好 2 个】segment（两页），要求：\n"
        "1. 每页最多 1 个列举类 + 最多 1 个数据类 widget；两页分别承载不同的内容，不重复；\n"
        "2. 每页配 2-4 个支撑元素（text/quote/image 等）把这页填充实，"
        "可补写与原文相关的正文，但不得编造原文没有的事实；\n"
        "3. 原 narration 的信息完整保留，拆成两段旁白（每页一段，各自完整通顺）；\n"
        "4. 每页 body 类型 ≤4 种；保留原有 image 元素的 src 字段；element 的 id 唯一；\n"
        "5. 只输出 JSON 数组：[{segment1},{segment2}]，不要额外文字。\n\n"
        f"原页：\n{seg_json}"
    )
    try:
        raw = chat_with_system(
            user_content=prompt,
            system_prompt="你是教学画面设计师，只输出 JSON，不要解释。",
            model=model, temperature=0.5, max_tokens=3000,
        )
    except Exception as exc:  # noqa: BLE001 — LLM/网络异常时回退
        print(f"  ⚠️ LLM 拆页失败，保持合并: {type(exc).__name__}")
        return None

    if not raw or not raw.strip():
        return None
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = (m.group(1) if m else raw).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        arr = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(arr, list) or len(arr) < 2:
        return None
    segs = [s for s in arr if isinstance(s, dict) and s.get("elements") and s.get("narration")]
    if len(segs) < 2:
        return None
    # 继承缺省字段
    return [{**seg, **s} for s in segs[:2]]


def split_overlapping_segments(segments: list[dict], model: str | None = None) -> list[dict]:
    """对所有含"同组重叠"的 segment 拆段，并重新编号 segment id。"""
    out: list[dict] = []
    for seg in segments:
        out.extend(_split_one(seg, model))
    for i, s in enumerate(out, 1):
        s["id"] = i
    if len(out) != len(segments):
        print(f"  ✂️  类型重叠拆段：{len(segments)} 段 → {len(out)} 段")
    return out


def _build_images_section(images: list[dict]) -> str:
    """构建可用图片的 prompt 片段。

    教材原图来自真实场景/示意，**教学价值 > AI 配图**：
    - 不耗 token/图像费用
    - 内容与教材正文严格一致
    - 视觉风格多样、不易雷同
    所以策略改为"有合适图必用"，而非"不强行塞入"。
    """
    n = len(images)
    target_usage = max(1, int(n * 0.6 + 0.5))  # 至少用 ≥60% 教材图
    lines = [
        f"## 本节可用的教材原图（共 {n} 张，优先使用）\n",
        "以下图片已从教材中提取。**这些是真实教材插图，优先级 > AI 自创**：",
        f"**强制目标：至少 {target_usage} 张应被引用**（占可用图的 ≥60%）；",
        "引用时在 image 类型元素中加上 `\"src\": \"<ID>\"` 字段。\n",
        "| ID | 描述 |",
        "|-----|------|",
    ]
    for img in images:
        lines.append(f"| {img['id']} | {img['description']} |")
    lines.append("")
    lines.extend([
        "### 用图规则",
        "1. **讲到某张图相关概念时必须引用它**——别让 AI 重画一张代替教材原图。",
        f"2. **本节至少 {target_usage} 张教材图被引用**；不达标视为浪费教材资源。",
        "3. 旁白没提到的图也可以放——只要 visual_type 是 illustration/timeline/process 且与"
        "该页主题相关，就该上图。",
        "4. 实在没合适图的页才用 `\"type\": \"image\", \"description\": \"...\"`"
        "（无 src，让动画师/AI 创作）；这种页**不应**超过总页数的 40%。",
    ])
    return "\n".join(lines)


def _sanitize_image_paths(storyboard: dict, available_images: list[dict] | None) -> None:
    """
    后处理：遍历 storyboard 中所有 image 元素。

    - 如果 src 引用了可用教材图 ID，则替换成真实文件名。
    - 如果没有可用教材图，或 src 是 LLM 编造的本地路径，则删除 src，
      保留 description，让后续 AI 配图/占位图流程接管。
    """
    id_to_file = {
        str(img.get("id")): str(img.get("filename"))
        for img in (available_images or [])
        if img.get("id") and img.get("filename")
    }

    for seg in storyboard.get("segments", []):
        fallback_desc = ""
        for elem in seg.get("elements", []):
            if elem.get("type") == "heading" and elem.get("text"):
                fallback_desc = str(elem.get("text"))
                break
        if not fallback_desc:
            fallback_desc = _first_sentence(seg.get("narration"), fallback="Concept illustration")
        for elem in seg.get("elements", []):
            if elem.get("type") != "image":
                continue
            src = elem.get("src", "")
            if src in id_to_file:
                elem["src"] = id_to_file[src]
            elif src:
                elem.pop("src", None)
            if not elem.get("src") and not str(elem.get("description") or "").strip():
                elem["description"] = fallback_desc


def _repair_truncated_json(json_str: str) -> dict | list | None:
    """
    尝试修复被 max_tokens 截断的 storyboard JSON。

    策略：从末尾向前找最后一个完整 segment 的闭合 ``}``，
    截断到那里，然后补全 ``]}}`` 让 JSON 合法。
    """
    # 找 segments 数组中最后一个完整 segment 的 "id": 位置，
    # 从它往前找上一个 }，那就是一个完整 segment 的结尾
    # 更可靠的方式：找最后一个 "id" key，然后从它之前的 } 截断
    last_seg_marker = json_str.rfind('"id"')
    if last_seg_marker < 0:
        return None

    # 从 last_seg_marker 往前找最近的 }, 这就是前一个完整 segment 的结尾
    cut_pos = json_str.rfind("}", 0, last_seg_marker)
    if cut_pos < 0:
        return None

    truncated = json_str[: cut_pos + 1]
    # 补全: 关闭当前 segment 的 } 已在 cut_pos，再关 segments 数组 ] 和外层 }}
    # 计算需要补多少层：先试最常见的 "segments": [ ... }]} 结构
    for suffix in ["]}", "]}}", "]}"]:
        try:
            return json.loads(truncated + suffix)
        except json.JSONDecodeError:
            continue

    return None


def _parse_storyboard(raw: str, lesson_title: str) -> dict[str, Any]:
    """
    解析 LLM 返回的 JSON，提取 segments。
    处理 LLM 可能输出的 markdown 代码块包裹及输出截断。
    """
    # 尝试提取 ```json ... ``` 包裹的 JSON
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_str = raw.strip()

    # 尝试解析 JSON
    data: dict | list = {}
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 尝试找第一个 { 到最后一个 }
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start != -1 and brace_end != -1:
            json_str = json_str[brace_start : brace_end + 1]
        # 第二次尝试：直接解析
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 第三次尝试：截断修复——丢弃最后一个不完整 segment，补全尾部
            repaired = _repair_truncated_json(json_str)
            if repaired is None:
                raise ValueError(
                    f"无法解析 LLM 输出的 JSON（含截断修复尝试）。\n原始输出:\n{raw[:500]}"
                ) from None
            data = repaired

    # 规范化结构
    if isinstance(data, list):
        # LLM 可能直接返回了数组
        data = {"lesson_title": lesson_title, "segments": data}
    if "segments" not in data:
            # 尝试找 segments 字段
            for key in data:
                if isinstance(data[key], list) and len(data[key]) > 0:
                    data = {"lesson_title": lesson_title, "segments": data[key]}
                    break
            else:
                raise ValueError(f"JSON 中未找到 segments 字段: {list(data.keys())}")

    # 强制使用传入的课程标题（LLM 可能自己发挥）
    data["lesson_title"] = lesson_title
    data.setdefault("metadata", {})
    data["metadata"]["total_slides"] = len(data["segments"])

    return data
