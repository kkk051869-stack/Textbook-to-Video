"""comparison_panel variants（暂 3 套，待 Phase 2 扩到 6）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


def _cp_panel(item: dict, accent: str) -> str:
    """通用单卡（两侧版式共用）。"""
    return (
        f'<div style="flex:1;padding:28px 34px;border-radius:18px;'
        f'background:var(--card-bg);border:1px solid {accent};'
        f'box-shadow:var(--card-shadow);text-align:center;">'
        f'<div style="font-size:{_fs(27)};font-weight:800;color:{accent};'
        f'margin-bottom:14px;">{_esc(item.get("title"))}</div>'
        f'<div style="font-size:{_fs(22)};line-height:1.6;color:var(--text-dim);">'
        f'{_esc(item.get("content"))}</div></div>'
    )


@register("comparison_panel", name="vs_centered", default=True)
def _cmp_vs_centered(elem, d, seg_id, _imgs) -> str:
    """左右两栏 + 中间 VS 字徽——活泼对抗版（原 variant 0）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    left, right = items[0], items[1]
    return (
        f'<div class="anim anim-card {d}" style="display:flex;align-items:stretch;'
        f'gap:0;max-width:1150px;width:100%;">'
        f'{_cp_panel(left, "var(--primary)")}'
        f'<div style="display:flex;align-items:center;justify-content:center;'
        f'width:64px;flex-shrink:0;font-size:26px;font-weight:900;'
        f'color:var(--accent);">VS</div>'
        f'{_cp_panel(right, "var(--secondary)")}</div>'
    )


@register("comparison_panel", name="side_by_side")
def _cmp_side_by_side(elem, d, seg_id, _imgs) -> str:
    """无 VS 分隔的并排版——更克制的对比（原 variant 1）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    left, right = items[0], items[1]
    return (
        f'<div class="anim anim-card {d}" style="display:flex;align-items:stretch;'
        f'gap:24px;max-width:1150px;width:100%;">'
        f'{_cp_panel(left, "var(--primary)")}{_cp_panel(right, "var(--secondary)")}'
        f'</div>'
    )


@register("comparison_panel", name="stacked_rows")
def _cmp_stacked_rows(elem, d, seg_id, _imgs) -> str:
    """上下叠放 + 左侧色条——文章/报刊版式（原 variant 2）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    def row(item, accent):
        return (
            f'<div style="display:flex;gap:24px;align-items:stretch;'
            f'padding:22px 30px;border-radius:14px;background:var(--card-bg);'
            f'border-left:6px solid {accent};box-shadow:var(--card-shadow);'
            f'text-align:left;">'
            f'<div style="flex:0 0 220px;font-size:{_fs(24)};font-weight:800;'
            f'color:{accent};display:flex;align-items:center;">'
            f'{_esc(item.get("title"))}</div>'
            f'<div style="flex:1;font-size:{_fs(22)};line-height:1.55;'
            f'color:var(--text-dim);">{_esc(item.get("content"))}</div></div>'
        )
    return (
        f'<div class="anim anim-card {d}" style="display:flex;flex-direction:column;'
        f'gap:18px;max-width:1100px;width:100%;">'
        f'{row(items[0], "var(--primary)")}{row(items[1], "var(--secondary)")}</div>'
    )
