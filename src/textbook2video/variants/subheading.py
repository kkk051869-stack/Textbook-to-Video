"""subheading variants（暂 2 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


@register("subheading", name="muted", default=True)
def _sh_muted(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(30)};'
        f'font-weight:600;color:var(--text-dim);">{_esc(elem.get("text"))}</p>'
    )


@register("subheading", name="bracketed")
def _sh_bracketed(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(30)};'
        f'font-weight:700;color:var(--accent);letter-spacing:2px;">'
        f'— {_esc(elem.get("text"))} —</p>'
    )


@register("subheading", name="accent_underline")
def _sh_accent_underline(elem, d, seg_id, _imgs) -> str:
    """大字号 + 下方细 accent 线（新）。"""
    return (
        f'<div class="anim anim-up {d}" style="display:inline-flex;flex-direction:column;'
        f'align-items:center;gap:6px;margin:0;">'
        f'<span style="font-size:{_fs(28)};font-weight:700;'
        f'color:var(--text-dim);letter-spacing:1px;">'
        f'{_esc(elem.get("text"))}</span>'
        f'<div style="width:60%;min-width:60px;height:2px;background:var(--accent);"></div>'
        f'</div>'
    )


@register("subheading", name="dim_italic")
def _sh_dim_italic(elem, d, seg_id, _imgs) -> str:
    """灰色斜体——杂志副标题（新）。"""
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(26)};'
        f'font-weight:400;font-style:italic;color:var(--text-dim);'
        f'font-family:Georgia,Times,serif;letter-spacing:0.3px;">'
        f'{_esc(elem.get("text"))}</p>'
    )


@register("subheading", name="boxed_caps")
def _sh_boxed_caps(elem, d, seg_id, _imgs) -> str:
    """小框 + 大写字母 + accent——课件章节标识（新）。"""
    return (
        f'<span class="anim anim-up {d}" style="display:inline-block;margin:0;'
        f'padding:6px 18px;border:1.5px solid var(--accent);border-radius:4px;'
        f'font-size:{_fs(20)};font-weight:800;color:var(--accent);'
        f'letter-spacing:3px;text-transform:uppercase;">'
        f'{_esc(elem.get("text"))}</span>'
    )
