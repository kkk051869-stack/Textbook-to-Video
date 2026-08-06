"""
讲稿生成器：教材文本 → 讲稿分段文本

用法：
  from textbook2video.pipeline.scriptwriter import generate_script
  segments = generate_script("教材文本")
"""

from __future__ import annotations

import re
from typing import Any


_SEGMENT_HEADER_RE = re.compile(
    r"^(?:第\s*\d+\s*段|Segment\s+\d+)\s*[：:]",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^```(?:[a-z0-9_+-]+)?\s*$", re.IGNORECASE)
_CONTENT_LABEL_RE = re.compile(r"^(?:讲稿)?内容\s*[：:]?\s*$")
_EMPTY_MARKERS = {"（无内容）", "(无内容)", "无内容", "N/A", "NA"}


def generate_script(
    lesson_text: str,
    model: str | None = None,
    lesson_plan: dict[str, Any] | None = None,
) -> list[str]:
    """
    根据教材文本生成讲稿分段。

    Args:
        lesson_text: 教材提取的课程文本
        model: 可选，指定模型名

    Returns:
        讲稿分段列表，每段对应一页动画
    """
    from textbook2video.llm.client import chat_with_system, load_prompt

    prompt_template = load_prompt("script.md")
    if lesson_plan:
        from textbook2video.pipeline.lesson_plan import lesson_plan_prompt_section

        lesson_text = lesson_plan_prompt_section(lesson_plan) + "\n\n## 教材内容\n" + lesson_text
    prompt = prompt_template.replace("{lesson_text}", lesson_text)

    result = chat_with_system(
        user_content=prompt,
        system_prompt="你是一位大学通识课讲师，将教材内容转化为生动、专业的课堂讲稿，面向大学本科生。",
        model=model,
        temperature=0.7,
        max_tokens=4096,
    )

    segments = _parse_script(result)
    if not segments:
        raise ValueError("讲稿模型未返回可用内容")
    if len(segments) > 12:
        raise ValueError(
            f"讲稿被解析为 {len(segments)} 段，超过 12 段上限；"
            "请检查模型是否输出了代码围栏或额外说明"
        )
    return segments


def _parse_script(raw: str) -> list[str]:
    """
    解析 LLM 返回的讲稿文本，拆分为段落列表。

    支持两种格式：
    1. "第1段：（8-12秒）\n内容..." 格式
    2. 纯段落格式（按空行分隔）
    """
    lines = raw.strip().split("\n")

    segments = []
    current = []

    for line in lines:
        stripped = line.strip()
        if _FENCE_RE.fullmatch(stripped) or _CONTENT_LABEL_RE.fullmatch(stripped):
            continue
        if stripped in _EMPTY_MARKERS:
            continue

        # 检测 "第N段：（x-y秒）" / "第N段：" / "Segment N:"。
        if _SEGMENT_HEADER_RE.match(stripped):
            # 保存前一段
            if current:
                segments.append("\n".join(current).strip())
                current = []
            # 这一行是标题行，跳过，内容从下一行开始
            continue

        # 空行 = 段落分隔
        if stripped == "":
            if current:
                segments.append("\n".join(current).strip())
                current = []
        else:
            current.append(stripped)

    # 最后一段
    if current:
        segments.append("\n".join(current).strip())

    # 如果没解析出段落（纯文本），按空行分割
    if not segments:
        paragraphs = [p.strip() for p in raw.strip().split("\n\n") if p.strip()]
        segments = paragraphs

    # 过滤纯分隔符、代码围栏、内容标签和空内容标记。
    segments = [
        s.strip() for s in segments
        if s.strip("—-\t *\n\r")
        and not _FENCE_RE.fullmatch(s.strip())
        and not _CONTENT_LABEL_RE.fullmatch(s.strip())
        and s.strip() not in _EMPTY_MARKERS
    ]

    return segments
