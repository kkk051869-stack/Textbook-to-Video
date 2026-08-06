"""quote / highlight_box variants（暂 3 套，待 Phase 2 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


def _q_highlight(elem, d, seg_id, _imgs) -> str:
    return (
        f'<div class="highlight-box anim anim-card {d}" '
        f'style="max-width:1000px;font-size:{_fs(26)};">'
        f'{_esc(elem.get("text"))}</div>'
    )


def _q_big_mark(elem, d, seg_id, _imgs) -> str:
    return (
        f'<div class="anim anim-card {d}" style="position:relative;'
        f'max-width:980px;padding:32px 56px 32px 80px;'
        f'background:var(--card-bg);border-radius:18px;'
        f'box-shadow:var(--card-shadow);">'
        f'<span style="position:absolute;top:-8px;left:14px;'
        f'font-family:Georgia,serif;font-size:96px;line-height:1;'
        f'color:var(--accent);opacity:0.55;">&ldquo;</span>'
        f'<div style="font-size:{_fs(26)};font-style:italic;line-height:1.55;'
        f'color:var(--text);">{_esc(elem.get("text"))}</div></div>'
    )


def _q_double_frame(elem, d, seg_id, _imgs) -> str:
    return (
        f'<div class="anim anim-card {d}" style="max-width:980px;'
        f'padding:26px 42px;text-align:center;font-size:{_fs(26)};'
        f'color:var(--text);background:transparent;'
        f'border-top:3px double var(--accent);border-bottom:3px double var(--accent);">'
        f'{_esc(elem.get("text"))}</div>'
    )


def _q_magazine_pullquote(elem, d, seg_id, _imgs) -> str:
    """上下细线 + 居中大字加粗——杂志拉引（新）。"""
    return (
        f'<div class="anim anim-card {d}" style="max-width:1000px;'
        f'padding:36px 56px;text-align:center;'
        f'border-top:1px solid var(--card-border);'
        f'border-bottom:1px solid var(--card-border);">'
        f'<div style="font-size:{_fs(32)};font-weight:800;line-height:1.4;'
        f'color:var(--text);font-family:var(--font-display);'
        f'letter-spacing:0.5px;">{_esc(elem.get("text"))}</div></div>'
    )


# 注册：quote 和 highlight_box 共享同一组 variants（4 套）
for _etype in ("quote", "highlight_box"):
    register(_etype, name="highlight", default=True)(_q_highlight)
    register(_etype, name="big_mark")(_q_big_mark)
    register(_etype, name="double_frame")(_q_double_frame)
    register(_etype, name="magazine_pullquote")(_q_magazine_pullquote)
