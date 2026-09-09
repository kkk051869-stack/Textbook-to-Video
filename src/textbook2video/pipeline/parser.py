"""
教材解析模块：教材 PDF / DOCX → 按课/节提取的文本（+ 图片）

用法：
  from textbook2video.pipeline.parser import extract_lesson, extract_section_from_docx

  # PDF
  text = extract_lesson("textbook.pdf", lesson_number=4)

  # DOCX
  text = extract_section_from_docx("textbook.docx", chapter="第一章", section="一、时代背景")
  sections = list_sections_from_docx("textbook.docx")

  # DOCX + 图片
  result = extract_section_from_docx("textbook.docx", chapter_number=0, section_number=0, include_images=True)
  # result = {"text": "...", "images": [{"id": "fig1-1", "filename": "...", "description": "..."}]}
"""

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


# ── DOCX 解析 ──

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_CAPTION_RE = re.compile(r"^图(\d+)-(\d+)\s+(.+)")
_SAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')

# 这本《数字素养》教材有两种样式体系：
#
# 前半部分（目录区, 段落 0-~280）:
#   Style 17 = 章标题（如 "第一章 绪论"）
#   Style 14 = 节标题（如 "一、时代背景"）
#   Style 18 = 小节标题（如 "（一）百年大变局"）
#   Style 19 = 篇标题（如 "第一篇 基础篇"）
#
# 后半部分（正文区, 段落 ~280 起）:
#   Style 2  = 章标题（如 "绪 论"）
#   Style 4  = 节标题（如 "一、时代背景"）
#   Style 5  = 小节标题（如 "（一）百年大变局"）
#   None     = 正文段落
#
# 目录区标题带有页码（如 "一、时代背景21"），正文区标题不带页码。


def _get_docx_style(paragraph) -> str | None:
    """Get paragraph style ID from a DOCX paragraph element."""
    pPr = paragraph.find("w:pPr/w:pStyle", _DOCX_NS)
    if pPr is not None:
        return pPr.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
    return None


def _get_docx_text(paragraph) -> str:
    """Get all text content from a DOCX paragraph element."""
    texts = []
    for t in paragraph.findall(".//w:t", _DOCX_NS):
        if t.text:
            texts.append(t.text)
    return "".join(texts)


def _get_blip_ids(paragraph) -> list[str]:
    """Extract all embedded image rIds from a paragraph."""
    blips = paragraph.findall(f".//{{{_NS_A}}}blip")
    ids = []
    for blip in blips:
        embed = blip.get(f"{{{_NS_R}}}embed")
        if embed:
            ids.append(embed)
    return ids


def _safe_filename(text: str, max_len: int = 40) -> str:
    """Convert text to a safe filename."""
    text = _SAFE_FILENAME_RE.sub("_", text)
    text = text.replace(" ", "_").strip("_")
    return text[:max_len] if len(text) > max_len else text


class _DocxData:
    """Holds parsed DOCX data to avoid re-opening the zip."""

    def __init__(self, docx_path: str):
        self.path = docx_path
        self.paragraphs: list[ET.Element] = []
        self.rid_map: dict[str, str] = {}
        self.media_sizes: dict[str, int] = {}
        self._zip = None
        self._load()

    def _load(self):
        with zipfile.ZipFile(self.path, "r") as z:
            self._zip_ref = z
            # Parse document.xml
            doc_xml = z.read("word/document.xml")
            root = ET.fromstring(doc_xml)
            self.paragraphs = root.findall(".//w:p", _DOCX_NS)

            # Build rId -> media path mapping
            rels_xml = z.read("word/_rels/document.xml.rels")
            rels_root = ET.fromstring(rels_xml)
            for rel in rels_root:
                rid = rel.get("Id")
                target = rel.get("Target")
                if target and "media" in target:
                    self.rid_map[rid] = target

            # Media file sizes
            for name in z.namelist():
                if name.startswith("word/media/"):
                    self.media_sizes[name] = z.getinfo(name).file_size

    def extract_image(self, media_path: str) -> bytes | None:
        """Extract image bytes from the DOCX zip."""
        full_path = media_path if media_path.startswith("word/") else f"word/{media_path}"
        try:
            with zipfile.ZipFile(self.path, "r") as z:
                return z.read(full_path)
        except KeyError:
            return None

    def get_parsed_paragraphs(self) -> list[tuple[str | None, str]]:
        """Return (style, text) tuples for all paragraphs."""
        return [(_get_docx_style(p), _get_docx_text(p)) for p in self.paragraphs]


def _extract_images_in_range(
    docx_data: _DocxData,
    start: int,
    end: int | None,
    output_dir: Path | None = None,
    min_size: int = 5000,
) -> list[dict]:
    """
    Extract images from paragraphs in [start, end) range.

    Returns list of image dicts with id, filename, description.
    If output_dir is provided, also writes image files to disk.
    """
    paras = docx_data.paragraphs
    end = end or len(paras)
    images = []
    seen_paths = {}

    for i in range(start, end):
        blip_ids = _get_blip_ids(paras[i])
        if not blip_ids:
            continue

        for rid in blip_ids:
            if rid not in docx_data.rid_map:
                continue

            media_path = docx_data.rid_map[rid]
            full_path = media_path if media_path.startswith("word/") else f"word/{media_path}"
            size = docx_data.media_sizes.get(full_path, 0)
            if size < min_size:
                continue

            # Find caption in next few paragraphs
            caption_seq = 0
            caption_chapter = 0
            title_text = ""
            for offset in range(1, 4):
                if i + offset >= len(paras):
                    break
                next_text = _get_docx_text(paras[i + offset])
                match = _CAPTION_RE.match(next_text)
                if match:
                    caption_chapter = int(match.group(1))
                    caption_seq = int(match.group(2))
                    title_text = match.group(3)
                    break
                if next_text and not next_text.startswith("图"):
                    break

            if not caption_seq:
                continue

            img_id = f"fig{caption_chapter}-{caption_seq}"
            ext = os.path.splitext(full_path)[1].lower()
            safe_title = _safe_filename(title_text)
            filename = f"{img_id}_{safe_title}{ext}"

            # Handle duplicates
            if filename in seen_paths:
                seen_paths[filename] += 1
                base, dot_ext = os.path.splitext(filename)
                filename = f"{base}_{seen_paths[filename]}{dot_ext}"
            else:
                seen_paths[filename] = 1

            # Write to disk if output_dir provided
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                data = docx_data.extract_image(full_path)
                if data:
                    (output_dir / filename).write_bytes(data)

            images.append({
                "id": img_id,
                "filename": filename,
                "description": title_text,
            })

    return images


def _parse_docx_paragraphs(docx_path: str) -> list[tuple[str | None, str]]:
    """
    Parse a DOCX file and return list of (style, text) tuples for ALL paragraphs.
    """
    with zipfile.ZipFile(docx_path, "r") as z:
        xml_data = z.read("word/document.xml")

    root = ET.fromstring(xml_data)
    paras = root.findall(".//w:p", _DOCX_NS)

    result = []
    for p in paras:
        style = _get_docx_style(p)
        text = _get_docx_text(p)
        result.append((style, text))

    return result


def _find_content_start(paras: list[tuple[str | None, str]]) -> int:
    """
    Find where the actual book content starts (after the table of contents).

    The TOC ends when we hit the first long body paragraph (style=None, >100 chars)
    that follows a style-2 heading (which marks the start of actual content like "序 言").
    """
    for i, (style, text) in enumerate(paras):
        if style == "2" and text.strip():
            # Style 2 in content area = chapter/title heading (e.g., "序 言")
            # Check if next few paragraphs have substantial body text
            for j in range(i + 1, min(i + 5, len(paras))):
                s, t = paras[j]
                if s is None and len(t.strip()) > 100:
                    return i
    return 0


def _strip_page_number(text: str) -> str:
    """Remove trailing page numbers from TOC heading text."""
    import re
    # Remove trailing digits (page numbers) like "一、时代背景21" -> "一、时代背景"
    return re.sub(r"\s*\d{1,4}\s*$", "", text).strip()


def _normalize_text(text: str) -> str:
    """Normalize text for matching: remove ALL whitespace."""
    import re
    # Remove ALL whitespace for matching (handles "绪    论" vs "绪论")
    return re.sub(r"\s+", "", text).strip()


def list_sections_from_docx(docx_path: str) -> list[dict]:
    """
    List all chapters and sections in a DOCX file.
    Uses the content area (after TOC) for accurate section listing.

    Returns:
        List of dicts: {"chapter": str, "section": str, "subsection": str}
    """
    paras = _parse_docx_paragraphs(docx_path)
    content_start = _find_content_start(paras)
    content_paras = paras[content_start:]

    sections = []
    current_chapter = None

    for style, text in content_paras:
        text_stripped = text.strip()
        if not text_stripped:
            continue

        if style == "2" and text_stripped:
            # Chapter heading
            current_chapter = text_stripped
        elif style == "4" and text_stripped:
            # Section heading
            sections.append({
                "chapter": current_chapter,
                "section": text_stripped,
            })

    return sections


def extract_section_from_docx(
    docx_path: str,
    *,
    chapter: str | None = None,
    section: str | None = None,
    chapter_number: int | None = None,
    section_number: int | None = None,
    include_images: bool = False,
    image_output_dir: str | None = None,
) -> str | dict:
    """
    Extract text content for a specific section from a DOCX file.

    Uses the content area (after TOC) with style-2/4/5 headings.

    Args:
        docx_path: Path to .docx file
        chapter: Chapter keyword (e.g., "绪论" or "第一章" or "第一章 绪论")
        section: Section keyword (e.g., "时代背景" or "一、时代背景")
        chapter_number: Chapter index (0-based)
        section_number: Section index within chapter (0-based)
        include_images: If True, also extract images and return dict
        image_output_dir: Directory to write image files (only when include_images=True)

    Returns:
        If include_images=False: str (text content)
        If include_images=True: {"text": str, "images": list[dict]}
    """
    docx_data = _DocxData(docx_path)
    paras = docx_data.get_parsed_paragraphs()
    content_start = _find_content_start(paras)

    # Collect boundaries from content area
    chapter_indices = []  # (para_index, text)
    section_indices = []  # (para_index, text)

    for i in range(content_start, len(paras)):
        style, text = paras[i]
        text_stripped = text.strip()
        if not text_stripped:
            continue
        if style == "2":
            chapter_indices.append((i, text_stripped))
        elif style == "4":
            section_indices.append((i, text_stripped))

    # Determine target range
    target_start = None
    target_end = None

    if chapter_number is not None and section_number is not None:
        if chapter_number >= len(chapter_indices):
            raise ValueError(
                f"章节号 {chapter_number} 超出范围 (共 {len(chapter_indices)} 章)"
            )

        ch_idx = chapter_indices[chapter_number][0]
        ch_text = chapter_indices[chapter_number][1]

        # Get sections within this chapter
        ch_sections = []
        for s_idx, s_text in section_indices:
            if s_idx > ch_idx:
                next_ch = None
                for c_idx, _ in chapter_indices:
                    if c_idx > s_idx:
                        next_ch = c_idx
                        break
                if next_ch is not None and s_idx >= next_ch:
                    break
                ch_sections.append((s_idx, s_text))

        if section_number >= len(ch_sections):
            raise ValueError(
                f"节号 {section_number} 超出范围 "
                f"(在「{ch_text}」中共 {len(ch_sections)} 节)"
            )

        target_start = ch_sections[section_number][0]
        if section_number + 1 < len(ch_sections):
            target_end = ch_sections[section_number + 1][0]
        else:
            next_ch = None
            for c_idx, _ in chapter_indices:
                if c_idx > target_start:
                    next_ch = c_idx
                    break
            target_end = next_ch

    elif chapter is not None and section is not None:
        # Find chapter by keyword (normalize spaces for matching)
        norm_chapter = _normalize_text(_strip_page_number(chapter))
        found_chapter = None
        for c_idx, c_text in chapter_indices:
            norm_c = _normalize_text(_strip_page_number(c_text))
            if norm_chapter in norm_c or norm_c in norm_chapter or chapter in c_text:
                found_chapter = c_idx
                break

        if found_chapter is None:
            raise ValueError(f"未找到章节: {chapter}")

        found_section = None
        norm_section = _normalize_text(_strip_page_number(section))
        for s_idx, s_text in section_indices:
            if s_idx > found_chapter:
                norm_s = _normalize_text(_strip_page_number(s_text))
                if norm_section in norm_s or norm_s in norm_section or section in s_text:
                    # Check we haven't passed the next chapter
                    next_ch = None
                    for c_idx, _ in chapter_indices:
                        if c_idx > s_idx:
                            next_ch = c_idx
                            break
                    if next_ch is not None and s_idx >= next_ch:
                        break
                    found_section = s_idx
                    break

        if found_section is None:
            raise ValueError(f"在章节中未找到节: {section}")

        target_start = found_section
        # End at next section
        for s_idx, _ in section_indices:
            if s_idx > found_section:
                target_end = s_idx
                break
    else:
        raise ValueError(
            "请提供 chapter+section（按名称）或 chapter_number+section_number（按序号）"
        )

    # Extract content
    content_lines = []
    for i in range(target_start, target_end if target_end else len(paras)):
        style, text = paras[i]
        if text.strip():
            content_lines.append(text.strip())

    text_content = "\n".join(content_lines)

    if not include_images:
        return text_content

    # Extract images in the same range
    out_dir = Path(image_output_dir) if image_output_dir else None
    images = _extract_images_in_range(
        docx_data, target_start, target_end, output_dir=out_dir
    )

    return {"text": text_content, "images": images}


# ── 课程页码范围映射（从目录提取） ──
# 格式：lesson_number -> (start_page_1based, end_page_1based)
# 根据《人工智能与智慧社会》目录整理
LESSON_PAGE_RANGES: dict[int, tuple[int, int]] = {
    # 第一单元：走进人工智能（第9-35页）
    1: (10, 16),    # 第1课　身边的人工智能
    2: (17, 23),    # 第2课　什么是人工智能
    3: (24, 28),    # 第3课　人工智能的实现方式
    4: (29, 34),    # 第4课　人工智能的技术基础
    # 第二单元：文本的智能生成（第35页起）
    5: (36, 41),    # 第5课　文本处理的基本单位
    6: (42, 47),    # 第6课　统计与文本生成
    7: (48, 53),    # 第7课　词的含义与语义编码
    8: (54, 59),    # 第8课　词的上下文与动态语义
    9: (60, 65),    # 第9课　文本生成与控制
    # 第三单元：图像、声音与视频的智能生成
    10: (66, 72),   # 第10课　图像特征的提取
    11: (73, 78),   # 第11课　图像的风格迁移
    12: (79, 84),   # 第12课　图像的生成方式
    13: (85, 90),   # 第13课　根据文字生成图像
    14: (91, 96),   # 第14课　声音的智能生成
    15: (97, 103),  # 第15课　视频的智能生成
    # 第四单元：智能推理的应用
    16: (104, 109), # 第16课　决策树与智能推理
    17: (110, 115), # 第17课　知识图谱与智能推理
    18: (116, 121), # 第18课　推理与搜索
    19: (122, 127), # 第19课　智能推荐
    20: (128, 133), # 第20课　智能推理的伦理
    # 第五单元：智慧社会与智能向善
    21: (134, 139), # 第21课　智慧社会与个人生活
    22: (140, 144), # 第22课　智慧社会与智能创新
    23: (145, 149), # 第23课　智慧社会与智能治理
    24: (150, 154), # 第24课　智能向善与伦理道德
    # 第六单元：AI项目工坊
    25: (155, 161), # 第25课　与机器下井字棋
    26: (162, 167), # 第26课　推荐出行方式
    27: (168, 173), # 第27课　智能环境播报助手
}


def extract_lesson(pdf_path: str, lesson_number: int) -> str:
    """
    从教材 PDF 中提取指定课程的文本内容。

    Args:
        pdf_path: PDF 文件路径
        lesson_number: 课号（1-27）

    Returns:
        该课的完整文本内容
    """
    if lesson_number not in LESSON_PAGE_RANGES:
        available = sorted(LESSON_PAGE_RANGES.keys())
        raise ValueError(f"不支持的课号: {lesson_number}，可选: {available}")

    start, end = LESSON_PAGE_RANGES[lesson_number]
    doc = fitz.open(pdf_path)

    pages_text = []
    for i in range(start - 1, min(end, doc.page_count)):  # 0-indexed
        text = doc[i].get_text()
        pages_text.append(text.strip())

    doc.close()

    return "\n\n".join(pages_text)


def extract_lesson_info(pdf_path: str, lesson_number: int) -> dict:
    """
    提取课程信息，包括文本和页码范围。

    Returns:
        {"lesson_number": int, "pages": (start, end), "text": str}
    """
    start, end = LESSON_PAGE_RANGES[lesson_number]
    text = extract_lesson(pdf_path, lesson_number)
    return {
        "lesson_number": lesson_number,
        "pages": (start, end),
        "text": text,
    }


def list_lessons(pdf_path: str) -> list[dict]:
    """列出 PDF 中所有可提取的课程信息。"""
    doc = fitz.open(pdf_path)
    total = doc.page_count
    doc.close()

    lessons = []
    for num in sorted(LESSON_PAGE_RANGES.keys()):
        start, end = LESSON_PAGE_RANGES[num]
        if start <= total:
            lessons.append({
                "lesson_number": num,
                "pages": (start, end),
                "page_count": end - start + 1,
            })
    return lessons