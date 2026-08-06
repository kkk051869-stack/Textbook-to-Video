"""text / label variants."""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


def _tx_centered(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(24)};'
        f'line-height:1.6;color:var(--text-dim);max-width:1100px;">'
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


def _tx_quote_indent(elem, d, seg_id, _imgs) -> str:
    """大左侧 padding + 灰色斜体——引用/说明段（无编号，新）。"""
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(23)};'
        f'line-height:1.7;color:var(--text-dim);max-width:1000px;'
        f'text-align:left;padding-left:48px;font-style:italic;'
        f'font-family:Georgia,Times,serif;">'
        f'{_esc(elem.get("text"))}</p>'
    )


# 注册：text 和 label 共享同一组 variants（4 套）
# 注：所有 variant 都不带序号——序号会和 heading.numbered_chapter 撞，且重复 text
# 同页时一页全是同编号，问题在这里彻底杜绝。
for _et in ("text", "label"):
    register(_et, name="centered", default=True)(_tx_centered)
    register(_et, name="indented")(_tx_indented)
    register(_et, name="accent_box")(_tx_accent_box)
    register(_et, name="quote_indent")(_tx_quote_indent)
