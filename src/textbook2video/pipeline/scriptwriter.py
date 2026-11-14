"""
讲稿生成器：教材文本 → 讲稿分段文本

用法：
  from textbook2video.pipeline.scriptwriter import generate_script
  segments = generate_script("教材文本")
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


_SEGMENT_HEADER_RE = re.compile(
    r"^(?:第\s*\d+\s*段|Segment\s+\d+)\s*"
    r"(?:[：:]\s*)?(?:[（(][^）)]*[）)])?\s*(?:[：:])?$",
    re.IGNORECASE,
)
_MARKDOWN_TITLE_RE = re.compile(r"^#{1,6}\s+\S")
_FENCE_RE = re.compile(r"^```(?:[a-z0-9_+-]+)?\s*$", re.IGNORECASE)
_CONTENT_LABEL_RE = re.compile(r"^(?:讲稿)?内容\s*[：:]?\s*$")
_EMPTY_MARKERS = {"（无内容）", "(无内容)", "无内容", "N/A", "NA"}


def generate_script(
    lesson_text: str,
    model: str | None = None,
    lesson_plan: dict[str, Any] | None = None,
    raw_response_path: str | Path | None = None,
) -> list[str]:
    """
    根据教材文本生成讲稿分段。

    Args:
        lesson_text: 教材提取的课程文本
        model: 可选，指定模型名
        raw_response_path: 可选的模型原文保存路径。配套解析报告写入同名 .parse.json。

    Returns:
        讲稿分段列表，每段对应一页动画
    """
    from textbook2video.llm.client import chat_with_system, load_prompt

    prompt_template = load_prompt("script.md")
    if lesson_plan:
        from textbook2video.pipeline.lesson_plan import lesson_plan_prompt_section

        lesson_text = lesson_plan_prompt_section(lesson_plan) + "\n\n## 教材内容\n" + lesson_text
    prompt = prompt_template.replace("{lesson_text}", lesson_text)

    response_path = Path(raw_response_path) if raw_response_path is not None else None
    report_path = response_path.with_suffix(".parse.json") if response_path else None
    if response_path is not None:
        response_path.parent.mkdir(parents=True, exist_ok=True)
        if response_path.exists() or report_path.exists():
            raise FileExistsError(
                f"script diagnostics already exist; choose a fresh output path: {response_path}"
            )

    result = chat_with_system(
        user_content=prompt,
        system_prompt="你是一位大学通识课讲师，将教材内容转化为生动、专业的课堂讲稿，面向大学本科生。",
        model=model,
        temperature=0.7,
        max_tokens=4096,
    )

    if response_path is not None:
        with response_path.open("x", encoding="utf-8", newline="") as stream:
            stream.write(result)

    segments: list[str] = []
    failure: Exception | None = None
    try:
        segments = _parse_script(result)
        if not segments:
            raise ValueError("讲稿模型未返回可用内容")
    except Exception as exc:
        failure = exc

    if report_path is not None:
        report = {
            "schema_version": "script-parse-diagnostic-v1",
            "parser": "textbook2video.pipeline.scriptwriter._parse_script",
            "status": "FAILED" if failure else "PARSED",
            "raw_response_path": str(response_path.resolve()),
            "raw_response_sha256": hashlib.sha256(result.encode("utf-8")).hexdigest(),
            "raw_response_char_count": len(result),
            "parsed_segment_count": len(segments),
            "boundary_offset_basis": "raw_response.strip(); Unicode character offsets; end exclusive",
            "segments": _script_segment_boundaries(result, segments),
            "failure": (
                {"type": type(failure).__name__, "message": str(failure)}
                if failure else None
            ),
        }
        with report_path.open("x", encoding="utf-8", newline="") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")

    if failure is not None:
        raise failure
    return segments


def _script_segment_boundaries(raw: str, segments: list[str]) -> list[dict[str, Any]]:
    """Locate parsed text blocks in the normalized response for offline review."""
    normalized = raw.strip()
    lines = normalized.split("\n") if normalized else []
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1

    boundaries: list[dict[str, Any]] = []
    cursor = 0
    for index, segment in enumerate(segments, start=1):
        target_lines = segment.splitlines()
        match_start: int | None = None
        if target_lines:
            for start in range(cursor, len(lines) - len(target_lines) + 1):
                if all(
                    lines[start + delta].strip() == target.strip()
                    for delta, target in enumerate(target_lines)
                ):
                    match_start = start
                    break
        if match_start is None:
            boundaries.append({
                "index": index,
                "parsed_char_count": len(segment),
                "boundary_status": "NOT_LOCATED_IN_RAW_RESPONSE",
            })
            continue

        end_line = match_start + len(target_lines) - 1
        start_char = line_offsets[match_start]
        end_char = line_offsets[end_line] + len(lines[end_line])
        boundaries.append({
            "index": index,
            "response_start_line": match_start + 1,
            "response_end_line": end_line + 1,
            "response_start_char": start_char,
            "response_end_char_exclusive": end_char,
            "parsed_char_count": len(segment),
            "boundary_status": "LOCATED",
        })
        cursor = end_line + 1
    return boundaries


def _parse_script(raw: str) -> list[str]:
    """
    解析 LLM 返回的讲稿文本，拆分为段落列表。

    支持格式：
    1. "第1段：（8-12秒）\n内容..." 格式
    2. "**第1段（约15秒）**\n\n内容..." 格式
    3. 纯段落格式（按空行分隔）
    """
    lines = raw.strip().split("\n")

    segments = []
    current = []
    seen_segment_header = False

    for line in lines:
        stripped = line.strip()
        if _FENCE_RE.fullmatch(stripped) or _CONTENT_LABEL_RE.fullmatch(stripped):
            continue
        if stripped in _EMPTY_MARKERS:
            continue

        # Accept plain and Markdown-bold headers, with optional duration:
        # 第1段：（8-12秒）, **第1段（约15秒）**, Segment 1:.
        header = stripped
        if header.startswith("**") and header.endswith("**") and len(header) >= 4:
            header = header[2:-2].strip()
        if _SEGMENT_HEADER_RE.fullmatch(header):
            # 保存前一段
            if current:
                segments.append("\n".join(current).strip())
                current = []
            # 这一行是标题行，跳过，内容从下一行开始
            seen_segment_header = True
            continue

        # A leading Markdown document title is metadata, not narration.
        if not seen_segment_header and not current and _MARKDOWN_TITLE_RE.match(stripped):
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
        and not _MARKDOWN_TITLE_RE.match(s.strip())
        and s.strip() not in _EMPTY_MARKERS
    ]

    return segments
