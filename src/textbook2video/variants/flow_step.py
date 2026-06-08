"""flow_step variants（暂 3 套，待 Phase 2 扩到 6）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


@register("flow_step", name="h_arrows", default=True)
def _fs_h_arrows(elem, d, seg_id, _imgs) -> str:
    """横向卡片 + 箭头连接——通用流程版（原 variant 0）。"""
    steps = elem.get("steps", []) or []
    parts = []
    for i, step in enumerate(steps):
        parts.append(
            f'<div style="display:flex;align-items:center;gap:16px;'
            f'padding:18px 30px;border-radius:16px;background:var(--card-bg);'
            f'border:1px solid var(--card-border);box-shadow:var(--card-shadow);">'
            f'<div style="width:44px;height:44px;border-radius:50%;flex-shrink:0;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:20px;font-weight:800;color:#fff;'
            f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
            f'box-shadow:0 3px 10px var(--glow-primary);">{i + 1}</div>'
            f'<div style="font-size:{_fs(23)};font-weight:700;color:var(--text);">'
            f'{_esc(step)}</div></div>'
        )
        if i < len(steps) - 1:
            parts.append(
                '<div style="font-size:30px;color:var(--accent);'
                'align-self:center;font-weight:700;">&rarr;</div>'
            )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;gap:16px;'
        f'justify-content:center;align-items:center;flex-wrap:wrap;">'
        f'{"".join(parts)}</div>'
    )


@register("flow_step", name="v_timeline")
def _fs_v_timeline(elem, d, seg_id, _imgs) -> str:
    """纵向时间线——圆点连线，竖向（原 variant 1）。"""
    steps = elem.get("steps", []) or []
    rows = []
    for i, step in enumerate(steps):
        is_last = i == len(steps) - 1
        rows.append(
            f'<div style="display:flex;align-items:stretch;gap:24px;">'
            f'<div style="display:flex;flex-direction:column;align-items:center;'
            f'flex-shrink:0;width:48px;">'
            f'<div style="width:36px;height:36px;border-radius:50%;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:18px;font-weight:800;color:#fff;'
            f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
            f'box-shadow:0 0 0 4px var(--glow-primary);">{i + 1}</div>'
            + (
                f'<div style="width:2px;flex:1;background:var(--accent);'
                f'margin-top:6px;opacity:0.5;"></div>'
                if not is_last else ""
            )
            + "</div>"
            f'<div style="flex:1;font-size:{_fs(23)};font-weight:600;'
            f'color:var(--text);padding:6px 0 22px 0;text-align:left;">'
            f'{_esc(step)}</div></div>'
        )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;flex-direction:column;'
        f'width:100%;max-width:900px;">{"".join(rows)}</div>'
    )


@register("flow_step", name="numbered_cards")
def _fs_numbered_cards(elem, d, seg_id, _imgs) -> str:
    """每步独立大卡 + 顶部悬浮编号——教学动画版（原 variant 2）。"""
    steps = elem.get("steps", []) or []
    cards = "".join(
        f'<div style="position:relative;flex:1;min-width:170px;max-width:240px;'
        f'padding:36px 22px 22px 22px;border-radius:18px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);text-align:center;">'
        f'<div style="position:absolute;top:-22px;left:50%;transform:translateX(-50%);'
        f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'width:46px;height:46px;border-radius:50%;color:#fff;'
        f'font-size:20px;font-weight:800;display:flex;align-items:center;'
        f'justify-content:center;box-shadow:0 4px 14px var(--glow-primary);">'
        f'{i + 1}</div>'
        f'<div style="font-size:{_fs(22)};font-weight:700;color:var(--text);'
        f'line-height:1.4;margin-top:8px;">{_esc(step)}</div></div>'
        for i, step in enumerate(steps)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;'
        f'gap:24px;justify-content:center;align-items:stretch;'
        f'flex-wrap:wrap;width:100%;max-width:1150px;margin-top:26px;">'
        f'{cards}</div>'
    )
