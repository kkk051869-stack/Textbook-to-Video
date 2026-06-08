"""heading variants（5 套，content 版式 title_bar 用）。

heading 与其他元素不同——它由 render_slide 单独处理为 title_bar
（content 布局），不进 content-box。

5 套版式按 hash(seg_id) % 5 轮换（或主题 preferred_variants 限定）：
  - badge_title:           左上彩色徽章 + 渐变分隔线（默认，活泼）
  - gradient_band:         整宽渐变 banner 居中（PPT 课件）
  - numbered_chapter:      左侧大数字章节号 + 标题（教材）
  - minimalist_underline:  无装饰大字号 + 下方细 accent 线（学术/3b1b）
  - left_accent_block:     左侧 accent 块条 + 大标题（杂志/编辑）

签名约定：返回完整的 title_bar HTML（含分隔线 div），由 render_slide 直接插入。
"""

from __future__ import annotations

from . import register
from ._shared import _esc


@register("heading", name="badge_title", default=True)
def _h_badge_title(elem, d, seg_id, _imgs) -> str:
    """左上彩色徽章 + 渐变分隔线——活泼通用（原唯一版式）。"""
    text = elem.get("text", "")
    return (
        f'<div class="anim anim-left d1" style="display:flex;align-items:center;'
        f'flex-shrink:0;">'
        f'<span style="display:inline-flex;align-items:center;gap:13px;'
        f'padding:12px 30px;border-radius:12px;'
        f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'box-shadow:0 6px 18px var(--glow-primary);">'
        f'<span style="width:6px;height:1.25em;background:var(--accent);'
        f'border-radius:3px;"></span>'
        f'<span style="font-size:1.55em;font-weight:800;color:#fff;'
        f'font-family:var(--font-heading);letter-spacing:1px;">'
        f'{_esc(text)}</span></span></div>\n'
        f'      <div style="height:2px;margin:8px 0 0;flex-shrink:0;'
        f'background:linear-gradient(to right,var(--accent),var(--border) 40%,transparent);'
        f'"></div>'
    )


@register("heading", name="gradient_band")
def _h_gradient_band(elem, d, seg_id, _imgs) -> str:
    """整宽渐变 banner 居中——PPT 课件版（新）。"""
    text = elem.get("text", "")
    return (
        f'<div class="anim anim-left d1" style="display:flex;align-items:center;'
        f'justify-content:center;flex-shrink:0;width:100%;'
        f'padding:18px 30px;border-radius:14px;'
        f'background:linear-gradient(90deg,var(--primary),var(--secondary));'
        f'box-shadow:0 6px 18px var(--glow-primary);">'
        f'<span style="font-size:1.55em;font-weight:800;color:#fff;'
        f'font-family:var(--font-heading);letter-spacing:2px;text-align:center;">'
        f'{_esc(text)}</span></div>'
    )


@register("heading", name="numbered_chapter")
def _h_numbered_chapter(elem, d, seg_id, _imgs) -> str:
    """左侧大数字章节号 + 标题——教材/书籍风（新）。
    数字来自 seg_id（如 03、08），编号大字号灰金，右侧标题黑/白色。"""
    text = elem.get("text", "")
    # seg_id 数字化用 01-99 编号
    try:
        num = int(str(seg_id))
    except (ValueError, TypeError):
        num = 1
    return (
        f'<div class="anim anim-left d1" style="display:flex;align-items:center;'
        f'gap:24px;flex-shrink:0;padding:6px 4px;'
        f'border-bottom:2px solid var(--accent);">'
        f'<span style="font-size:3.2em;font-weight:300;color:var(--accent);'
        f'font-family:Georgia,Times,serif;font-variant-numeric:tabular-nums;'
        f'line-height:1;letter-spacing:-2px;">{num:02d}</span>'
        f'<span style="font-size:1.45em;font-weight:700;color:var(--text);'
        f'font-family:var(--font-heading);letter-spacing:1px;">{_esc(text)}</span>'
        f'</div>'
    )


@register("heading", name="minimalist_underline")
def _h_minimalist_underline(elem, d, seg_id, _imgs) -> str:
    """无装饰大字号 + 下方细 accent 线——学术/3b1b 极简（新）。"""
    text = elem.get("text", "")
    return (
        f'<div class="anim anim-left d1" style="display:flex;align-items:flex-end;'
        f'gap:12px;flex-shrink:0;padding:6px 0 12px;">'
        f'<span style="font-size:1.7em;font-weight:600;color:var(--text);'
        f'font-family:var(--font-heading);letter-spacing:0.5px;line-height:1;">'
        f'{_esc(text)}</span>'
        f'<div style="flex:1;height:1px;background:var(--accent);'
        f'margin-bottom:8px;opacity:0.6;"></div></div>'
    )


@register("heading", name="left_accent_block")
def _h_left_accent_block(elem, d, seg_id, _imgs) -> str:
    """左侧粗 accent 块条 + 大标题——杂志/编辑风（新）。"""
    text = elem.get("text", "")
    return (
        f'<div class="anim anim-left d1" style="display:flex;align-items:center;'
        f'gap:18px;flex-shrink:0;padding:4px 0;">'
        f'<div style="width:8px;height:48px;background:linear-gradient('
        f'180deg,var(--primary),var(--secondary));border-radius:4px;'
        f'box-shadow:0 0 12px var(--glow-primary);"></div>'
        f'<span style="font-size:1.55em;font-weight:800;color:var(--text);'
        f'font-family:var(--font-heading);letter-spacing:1px;">{_esc(text)}</span>'
        f'</div>'
    )
