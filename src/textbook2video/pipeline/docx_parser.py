"""
DOCX 文档解析模块：DOCX 文件 → 文本 / 按章节拆分

支持两种用法：
  1. 整文档提取：extract_full_text("file.docx")
  2. 按标题拆分章节：list_sections("file.docx") / extract_section("file.docx", 2)

与 PDF parser 对齐的接口：
  extract_lesson_info(path, section_number) -> {"lesson_number", "pages", "text"}
  list_lessons(path) -> [{"lesson_number", "pages", "page_count"}, ...]
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT  # noqa: F401


# 被视为"章节标题"的 Word 样式前缀
_HEADING_STYLES = ("Heading", "heading", "标题")

# 最小有效段落字符数（过滤空行/页码）
_MIN_PARAGRAPH_CHARS = 2


def _is_heading(paragraph) -> bool:
    """判断段落是否为标题（基于样式名称）。"""
    style_name = paragraph.style.name or ""
    return any(style_name.startswith(prefix) for prefix in _HEADING_STYLES)


def _heading_level(paragraph) -> int:
    """提取标题级别（Heading 1 → 1, Heading 2 → 2, …），非标题返回 0。"""
    style_name = paragraph.style.name or ""
    for prefix in _HEADING_STYLES:
        if style_name.startswith(prefix):
            rest = style_name[len(prefix):].strip()
            if rest.isdigit():
                return int(rest)
            return 1  # 没有数字的标题默认为 1 级
    return 0


def _para_text(paragraph) -> str:
    """获取段落文本，包括嵌套的 run 文本。"""
    return paragraph.text.strip()


# ─────────────────────────────────────────────
# 公开接口
# ─────────────────────────────────────────────

def extract_full_text(docx_path: str) -> str:
    """
    提取 DOCX 全文（所有段落拼接）。

    Args:
        docx_path: DOCX 文件路径

    Returns:
        完整文本，段落间以换行分隔
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {docx_path}")
    if not path.suffix.lower() == ".docx":
        raise ValueError(f"非 DOCX 文件: {docx_path}")

    doc = Document(str(path))
    lines: list[str] = []
    for para in doc.paragraphs:
        text = _para_text(para)
        if len(text) >= _MIN_PARAGRAPH_CHARS:
            lines.append(text)

    # 表格中的文本也提取
    for table in doc.tables:
        for row in table.rows:
            cells_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells_text:
                lines.append(" | ".join(cells_text))

    return "\n".join(lines)


def list_sections(docx_path: str, *, max_level: int = 2) -> list[dict]:
    """
    按标题拆分章节，返回结构化列表。

    只把 Heading 1 ~ max_level 作为章节分界。

    Args:
        docx_path: DOCX 文件路径
        max_level: 最大标题级别（默认 2，只识别 Heading 1/2）

    Returns:
        [{"section_number": 1, "title": "...", "para_count": N}, ...]
    """
    sections = _split_sections(docx_path, max_level=max_level)
    return [
        {
            "section_number": i + 1,
            "title": sec["title"],
            "para_count": len(sec["paragraphs"]),
        }
        for i, sec in enumerate(sections)
    ]


def extract_section(docx_path: str, section_number: int, *, max_level: int = 2) -> str:
    """
    提取指定章节的文本。

    Args:
        docx_path: DOCX 文件路径
        section_number: 章节编号（从 1 开始）
        max_level: 章节划分的最大标题级别

    Returns:
        该章节的文本
    """
    sections = _split_sections(docx_path, max_level=max_level)
    if section_number < 1 or section_number > len(sections):
        raise ValueError(
            f"不支持的章节号: {section_number}，可选: 1-{len(sections)}"
        )
    sec = sections[section_number - 1]
    return "\n".join(sec["paragraphs"])


# ─────────────────────────────────────────────
# 与 PDF parser 对齐的接口（供 CLI 统一调用）
# ─────────────────────────────────────────────

def extract_lesson_info(docx_path: str, section_number: int) -> dict:
    """
    对齐 PDF parser 的 extract_lesson_info 接口。

    Returns:
        {"lesson_number": int, "pages": (0, 0), "text": str, "title": str}
        注意: DOCX 没有页码概念，pages 固定返回 (0, 0)。
    """
    sections = _split_sections(docx_path)
    if section_number < 1 or section_number > len(sections):
        raise ValueError(
            f"不支持的章节号: {section_number}，可选: 1-{len(sections)}"
        )
    sec = sections[section_number - 1]
    return {
        "lesson_number": section_number,
        "pages": (0, 0),
        "text": "\n".join(sec["paragraphs"]),
        "title": sec["title"],
    }


def list_lessons(docx_path: str) -> list[dict]:
    """
    对齐 PDF parser 的 list_lessons 接口。

    Returns:
        [{"lesson_number": int, "pages": (0,0), "page_count": 0, "title": str, "para_count": int}, ...]
    """
    sections = _split_sections(docx_path)
    return [
        {
            "lesson_number": i + 1,
            "pages": (0, 0),
            "page_count": 0,
            "title": sec["title"],
            "para_count": len(sec["paragraphs"]),
        }
        for i, sec in enumerate(sections)
    ]


# ─────────────────────────────────────────────
# 内部实现
# ─────────────────────────────────────────────

def _split_sections(docx_path: str, *, max_level: int = 2) -> list[dict]:
    """
    内部方法：按标题拆分 DOCX 为章节。

    Returns:
        [{"title": str, "paragraphs": [str, ...]}, ...]
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {docx_path}")
    if not path.suffix.lower() == ".docx":
        raise ValueError(f"非 DOCX 文件: {docx_path}")

    doc = Document(str(path))

    sections: list[dict] = []
    current_title = ""
    current_paras: list[str] = []

    for para in doc.paragraphs:
        level = _heading_level(para)
        text = _para_text(para)

        if level > 0 and level <= max_level and text:
            # 遇到新章节标题 → 保存上一段
            if current_paras or current_title:
                sections.append({
                    "title": current_title,
                    "paragraphs": current_paras,
                })
            current_title = text
            current_paras = []
        else:
            if len(text) >= _MIN_PARAGRAPH_CHARS:
                current_paras.append(text)

    # 最后一个章节
    if current_paras or current_title:
        sections.append({
            "title": current_title,
            "paragraphs": current_paras,
        })

    # 如果整个文档没有任何标题，把全文当作一个章节
    if not sections:
        all_text = [
            _para_text(p) for p in doc.paragraphs
            if len(_para_text(p)) >= _MIN_PARAGRAPH_CHARS
        ]
        sections.append({
            "title": path.stem,
            "paragraphs": all_text,
        })

    # 过滤空章节
    sections = [s for s in sections if s["paragraphs"]]

    return sections
