"""Image variants for readable teaching visuals.

默认教学图使用至少 780×480 px 的无框图面：相对于旧的 520×320 px 默认图框，
两个方向均扩大 50%。拍立得相纸模板已退役；窄画框和圆形裁切也绝不进入自动
编排。

注意：图框用**定高** px 而非 max-height——注入的 <img> 是
`max-height:100%;object-fit:contain`，百分比高度只在父级有确定高度时才生效；
只给 max-height 时百分比解析为 none，竖图会按原始比例溢出再被 overflow:hidden
裁掉（QA 难测、肉眼可见底部被切）。定高后 object-fit:contain 会等比缩放塞进框
（短图轻微留白，绝不裁切）。高度仍 <345 避开 viewport*0.45 的"大视觉"QA。
"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


def _source_caption(elem: dict, *, max_chars: int | None = None) -> str:
    """Return provenance-backed display text before falling back to a summary.

    ``description`` is often a long VLM interpretation intended for semantic
    matching, not a reader-facing figure label.  Source figures should retain
    their original caption (or at least the source Figure id) in the renderer.
    Truncation happens before HTML escaping so entities are never cut in half.
    """
    value = str(
        elem.get("source_caption")
        or elem.get("caption")
        or elem.get("figure_id")
        or elem.get("description")
        or ""
    ).strip()
    if max_chars and len(value) > max_chars:
        value = value[: max_chars - 1].rstrip() + "…"
    return value


@register("image", name="framed", default=True)
def _img_framed(elem, d, seg_id, imgs) -> str:
    """Default large, plain teaching image surface (the name is legacy)."""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card t2v-image-surface {d}" '
            f'aria-label="{_esc(_source_caption(elem))}" '
            f'style="width:780px;max-width:100%;height:480px;display:flex;'
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


def _figure_label(elem: dict) -> str:
    """Keep a short source label outside the pixels of a textbook figure."""
    if elem.get("visual_tools_run"):
        return ""
    figure_id = str(elem.get("figure_id") or "").strip()
    if figure_id:
        return figure_id
    source_id = str(elem.get("source_image_id") or "").strip()
    return source_id or "教材图"


@register("image", name="diagram_full")
def _img_diagram_full(elem, d, seg_id, imgs) -> str:
    """Large, readable layout for explanatory/result figures.

    Paper figures are teaching diagrams, not decorative photo cards.  The
    source caption remains structured metadata; only a short Figure label is
    rendered below the image so the visual area is not consumed by a long
    paper caption.
    """
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        label = _figure_label(elem)
        label_html = (
            f'<div style="font-size:{_fs(16)};line-height:1.3;'
            f'color:var(--text-dim);font-family:var(--font-label);">'
            f'{_esc(label)}</div>' if label else ""
        )
        return (
            f'<div class="anim anim-card t2v-image-surface {d}" '
            f'style="width:min(100%,1100px);max-width:1100px;'
            f'display:flex;flex-direction:column;align-items:center;'
            f'justify-content:center;gap:10px;overflow:visible;">'
            f'<div style="width:100%;height:min(65vh,720px);min-height:480px;'
            f'display:flex;align-items:center;justify-content:center;'
            f'overflow:hidden;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
            f'{label_html}</div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" style="max-width:1100px;'
        f'padding:18px 28px;font-size:{_fs(20)};color:var(--text-dim);">'
        f'{_esc(desc)}</div>'
    )


@register("image", name="borderless")
def _img_borderless(elem, d, seg_id, imgs) -> str:
    """无框无阴影，纯图——靠尺寸主导（杂志/极简风）。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card t2v-image-surface {d}" '
            f'style="width:780px;max-width:100%;height:480px;display:flex;'
            f'align-items:center;justify-content:center;overflow:hidden;">'
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


def _img_polaroid(elem, d, seg_id, imgs) -> str:
    """Retired photo-card renderer, retained only for old generated HTML.

    It is deliberately not registered: new lessons must never put a teaching
    image in a Polaroid/paper frame.
    """
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    # 派生稳定旋转角（-2° ~ +2°）
    try:
        rot = ((int(str(seg_id)) % 5) - 2) * 0.8
    except (ValueError, TypeError):
        rot = 0
    if elem_id and key in imgs:
        caption = _source_caption(elem, max_chars=96) or "\u00a0"
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:480px;padding:12px 12px 36px 12px;'
            f'background:#f5f5f0;border:1px solid rgba(0,0,0,0.08);'
            f'box-shadow:0 12px 28px rgba(0,0,0,0.35),0 4px 8px rgba(0,0,0,0.2);'
            f'transform:rotate({rot}deg);display:inline-block;'
            f'border-radius:3px;">'
            f'<div style="height:270px;overflow:hidden;border-radius:2px;'
            f'background:#e8e8e0;display:flex;align-items:center;'
            f'justify-content:center;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
            f'<div style="text-align:center;margin-top:14px;font-size:14px;'
            f'color:#666;font-style:italic;font-family:var(--font-label);">'
            f'{_esc(caption)}</div></div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:480px;padding:18px 22px 28px;background:#f5f5f0;'
        f'border:1px solid rgba(0,0,0,0.08);'
        f'box-shadow:0 12px 28px rgba(0,0,0,0.35);'
        f'transform:rotate({rot}deg);font-family:var(--font-body);'
        f'color:#333;text-align:center;font-style:italic;">'
        f'🖼️ {_esc(desc)}</div>'
    )


@register("image", name="frame_caption", automatic=False)
def _img_frame_caption(elem, d, seg_id, imgs) -> str:
    """细画框 + 下方居中说明——传统课本/博物馆图注（新）。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    desc = _source_caption(elem)
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
            f'<div style="max-width:520px;height:290px;padding:8px;'
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


@register("image", name="circle_mask", automatic=False)
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
