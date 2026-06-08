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


# 注册：text 和 label 共享同一组 variants
register("text", name="centered", default=True)(_tx_centered)
register("text", name="left_border")(_tx_left_border)
register("text", name="indented")(_tx_indented)
register("label", name="centered", default=True)(_tx_centered)
register("label", name="left_border")(_tx_left_border)
register("label", name="indented")(_tx_indented)
