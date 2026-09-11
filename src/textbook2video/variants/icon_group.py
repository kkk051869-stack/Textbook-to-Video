"""icon_group 元素的 variants。

6 套版式，按 seg_id 在主题的 preferred_variants 子集内（或全库）轮换。

设计：
- badge_grid:        圆徽章卡片网格（auto-fit，活泼）         [default]
- number_list:       大编号侧栏列表（竖向，学术）
- pill_row:          扁平胶囊横排（紧凑）
- minimal_squares:   方块卡 + 数字 + 无渐变（极简）            [new]
- circle_badge_side: 圆徽章在左 + 文字右大字号（杂志）         [new]
- bordered_minimal:  细边框 + 大数字 + 无 bg（课本印刷感）     [new]
"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


@register("icon_group", name="badge_grid", default=True)
def _ig_badge_grid(elem, d, seg_id, _imgs) -> str:
    """圆徽章卡片网格——活泼通用版（原 variant 0）。"""
    items = elem.get("items", []) or []
    cards = "".join(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'gap:16px;padding:30px 26px;border-radius:20px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="width:66px;height:66px;border-radius:50%;display:flex;'
        f'align-items:center;justify-content:center;font-size:28px;font-weight:800;'
        f'color:#fff;background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'box-shadow:0 4px 14px var(--glow-primary);">{i + 1}</div>'
        f'<div style="font-size:{_fs(24)};font-weight:700;color:var(--text);'
        f'text-align:center;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="deterministic-icon-group anim anim-up {d}" style="display:grid;'
        f'grid-template-columns:repeat(auto-fit,minmax(170px,1fr));'
        f'gap:24px;width:100%;max-width:1150px;">{cards}</div>'
    )


@register("icon_group", name="number_list")
def _ig_number_list(elem, d, seg_id, _imgs) -> str:
    """大编号侧栏列表——学术沉稳（原 variant 1）。"""
    items = elem.get("items", []) or []
    rows = "".join(
        f'<div style="display:flex;align-items:center;gap:24px;'
        f'padding:18px 28px;border-radius:14px;'
        f'background:var(--card-bg);border-left:4px solid var(--primary);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="font-size:{_fs(42)};font-weight:800;'
        f'color:var(--gold);min-width:64px;text-align:right;'
        f'font-variant-numeric:tabular-nums;letter-spacing:-1px;">'
        f'{i + 1:02d}</div>'
        f'<div style="flex:1;font-size:{_fs(24)};font-weight:600;'
        f'color:var(--text);line-height:1.4;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="deterministic-icon-group anim anim-up {d}" style="display:flex;'
        f'flex-direction:column;gap:14px;width:100%;max-width:900px;">{rows}</div>'
    )


@register("icon_group", name="pill_row")
def _ig_pill_row(elem, d, seg_id, _imgs) -> str:
    """扁平胶囊横排——紧凑横排（原 variant 2）。"""
    items = elem.get("items", []) or []
    pills = "".join(
        f'<div style="display:inline-flex;align-items:center;gap:18px;'
        f'padding:20px 34px;border-radius:999px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="font-size:{_fs(26)};font-weight:800;letter-spacing:1px;'
        f'color:var(--gold);font-variant-numeric:tabular-nums;">{i + 1:02d}</div>'
        f'<div style="width:1px;height:30px;background:var(--card-border);"></div>'
        f'<div style="font-size:{_fs(26)};font-weight:700;color:var(--text);'
        f'line-height:1.3;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="deterministic-icon-group anim anim-up {d}" style="display:flex;'
        f'flex-wrap:wrap;gap:20px;justify-content:center;'
        f'width:100%;max-width:1150px;">{pills}</div>'
    )


@register("icon_group", name="minimal_squares")
def _ig_minimal_squares(elem, d, seg_id, _imgs) -> str:
    """方块卡 + 数字 + 无渐变——极简学术风（新）。"""
    items = elem.get("items", []) or []
    cards = "".join(
        f'<div style="display:flex;flex-direction:column;align-items:flex-start;'
        f'gap:14px;padding:24px 26px;border-radius:8px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="font-size:{_fs(34)};font-weight:800;color:var(--accent);'
        f'font-variant-numeric:tabular-nums;letter-spacing:-1px;line-height:1.2;">'
        f'{i + 1:02d}</div>'
        f'<div style="font-size:{_fs(22)};font-weight:600;color:var(--text);'
        f'line-height:1.4;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="deterministic-icon-group anim anim-up {d}" style="display:grid;'
        f'grid-template-columns:repeat(auto-fit,minmax(180px,1fr));'
        f'gap:18px;width:100%;max-width:1100px;">{cards}</div>'
    )


@register("icon_group", name="circle_badge_side")
def _ig_circle_badge_side(elem, d, seg_id, _imgs) -> str:
    """圆徽章在左 + 文字大字号在右——杂志/印刷版式（新）。"""
    items = elem.get("items", []) or []
    rows = "".join(
        f'<div style="display:flex;align-items:center;gap:22px;'
        f'padding:18px 24px;border-radius:0;border-bottom:1px solid var(--card-border);">'
        f'<div style="width:54px;height:54px;border-radius:50%;flex-shrink:0;'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:22px;font-weight:800;color:var(--accent);'
        f'border:2px solid var(--accent);background:transparent;">{i + 1}</div>'
        f'<div style="flex:1;font-size:{_fs(26)};font-weight:700;'
        f'color:var(--text);line-height:1.35;letter-spacing:0.3px;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="deterministic-icon-group anim anim-up {d}" style="display:flex;flex-direction:column;'
        f'width:100%;max-width:920px;border-top:1px solid var(--card-border);">{rows}</div>'
    )


@register("icon_group", name="bordered_minimal")
def _ig_bordered_minimal(elem, d, seg_id, _imgs) -> str:
    """细边框 + 大数字 + 无 bg——课本印刷感（新）。"""
    items = elem.get("items", []) or []
    cards = "".join(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'gap:10px;padding:28px 22px;border-radius:0;'
        f'border:1px solid var(--card-border);background:transparent;">'
        f'<div style="font-size:{_fs(48)};font-weight:300;color:var(--accent);'
        f'font-variant-numeric:lining-nums tabular-nums;line-height:1.2;'
        f'font-family:var(--font-number);">{i + 1:02d}</div>'
        f'<div style="width:32px;height:1px;background:var(--accent);"></div>'
        f'<div style="font-size:{_fs(20)};font-weight:600;color:var(--text);'
        f'text-align:center;line-height:1.4;letter-spacing:0.5px;'
        f'text-transform:uppercase;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="deterministic-icon-group anim anim-up {d}" style="display:grid;'
        f'grid-template-columns:repeat(auto-fit,minmax(160px,1fr));'
        f'gap:12px;width:100%;max-width:1100px;">{cards}</div>'
    )
