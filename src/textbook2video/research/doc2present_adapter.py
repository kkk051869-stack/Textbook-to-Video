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
import shutil
from pathlib import Path
from typing import Any

import fitz


_FIGURE_CAPTION_RE = re.compile(
    r"\b(?P<label>fig(?:ure)?\.?\s*\d+(?:\s*\([a-z]\))?)\s*[:.]?\s*",
    flags=re.IGNORECASE,
)
_MAX_FIGURE_LABEL_OFFSET = 80


def _safe_stem(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower() or "doc2present"


def _clean_pdf_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _figure_captions(page: fitz.Page) -> list[dict[str, Any]]:
    """Return explicit Figure/Fig. text blocks with their page geometry.

    PDF embedded images have no dependable semantic name.  A nearby figure
    caption is the primary source-grounded description, so we keep it as a
    separate field rather than pretending a page prefix is a caption.
    """
    captions: list[dict[str, Any]] = []
    for block in page.get_text("blocks", sort=True):
        if len(block) < 5:
            continue
        text = _clean_pdf_text(str(block[4] or ""))
        match = _FIGURE_CAPTION_RE.search(text)
        # A plain-text paragraph may contain a cross-reference such as
        # ``Fig. 2``.  It is not a caption.  Real captions begin with the
        # label or, for multi-panel figures, place it very near the beginning
        # after short ``(a)/(b)`` panel labels.  This prevents body paragraphs
        # from expanding a display crop far beyond the actual Figure.
        if not match or match.start("label") > _MAX_FIGURE_LABEL_OFFSET:
            continue
        captions.append(
            {
                "figure_id": re.sub(r"\s+", " ", match.group("label")).strip(),
                "caption": text,
                "bbox": [round(float(value), 2) for value in block[:4]],
            }
        )
    return captions


def _nearest_caption(
    captions: list[dict[str, Any]], image_rects: list[fitz.Rect],
) -> dict[str, Any] | None:
    """Choose the closest caption, preferring one directly below an image."""
    if not captions or not image_rects:
        return None
    first_rect = image_rects[0]
    # PyMuPDF returns Rect in older versions and (Rect, Matrix) when
    # ``transform=True`` in newer ones.
    image_rect = first_rect[0] if isinstance(first_rect, tuple) else first_rect

    def score(item: dict[str, Any]) -> tuple[float, float, str]:
        left, top, right, bottom = item["bbox"]
        horizontal_gap = max(0.0, max(image_rect.x0 - right, left - image_rect.x1))
        vertical_gap = top - image_rect.y1
        # Captions conventionally sit below a figure.  A block above is still
        # possible, but pays a material penalty rather than being discarded.
        direction_penalty = 0.0 if vertical_gap >= -8 else 250.0
        distance = abs(vertical_gap) + horizontal_gap + direction_penalty
        return (distance, horizontal_gap, str(item["figure_id"]))

    return min(captions, key=score)


def _caption_span(page_text: str, caption: str, page_raw_offset: int) -> dict[str, int] | None:
    """Locate a caption in extracted page text for audit-friendly provenance."""
    normalized_caption = _clean_pdf_text(caption)
    if not normalized_caption:
        return None
    # The block string can differ in line wrapping from get_text("text").
    # Use its stable figure label as a conservative span anchor when needed.
    match = _FIGURE_CAPTION_RE.search(normalized_caption)
    needle = match.group("label") if match else normalized_caption
    index = page_text.lower().find(needle.lower())
    if index < 0:
        return None
    end = min(len(page_text), index + len(normalized_caption))
    return {"start": page_raw_offset + index, "end": page_raw_offset + end}


def _page_rect(value: Any) -> fitz.Rect:
    """Normalize PyMuPDF's Rect or (Rect, Matrix) image-location result."""
    return value[0] if isinstance(value, tuple) else value


def _figure_visual_clip(
    page: fitz.Page,
    image_rects: list[Any],
    caption_bbox: list[float],
    page_captions: list[dict[str, Any]],
) -> fitz.Rect:
    """Crop the visual Figure only, keeping its caption as metadata.

    The earlier implementation included the PDF caption in the image crop.
    That made the video look like a page screenshot and, when a following
    paragraph was close to the caption, also leaked unrelated paper text.
    Captions are already available as structured fields and rendered by the
    video template, so the pixels supplied to the video should contain only
    the diagram/photo itself.
    """
    rect: fitz.Rect | None = None
    for value in image_rects:
        component_rect = _page_rect(value)
        if rect is None:
            rect = fitz.Rect(component_rect)
        else:
            rect.include_rect(component_rect)
    if rect is None:
        raise ValueError("figure visual crop requires at least one image rectangle")

    caption_rect = fitz.Rect(caption_bbox)
    horizontal_margin = 10.0
    top_margin = 24.0
    # Never use the bottom margin to cross into the caption.  Keep only a
    # sub-point gap so labels that sit directly above a caption are retained.
    # If the PDF geometry overlaps, keep the component boundary rather than
    # swallowing the caption.
    caption_top = caption_rect.y0
    bottom_limit = caption_top - 0.5

    # Technical-paper diagrams are commonly assembled from small raster
    # samples plus vector boxes, arrows, and labels.  The caption width is the
    # only reliable page-level extent for those vector elements, so use it for
    # the horizontal figure extent while keeping caption pixels out vertically.
    rect.x0 = min(rect.x0, caption_rect.x0) - horizontal_margin
    rect.x1 = max(rect.x1, caption_rect.x1) + horizontal_margin
    component_top = rect.y0
    rect.y0 = max(page.rect.y0, rect.y0 - top_margin)
    # A single embedded xref can represent just one panel of a multi-panel
    # Figure.  The caption is the reliable lower boundary of the whole Figure,
    # so include the entire page region immediately above it.
    rect.y1 = min(page.rect.y1, max(rect.y1, bottom_limit))

    # A later figure in the same column must not drift up into the previous
    # Figure's caption.  This matters when its own raster component begins
    # below a vector heading or arrow.
    preceding_bottoms = []
    for candidate in page_captions:
        candidate_rect = fitz.Rect(candidate["bbox"])
        horizontal_overlap = min(candidate_rect.x1, rect.x1) - max(candidate_rect.x0, rect.x0)
        if candidate_rect.y1 <= caption_top and horizontal_overlap > 0:
            preceding_bottoms.append(candidate_rect.y1)
    if preceding_bottoms:
        rect.y0 = max(rect.y0, max(preceding_bottoms) + 2.0)

    # Avoid a preceding author line or paragraph when there is a genuine gap
    # before the first visual component.  Do not apply this to diagram labels
    # immediately above a component: those sit within 12pt and must remain.
    overlapping_text_bottoms = []
    for block in page.get_text("blocks", sort=True):
        if len(block) < 4:
            continue
        left, _top, right, bottom = [float(value) for value in block[:4]]
        overlap = min(right, rect.x1) - max(left, rect.x0)
        if bottom <= component_top and overlap > 0:
            overlapping_text_bottoms.append(bottom)
    if overlapping_text_bottoms:
        nearest_text_bottom = max(overlapping_text_bottoms)
        if component_top - nearest_text_bottom >= 12.0:
            rect.y0 = max(rect.y0, nearest_text_bottom + 2.0)
    rect.x0 = max(page.rect.x0, rect.x0)
    rect.x1 = min(page.rect.x1, rect.x1)
    return rect


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
        page_prefix = f"[PDF page {page_number}]\n"
        page_raw_offset = sum(len(value) + 2 for value in text_pages) + len(page_prefix)
        text_pages.append(f"{page_prefix}{text}")
        context = re.sub(r"\s+", " ", text)[:500]
        captions = _figure_captions(page)
        components: list[dict[str, Any]] = []
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
            try:
                image_rects = list(page.get_image_rects(xref, transform=True))
            except (RuntimeError, ValueError):
                image_rects = []
            caption_record = _nearest_caption(captions, image_rects)
            caption = str(caption_record["caption"]) if caption_record else ""
            figure_id = str(caption_record["figure_id"]) if caption_record else ""
            caption_span = _caption_span(text, caption, page_raw_offset) if caption else None
            first_rect = _page_rect(image_rects[0]) if image_rects else None
            image_bbox = (
                [round(float(value), 2) for value in first_rect]
                if first_rect is not None else None
            )
            components.append(
                {
                    "id": image_id,
                    "filename": filename,
                    "binary": binary,
                    "source_locator": f"pdf:page:{page_number}:xref:{xref}",
                    "sha256": hashlib.sha256(binary).hexdigest(),
                    "figure_id": figure_id or None,
                    "caption": caption or None,
                    "caption_bbox": caption_record.get("bbox") if caption_record else None,
                    "caption_source_span": caption_span,
                    "image_rects": image_rects,
                    "image_bbox": image_bbox,
                }
            )
            seen_xrefs.add(xref)

        # A paper Figure can be composed of several small raster xrefs plus
        # vector arrows and labels.  Reviewing one xref in isolation loses the
        # actual technical content.  Emit one rendered crop per captioned
        # figure, rather than leaking its photo-like components downstream.
        grouped: dict[str, list[dict[str, Any]]] = {}
        for component in components:
            if component["caption"] and component["caption_bbox"]:
                grouped.setdefault(str(component["figure_id"]), []).append(component)
        grouped_component_ids: set[str] = set()
        for figure_id, group in grouped.items():
            caption = str(group[0]["caption"])
            caption_bbox = group[0]["caption_bbox"]
            all_rects = [rect for component in group for rect in component["image_rects"]]
            if not all_rects:
                continue
            figure_match = re.search(r"\d+", figure_id)
            figure_number = figure_match.group(0) if figure_match else str(len(grouped))
            figure_asset_id = f"pdf-p{page_number:03d}-fig{int(figure_number):02d}"
            figure_filename = f"{stem}_{figure_asset_id}.png"
            visual_clip = _figure_visual_clip(page, all_rects, caption_bbox, captions)
            pixmap = page.get_pixmap(
                # Render vector-heavy Figures above the 1080p display target;
                # the renderer may now enlarge explanatory diagrams to fill
                # a substantial portion of the slide without pixelating the
                # source labels and arrows.
                matrix=fitz.Matrix(3, 3),
                clip=visual_clip,
                alpha=False,
            )
            pixmap.save(image_dir / figure_filename)
            images.append(
                {
                    "id": figure_asset_id,
                    "filename": figure_filename,
                    "description": caption,
                    "source_locator": f"pdf:page:{page_number}:figure:{figure_id}",
                    "page_number": page_number,
                    "figure_id": figure_id,
                    "caption": caption,
                    "caption_bbox": [round(float(value), 2) for value in caption_bbox],
                    "caption_source_span": group[0]["caption_source_span"],
                    "nearby_text": context,
                    "asset_kind": "RENDERED_FIGURE_CROP",
                    "crop_policy": "FIGURE_COLUMN_VISUAL_ONLY_EXCLUDES_PDF_CAPTION",
                    "visual_bbox": [round(float(value), 2) for value in visual_clip],
                    "source_component_ids": [component["id"] for component in group],
                    "caption_status": "PDF_FIGURE_CAPTION_LINKED",
                }
            )
            grouped_component_ids.update(component["id"] for component in group)

        # Keep uncaptioned embedded images as a fallback, but never emit a
        # captioned Figure's isolated components as ordinary teaching assets.
        for component in components:
            if component["id"] in grouped_component_ids:
                continue
            (image_dir / component["filename"]).write_bytes(component["binary"])
            images.append(
                {
                    "id": component["id"],
                    "filename": component["filename"],
                    "description": f"PDF page {page_number} contextual text: {context}",
                    "source_locator": component["source_locator"],
                    "page_number": page_number,
                    "sha256": component["sha256"],
                    "figure_id": None,
                    "caption": None,
                    "caption_source_span": None,
                    "nearby_text": context,
                    "image_bbox": component["image_bbox"],
                    "asset_kind": "UNCAPTIONED_EMBEDDED_IMAGE",
                    "caption_status": "NO_FIGURE_CAPTION_FOUND",
                }
            )
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
                "claim": (
                    "Embedded PDF image extraction with nearest Figure/Fig. caption "
                    "linking when an explicit caption is recoverable; visual relevance "
                    "still requires proposition-conditioned review."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"raw_path": raw_path, "images_path": images_path, "manifest_path": manifest_path}


def stage_storyboard_with_image_inventory(
    storyboard_path: str | Path,
    image_inventory_path: str | Path,
    *,
    output_dir: str | Path,
    raw_path: str | Path | None = None,
    script_path: str | Path | None = None,
    lesson_plan_path: str | Path | None = None,
) -> dict[str, Path]:
    """Create an isolated storyboard candidate using a verified image inventory.

    The original candidate remains untouched.  Every existing source-backed
    image element is rebound to the inventory's clean display crop while its
    Figure id and caption stay as explicit metadata.  This is intentionally a
    staging operation: it changes no narration, layout, timeline, or TTS
    input, so a Baseline/P0 pair can be re-rendered fairly.
    """
    source_storyboard = Path(storyboard_path)
    inventory_file = Path(image_inventory_path)
    destination_dir = Path(output_dir)
    if not source_storyboard.is_file():
        raise FileNotFoundError(source_storyboard)
    if not inventory_file.is_file():
        raise FileNotFoundError(inventory_file)
    if destination_dir.resolve() == source_storyboard.parent.resolve():
        raise ValueError("output_dir must differ from the source storyboard directory")

    storyboard = json.loads(source_storyboard.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))
    if not isinstance(inventory, list):
        raise ValueError("image inventory must be a JSON list")
    records = [item for item in inventory if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in records if item.get("id")}
    by_filename = {
        str(item.get("filename")): item
        for item in records
        if item.get("filename")
    }
    source_image_dir = inventory_file.parent / "images"
    destination_image_dir = destination_dir / "images"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_image_dir.mkdir(exist_ok=True)
    copied: set[str] = set()

    for segment in storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        for element in segment.get("elements", []) or []:
            if not isinstance(element, dict) or element.get("type") != "image":
                continue
            source_key = str(element.get("source_image_id") or element.get("src") or "")
            record = by_id.get(source_key) or by_filename.get(source_key)
            if record is None:
                # Non-source/generated image elements are intentionally left
                # alone.  The formal P0 path separately filters those assets.
                continue
            filename = str(record.get("filename") or "")
            source_image = source_image_dir / filename
            if not filename or not source_image.is_file():
                raise FileNotFoundError(
                    f"inventory image is unavailable for {source_key}: {source_image}"
                )
            element["src"] = filename
            element["source_image_id"] = record["id"]
            if record.get("figure_id"):
                element["figure_id"] = record["figure_id"]
            if record.get("caption"):
                element["source_caption"] = record["caption"]
            if filename not in copied:
                shutil.copy2(source_image, destination_image_dir / filename)
                copied.add(filename)

    storyboard.setdefault("metadata", {})["available_images"] = records
    storyboard["metadata"]["image_inventory_path"] = str(inventory_file)
    storyboard["metadata"]["image_staging"] = {
        "status": "CLEAN_SOURCE_FIGURES_STAGED",
        "copied_image_count": len(copied),
        "crop_policy": "display crops are visual-only; captions remain structured metadata",
    }
    staged_storyboard = destination_dir / source_storyboard.name
    staged_storyboard.write_text(
        json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    staged_inventory = destination_dir / inventory_file.name
    staged_inventory.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    copied_artifacts = {
        "storyboard_path": staged_storyboard,
        "images_path": staged_inventory,
        "image_dir": destination_image_dir,
    }
    for label, supplied in (
        ("raw_path", raw_path),
        ("script_path", script_path),
        ("lesson_plan_path", lesson_plan_path),
    ):
        if supplied is None:
            continue
        source_artifact = Path(supplied)
        if not source_artifact.is_file():
            raise FileNotFoundError(source_artifact)
        target = destination_dir / source_artifact.name
        shutil.copy2(source_artifact, target)
        copied_artifacts[label] = target
    return copied_artifacts


__all__ = ["extract_doc2present_pdf", "stage_storyboard_with_image_inventory"]
