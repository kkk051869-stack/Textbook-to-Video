"""text / label variants（暂 3 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


def _tx_centered(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(24)};'
        f'line-height:1.6;color:var(--text-dim);max-width:1100px;">'
        f'{_esc(elem.get("text"))}</p>'
    )


def _tx_left_border(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(24)};'
        f'line-height:1.6;color:var(--text);max-width:1000px;text-align:left;'
        f'padding:8px 0 8px 22px;border-left:3px solid var(--accent);">'
        f'{_esc(elem.get("text"))}</p>'
    )


def _tx_indented(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(24)};'
        f'line-height:1.7;color:var(--text-dim);max-width:1050px;'
        f'text-align:left;text-indent:2em;">'
        f'{_esc(elem.get("text"))}</p>'
    )


def _tx_accent_box(elem, d, seg_id, _imgs) -> str:
    """浅色 accent 背景框——课件/讲义版（新）。"""
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(24)};'
        f'line-height:1.6;color:var(--text);max-width:1000px;text-align:left;'
        f'padding:18px 28px;border-radius:10px;'
        f'background:rgba(127,127,127,0.08);'
        f'border-left:4px solid var(--accent);">'
        f'{_esc(elem.get("text"))}</p>'
    )


def _tx_numbered_para(elem, d, seg_id, _imgs) -> str:
    """前缀 01/02 编号——文档/手册版（新）。
    用 delay class（d2/d3/...）的序号作为页内编号，每段不同。
    delay 从 d2 开始（d1 留给 heading），所以 d2 → 01、d3 → 02、...
    """
    try:
        num = int(d.lstrip("d")) - 1  # d2 → 1, d3 → 2
    except (ValueError, TypeError):
        num = 1
    if num < 1:
        num = 1
    return (
        f'<div class="anim anim-up {d}" style="display:flex;align-items:flex-start;'
        f'gap:18px;max-width:1050px;text-align:left;">'
        f'<span style="font-size:{_fs(34)};font-weight:300;color:var(--accent);'
        f'font-variant-numeric:tabular-nums;line-height:1;flex-shrink:0;'
        f'font-family:Georgia,Times,serif;">{num:02d}</span>'
        f'<p style="margin:0;font-size:{_fs(24)};line-height:1.6;'
        f'color:var(--text-dim);">{_esc(elem.get("text"))}</p></div>'
    )


# 注册：text 和 label 共享同一组 variants（5 套）
for _et in ("text", "label"):
    register(_et, name="centered", default=True)(_tx_centered)
    register(_et, name="left_border")(_tx_left_border)
    register(_et, name="indented")(_tx_indented)
    register(_et, name="accent_box")(_tx_accent_box)
    register(_et, name="numbered_para")(_tx_numbered_para)
