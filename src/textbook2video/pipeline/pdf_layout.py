"""Generic PDF layout inspection for textbook parsing.

This module is intentionally source-agnostic. It extracts low-level page layout
signals from text-based PDFs so a later step can rebuild textbook structure with
a small profile and optional LLM repair, instead of hard-coding page ranges for
each book.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

import fitz


DEFAULT_HEADING_PATTERNS = [
    r"^第[一二三四五六七八九十百\d]+[章节课]",
    r"^[一二三四五六七八九十]+[、.]",
    r"^\d+(\.\d+)*[、. ]",
    r"^专题[一二三四五六七八九十\d]+",
    r"^任务[一二三四五六七八九十\d]+",
]

DEFAULT_CAPTION_PATTERNS = [
    r"^图\s*[一二三四五六七八九十\d]+([-.]\d+)?",
    r"^表\s*[一二三四五六七八九十\d]+([-.]\d+)?",
    r"^Figure\s+\d+",
    r"^Table\s+\d+",
]

DEFAULT_IGNORE_PATTERNS = [
    r"^\d+$",
    r"^第\s*\d+\s*页$",
]


@dataclass(slots=True)
class PdfProfile:
    """Small configuration layer for textbook-specific layout hints."""

    heading_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_HEADING_PATTERNS))
    caption_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_CAPTION_PATTERNS))
    ignore_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))
    header_footer_margin_ratio: float = 0.08
    min_image_width: float = 24.0
    min_image_height: float = 24.0

    @classmethod
    def from_file(cls, path: str | Path) -> "PdfProfile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            heading_patterns=list(data.get("heading_patterns", DEFAULT_HEADING_PATTERNS)),
            caption_patterns=list(data.get("caption_patterns", DEFAULT_CAPTION_PATTERNS)),
            ignore_patterns=list(data.get("ignore_patterns", DEFAULT_IGNORE_PATTERNS)),
            header_footer_margin_ratio=float(data.get("header_footer_margin_ratio", 0.08)),
            min_image_width=float(data.get("min_image_width", 24.0)),
            min_image_height=float(data.get("min_image_height", 24.0)),
        )


def inspect_pdf_layout(
    pdf_path: str | Path,
    *,
    profile: PdfProfile | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Inspect a text-based PDF and return page-level layout signals.

    The result is deliberately a JSON-friendly dict. Downstream code can use it
    for automatic profile calibration, section reconstruction, image-caption
    association, and LLM structure repair.
    """

    profile = profile or PdfProfile()
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    try:
        pages = []
        all_font_sizes: list[float] = []
        repeated_edge_text: Counter[str] = Counter()

        page_count = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for page_index in range(page_count):
            page = doc[page_index]
            text_blocks, font_sizes = _extract_text_blocks(page, profile)
            all_font_sizes.extend(font_sizes)
            repeated_edge_text.update(
                block["text"] for block in text_blocks if block["zone"] in {"header", "footer"}
            )
            pages.append(
                {
                    "page_no": page_index + 1,
                    "width": round(page.rect.width, 2),
                    "height": round(page.rect.height, 2),
                    "text_blocks": text_blocks,
                    "image_blocks": _extract_image_blocks(page, profile),
                }
            )

        body_font_size = _infer_body_font_size(all_font_sizes)
        repeated = {text for text, count in repeated_edge_text.items() if count >= 2}
        for page in pages:
            for block in page["text_blocks"]:
                block["is_repeated_edge_text"] = block["text"] in repeated
                block["role"] = _classify_text_block(block, body_font_size, profile)
            page["heading_candidates"] = [
                b for b in page["text_blocks"] if b["role"] == "heading"
            ]
            page["caption_candidates"] = [
                b for b in page["text_blocks"] if b["role"] == "caption"
            ]

        return {
            "source": str(pdf_path),
            "page_count": doc.page_count,
            "inspected_pages": page_count,
            "profile": {
                "heading_patterns": profile.heading_patterns,
                "caption_patterns": profile.caption_patterns,
                "ignore_patterns": profile.ignore_patterns,
                "header_footer_margin_ratio": profile.header_footer_margin_ratio,
                "min_image_width": profile.min_image_width,
                "min_image_height": profile.min_image_height,
            },
            "stats": {
                "body_font_size": body_font_size,
                "font_size_counts": _font_size_counts(all_font_sizes),
                "repeated_edge_text": sorted(repeated),
            },
            "pages": pages,
        }
    finally:
        doc.close()


def write_pdf_layout_report(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    profile: PdfProfile | None = None,
    max_pages: int | None = None,
) -> Path:
    report = inspect_pdf_layout(pdf_path, profile=profile, max_pages=max_pages)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _extract_text_blocks(page: fitz.Page, profile: PdfProfile) -> tuple[list[dict[str, Any]], list[float]]:
    raw = page.get_text("dict")
    blocks: list[dict[str, Any]] = []
    sizes: list[float] = []

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        text_parts: list[str] = []
        block_sizes: list[float] = []
        fonts: Counter[str] = Counter()
        flags = 0

        for line in lines:
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans).strip()
            if line_text:
                text_parts.append(line_text)
            for span in spans:
                size = round(float(span.get("size", 0.0)), 1)
                if size > 0:
                    block_sizes.append(size)
                font = span.get("font")
                if font:
                    fonts[font] += 1
                flags |= int(span.get("flags", 0))

        text = _normalize_text(" ".join(text_parts))
        if not text or _matches_any(text, profile.ignore_patterns):
            continue

        bbox = _round_bbox(block.get("bbox", (0, 0, 0, 0)))
        zone = _page_zone(bbox, page.rect.height, profile)
        if zone == "body":
            sizes.extend(block_sizes)
        blocks.append(
            {
                "text": text,
                "bbox": bbox,
                "font_size": _median(block_sizes) if block_sizes else 0.0,
                "font": fonts.most_common(1)[0][0] if fonts else "",
                "flags": flags,
                "is_boldish": bool(flags & 16),
                "zone": zone,
            }
        )

    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return blocks, sizes


def _extract_image_blocks(page: fitz.Page, profile: PdfProfile) -> list[dict[str, Any]]:
    images = []
    seen: set[tuple[int, tuple[float, float, float, float]]] = set()
    for img in page.get_images(full=True):
        xref = int(img[0])
        for rect in page.get_image_rects(xref):
            bbox = _round_bbox(rect)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            if width < profile.min_image_width or height < profile.min_image_height:
                continue
            key = (xref, tuple(bbox))
            if key in seen:
                continue
            seen.add(key)
            images.append(
                {
                    "xref": xref,
                    "bbox": bbox,
                    "width": round(width, 2),
                    "height": round(height, 2),
                }
            )
    images.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return images


def _classify_text_block(block: dict[str, Any], body_font_size: float, profile: PdfProfile) -> str:
    text = block["text"]
    if block.get("is_repeated_edge_text"):
        return "repeated_edge"
    if _matches_any(text, profile.caption_patterns):
        return "caption"
    if _matches_any(text, profile.heading_patterns):
        return "heading"
    size = float(block.get("font_size") or 0.0)
    if body_font_size and size >= body_font_size + 2.0 and len(text) <= 80:
        return "heading"
    if block.get("zone") in {"header", "footer"}:
        return "edge"
    return "paragraph"


def _infer_body_font_size(sizes: list[float]) -> float | None:
    if not sizes:
        return None
    counts = Counter(sizes)
    return counts.most_common(1)[0][0]


def _font_size_counts(sizes: list[float]) -> list[dict[str, Any]]:
    counts = Counter(sizes)
    return [
        {"size": size, "count": count}
        for size, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _page_zone(bbox: list[float], page_height: float, profile: PdfProfile) -> str:
    top = page_height * profile.header_footer_margin_ratio
    bottom = page_height * (1 - profile.header_footer_margin_ratio)
    if bbox[3] <= top:
        return "header"
    if bbox[1] >= bottom:
        return "footer"
    return "body"


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _round_bbox(value: Any) -> list[float]:
    return [round(float(v), 2) for v in value]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)
