"""table variants（暂 2 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc


@register("table", name="bordered", default=True)
def _tb_bordered(elem, d, seg_id, _imgs) -> str:
    """带框网格 + zebra 行——通用表格（原 variant 0）。"""
    headers = elem.get("headers", []) or []
    rows = elem.get("rows", []) or []
    if not rows:
        return ""
    thead = ""
    if headers:
        ths = "".join(
            f'<th style="padding:11px 18px;font-weight:800;color:var(--text);'
            f'border-bottom:2px solid var(--accent);text-align:left;'
            f'white-space:nowrap;">{_esc(h)}</th>'
            for h in headers
        )
        thead = f"<thead><tr>{ths}</tr></thead>"
    trs = []
    for ridx, row in enumerate(rows):
        cells = row if isinstance(row, list) else [row]
        bg = "background:rgba(255,255,255,0.03);" if ridx % 2 else ""
        tds = "".join(
            f'<td style="padding:9px 18px;color:var(--text-dim);'
            f'border-bottom:1px solid var(--border);">{_esc(c)}</td>'
            for c in cells
        )
        trs.append(f'<tr style="{bg}">{tds}</tr>')
    return (
        f'<div class="anim anim-card {d}" style="max-width:1100px;width:100%;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'border-radius:14px;padding:14px 20px;overflow:auto;'
        f'box-shadow:var(--card-shadow);">'
        f'<table style="width:100%;border-collapse:collapse;font-size:18px;">'
        f'{thead}<tbody>{"".join(trs)}</tbody></table></div>'
    )


@register("table", name="minimal_zebra")
def _tb_minimal_zebra(elem, d, seg_id, _imgs) -> str:
    """无外框 + header 加粗线 + 行间 zebra——极简编辑器风（原 variant 1）。"""
    headers = elem.get("headers", []) or []
    rows = elem.get("rows", []) or []
    if not rows:
        return ""
    thead = ""
    if headers:
        ths = "".join(
            f'<th style="padding:14px 22px;font-weight:800;color:var(--accent);'
            f'border-bottom:3px solid var(--accent);text-align:left;'
            f'text-transform:uppercase;letter-spacing:1px;font-size:14px;'
            f'white-space:nowrap;">{_esc(h)}</th>'
            for h in headers
        )
        thead = f"<thead><tr>{ths}</tr></thead>"
    trs = []
    for ridx, row in enumerate(rows):
        cells = row if isinstance(row, list) else [row]
        bg = "background:rgba(127,127,127,0.06);" if ridx % 2 else ""
        tds = "".join(
            f'<td style="padding:13px 22px;color:var(--text);font-size:19px;">'
            f'{_esc(c)}</td>'
            for c in cells
        )
        trs.append(f'<tr style="{bg}">{tds}</tr>')
    return (
        f'<div class="anim anim-card {d}" style="max-width:1100px;width:100%;'
        f'overflow:auto;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'{thead}<tbody>{"".join(trs)}</tbody></table></div>'
    )
