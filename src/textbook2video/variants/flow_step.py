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


@register("flow_step", name="chevron_strip")
def _fs_chevron_strip(elem, d, seg_id, _imgs) -> str:
    """雪佛龙横条——商务/PPT 风（新）。
    每步是带尾箭头的形状块，颜色渐变递进。"""
    steps = elem.get("steps", []) or []
    n = len(steps)
    if n == 0:
        return ""
    # 颜色从 primary 到 secondary 渐变（简单 hsl 计算用 opacity 模拟）
    cells = []
    for i, step in enumerate(steps):
        # 越往后 opacity 越低，制造"由强到弱"感
        opacity = 1.0 - 0.12 * i
        is_last = i == n - 1
        # 雪佛龙形：左 5° 缺口 + 右 5° 尖头（最后一个不带尖头）
        clip = (
            "polygon(0 0,calc(100% - 18px) 0,100% 50%,calc(100% - 18px) 100%,0 100%,18px 50%)"
            if not is_last else
            "polygon(0 0,100% 0,100% 100%,0 100%,18px 50%)"
        )
        cells.append(
            f'<div style="flex:1;min-width:0;margin-right:-12px;'
            f'background:var(--primary);opacity:{opacity:.2f};'
            f'clip-path:{clip};padding:18px 28px 18px 36px;'
            f'display:flex;align-items:center;justify-content:center;'
            f'color:#fff;font-weight:800;font-size:{_fs(20)};text-align:center;'
            f'line-height:1.3;">{_esc(step)}</div>'
        )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;align-items:stretch;'
        f'width:100%;max-width:1150px;">{"".join(cells)}</div>'
    )


@register("flow_step", name="pipeline")
def _fs_pipeline(elem, d, seg_id, _imgs) -> str:
    """粗箭头管道 + 渐变阶段色——工程感（新）。
    一条粗渐变横管，每段写步骤，转折用 chevron 圆点。"""
    steps = elem.get("steps", []) or []
    n = len(steps)
    if n == 0:
        return ""
    cells = []
    for i, step in enumerate(steps):
        cells.append(
            f'<div style="flex:1;min-width:0;padding:18px 14px;text-align:center;'
            f'color:#fff;font-weight:700;font-size:{_fs(20)};line-height:1.3;'
            f'position:relative;">'
            f'<div style="font-size:{_fs(14)};opacity:0.7;letter-spacing:2px;'
            f'margin-bottom:6px;">STEP {i + 1:02d}</div>'
            f'<div>{_esc(step)}</div></div>'
        )
        if i < n - 1:
            cells.append(
                '<div style="width:24px;flex-shrink:0;display:flex;align-items:center;'
                'justify-content:center;color:rgba(255,255,255,0.8);'
                'font-size:24px;font-weight:900;">▶</div>'
            )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;align-items:stretch;'
        f'width:100%;max-width:1150px;border-radius:50px;'
        f'background:linear-gradient(90deg,var(--primary),var(--secondary));'
        f'box-shadow:var(--card-shadow);overflow:hidden;">'
        f'{"".join(cells)}</div>'
    )


@register("flow_step", name="card_chain")
def _fs_card_chain(elem, d, seg_id, _imgs) -> str:
    """卡片链 + 短弧线连接——教学动画版（新）。
    卡片之间用 SVG 曲线箭头连接，更有"演变"感。"""
    steps = elem.get("steps", []) or []
    n = len(steps)
    if n == 0:
        return ""
    parts = []
    for i, step in enumerate(steps):
        parts.append(
            f'<div style="flex:0 0 auto;display:flex;flex-direction:column;align-items:center;'
            f'gap:10px;min-width:160px;max-width:200px;">'
            f'<div style="width:48px;height:48px;border-radius:50%;display:flex;'
            f'align-items:center;justify-content:center;font-size:22px;font-weight:800;'
            f'color:#fff;background:var(--accent);'
            f'box-shadow:0 4px 14px var(--glow-accent);">{i + 1}</div>'
            f'<div style="font-size:{_fs(20)};font-weight:600;color:var(--text);'
            f'text-align:center;line-height:1.4;padding:0 8px;">{_esc(step)}</div></div>'
        )
        if i < n - 1:
            # SVG 弧线连接
            parts.append(
                '<div style="flex:0 0 56px;display:flex;align-items:center;'
                'justify-content:center;color:var(--accent);">'
                '<svg width="56" height="36" viewBox="0 0 56 36" fill="none">'
                '<path d="M2 28 Q28 -4 54 28" stroke="currentColor" stroke-width="2" '
                'stroke-dasharray="4 4" fill="none"/>'
                '<polygon points="50,22 54,28 48,30" fill="currentColor"/>'
                '</svg></div>'
            )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;align-items:flex-start;'
        f'gap:0;width:100%;max-width:1150px;justify-content:center;flex-wrap:wrap;">'
        f'{"".join(parts)}</div>'
    )
