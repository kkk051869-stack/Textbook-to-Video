"""Small deterministic renderer for the storyboard ``bar`` element."""

from __future__ import annotations

import re

from . import register
from ._shared import _esc, _fs


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _numeric_value(value) -> float | None:
    match = _NUMBER.search(str(value or ""))
    return float(match.group(0)) if match else None


@register("bar", name="horizontal", default=True)
def _bar_horizontal(elem, d, _seg_id, _imgs) -> str:
    items = [item for item in (elem.get("items") or []) if isinstance(item, dict)]
    if not items:
        return ""
    values = [_numeric_value(item.get("value")) for item in items]
    numeric = [value for value in values if value is not None]
    maximum = max(numeric, default=1.0) or 1.0
    rows: list[str] = []
    for item, value in zip(items, values):
        width = 0.0 if value is None else max(0.0, min(value / maximum, 1.0))
        label = _esc(item.get("label") or item.get("name") or "")
        display_value = _esc(item.get("value"))
        rows.append(
            '<div style="display:grid;grid-template-columns:minmax(120px,0.32fr) 1fr;'
            f'gap:12px;align-items:center;margin:10px 0;font-size:{_fs(18)};">'
            f'<span style="color:var(--text);font-weight:700;">{label}</span>'
            '<div style="display:flex;align-items:center;gap:10px;min-width:0;">'
            '<div style="height:20px;flex:1;border-radius:999px;overflow:hidden;'
            'background:color-mix(in srgb,var(--primary) 12%,transparent);">'
            f'<div data-bar="1" style="height:100%;width:{width * 100:.2f}%;'
            'border-radius:999px;background:linear-gradient(90deg,var(--primary),var(--accent));"></div>'
            '</div>'
            f'<span style="min-width:4em;color:var(--text-dim);text-align:right;">{display_value}</span>'
            '</div></div>'
        )
    return (
        f'<div class="anim anim-bar {d}" style="width:min(1100px,100%);padding:24px 30px;'
        'border-radius:18px;background:var(--card-bg);border:1px solid var(--card-border);'
        'box-shadow:var(--card-shadow);">'
        + "".join(rows)
        + "</div>"
    )
