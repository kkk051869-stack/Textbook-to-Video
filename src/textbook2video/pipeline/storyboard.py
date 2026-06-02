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


def generate_storyboard(
    script_segments: list[str],
    *,
    lesson_title: str = "",
    model: str | None = None,
    available_images: list[dict] | None = None,
) -> dict[str, Any]:
    """
    根据讲稿分段生成画面大纲 JSON。

    Args:
        script_segments: 讲稿分段列表
        lesson_title: 课程标题
        model: 可选，指定模型名
        available_images: 可用的教材原图列表，每项含 id, filename, description

    Returns:
        画面大纲 dict,符合 storyboard JSON schema
    """
    # 组装讲稿文本
    script_text = ""
    for i, seg in enumerate(script_segments, 1):
        script_text += f"第{i}段讲稿：\n{seg}\n\n"

    # 注入可用图片信息
    if available_images:
        script_text += _build_images_section(available_images)

    prompt_template = load_prompt("storyboard.md")
    prompt = prompt_template.replace("{script_text}", script_text)

    result = chat_with_system(
        user_content=prompt,
        system_prompt=(
            "你是一位教学动画设计师。根据讲稿内容输出 JSON 格式的画面大纲。"
            "只输出 JSON,不要额外文字。"
        ),
        model=model,
        temperature=0.7,
        max_tokens=8192,
    )

    storyboard = _parse_storyboard(result, lesson_title)

    # 后处理：把 LLM 选的图片 src ID 替换成真实文件路径
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


def _parse_storyboard(raw: str, lesson_title: str) -> dict[str, Any]:
    """
    解析 LLM 返回的 JSON，提取 segments。
    处理 LLM 可能输出的 markdown 代码块包裹。
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
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"无法解析 LLM 输出的 JSON: {e}\n原始输出:\n{raw[:500]}")
        else:
            raise ValueError(f"未能找到 JSON 数据\n原始输出:\n{raw[:500]}")

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