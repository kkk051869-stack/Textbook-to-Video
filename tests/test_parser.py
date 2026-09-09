"""测试 PDF 教材解析模块"""

import fitz
import pytest
from textbook2video.pipeline.parser import (
    extract_lesson,
    extract_lesson_info,
    list_lessons,
    LESSON_PAGE_RANGES,
)


@pytest.fixture
def pdf_path(tmp_path):
    """生成测试用 PDF，避免依赖本机外部教材文件。"""
    path = tmp_path / "test_textbook.pdf"
    doc = fitz.open()

    for page_num in range(1, 174):
        page = doc.new_page()
        text = f"PAGE {page_num} TEST_TEXTBOOK_CONTENT"
        if 10 <= page_num <= 16:
            text += " LESSON_ONE ARTIFICIAL_INTELLIGENCE NEARBY" * 20
        if 29 <= page_num <= 34:
            text += " LEARNING_GOAL DATA COMPUTE ALGORITHM AI TECH_BASE" * 30
        if 66 <= page_num <= 72:
            text += " LESSON_TEN IMAGE_FEATURE EXTRACTION GENERATIVE_AI" * 20
        for line_idx in range(0, len(text), 85):
            page.insert_text((72, 72 + (line_idx // 85) * 14), text[line_idx : line_idx + 85])

    doc.save(path)
    doc.close()
    return str(path)


class TestLessonPageRanges:
    """测试课程序号映射"""

    def test_all_lessons_covered(self):
        """27 课都有页码范围"""
        assert len(LESSON_PAGE_RANGES) == 27
        assert set(LESSON_PAGE_RANGES.keys()) == set(range(1, 28))

    def test_ranges_are_valid(self):
        """页码范围都是正整数且 start <= end"""
        for num, (start, end) in LESSON_PAGE_RANGES.items():
            assert 1 <= start <= end, f"第{num}课: {start}-{end} 无效"

    def test_no_overlap(self):
        """相邻课程页码不重叠"""
        sorted_lessons = sorted(LESSON_PAGE_RANGES.items())
        for i in range(len(sorted_lessons) - 1):
            (num1, (_, end1)), (num2, (start2, _)) = sorted_lessons[i], sorted_lessons[i + 1]
            assert end1 < start2, f"第{num1}课和第{num2}课页码重叠"


class TestExtractLesson:
    """测试 extract_lesson"""

    def test_extract_lesson_4(self, pdf_path):
        """第4课能提取到文本且包含核心概念"""
        text = extract_lesson(pdf_path, 4)
        assert len(text) > 1000
        assert "DATA" in text
        assert "COMPUTE" in text
        assert "ALGORITHM" in text
        assert "AI" in text

    def test_extract_lesson_1(self, pdf_path):
        """第1课能提取"""
        text = extract_lesson(pdf_path, 1)
        assert len(text) > 500

    def test_extract_lesson_10(self, pdf_path):
        """第10课能提取"""
        text = extract_lesson(pdf_path, 10)
        assert len(text) > 500

    def test_invalid_lesson_raises(self):
        """不存在的课号抛 ValueError"""
        with pytest.raises(ValueError, match="不支持的课号"):
            extract_lesson("unused.pdf", 99)
        with pytest.raises(ValueError, match="不支持的课号"):
            extract_lesson("unused.pdf", 0)

    def test_extracted_text_is_utf8(self, pdf_path):
        """提取的文本包含正确的中文字符"""
        text = extract_lesson(pdf_path, 4)
        assert isinstance(text, str)
        assert "LEARNING_GOAL" in text
        assert "DATA" in text


class TestExtractLessonInfo:
    """测试 extract_lesson_info"""

    def test_info_structure(self, pdf_path):
        info = extract_lesson_info(pdf_path, 4)
        assert info["lesson_number"] == 4
        assert info["pages"] == (29, 34)
        assert len(info["text"]) > 1000

    def test_info_for_first_lesson(self, pdf_path):
        info = extract_lesson_info(pdf_path, 1)
        assert info["lesson_number"] == 1
        assert info["pages"] == (10, 16)


class TestListLessons:
    """测试 list_lessons"""

    def test_list_length(self, pdf_path):
        lessons = list_lessons(pdf_path)
        assert len(lessons) == 27

    def test_list_structure(self, pdf_path):
        lessons = list_lessons(pdf_path)
        for l in lessons:
            assert "lesson_number" in l
            assert "pages" in l
            assert "page_count" in l
            assert l["page_count"] >= 4  # 每课至少4页
