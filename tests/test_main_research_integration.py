"""Compatibility boundaries between the main pipeline and recent research."""

import inspect
import sys

from textbook2video import cli
from textbook2video.pipeline import orchestrator


def test_plain_cli_produce_keeps_non_joint_default(tmp_path, monkeypatch):
    assert inspect.signature(orchestrator.produce).parameters["joint_planning"].default is False
    calls = []
    monkeypatch.setattr(
        orchestrator, "produce", lambda *a, **kw: calls.append(kw) or tmp_path / "out.mp4"
    )
    monkeypatch.setattr(
        sys, "argv", ["t2v", "produce", "book.docx", "--chapter", "3", "--section", "0"]
    )
    cli.main()
    assert calls[0]["joint_planning"] is False
    assert calls[0]["p0_research"] is False
    assert calls[0]["auto_visual_enhancement"] is False
