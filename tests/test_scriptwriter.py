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

    def test_parse_markdown_bold_segment_headers_and_leading_title(self):
        raw = """# 《数字素养》课堂讲稿：多尺度自回归先验

**第1段（约15秒）**

第一段正文。

**第2段（约25秒）**

第二段正文。"""

        assert _parse_script(raw) == ["第一段正文。", "第二段正文。"]


def test_generate_script_saves_raw_response_and_parse_boundaries(tmp_path, monkeypatch):
    import json

    from textbook2video.llm import client
    from textbook2video.pipeline.scriptwriter import generate_script

    raw = "第1段：\n第一段内容。\n\n第2段：\n第二段内容。"
    monkeypatch.setattr(client, "chat_with_system", lambda **_kwargs: raw)
    raw_path = tmp_path / "lesson_script_model_response.txt"

    assert generate_script("教材", raw_response_path=raw_path) == ["第一段内容。", "第二段内容。"]
    assert raw_path.read_text(encoding="utf-8") == raw
    report = json.loads(raw_path.with_suffix(".parse.json").read_text(encoding="utf-8"))
    assert report["status"] == "PARSED"
    assert report["parsed_segment_count"] == 2
    assert [row["boundary_status"] for row in report["segments"]] == ["LOCATED", "LOCATED"]
    assert report["segments"][0]["response_start_line"] == 2
    assert report["segments"][1]["response_start_line"] == 5


def test_generate_script_accepts_more_than_twelve_valid_segments(tmp_path, monkeypatch):
    import json

    from textbook2video.llm import client
    from textbook2video.pipeline.scriptwriter import generate_script

    raw = "# 讲稿标题\n\n" + "\n\n".join(
        f"**第{i}段（约10秒）**\n\n第{i}段讲稿内容。" for i in range(1, 20)
    )
    monkeypatch.setattr(client, "chat_with_system", lambda **_kwargs: raw)
    raw_path = tmp_path / "lesson_script_model_response.txt"

    segments = generate_script("教材", raw_response_path=raw_path)

    assert raw_path.read_text(encoding="utf-8") == raw
    report = json.loads(raw_path.with_suffix(".parse.json").read_text(encoding="utf-8"))
    assert len(segments) == 19
    assert segments[0] == "第1段讲稿内容。"
    assert segments[-1] == "第19段讲稿内容。"
    assert report["status"] == "PARSED"
    assert report["parsed_segment_count"] == 19
    assert len(report["segments"]) == 19
    assert report["failure"] is None


def test_generate_script_still_rejects_empty_output_and_records_reason(tmp_path, monkeypatch):
    import json

    import pytest

    from textbook2video.llm import client
    from textbook2video.pipeline.scriptwriter import generate_script

    monkeypatch.setattr(client, "chat_with_system", lambda **_kwargs: "   ")
    raw_path = tmp_path / "lesson_script_model_response.txt"

    with pytest.raises(ValueError, match="讲稿模型未返回可用内容"):
        generate_script("教材", raw_response_path=raw_path)

    report = json.loads(raw_path.with_suffix(".parse.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAILED"
    assert report["parsed_segment_count"] == 0
    assert report["failure"]["message"] == "讲稿模型未返回可用内容"


def test_generate_script_does_not_overwrite_existing_diagnostics(tmp_path, monkeypatch):
    import pytest

    from textbook2video.llm import client
    from textbook2video.pipeline.scriptwriter import generate_script

    raw_path = tmp_path / "lesson_script_model_response.txt"
    raw_path.write_text("existing evidence", encoding="utf-8")
    called = False

    def unexpected_call(**_kwargs):
        nonlocal called
        called = True
        return "should not run"

    monkeypatch.setattr(client, "chat_with_system", unexpected_call)
    with pytest.raises(FileExistsError):
        generate_script("教材", raw_response_path=raw_path)
    assert called is False


def test_pdf_storyboard_generation_wires_script_diagnostics(tmp_path, monkeypatch):
    from textbook2video.pipeline import lesson_plan, parser, scriptwriter, storyboard
    from textbook2video.pipeline.orchestrator import build_storyboard_pdf

    captured = {}
    monkeypatch.setattr(parser, "extract_pdf_pages_info", lambda *_args: {
        "text": "教材正文", "pages": (1, 1), "title": "Flows", "images": [],
    })
    monkeypatch.setattr(lesson_plan, "generate_lesson_plan", lambda *_args, **_kwargs: {
        "knowledge_points": [],
    })

    def fake_script(*_args, **kwargs):
        captured["raw_response_path"] = kwargs.get("raw_response_path")
        return ["讲稿"]

    monkeypatch.setattr(scriptwriter, "generate_script", fake_script)
    monkeypatch.setattr(storyboard, "generate_storyboard", lambda *_args, **_kwargs: {
        "lesson_title": "Flows", "segments": [{"id": "1", "narration": "讲稿", "elements": []}],
        "metadata": {},
    })
    monkeypatch.setattr(
        "textbook2video.pipeline.orchestrator._dual_write_research_generation_v2",
        lambda **_kwargs: None,
    )

    build_storyboard_pdf(
        "flows.pdf", page_range=(1, 1), output_dir=tmp_path, skip_tts=True,
    )

    assert captured["raw_response_path"] == tmp_path / "pdfpages1-1_script_model_response.txt"
