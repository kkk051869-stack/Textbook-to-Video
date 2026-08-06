"""测试讲稿生成模块（仅测试解析逻辑，不调LLM）"""

from textbook2video.pipeline.scriptwriter import _parse_script


class TestParseScript:
    """测试 LLM 返回文本的解析逻辑"""

    def test_parse_with_segment_labels(self):
        """带"第N段："标签的格式"""
        raw = """第1段：（8-12秒）
好的同学们，今天我们来学习人工智能。

第2段：（12-15秒）
首先，我们来说说数据。
数据是人工智能的养料。

第3段：（8-10秒）
这就是今天的全部内容。"""
        result = _parse_script(raw)
        assert len(result) == 3
        assert "同学们" in result[0]
        assert "数据" in result[1]
        assert "全部内容" in result[2]

    def test_parse_plain_paragraphs(self):
        """无标签纯段落格式"""
        raw = """好的同学们，今天我们来学习人工智能。

首先，我们来说说数据。数据是人工智能的养料。

这就是今天的全部内容。"""
        result = _parse_script(raw)
        assert len(result) == 3

    def test_parse_filters_dash_separators(self):
        """过滤 --- 分隔符段落"""
        raw = """第1段：
同学们好！

---

第2段：
我们继续学习。"""
        result = _parse_script(raw)
        assert len(result) == 2
        assert "同学们" in result[0]
        assert "继续学习" in result[1]

    def test_parse_single_paragraph(self):
        """单段落"""
        raw = "同学们好，今天我们来学习人工智能的技术基础。"
        result = _parse_script(raw)
        assert len(result) == 1

    def test_parse_with_duration_in_parens(self):
        """带（x-y秒）时长标注"""
        raw = """第1段：（8-12秒）
开场白

第2段：（15-20秒）
正文内容"""
        result = _parse_script(raw)
        assert len(result) == 2
        assert result[0] == "开场白"
        assert result[1] == "正文内容"

    def test_parse_empty_input(self):
        """空输入"""
        assert _parse_script("") == []
        assert _parse_script("   ") == []
        assert _parse_script("\n\n\n") == []

    def test_parse_mixed_separators(self):
        """多种分隔符（---、***）"""
        raw = """第一段内容。

---

第二段内容。

***

第三段内容。"""
        result = _parse_script(raw)
        assert len(result) == 3

    def test_parse_strips_markdown_fences_and_content_labels(self):
        raw = """```text
第1段：（10-15秒）
讲稿内容：
第一段真实讲稿。

第2段：（15-20秒）
讲稿内容：
第二段真实讲稿。
```"""

        assert _parse_script(raw) == ["第一段真实讲稿。", "第二段真实讲稿。"]

    def test_parse_strips_empty_markers_and_english_headers(self):
        raw = """Segment 1:
（无内容）

Segment 2:
有效内容。"""

        assert _parse_script(raw) == ["有效内容。"]
