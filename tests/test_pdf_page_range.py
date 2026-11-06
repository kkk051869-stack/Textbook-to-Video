from __future__ import annotations

import sys

import pytest

fitz = pytest.importorskip("fitz")

from textbook2video.cli import _parse_pdf_page_range
from textbook2video.pipeline.parser import extract_pdf_pages_info


def test_explicit_pdf_page_range_extracts_inclusive_pages(tmp_path):
    pdf_path = tmp_path / "new-source.pdf"
    document = fitz.open()
    for text in ("first page", "selected page two", "selected page three", "last page"):
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.set_metadata({"title": "New Source"})
    document.save(pdf_path)
    document.close()

    result = extract_pdf_pages_info(pdf_path, 2, 3)

    assert result["pages"] == (2, 3)
    assert "selected page two" in result["text"]
    assert "selected page three" in result["text"]
    assert "first page" not in result["text"]
    assert "last page" not in result["text"]
    assert result["title"] == "New Source"


@pytest.mark.parametrize("start,end", [(0, 1), (3, 2), (1, 5)])
def test_explicit_pdf_page_range_rejects_invalid_bounds(tmp_path, start, end):
    pdf_path = tmp_path / "two-pages.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(pdf_path)
    document.close()

    with pytest.raises(ValueError):
        extract_pdf_pages_info(pdf_path, start, end)


def test_cli_parses_pdf_page_range():
    assert _parse_pdf_page_range("3-6") == (3, 6)
    with pytest.raises(Exception):
        _parse_pdf_page_range("6-3")


def test_produce_cli_routes_explicit_pdf_pages(tmp_path, monkeypatch):
    from textbook2video import cli
    from textbook2video.pipeline import orchestrator

    captured = {}

    def fake_produce(input_path, **kwargs):
        captured.update(kwargs)
        return tmp_path / "video.mp4"

    monkeypatch.setattr(orchestrator, "produce", fake_produce)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "t2v", "produce", str(tmp_path / "new-source.pdf"),
            "--pdf-pages", "2-4", "--auto-visual-enhancement",
        ],
    )

    cli.main()

    assert captured["pdf_page_range"] == (2, 4)
    assert captured["auto_visual_enhancement"] is True
