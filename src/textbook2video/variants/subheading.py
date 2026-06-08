"""subheading variants（暂 2 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


@register("subheading", name="muted", default=True)
def _sh_muted(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(30)};'
        f'font-weight:600;color:var(--text-dim);">{_esc(elem.get("text"))}</p>'
    )


@register("subheading", name="bracketed")
def _sh_bracketed(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(30)};'
        f'font-weight:700;color:var(--accent);letter-spacing:2px;">'
        f'— {_esc(elem.get("text"))} —</p>'
    )
