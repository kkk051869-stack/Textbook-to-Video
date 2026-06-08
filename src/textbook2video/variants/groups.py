"""段落组 / 徽章组的 variants。

text_group: 多段 text/label 合并时使用（暂 3 套，Phase 3 扩到 5）
badge_row:  多个 badge 横排合并时使用（暂 2 套，Phase 3 扩到 3）
"""

from __future__ import annotations

from . import register_group


@register_group("text_group", name="centered_column", default=True)
def _grp_centered_column(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:14px;'
        'align-items:center;width:100%;">' + "".join(htmls) + "</div>"
    )


@register_group("text_group", name="left_accent")
def _grp_left_accent(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:12px;'
        'align-items:stretch;width:100%;max-width:1000px;'
        'border-left:3px solid var(--accent);padding-left:24px;text-align:left;">'
        + "".join(htmls) + "</div>"
    )


@register_group("text_group", name="indent_blocks")
def _grp_indent_blocks(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:16px;'
        'align-items:stretch;width:100%;max-width:1050px;text-align:left;'
        'text-indent:1.8em;">' + "".join(htmls) + "</div>"
    )


@register_group("text_group", name="drop_cap")
def _grp_drop_cap(htmls: list[str], _seg_id) -> str:
    """首字下沉——杂志/报刊版式。
    首段第一个字符放大、加粗、accent 色；其余段落正常排版。"""
    if not htmls:
        return ""
    # 不用尝试操作每段的首字符（HTML 已渲染），用 CSS 伪元素只对第一个段落起效
    return (
        '<div style="display:flex;flex-direction:column;gap:14px;'
        'align-items:stretch;width:100%;max-width:980px;text-align:left;'
        'font-family:Georgia,Times,serif;">'
        '<style>.dropcap-grp > p:first-child::first-letter{'
        'float:left;font-size:5em;line-height:0.85;padding:6px 14px 0 0;'
        'font-weight:800;color:var(--accent);font-family:Georgia,serif;}</style>'
        '<div class="dropcap-grp">' + "".join(htmls) + "</div></div>"
    )


@register_group("text_group", name="two_column")
def _grp_two_column(htmls: list[str], _seg_id) -> str:
    """双栏并排——杂志排版（多段并列时压缩纵向）。"""
    n = len(htmls)
    if n <= 1:
        return "".join(htmls)
    mid = (n + 1) // 2
    left = "".join(htmls[:mid])
    right = "".join(htmls[mid:])
    return (
        '<div style="display:flex;gap:32px;align-items:flex-start;'
        'width:100%;max-width:1050px;text-align:left;">'
        f'<div style="flex:1;display:flex;flex-direction:column;gap:12px;">{left}</div>'
        f'<div style="flex:1;display:flex;flex-direction:column;gap:12px;">{right}</div>'
        '</div>'
    )


@register_group("badge_row", name="pills_centered", default=True)
def _badge_row_pills(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;gap:24px;justify-content:center;'
        'align-items:stretch;flex-wrap:wrap;width:100%;">'
        + "".join(htmls) + "</div>"
    )


@register_group("badge_row", name="chips_panel")
def _badge_row_chips(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;gap:12px;justify-content:center;'
        'align-items:center;flex-wrap:wrap;width:100%;padding:12px 24px;'
        'border-radius:18px;background:rgba(127,127,127,0.05);">'
        + "".join(htmls) + "</div>"
    )


@register_group("badge_row", name="cloud_scatter")
def _badge_row_cloud(htmls: list[str], _seg_id) -> str:
    """不规则散布的标签云——更松散的版式。"""
    return (
        '<div style="display:flex;gap:20px;justify-content:center;'
        'align-items:center;flex-wrap:wrap;width:100%;padding:20px 40px;'
        'transform-origin:center;">'
        + "".join(htmls) + "</div>"
    )
