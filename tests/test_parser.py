"""测试 PDF 教材解析模块"""

import pytest
from textbook2video.pipeline.parser import (
    extract_lesson,
    extract_lesson_info,
    list_lessons,
    LESSON_PAGE_RANGES,
)

PDF_PATH = "D:\\text python\\Textbook-to-Video-master\\Textbook-to-Video-master\\the_aim.pdf"


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

    def test_extract_lesson_4(self):
        """第4课能提取到文本且包含核心概念"""
        text = extract_lesson(PDF_PATH, 4)
        assert len(text) > 1000
        assert "数据" in text
        assert "算力" in text
        assert "算法" in text
        assert "人工智能" in text

    def test_extract_lesson_1(self):
        """第1课能提取"""
        text = extract_lesson(PDF_PATH, 1)
        assert len(text) > 500

    def test_extract_lesson_10(self):
        """第10课能提取"""
        text = extract_lesson(PDF_PATH, 10)
        assert len(text) > 500

    def test_invalid_lesson_raises(self):
        """不存在的课号抛 ValueError"""
        with pytest.raises(ValueError, match="不支持的课号"):
            extract_lesson(PDF_PATH, 99)
        with pytest.raises(ValueError, match="不支持的课号"):
            extract_lesson(PDF_PATH, 0)

    def test_extracted_text_is_utf8(self):
        """提取的文本包含正确的中文字符"""
        text = extract_lesson(PDF_PATH, 4)
        # PyMuPDF 返回的文本应该包含这些教材中出现的短语
        assert "学习目标" in text
        assert "数据" in text


class TestExtractLessonInfo:
    """测试 extract_lesson_info"""

    def test_info_structure(self):
        info = extract_lesson_info(PDF_PATH, 4)
        assert info["lesson_number"] == 4
        assert info["pages"] == (29, 34)
        assert len(info["text"]) > 1000

    def test_info_for_first_lesson(self):
        info = extract_lesson_info(PDF_PATH, 1)
        assert info["lesson_number"] == 1
        assert info["pages"] == (10, 16)


class TestListLessons:
    """测试 list_lessons"""

    def test_list_length(self):
        lessons = list_lessons(PDF_PATH)
        assert len(lessons) == 27

    def test_list_structure(self):
        lessons = list_lessons(PDF_PATH)
        for l in lessons:
            assert "lesson_number" in l
            assert "pages" in l
            assert "page_count" in l
            assert l["page_count"] >= 4  # 每课至少4页