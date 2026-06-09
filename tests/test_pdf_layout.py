import base64
import json
from pathlib import Path

import fitz

from textbook2video.pipeline.pdf_layout import (
    PdfProfile,
    build_pdf_structure,
    inspect_pdf_layout,
    write_pdf_extract_bundle,
    write_pdf_structure,
    write_pdf_layout_report,
)


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _make_layout_pdf(path):
    doc = fitz.open()
    for page_no in range(1, 3):
        page = doc.new_page(width=400, height=600)
        page.insert_text((40, 25), "TEXTBOOK HEADER", fontsize=8)
        page.insert_text((40, 80), "Chapter 1 AI Basics", fontsize=20)
        page.insert_text((40, 125), "1.1 Data and Algorithms", fontsize=16)
        page.insert_text((40, 170), "Body text uses the dominant font size.", fontsize=11)
        page.insert_text((40, 192), "Another body line uses the same font size.", fontsize=11)
        page.insert_image(fitz.Rect(45, 230, 145, 310), stream=ONE_PIXEL_PNG)
        page.insert_text((45, 335), "Figure 1 Data pipeline", fontsize=9)
        page.insert_text((190, 575), str(page_no), fontsize=8)
    doc.save(path)
    doc.close()


def test_inspect_pdf_layout_classifies_common_blocks(tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_layout_pdf(pdf)

    report = inspect_pdf_layout(pdf)

    assert report["page_count"] == 2
    assert report["stats"]["body_font_size"] == 11.0
    page = report["pages"][0]
    roles = {block["text"]: block["role"] for block in page["text_blocks"]}
    assert roles["TEXTBOOK HEADER"] == "repeated_edge"
    assert roles["Chapter 1 AI Basics"] == "heading"
    assert roles["1.1 Data and Algorithms"] == "heading"
    assert roles["Figure 1 Data pipeline"] == "caption"
    assert page["image_blocks"]


def test_write_pdf_layout_report_with_profile(tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_layout_pdf(pdf)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps({"heading_patterns": ["^Custom Heading"], "caption_patterns": ["^Figure"]}),
        encoding="utf-8",
    )

    out = write_pdf_layout_report(
        pdf,
        tmp_path / "report.json",
        profile=PdfProfile.from_file(profile_path),
        max_pages=1,
    )

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["inspected_pages"] == 1
    assert data["profile"]["heading_patterns"] == ["^Custom Heading"]
    assert data["pages"][0]["caption_candidates"]


def test_build_pdf_structure_creates_sections_and_image_blocks(tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_layout_pdf(pdf)

    ir = build_pdf_structure(pdf)

    assert ir["kind"] == "textbook_pdf_ir"
    assert ir["llm_repair"]["recommended"] is True
    assert ir["sections"]
    first = ir["sections"][0]
    assert first["title"] == "Chapter 1 AI Basics"
    assert first["level"] == 1
    all_blocks = [
        block
        for section in ir["sections"]
        for block in section["content_blocks"]
    ]
    assert any(block["type"] == "paragraph" for block in all_blocks)
    image_blocks = [block for block in all_blocks if block["type"] == "image"]
    assert image_blocks
    assert image_blocks[0]["caption"] == "Figure 1 Data pipeline"


def test_write_pdf_structure(tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_layout_pdf(pdf)

    out = write_pdf_structure(pdf, tmp_path / "structure.json", max_pages=1)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["inspected_pages"] == 1
    assert data["sections"][0]["title"] == "Chapter 1 AI Basics"


def test_pdf_structure_can_start_from_later_page(tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_layout_pdf(pdf)

    ir = build_pdf_structure(pdf, start_page=2, max_pages=1)

    assert ir["start_page"] == 2
    assert ir["inspected_pages"] == 1
    assert all(section["page_start"] == 2 for section in ir["sections"])


def test_write_pdf_extract_bundle_exports_text_and_images(tmp_path):
    pdf = tmp_path / "book.pdf"
    _make_layout_pdf(pdf)

    outputs = write_pdf_extract_bundle(
        pdf,
        tmp_path / "bundle",
        start_page=1,
        max_pages=1,
        stem="sample",
    )

    raw_text = outputs["raw_path"].read_text(encoding="utf-8")
    images = json.loads(outputs["images_path"].read_text(encoding="utf-8"))
    structure = json.loads(outputs["structure_path"].read_text(encoding="utf-8"))
    image_blocks = [
        block
        for section in structure["sections"]
        for block in section["content_blocks"]
        if block["type"] == "image"
    ]

    assert "Chapter 1 AI Basics" in raw_text
    assert "Body text uses the dominant font size." in raw_text
    assert images
    assert image_blocks[0]["src"]
    assert (tmp_path / "bundle" / "images").is_dir()
    image_path = tmp_path / "bundle" / Path(images[0]["src"])
    assert image_path.exists()
