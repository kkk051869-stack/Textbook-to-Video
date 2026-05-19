"""
PDF 教材解析模块：教材 PDF → 按课提取的文本

用法：
  from textbook2video.pipeline.parser import extract_lesson
  text = extract_lesson("the_aim.pdf", lesson_number=4)
"""

from pathlib import Path

import fitz  # PyMuPDF


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