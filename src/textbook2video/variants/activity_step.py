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
