"""script/storyboard 拆分命令测试：讲稿回读、标题推测、从讲稿续跑 storyboard。"""

import json

import pytest

from textbook2video.pipeline import orchestrator
from textbook2video.pipeline.orchestrator import (
    _title_from_stem,
    build_storyboard_from_script,
    read_script_segments,
)


def test_read_script_segments_docx_format(tmp_path):
    p = tmp_path / "ch3_s0_script.txt"
    p.write_text("第1段：\n第一段讲稿内容。\n\n第2段：\n第二段讲稿内容。\n\n",
                 encoding="utf-8")
    assert read_script_segments(p) == ["第一段讲稿内容。", "第二段讲稿内容。"]


def test_read_script_segments_pdf_format(tmp_path):
    p = tmp_path / "lesson4_script.txt"
    p.write_text("Segment 1:\nHello world.\n\nSegment 2:\nSecond part.\n\n",
                 encoding="utf-8")
    assert read_script_segments(p) == ["Hello world.", "Second part."]


def test_read_script_segments_multiline_body(tmp_path):
    p = tmp_path / "x_script.txt"
    # 段体跨多行、含标点，但段间用段头分隔
    p.write_text("第1：\n第一行\n仍是第一段\n\n第2：\n第二段\n", encoding="utf-8")
    segs = read_script_segments(p)
    assert segs == ["第一行\n仍是第一段", "第二段"]


def test_read_script_segments_fallback_no_headers(tmp_path):
    p = tmp_path / "plain.txt"
    p.write_text("纯文本一段。\n\n纯文本二段。\n", encoding="utf-8")
    assert read_script_segments(p) == ["纯文本一段。", "纯文本二段。"]


@pytest.mark.parametrize("stem,expected", [
    ("ch3_s0", "第4章"),
    ("ch0_s2", "第1章"),
    ("lesson4", "Lesson 4"),
    ("weird_name", ""),
])
def test_title_from_stem(stem, expected):
    assert _title_from_stem(stem) == expected


def test_build_storyboard_from_script_wires_and_autodiscovers_images(
    tmp_path, monkeypatch
):
    script = tmp_path / "ch3_s0_script.txt"
    script.write_text("第1段：\n讲稿一。\n\n第2段：\n讲稿二。\n\n", encoding="utf-8")
    # 同级 images.json 应被自动发现
    images = [{"id": "fig1", "filename": "fig1.png", "description": "示意图"}]
    (tmp_path / "ch3_s0_images.json").write_text(
        json.dumps(images, ensure_ascii=False), encoding="utf-8"
    )

    captured = {}

    def fake_generate_storyboard(
        segments, *, lesson_title, model, available_images, lesson_plan=None, **kwargs
    ):
        captured["segments"] = segments
        captured["title"] = lesson_title
        captured["available_images"] = available_images
        return {"lesson_title": lesson_title,
                "segments": [{"id": 1, "narration": s} for s in segments],
                "metadata": {}}

    monkeypatch.setattr(
        "textbook2video.pipeline.storyboard.generate_storyboard",
        fake_generate_storyboard,
    )

    arts = build_storyboard_from_script(script)

    assert captured["segments"] == ["讲稿一。", "讲稿二。"]
    assert captured["title"] == "第4章"                 # 由 stem 推测
    assert captured["available_images"] == images       # 自动发现并透传
    assert arts.storyboard_path == tmp_path / "ch3_s0_storyboard.json"
    on_disk = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
    assert on_disk["metadata"]["available_images"] == images
    assert len(on_disk["segments"]) == 2


def test_build_storyboard_from_script_empty_raises(tmp_path):
    script = tmp_path / "empty_script.txt"
    script.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(ValueError):
        build_storyboard_from_script(script)
