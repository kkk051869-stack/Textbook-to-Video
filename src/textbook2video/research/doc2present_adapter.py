"""Prepare a Doc2Present PDF as standard Textbook-to-Video source artifacts.

This adapter is deliberately research-only.  It avoids the production PDF
lesson map, which is specific to the original school textbook, while emitting
the normal ``*_raw.txt`` and ``*_images.json`` inputs consumed by the mature
script → storyboard → animation pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import fitz


def _safe_stem(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower() or "doc2present"


def extract_doc2present_pdf(
    pdf_path: str | Path,
    *,
    output_dir: str | Path,
    page_start: int,
    page_end: int,
    case_id: str | None = None,
    min_image_bytes: int = 5_000,
) -> dict[str, Path]:
    """Extract one inclusive PDF page range to regular raw/image artifacts.

    Image descriptions intentionally contain only page-local textual context.
    They are provenance hints, *not* visual captions.  A later VLM captioning
    step may add captions without replacing the original locator or filename.
    """
    source = Path(pdf_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if page_start < 1 or page_end < page_start:
        raise ValueError("page range must be 1-based and inclusive")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(case_id or source.stem)
    image_dir = out / "images"
    image_dir.mkdir(exist_ok=True)

    document = fitz.open(source)
    if page_end > document.page_count:
        raise ValueError(f"page_end {page_end} exceeds PDF page count {document.page_count}")

    text_pages: list[str] = []
    images: list[dict[str, Any]] = []
    seen_xrefs: set[int] = set()
    for page_number in range(page_start, page_end + 1):
        page = document[page_number - 1]
        text = page.get_text("text").strip()
        text_pages.append(f"[PDF page {page_number}]\n{text}")
        context = re.sub(r"\s+", " ", text)[:500]
        for image_index, image in enumerate(page.get_images(full=True), start=1):
            xref = int(image[0])
            if xref in seen_xrefs:
                continue
            payload = document.extract_image(xref)
            binary = payload.get("image", b"")
            if len(binary) < min_image_bytes:
                continue
            ext = str(payload.get("ext") or "png").lower()
            if ext not in {"png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp"}:
                ext = "png"
            image_id = f"pdf-p{page_number:03d}-img{image_index:02d}"
            filename = f"{stem}_{image_id}.{ext}"
            (image_dir / filename).write_bytes(binary)
            images.append(
                {
                    "id": image_id,
                    "filename": filename,
                    "description": f"PDF page {page_number} contextual text: {context}",
                    "source_locator": f"pdf:page:{page_number}:xref:{xref}",
                    "page_number": page_number,
                    "sha256": hashlib.sha256(binary).hexdigest(),
                    "caption_status": "PAGE_TEXT_CONTEXT_NOT_VISUAL_CAPTION",
                }
            )
            seen_xrefs.add(xref)
    document.close()

    raw_path = out / f"{stem}_raw.txt"
    images_path = out / f"{stem}_images.json"
    manifest_path = out / f"{stem}_source_manifest.json"
    raw_path.write_text("\n\n".join(text_pages) + "\n", encoding="utf-8")
    images_path.write_text(
        json.dumps(images, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps(
            {
                "source_pdf": str(source),
                "page_range": {"start": page_start, "end": page_end},
                "raw_path": str(raw_path),
                "images_path": str(images_path),
                "image_count": len(images),
                "claim": "Embedded PDF image extraction; no visual captioning has been performed.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"raw_path": raw_path, "images_path": images_path, "manifest_path": manifest_path}


__all__ = ["extract_doc2present_pdf"]
