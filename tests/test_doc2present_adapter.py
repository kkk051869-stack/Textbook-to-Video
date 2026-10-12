import json
from pathlib import Path

import fitz

from textbook2video.research.doc2present_adapter import (
    extract_doc2present_pdf,
    stage_storyboard_with_image_inventory,
)


def test_extract_doc2present_pdf_writes_standard_raw_and_image_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    image = tmp_path / "figure.png"
    pixmap = fitz.Pixmap(fitz.csRGB, (0, 0, 40, 40), 0)
    pixmap.save(image)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "A diagram explains the codec pipeline.")
    page.insert_image(fitz.Rect(72, 100, 220, 248), filename=image)
    document.save(source)
    document.close()

    artifacts = extract_doc2present_pdf(
        source,
        output_dir=tmp_path / "prepared",
        page_start=1,
        page_end=1,
        case_id="codec",
        min_image_bytes=1,
    )

    assert "codec pipeline" in artifacts["raw_path"].read_text(encoding="utf-8")
    images = json.loads(artifacts["images_path"].read_text(encoding="utf-8"))
    assert len(images) == 1
    assert images[0]["source_locator"].startswith("pdf:page:1:")
    assert (artifacts["images_path"].parent / "images" / images[0]["filename"]).is_file()


def test_extract_doc2present_pdf_links_nearest_figure_caption(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    image = tmp_path / "figure.png"
    pixmap = fitz.Pixmap(fitz.csRGB, (0, 0, 40, 40), 0)
    pixmap.save(image)
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(72, 100, 220, 248), filename=image)
    page.insert_text(
        (72, 268),
        "Figure 1. Motion-compensated prediction from a reference frame.",
    )
    document.save(source)
    document.close()

    artifacts = extract_doc2present_pdf(
        source,
        output_dir=tmp_path / "prepared",
        page_start=1,
        page_end=1,
        case_id="codec",
        min_image_bytes=1,
    )

    image_record = json.loads(artifacts["images_path"].read_text(encoding="utf-8"))[0]
    assert image_record["figure_id"] == "Figure 1"
    assert image_record["caption"].startswith("Figure 1.")
    assert image_record["description"] == image_record["caption"]
    assert image_record["caption_status"] == "PDF_FIGURE_CAPTION_LINKED"
    assert image_record["caption_source_span"]["start"] < image_record["caption_source_span"]["end"]
    assert image_record["crop_policy"] == "FIGURE_COLUMN_VISUAL_ONLY_EXCLUDES_PDF_CAPTION"
    assert image_record["visual_bbox"][3] < image_record["caption_bbox"][1]
    assert image_record["visual_bbox"][0] <= image_record["caption_bbox"][0]
    assert image_record["visual_bbox"][2] >= image_record["caption_bbox"][2]

    # The display asset contains the diagram only.  The caption remains in
    # structured metadata and must not inflate the rendered image crop.
    crop = fitz.Pixmap(artifacts["images_path"].parent / "images" / image_record["filename"])
    assert crop.height < 700


def test_stage_storyboard_with_clean_image_inventory_isolates_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_storyboard = source_dir / "lesson_storyboard.json"
    original = {
        "segments": [{"id": "1", "narration": "Explain the figure.", "elements": [
            {"id": "figure", "type": "image", "src": "old.png", "source_image_id": "fig-1"},
        ]}],
    }
    source_storyboard.write_text(json.dumps(original), encoding="utf-8")
    raw = source_dir / "lesson_raw.txt"
    raw.write_text("source text", encoding="utf-8")
    script = source_dir / "lesson_script.txt"
    script.write_text("narration", encoding="utf-8")

    clean_dir = tmp_path / "clean"
    (clean_dir / "images").mkdir(parents=True)
    (clean_dir / "images" / "figure.png").write_bytes(b"clean-figure")
    inventory = [{
        "id": "fig-1", "filename": "figure.png", "figure_id": "Figure 1",
        "caption": "Figure 1: Clean source figure.",
    }]
    inventory_path = clean_dir / "lesson_images.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    staged = stage_storyboard_with_image_inventory(
        source_storyboard, inventory_path, output_dir=tmp_path / "staged",
        raw_path=raw, script_path=script,
    )

    assert json.loads(source_storyboard.read_text(encoding="utf-8")) == original
    staged_storyboard = json.loads(staged["storyboard_path"].read_text(encoding="utf-8"))
    image = staged_storyboard["segments"][0]["elements"][0]
    assert image["src"] == "figure.png"
    assert image["figure_id"] == "Figure 1"
    assert image["source_caption"] == "Figure 1: Clean source figure."
    assert (staged["image_dir"] / "figure.png").read_bytes() == b"clean-figure"
    assert staged["raw_path"].is_file()
    assert staged["script_path"].is_file()
