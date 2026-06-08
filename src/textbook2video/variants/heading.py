"""heading variants（暂 1 套，Phase 2 扩到 5；需 render_slide 配合）。

heading 与其他元素不同——它由 render_slide 单独处理为 title_bar
（content 布局）或居中大标题（封面布局），不进 content-box。

第一版只迁现有的 badge_title（左上彩色渐变徽章 + 分隔线）。
Phase 2 加：
  - gradient_band: 整宽渐变 banner 居中标题
  - numbered_chapter: 左侧大数字 + 标题（章节感）
  - minimalist_underline: 大字号 + 下方一条细 accent 线（学术/3b1b）
"""

from __future__ import annotations

from . import register
from ._shared import _esc


def _render_badge_title(text: str) -> str:
    """content 版式默认 title_bar：左上彩色徽章 + 渐变分隔线。"""
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


# heading 不通过 pick_variant_html 渲染（由 render_slide 直接调用），
# 但仍注册到 VARIANTS 以便后续主题切换；当前 render_slide 暂只走 default。
@register("heading", name="badge_title", default=True)
def _h_badge_title(elem, d, seg_id, _imgs) -> str:
    return _render_badge_title(elem.get("text", ""))
