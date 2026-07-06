"""produce 端到端编排接线测试（不依赖 LLM/浏览器/网络，全部 mock 重步骤）。"""

import json
import math
import sys
import types
from pathlib import Path

import pytest

from textbook2video.pipeline import orchestrator
from textbook2video.pipeline.orchestrator import Artifacts, produce


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """把 produce 依赖的重步骤替换为轻量桩，返回记录调用参数的字典。"""
    calls = {}

    audio_dir = tmp_path / "ch3_s0_audio"
    audio_dir.mkdir()
    sb_path = tmp_path / "ch3_s0_storyboard.json"
    sb_path.write_text("{}", encoding="utf-8")

    fake_arts = Artifacts(
        stem="ch3_s0", title="第4章", raw_path=tmp_path / "r.txt",
        script_path=tmp_path / "s.txt", storyboard_path=sb_path,
        output_dir=tmp_path, audio_dir=audio_dir, durations=[3.0, 4.5, 2.5],
    )

    def fake_build_docx(*a, **k):
        calls["build"] = k
        return fake_arts

    def fake_animate(sb, **k):
        calls["animate"] = (sb, k)
        html = tmp_path / "anim.html"
        html.write_text("<html></html>", encoding="utf-8")
        return html

    def fake_record(html, out, **k):
        calls["record"] = (html, out, k)
        Path(out).write_bytes(b"VIDEO")   # 造出无声中间视频

    def fake_compose(video, adir, out, **k):
        calls["compose"] = (video, adir, out, k)
        Path(out).write_bytes(b"FINAL")

    def fake_srt(storyboard, out, **k):
        calls["srt"] = (storyboard, out, k)
        Path(out).write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
        return Path(out)

    def fake_quality(storyboard, out, **k):
        calls["quality"] = (storyboard, out, k)
        Path(out).write_text("{}", encoding="utf-8")
        return Path(out)

    monkeypatch.setattr(orchestrator, "build_storyboard_docx", fake_build_docx)
    monkeypatch.setitem(
        sys.modules,
        "textbook2video.animation_gen",
        types.SimpleNamespace(generate=fake_animate),
    )
    monkeypatch.setitem(
        sys.modules,
        "textbook2video.pipeline.recorder",
        types.SimpleNamespace(record_html_to_video=fake_record),
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.compose.compose_video", fake_compose
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.subtitles.generate_srt", fake_srt
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.quality.write_quality_report", fake_quality
    )
    return calls, fake_arts, tmp_path


def test_produce_wires_full_chain(wired):
    calls, arts, tmp_path = wired
    final = produce(
        "book.docx", chapter=3, section=0, output_dir=tmp_path,
        theme="dark-blue-academic", model="ecnu-plus",
    )
    # 最终成片路径 = <stem>.mp4
    assert final == tmp_path / "ch3_s0.mp4"
    assert final.read_bytes() == b"FINAL"

    # 录制时长 = ceil(总时长) + 1 余量
    total = sum(arts.durations)            # 10.0
    _, _, rec_kw = calls["record"]
    assert rec_kw["duration"] == math.ceil(total) + 1

    # compose 收到 (无声视频, 音频目录, 成片)
    video, adir, out, compose_kw = calls["compose"]
    assert Path(adir) == arts.audio_dir
    assert Path(out) == final
    assert Path(compose_kw["subtitle_path"]) == tmp_path / "ch3_s0.srt"

    # animate 收到 storyboard 路径 + 主题透传
    sb, anim_kw = calls["animate"]
    assert Path(sb) == arts.storyboard_path
    assert anim_kw["theme_id"] == "dark-blue-academic"
    assert Path(calls["quality"][1]) == tmp_path / "ch3_s0_quality.json"


def test_produce_removes_silent_intermediate_by_default(wired):
    calls, arts, tmp_path = wired
    produce("book.docx", chapter=3, section=0, output_dir=tmp_path)
    assert not (tmp_path / "ch3_s0_silent.mp4").exists()


def test_produce_keeps_intermediate_when_requested(wired):
    calls, arts, tmp_path = wired
    produce("book.docx", chapter=3, section=0, output_dir=tmp_path,
            keep_intermediate=True)
    assert (tmp_path / "ch3_s0_silent.mp4").exists()


def test_produce_requires_lesson_or_chapter(tmp_path):
    with pytest.raises(ValueError):
        produce("book.pdf", output_dir=tmp_path)


def test_produce_from_storyboard_skips_content_generation(wired, monkeypatch):
    calls, arts, tmp_path = wired

    def fake_from_storyboard(*a, **k):
        calls["from_storyboard"] = (a, k)
        return arts

    monkeypatch.setattr(orchestrator, "_artifacts_from_storyboard", fake_from_storyboard)

    final = produce(
        "book.docx",
        output_dir=tmp_path,
        from_storyboard=tmp_path / "ch3_s0_storyboard.json",
    )

    assert final == tmp_path / "ch3_s0.mp4"
    assert "from_storyboard" in calls
    assert "build" not in calls


def test_produce_require_review_rejects_unapproved_storyboard(wired):
    calls, arts, tmp_path = wired
    arts.storyboard_path.write_text(
        json.dumps({"segments": [], "metadata": {}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="human-approved"):
        produce(
            "book.docx",
            chapter=3,
            section=0,
            output_dir=tmp_path,
            require_review=True,
        )

    assert "animate" not in calls


def test_produce_require_review_allows_approved_storyboard(wired):
    calls, arts, tmp_path = wired
    arts.storyboard_path.write_text(
        json.dumps({
            "segments": [],
            "metadata": {"human_review": {"status": "approved"}},
        }),
        encoding="utf-8",
    )

    final = produce(
        "book.docx",
        chapter=3,
        section=0,
        output_dir=tmp_path,
        require_review=True,
    )

    assert final == tmp_path / "ch3_s0.mp4"
    assert "animate" in calls


def test_produce_from_html_requires_storyboard(tmp_path):
    with pytest.raises(ValueError):
        produce("book.docx", output_dir=tmp_path, from_html=tmp_path / "x.html")
