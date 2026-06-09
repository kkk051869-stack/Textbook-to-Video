"""Generic PDF layout and structure extraction for textbooks.

The goal is not to make every PDF magically perfect. Instead, this module gives
the project a reusable front-end:

PDF pages -> layout blocks -> profile-driven structure IR -> later LLM repair.

That keeps new textbook adaptation in a small profile JSON whenever possible,
instead of scattering book-specific rules through the code.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

import fitz


DEFAULT_HEADING_PATTERNS = [
    r"^\u7b2c[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]+[\u7ae0\u8282\u8bfe]",
    r"^[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+[\u3001.]",
    r"^\d+(\.\d+)+\s+",
    r"^\d+[\u3001.]",
    r"^\u4e13\u9898[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+",
    r"^\u4efb\u52a1[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+",
    r"^Chapter\s+\d+",
    r"^Section\s+\d+",
]

DEFAULT_CAPTION_PATTERNS = [
    r"^\u56fe\s*[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+([-.]\d+)?",
    r"^\u8868\s*[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+([-.]\d+)?",
    r"^Figure\s+\d+",
    r"^Table\s+\d+",
]

DEFAULT_IGNORE_PATTERNS = [
    r"^\d+$",
    r"^\u7b2c\s*\d+\s*\u9875$",
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
    caption_max_distance: float = 90.0
    heading_font_delta: float = 2.0
    max_heading_chars: int = 80

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
            caption_max_distance=float(data.get("caption_max_distance", 90.0)),
            heading_font_delta=float(data.get("heading_font_delta", 2.0)),
            max_heading_chars=int(data.get("max_heading_chars", 80)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "heading_patterns": self.heading_patterns,
            "caption_patterns": self.caption_patterns,
            "ignore_patterns": self.ignore_patterns,
            "header_footer_margin_ratio": self.header_footer_margin_ratio,
            "min_image_width": self.min_image_width,
            "min_image_height": self.min_image_height,
            "caption_max_distance": self.caption_max_distance,
            "heading_font_delta": self.heading_font_delta,
            "max_heading_chars": self.max_heading_chars,
        }


def inspect_pdf_layout(
    pdf_path: str | Path,
    *,
    profile: PdfProfile | None = None,
    start_page: int = 1,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Inspect a text-based PDF and return page-level layout signals."""

    profile = profile or PdfProfile()
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    try:
        pages = []
        all_font_sizes: list[float] = []
        repeated_edge_text: Counter[str] = Counter()

        if start_page < 1:
            raise ValueError("start_page must be >= 1")
        start_index = min(start_page - 1, doc.page_count)
        end_index = doc.page_count if max_pages is None else min(doc.page_count, start_index + max_pages)
        inspected_pages = max(0, end_index - start_index)
        for page_index in range(start_index, end_index):
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
            "start_page": start_page,
            "inspected_pages": inspected_pages,
            "profile": profile.to_dict(),
            "stats": {
                "body_font_size": body_font_size,
                "font_size_counts": _font_size_counts(all_font_sizes),
                "repeated_edge_text": sorted(repeated),
            },
            "pages": pages,
        }
    finally:
        doc.close()


def build_pdf_structure(
    pdf_path: str | Path,
    *,
    profile: PdfProfile | None = None,
    start_page: int = 1,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Build a textbook structure IR from a PDF.

    The IR intentionally stays close to source layout. It is suitable for:
    - deterministic section/content extraction,
    - profile calibration,
    - sending a compact repair payload to an LLM later.
    """

    profile = profile or PdfProfile()
    layout = inspect_pdf_layout(
        pdf_path,
        profile=profile,
        start_page=start_page,
        max_pages=max_pages,
    )
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for page in layout["pages"]:
        caption_by_index = _associate_captions(page, profile)
        associated_caption_ids = {
            id(caption) for caption in caption_by_index.values() if caption is not None
        }
        for item in _reading_order_items(page):
            if item["kind"] == "text":
                block = item["block"]
                role = block["role"]
                if role in {"edge", "repeated_edge"}:
                    continue
                if role == "heading":
                    current = _new_section(block, page, len(sections) + 1, layout["stats"])
                    sections.append(current)
                    continue
                if current is None:
                    current = _new_front_matter_section(page, len(sections) + 1)
                    sections.append(current)
                if role == "caption" and id(block) in associated_caption_ids:
                    continue
                current["content_blocks"].append(_text_content_block(block, page, role))
            else:
                if current is None:
                    current = _new_front_matter_section(page, len(sections) + 1)
                    sections.append(current)
                image = item["block"]
                caption = caption_by_index.get(item["index"])
                current["content_blocks"].append(_image_content_block(image, caption, page))

    for section in sections:
        pages = [
            block["page_no"]
            for block in section["content_blocks"]
            if "page_no" in block
        ]
        if pages:
            section["page_start"] = min(section["page_start"], min(pages))
            section["page_end"] = max(section["page_end"], max(pages))
        section["text"] = "\n".join(
            block["text"]
            for block in section["content_blocks"]
            if block.get("type") in {"paragraph", "caption"} and block.get("text")
        )

    return {
        "source": layout["source"],
        "kind": "textbook_pdf_ir",
        "page_count": layout["page_count"],
        "start_page": layout["start_page"],
        "inspected_pages": layout["inspected_pages"],
        "profile": layout["profile"],
        "stats": layout["stats"],
        "sections": sections,
        "llm_repair": {
            "recommended": True,
            "reason": "PDF layout is heuristic; use LLM repair to confirm section levels, paragraph merges, and image-caption ownership.",
        },
    }


def write_pdf_layout_report(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    profile: PdfProfile | None = None,
    start_page: int = 1,
    max_pages: int | None = None,
) -> Path:
    report = inspect_pdf_layout(
        pdf_path,
        profile=profile,
        start_page=start_page,
        max_pages=max_pages,
    )
    return _write_json(report, output_path)


def write_pdf_structure(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    profile: PdfProfile | None = None,
    start_page: int = 1,
    max_pages: int | None = None,
) -> Path:
    structure = build_pdf_structure(
        pdf_path,
        profile=profile,
        start_page=start_page,
        max_pages=max_pages,
    )
    return _write_json(structure, output_path)


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
    if (
        body_font_size
        and size >= body_font_size + profile.heading_font_delta
        and len(text) <= profile.max_heading_chars
    ):
        return "heading"
    if block.get("zone") in {"header", "footer"}:
        return "edge"
    return "paragraph"


def _associate_captions(
    page: dict[str, Any],
    profile: PdfProfile,
) -> dict[int, dict[str, Any] | None]:
    captions = [b for b in page["text_blocks"] if b["role"] == "caption"]
    result: dict[int, dict[str, Any] | None] = {}
    used: set[int] = set()
    for index, image in enumerate(page["image_blocks"]):
        best = None
        best_score = float("inf")
        for caption in captions:
            if id(caption) in used:
                continue
            score = _caption_distance(image["bbox"], caption["bbox"])
            if score is not None and score <= profile.caption_max_distance and score < best_score:
                best = caption
                best_score = score
        if best is not None:
            used.add(id(best))
        result[index] = best
    return result


def _caption_distance(image_bbox: list[float], caption_bbox: list[float]) -> float | None:
    image_left, image_top, image_right, image_bottom = image_bbox
    cap_left, cap_top, cap_right, cap_bottom = caption_bbox
    overlap = max(0.0, min(image_right, cap_right) - max(image_left, cap_left))
    min_width = max(1.0, min(image_right - image_left, cap_right - cap_left))
    if overlap / min_width < 0.15:
        return None
    if cap_top >= image_bottom:
        return cap_top - image_bottom
    if image_top >= cap_bottom:
        return image_top - cap_bottom
    return 0.0


def _reading_order_items(page: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        {"kind": "text", "block": block, "bbox": block["bbox"]}
        for block in page["text_blocks"]
    ]
    items.extend(
        {"kind": "image", "block": image, "bbox": image["bbox"], "index": index}
        for index, image in enumerate(page["image_blocks"])
    )
    return sorted(items, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def _new_section(
    block: dict[str, Any],
    page: dict[str, Any],
    section_id: int,
    stats: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": block["text"],
        "level": _infer_heading_level(block, stats.get("body_font_size")),
        "page_start": page["page_no"],
        "page_end": page["page_no"],
        "source_bbox": block["bbox"],
        "content_blocks": [],
    }


def _new_front_matter_section(page: dict[str, Any], section_id: int) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": "Front Matter",
        "level": 0,
        "page_start": page["page_no"],
        "page_end": page["page_no"],
        "source_bbox": None,
        "content_blocks": [],
    }


def _infer_heading_level(block: dict[str, Any], body_font_size: float | None) -> int:
    text = block["text"]
    size = float(block.get("font_size") or 0.0)
    if re.match(r"^(Chapter\s+\d+|\u7b2c.+\u7ae0)", text, flags=re.IGNORECASE):
        return 1
    if re.match(r"^(\d+\.\d+|\u7b2c.+\u8282)", text, flags=re.IGNORECASE):
        return 2
    if body_font_size and size >= body_font_size + 6:
        return 1
    if body_font_size and size >= body_font_size + 3:
        return 2
    return 3


def _text_content_block(
    block: dict[str, Any],
    page: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    return {
        "type": "caption" if role == "caption" else "paragraph",
        "text": block["text"],
        "page_no": page["page_no"],
        "bbox": block["bbox"],
        "font_size": block["font_size"],
    }


def _image_content_block(
    image: dict[str, Any],
    caption: dict[str, Any] | None,
    page: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "image",
        "page_no": page["page_no"],
        "bbox": image["bbox"],
        "xref": image["xref"],
        "caption": caption["text"] if caption else None,
        "caption_bbox": caption["bbox"] if caption else None,
    }


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


def _write_json(data: dict[str, Any], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
