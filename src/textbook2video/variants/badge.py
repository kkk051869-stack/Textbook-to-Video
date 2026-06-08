"""badge variants（暂 2 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


@register("badge", name="pill", default=True)
def _bd_pill(elem, d, seg_id, _imgs) -> str:
    return (
        f'<span class="badge primary anim anim-scale {d}">'
        f'{_esc(elem.get("text"))}</span>'
    )


@register("badge", name="tag")
def _bd_tag(elem, d, seg_id, _imgs) -> str:
    return (
        f'<span class="anim anim-scale {d}" style="position:relative;'
        f'display:inline-flex;align-items:center;padding:8px 22px 8px 30px;'
        f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'color:#fff;font-weight:700;font-size:{_fs(20)};'
        f'clip-path:polygon(14px 0,100% 0,100% 100%,14px 100%,0 50%);">'
        f'{_esc(elem.get("text"))}</span>'
    )


@register("badge", name="outline_chip")
def _bd_outline_chip(elem, d, seg_id, _imgs) -> str:
    """透明背景 + 边框——极简版（新）。"""
    return (
        f'<span class="anim anim-scale {d}" style="display:inline-flex;'
        f'align-items:center;padding:8px 22px;border-radius:999px;'
        f'background:transparent;border:1.5px solid var(--accent);'
        f'color:var(--accent);font-weight:700;font-size:{_fs(20)};'
        f'letter-spacing:1px;">'
        f'{_esc(elem.get("text"))}</span>'
    )


@register("badge", name="gradient_solid")
def _bd_gradient_solid(elem, d, seg_id, _imgs) -> str:
    """实心强渐变——活泼版（新）。"""
    return (
        f'<span class="anim anim-scale {d}" style="display:inline-flex;'
        f'align-items:center;padding:10px 28px;border-radius:8px;'
        f'background:linear-gradient(135deg,var(--accent),var(--gold));'
        f'color:#fff;font-weight:800;font-size:{_fs(22)};'
        f'letter-spacing:1.5px;text-transform:uppercase;'
        f'box-shadow:0 3px 12px var(--glow-accent);">'
        f'{_esc(elem.get("text"))}</span>'
    )


@register("badge", name="square_corner")
def _bd_square_corner(elem, d, seg_id, _imgs) -> str:
    """方角 + 实心——极客/数据库风（新）。"""
    return (
        f'<span class="anim anim-scale {d}" style="display:inline-flex;'
        f'align-items:center;padding:8px 18px;border-radius:0;'
        f'background:var(--primary);color:#fff;font-weight:700;'
        f'font-size:{_fs(18)};letter-spacing:1px;'
        f'font-family:monospace,Consolas;">'
        f'{_esc(elem.get("text"))}</span>'
    )
