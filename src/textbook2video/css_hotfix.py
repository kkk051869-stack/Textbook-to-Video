"""Apply a bounded, page-scoped layout adjustment before retrying rendering."""

from pathlib import Path
import re
from typing import Any


_LAYOUT_ISSUES = {
    "content_out_of_view",
    "heading_out_of_view",
    "text_out_of_view",
    "text_out_of_bottom_safe_area",
    "text_clipped_vertical",
    "text_clipped_horizontal",
    "text_clipped_by_container",
    "text_overlap",
}


def apply_css_hotfixes(
    html_path: Path,
    report: dict[str, Any],
    *,
    browser_channel: str = "msedge",
) -> int:
    """Reduce layout spacing and large visual height on the affected pages."""
    pages = sorted({
        slide["index"]
        for slide in report.get("slides", [])
        if isinstance(slide.get("index"), int) and slide["index"] > 0
        and any(issue.get("severity") == "fail" and issue.get("type") in _LAYOUT_ISSUES
                for issue in slide.get("issues", []))
    })
    if not pages:
        return 0

    page_selector = ":is(" + ", ".join(f".slide:nth-child({index} of .slide)" for index in pages) + ")"
    css = f"""
<style id="t2v-layout-compaction">
{page_selector} :is(.fit-scale, .t2v-content-box, .fit-scale > div:not(.anim)) {{
    row-gap: 8px !important;
}}
{page_selector} .fit-scale {{
    padding-block: 8px !important;
}}
{page_selector} .fit-scale img:not([src^="data:image/svg+xml"]) {{
    max-height: 38vh;
    object-fit: contain;
}}
</style>
"""
    html = html_path.read_text(encoding="utf-8")
    if 'id="t2v-layout-compaction"' in html:
        return 0
    updated, count = re.subn(r"</head\s*>", lambda match: css + match[0], html, count=1, flags=re.I)
    if count:
        html_path.write_text(updated, encoding="utf-8")
    return len(pages) if count else 0
