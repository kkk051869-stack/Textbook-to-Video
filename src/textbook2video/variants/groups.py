"""段落组 / 徽章组的 variants。

text_group: 多段 text/label 合并时使用。
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


@register_group("text_group", name="indent_blocks")
def _grp_indent_blocks(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:16px;'
        'align-items:stretch;width:100%;max-width:1050px;text-align:left;'
        'text-indent:1.8em;">' + "".join(htmls) + "</div>"
    )


@register_group("text_group", name="left_accent_stack")
def _grp_left_accent_stack(htmls: list[str], _seg_id) -> str:
    """A single accent rail for a vertically stacked run of related prose."""
    return (
        '<div style="display:flex;flex-direction:column;gap:16px;'
        'align-items:stretch;width:100%;max-width:1050px;text-align:left;'
        'padding-left:28px;border-left:3px solid var(--accent);">'
        + "".join(htmls) + "</div>"
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
