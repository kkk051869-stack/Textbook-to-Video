import json
from pathlib import Path

import fitz

from textbook2video.research.doc2present_adapter import extract_doc2present_pdf


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
