"""badge variants（暂 2 套，待 Phase 3 扩到 5）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


@register("badge", name="pill", default=True)
def _bd_pill(elem, d, seg_id, _imgs) -> str:
    return (
        f'<span class="badge primary anim anim-scale {d}">'
        f'{_esc(elem.get("text"))}</span>'
    )


@register("badge", name="tag")
def _bd_tag(elem, d, seg_id, _imgs) -> str:
    return (
        f'<span class="anim anim-scale {d}" style="position:relative;'
        f'display:inline-flex;align-items:center;padding:8px 22px 8px 30px;'
        f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'color:#fff;font-weight:700;font-size:{_fs(20)};'
        f'clip-path:polygon(14px 0,100% 0,100% 100%,14px 100%,0 50%);">'
        f'{_esc(elem.get("text"))}</span>'
    )
