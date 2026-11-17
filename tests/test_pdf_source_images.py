"""Offline production wiring: real PDF extraction, mocked content models."""
import hashlib
import json
from pathlib import Path

import fitz
import pytest

from textbook2video.pipeline import orchestrator, parser


def make_pdf(path):
    doc = fitz.open()
    for number in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Source page {number + 1}")
        # Engineering fixture, intentionally uncaptioned, no teaching claim.
        import random
        samples = random.Random(42).randbytes(160 * 160 * 3)
        pix = fitz.Pixmap(fitz.csRGB, 160, 160, samples, False)
        page.insert_image(fitz.Rect(72, 100, 300, 328), pixmap=pix)
    doc.save(path)
    doc.close()


@pytest.mark.parametrize("use_lesson", [False, True])
def test_pdf_images_reach_legacy_storyboard_and_source_evidence(tmp_path, monkeypatch, use_lesson):
    from textbook2video.pipeline import lesson_plan, scriptwriter, storyboard
    from textbook2video.research.source_evidence import build_source_evidence

    pdf = tmp_path / "input.pdf"
    make_pdf(pdf)
    captured = {}
    def plan(text, **kwargs):
        captured["plan"] = kwargs["available_images"]
        return {"knowledge_points": []}
    def board(segments, **kwargs):
        captured["board"] = kwargs["available_images"]
        image = kwargs["available_images"][0]
        return {"segments": [{"id": "1", "narration": segments[0], "elements": [
            {"id": "e1", "type": "image", "src": image["filename"], "source_image_id": image["id"]}
        ]}]}
    monkeypatch.setattr(lesson_plan, "generate_lesson_plan", plan)
    monkeypatch.setattr(scriptwriter, "generate_script", lambda *a, **k: ["Original narration"])
    monkeypatch.setattr(storyboard, "generate_storyboard", board)
    monkeypatch.setattr(orchestrator, "_dual_write_research_generation_v2", lambda **k: None)
    out = tmp_path / "out"
    monkeypatch.setitem(parser.LESSON_PAGE_RANGES, 99, (1, 1))
    route = {"lesson": 99} if use_lesson else {"page_range": (1, 1)}
    arts = orchestrator.build_storyboard_pdf(str(pdf), **route, output_dir=out, skip_tts=True)
    saved = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
    images = saved["metadata"]["available_images"]
    assert images and images == captured["plan"] == captured["board"]
    assert {i["page_number"] for i in images} == {1}
    assert arts.raw_path.read_text(encoding="utf-8") == parser.extract_pdf_pages_info(str(pdf), 1, 1)["text"]
    for item in images:
        assert hashlib.sha256((out / "images" / item["filename"]).read_bytes()).hexdigest() == item["sha256"]
    evidence_path = build_source_evidence(arts.raw_path, images, output_path=out / "evidence.json")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["source_images"]
    assert all(i["availability"] == "AVAILABLE_LOCAL" for i in evidence["source_images"])
    from textbook2video.animation_gen import load_textbook_images
    loaded = load_textbook_images(saved["segments"], out / "images", images, review_policy="development")
    assert Path(loaded["1:e1"]).is_file()
    assert not saved["segments"][0]["elements"][0].get("_render_blocked")



def test_pdf_inventory_preserves_colliding_existing_asset(tmp_path):
    pdf = tmp_path / "input.pdf"
    make_pdf(pdf)
    out = tmp_path / "out"
    out.mkdir()
    raw = parser.extract_pdf_pages_info(str(pdf), 1, 1)["text"]
    first = parser.extract_pdf_image_inventory(str(pdf), 1, 1, output_dir=out, raw_text=raw)
    original = out / "images" / first[0]["filename"]
    original.write_bytes(b"unrelated asset")
    second = parser.extract_pdf_image_inventory(str(pdf), 1, 1, output_dir=out, raw_text=raw)
    assert original.read_bytes() == b"unrelated asset"
    assert second[0]["filename"] != first[0]["filename"]
    assert second[0]["id"] == first[0]["id"]


def test_pdf_inventory_empty_is_valid(tmp_path):
    pdf = tmp_path / "text.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Text only")
    doc.save(pdf)
    doc.close()
    assert parser.extract_pdf_image_inventory(str(pdf), 1, 1, output_dir=tmp_path / "out", raw_text="Text only") == []
