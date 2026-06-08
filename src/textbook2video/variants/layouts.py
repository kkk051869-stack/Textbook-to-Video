"""图文构图（compose_image_text）的 layout 模式。

按"右栏轻元素数 + 视觉重量"自动选版式（非 hash 轮换）。
Phase 4 计划扩到 6 套（加 magazine_split / circular_image / offset_overlap）。

当前 3 套：
  - classic:    经典图左文右（少量轻元素时）
  - span_bottom: 图左文右 + 末位元素横跨底栏（中等密度）
  - full_stack:  图顶中央 + 文居中下全宽（重元素 / 满屏）
"""

from __future__ import annotations

from typing import Any


# _LIGHT_WEIGHT 与 checks.py 同步保持（粗粒度，控密度用）
_LIGHT_WEIGHT = {
    "text": 1.0, "label": 0.5,
    "quote": 1.3, "highlight_box": 1.3,
    "badge": 0.4, "icon_group": 1.8,
}


def light_weight(types: list[str]) -> float:
    return sum(_LIGHT_WEIGHT.get(t, 1.0) for t in types)


def _gap(k: int) -> str:
    """右栏内部 gap 按元素数分级。"""
    return "36px" if k <= 2 else "28px" if k == 3 else "22px" if k == 4 else "16px"


def compose_image_text(
    image_html: list[str], light_html: list[str], weight: float, seg_id: Any,
) -> str:
    """图 + 轻元素的构图——按"轻元素数 + 视觉重量"自动选版式：

      n ≤2 且 weight <3.5      → classic（经典图左文右）
      n  =3 或 weight 3.5-5.5  → span_bottom（图左文右 + 末位横跨底）
      n ≥4 或 weight ≥5.5      → full_stack（图顶 + 全宽文字下方）
    """
    n = len(light_html)
    w = weight

    if n >= 4 or w >= 5.5:
        return _layout_full_stack(image_html, light_html)
    if n >= 3 or w >= 3.5:
        return _layout_span_bottom(image_html, light_html)
    return _layout_classic(image_html, light_html)


def _layout_classic(image_html: list[str], light_html: list[str]) -> str:
    n = len(light_html)
    left = "\n".join(image_html)
    right = "\n".join(light_html)
    return (
        '<div style="display:flex;gap:46px;align-items:center;width:100%;">'
        '<div style="flex:1.15;min-width:0;display:flex;flex-direction:column;'
        'gap:18px;align-items:center;justify-content:center;">'
        f'{left}</div>'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        f'gap:{_gap(n)};align-items:stretch;justify-content:center;text-align:left;">'
        f'{right}</div></div>'
    )


def _layout_span_bottom(image_html: list[str], light_html: list[str]) -> str:
    right_top = light_html[:-1]
    spanning = light_html[-1]
    left = "\n".join(image_html)
    right_join = "\n".join(right_top)
    return (
        '<div style="display:flex;flex-direction:column;gap:24px;width:100%;">'
        '<div style="display:flex;gap:46px;align-items:center;width:100%;">'
        '<div style="flex:1.15;min-width:0;display:flex;flex-direction:column;'
        'gap:18px;align-items:center;justify-content:center;">'
        f'{left}</div>'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        f'gap:{_gap(len(right_top))};align-items:stretch;justify-content:center;'
        f'text-align:left;">{right_join}</div></div>'
        '<div style="width:100%;display:flex;justify-content:center;'
        f'align-items:center;">{spanning}</div>'
        '</div>'
    )


def _layout_full_stack(image_html: list[str], light_html: list[str]) -> str:
    n = len(light_html)
    top = "\n".join(image_html)
    bot = "\n".join(light_html)
    return (
        '<div style="display:flex;flex-direction:column;gap:28px;'
        'align-items:center;width:100%;">'
        f'<div style="display:flex;justify-content:center;align-items:center;'
        f'width:100%;max-width:760px;">{top}</div>'
        f'<div style="display:flex;flex-direction:column;gap:{_gap(n)};'
        f'align-items:center;justify-content:center;width:100%;max-width:1100px;'
        f'text-align:center;">{bot}</div>'
        '</div>'
    )
