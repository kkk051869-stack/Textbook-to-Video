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
) -> dict[str, Any]:
    """
    根据讲稿分段生成画面大纲 JSON。

    Args:
        script_segments: 讲稿分段列表
        lesson_title: 课程标题
        model: 可选，指定模型名

    Returns:
        画面大纲 dict,符合 storyboard JSON schema
    """
    # 组装讲稿文本
    script_text = ""
    for i, seg in enumerate(script_segments, 1):
        script_text += f"第{i}段讲稿：\n{seg}\n\n"

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

    return _parse_storyboard(result, lesson_title)


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