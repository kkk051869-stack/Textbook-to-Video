from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("with_source", [False, True])
def test_course_preview_declares_and_passes_actual_source_without_rewriting_narration(
    monkeypatch, tmp_path, with_source
):
    from textbook2video.pipeline import course_visuals

    script = Path(__file__).resolve().parents[1] / "scripts/preview_visual_agent.py"
    spec = importlib.util.spec_from_file_location("preview_visual_agent_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    board = tmp_path / "storyboard.json"
    board.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": 1,
                        "narration": "原始旁白",
                        "elements": [{"id": "h", "type": "heading", "text": "教学标题"}],
                    },
                    {"id": 2, "narration": "第二页旁白", "elements": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "textbook.md"
    source.write_text("教材原文，不是图像生成指令。", encoding="utf-8")
    output = tmp_path / "preview"
    argv = [
        str(script),
        "--storyboard",
        str(board),
        "--segments",
        "1,2",
        "--output-dir",
        str(output),
        "--course-plan",
        "--before-tts",
    ]
    if with_source:
        argv += ["--source", str(source)]
    observed = {}
    batches = []

    def generate(segments, **kwargs):
        batches.append([s["id"] for s in segments])
        assert segments[0]["narration"] == "原始旁白"
        observed.update(kwargs)
        return {}

    monkeypatch.setattr(course_visuals, "generate_course_visuals", generate)
    monkeypatch.setattr(module, "render_course_page", lambda *a, **kw: [])
    monkeypatch.setattr(sys, "argv", argv)
    assert module.main() == 0
    assert batches == [[1, 2]]
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert observed["source_text"] == (source.read_text(encoding="utf-8") if with_source else None)
    assert manifest["source_scope"] == ("provided-raw-text" if with_source else "narration-derived")
    assert manifest["source_text_sha256"] == (
        hashlib.sha256(source.read_bytes()).hexdigest() if with_source else None
    )
