"""image variants（暂 2 套，Phase 4 单独扩到 5 处理 QA 适配）。

注意：max-height 用绝对 px（320/330）避免被判"大视觉"(viewport*0.45) 触发
visual_text_gap_too_small QA → LLM repair 重写整页。
"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


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


@register("image", name="polaroid")
def _img_polaroid(elem, d, seg_id, imgs) -> str:
    """拍立得风——白边 + 阴影 + 微旋转（新；杂志/复古）。
    尺寸缩到 max-height:310 + padding 让总高仍 <345（1366x768 QA 安全）。
    旋转用 seg_id 派生 ±1.5°。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    # 派生稳定旋转角（-2° ~ +2°）
    try:
        rot = ((int(str(seg_id)) % 5) - 2) * 0.8
    except (ValueError, TypeError):
        rot = 0
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:480px;padding:12px 12px 36px 12px;'
            f'background:#f5f5f0;border:1px solid rgba(0,0,0,0.08);'
            f'box-shadow:0 12px 28px rgba(0,0,0,0.35),0 4px 8px rgba(0,0,0,0.2);'
            f'transform:rotate({rot}deg);display:inline-block;'
            f'border-radius:3px;">'
            f'<div style="max-height:270px;overflow:hidden;border-radius:2px;'
            f'background:#e8e8e0;display:flex;align-items:center;'
            f'justify-content:center;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
            f'<div style="text-align:center;margin-top:14px;font-size:14px;'
            f'color:#666;font-style:italic;font-family:Georgia,Times,serif;">'
            f'{_esc(elem.get("description", "") or "&nbsp;")[:40]}</div></div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:480px;padding:18px 22px 28px;background:#f5f5f0;'
        f'border:1px solid rgba(0,0,0,0.08);'
        f'box-shadow:0 12px 28px rgba(0,0,0,0.35);'
        f'transform:rotate({rot}deg);font-family:Georgia,serif;'
        f'color:#333;text-align:center;font-style:italic;">'
        f'🖼️ {_esc(desc)}</div>'
    )


@register("image", name="frame_caption")
def _img_frame_caption(elem, d, seg_id, imgs) -> str:
    """细画框 + 下方居中说明——传统课本/博物馆图注（新）。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    desc = elem.get("description", "")
    if elem_id and key in imgs:
        caption_html = (
            f'<div style="text-align:center;margin-top:10px;'
            f'font-size:{_fs(16)};color:var(--text-dim);font-style:italic;'
            f'line-height:1.4;max-width:480px;">{_esc(desc)}</div>'
            if desc else ""
        )
        return (
            f'<div class="anim anim-card {d}" '
            f'style="display:inline-flex;flex-direction:column;'
            f'max-width:520px;">'
            f'<div style="max-width:520px;max-height:290px;padding:8px;'
            f'background:var(--card-bg);border:1px solid var(--card-border);'
            f'border-radius:4px;box-shadow:var(--card-shadow);'
            f'display:flex;align-items:center;justify-content:center;'
            f'overflow:hidden;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
            f'{caption_html}</div>'
        )
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:560px;padding:30px 36px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'border-radius:4px;text-align:center;font-size:{_fs(18)};'
        f'color:var(--text-dim);font-style:italic;">'
        f'🖼️ {_esc(desc)}</div>'
    )


@register("image", name="circle_mask")
def _img_circle_mask(elem, d, seg_id, imgs) -> str:
    """圆形遮罩——人物/Logo 风（新）。
    用 border-radius:50% 强制圆形，配合 object-fit:cover 居中裁切。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card {d}" '
            f'style="width:280px;height:280px;border-radius:50%;overflow:hidden;'
            f'border:4px solid var(--accent);box-shadow:0 6px 20px var(--glow-accent);'
            f'display:flex;align-items:center;justify-content:center;'
            f'flex-shrink:0;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="width:240px;height:240px;border-radius:50%;'
        f'background:rgba(127,127,127,0.08);'
        f'border:3px solid var(--accent);'
        f'display:flex;align-items:center;justify-content:center;'
        f'text-align:center;padding:20px;font-size:{_fs(16)};'
        f'color:var(--text-dim);">'
        f'🖼️ {_esc(desc)[:30]}</div>'
    )
