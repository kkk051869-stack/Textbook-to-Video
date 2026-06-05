"""
画面大纲生成器：讲稿文本 → 画面大纲 JSON

用法：
  from textbook2video.pipeline.storyboard import generate_storyboard
  storyboard = generate_storyboard(script_segments, lesson_title="第4课")
"""

import json
import re
from typing import Any

from textbook2video.llm.client import chat_with_system, load_prompt

# 每批最多处理的讲稿段数，避免单次 LLM 输出被 max_tokens 截断
_BATCH_SIZE = 3


def generate_storyboard(
    script_segments: list[str],
    *,
    lesson_title: str = "",
    model: str | None = None,
    available_images: list[dict] | None = None,
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

    storyboard: dict[str, Any] = {
        "lesson_title": lesson_title,
        "segments": all_segments,
        "metadata": {"total_slides": len(all_segments)},
    }

    if available_images:
        _resolve_image_paths(storyboard, available_images)

    return storyboard


def _build_images_section(images: list[dict]) -> str:
    """构建可用图片的 prompt 片段。"""
    lines = [
        "## 本节可用的教材原图\n",
        "以下图片已从教材中提取，你可以在 elements 中引用它们。",
        '引用时在 image 类型元素中加上 `"src": "<ID>"` 字段。\n',
        "| ID | 描述 |",
        "|-----|------|",
    ]
    for img in images:
        lines.append(f"| {img['id']} | {img['description']} |")
    lines.append("")
    lines.append("注意：只在画面确实需要该图时才引用，不要强行塞入所有图片。")
    lines.append('没有合适图片时仍然用 `"type": "image", "description": "..."` 让动画师自行创作。\n')
    return "\n".join(lines)


def _resolve_image_paths(storyboard: dict, available_images: list[dict]) -> None:
    """
    后处理：遍历 storyboard 中所有 image 元素，
    把 LLM 输出的 src ID（如 "fig1-1"）替换成真实文件名（如 "fig1-1_人类的四次工业革命.png"）。
    """
    id_to_file = {img["id"]: img["filename"] for img in available_images}

    for seg in storyboard.get("segments", []):
        for elem in seg.get("elements", []):
            if elem.get("type") != "image":
                continue
            src = elem.get("src", "")
            if src in id_to_file:
                elem["src"] = id_to_file[src]


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