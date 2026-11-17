"""activity_step variants（暂 2 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs
from .flow_step import _fs_h_arrows


# activity_step 的"横排编号"与 flow_step 的 h_arrows 形态一致——复用
register("activity_step", name="numbered_list", default=True)(_fs_h_arrows)


@register("activity_step", name="checklist")
def _as_checklist(elem, d, seg_id, _imgs) -> str:
    """复选框列表——任务执行风。"""
    steps = elem.get("steps", []) or []
    rows = "".join(
        f'<div style="display:flex;align-items:center;gap:18px;'
        f'padding:14px 24px;border-radius:12px;background:var(--card-bg);'
        f'border:1px solid var(--card-border);">'
        f'<div style="width:28px;height:28px;border-radius:6px;'
        f'border:2px solid var(--accent);flex-shrink:0;display:flex;'
        f'align-items:center;justify-content:center;color:var(--accent);'
        f'font-size:20px;font-weight:900;">{i + 1}</div>'
        f'<div style="flex:1;font-size:{_fs(23)};font-weight:600;'
        f'color:var(--text);text-align:left;">{_esc(step)}</div></div>'
        for i, step in enumerate(steps)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;flex-direction:column;'
        f'gap:10px;width:100%;max-width:880px;">{rows}</div>'
    )


@register("activity_step", name="numbered_circles")
def _as_numbered_circles(elem, d, seg_id, _imgs) -> str:
    """大圆圈编号 + 步骤文字——教学步骤版（新）。"""
    steps = elem.get("steps", []) or []
    cards = "".join(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'gap:12px;flex:1;min-width:160px;max-width:220px;text-align:center;">'
        f'<div style="width:68px;height:68px;border-radius:50%;display:flex;'
        f'align-items:center;justify-content:center;font-size:30px;font-weight:800;'
        f'color:var(--accent);background:transparent;'
        f'border:3px solid var(--accent);'
        f'font-family:Georgia,serif;">{i + 1}</div>'
        f'<div style="font-size:{_fs(20)};font-weight:600;color:var(--text);'
        f'line-height:1.4;">{_esc(step)}</div></div>'
        for i, step in enumerate(steps)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;gap:32px;'
        f'justify-content:center;align-items:flex-start;flex-wrap:wrap;'
        f'width:100%;max-width:1100px;">{cards}</div>'
    )


@register("activity_step", name="indent_arrow")
def _as_indent_arrow(elem, d, seg_id, _imgs) -> str:
    """箭头层级缩进——指令序列版（新）。"""
    steps = elem.get("steps", []) or []
    rows = "".join(
        f'<div style="display:flex;align-items:flex-start;gap:14px;'
        f'padding:8px 20px;text-align:left;">'
        f'<span style="color:var(--accent);font-size:22px;font-weight:900;'
        f'flex-shrink:0;line-height:1.5;">&#8627;</span>'
        f'<span style="flex:1;font-size:{_fs(22)};font-weight:600;'
        f'color:var(--text);line-height:1.5;">{_esc(step)}</span></div>'
        for step in steps
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;flex-direction:column;'
        f'gap:8px;width:100%;max-width:920px;'
        f'padding:18px 24px;border-radius:10px;background:var(--card-bg);'
        f'border:1px solid var(--card-border);">{rows}</div>'
    )
