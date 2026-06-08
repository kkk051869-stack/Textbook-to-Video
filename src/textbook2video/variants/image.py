"""image variants（暂 2 套，Phase 4 单独扩到 5 处理 QA 适配）。

注意：max-height 用绝对 px（320/330）避免被判"大视觉"(viewport*0.45) 触发
visual_text_gap_too_small QA → LLM repair 重写整页。
"""

from __future__ import annotations

from . import register
from ._shared import _esc


@register("image", name="framed", default=True)
def _img_framed(elem, d, seg_id, imgs) -> str:
    """带 caption 的画框图。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:520px;max-height:320px;display:flex;'
            f'align-items:center;justify-content:center;overflow:hidden;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:760px;padding:18px 28px;border-radius:16px;'
        f'background:rgba(127,127,127,0.08);font-size:20px;'
        f'color:var(--text-dim);">🖼️ {_esc(desc)}</div>'
    )


@register("image", name="borderless")
def _img_borderless(elem, d, seg_id, imgs) -> str:
    """无框无阴影，纯图——靠尺寸主导（杂志/极简风）。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:600px;max-height:330px;display:flex;'
            f'align-items:center;justify-content:center;overflow:hidden;'
            f'border-radius:6px;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:760px;padding:14px 24px;font-size:20px;'
        f'color:var(--text-dim);border-bottom:2px dashed var(--border);">'
        f'🖼️ {_esc(desc)}</div>'
    )
