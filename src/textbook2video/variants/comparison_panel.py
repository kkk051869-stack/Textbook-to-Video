"""comparison_panel variants（暂 3 套，待 Phase 2 扩到 6）。"""

from __future__ import annotations

from . import register
from ._shared import _esc, _fs


def _cp_panel(item: dict, accent: str) -> str:
    """通用单卡（两侧版式共用）。"""
    return (
        f'<div style="flex:1;padding:28px 34px;border-radius:18px;'
        f'background:var(--card-bg);border:1px solid {accent};'
        f'box-shadow:var(--card-shadow);text-align:center;">'
        f'<div style="font-size:{_fs(27)};font-weight:800;color:{accent};'
        f'margin-bottom:14px;">{_esc(item.get("title"))}</div>'
        f'<div style="font-size:{_fs(22)};line-height:1.6;color:var(--text-dim);">'
        f'{_esc(item.get("content"))}</div></div>'
    )


@register("comparison_panel", name="vs_centered", default=True)
def _cmp_vs_centered(elem, d, seg_id, _imgs) -> str:
    """左右两栏 + 中间 VS 字徽——活泼对抗版（原 variant 0）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    left, right = items[0], items[1]
    return (
        f'<div class="anim anim-card {d}" style="display:flex;align-items:stretch;'
        f'gap:0;max-width:1150px;width:100%;">'
        f'{_cp_panel(left, "var(--primary)")}'
        f'<div style="display:flex;align-items:center;justify-content:center;'
        f'width:64px;flex-shrink:0;font-size:26px;font-weight:900;'
        f'color:var(--accent);">VS</div>'
        f'{_cp_panel(right, "var(--secondary)")}</div>'
    )


@register("comparison_panel", name="side_by_side")
def _cmp_side_by_side(elem, d, seg_id, _imgs) -> str:
    """无 VS 分隔的并排版——更克制的对比（原 variant 1）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    left, right = items[0], items[1]
    return (
        f'<div class="anim anim-card {d}" style="display:flex;align-items:stretch;'
        f'gap:24px;max-width:1150px;width:100%;">'
        f'{_cp_panel(left, "var(--primary)")}{_cp_panel(right, "var(--secondary)")}'
        f'</div>'
    )


@register("comparison_panel", name="stacked_rows")
def _cmp_stacked_rows(elem, d, seg_id, _imgs) -> str:
    """上下叠放 + 左侧色条——文章/报刊版式（原 variant 2）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    def row(item, accent):
        return (
            f'<div style="display:flex;gap:24px;align-items:stretch;'
            f'padding:22px 30px;border-radius:14px;background:var(--card-bg);'
            f'border-left:6px solid {accent};box-shadow:var(--card-shadow);'
            f'text-align:left;">'
            f'<div style="flex:0 0 220px;font-size:{_fs(24)};font-weight:800;'
            f'color:{accent};display:flex;align-items:center;">'
            f'{_esc(item.get("title"))}</div>'
            f'<div style="flex:1;font-size:{_fs(22)};line-height:1.55;'
            f'color:var(--text-dim);">{_esc(item.get("content"))}</div></div>'
        )
    return (
        f'<div class="anim anim-card {d}" style="display:flex;flex-direction:column;'
        f'gap:18px;max-width:1100px;width:100%;">'
        f'{row(items[0], "var(--primary)")}{row(items[1], "var(--secondary)")}</div>'
    )


@register("comparison_panel", name="v_split_dashed")
def _cmp_v_split_dashed(elem, d, seg_id, _imgs) -> str:
    """中线虚线分隔无 VS——学术克制版（新）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    def col(item):
        return (
            f'<div style="flex:1;padding:20px 32px;text-align:center;">'
            f'<div style="font-size:{_fs(28)};font-weight:800;color:var(--accent);'
            f'margin-bottom:18px;letter-spacing:0.5px;">'
            f'{_esc(item.get("title"))}</div>'
            f'<div style="font-size:{_fs(22)};line-height:1.7;color:var(--text);'
            f'font-weight:500;">{_esc(item.get("content"))}</div></div>'
        )
    return (
        f'<div class="anim anim-card {d}" style="display:flex;align-items:stretch;'
        f'gap:0;max-width:1100px;width:100%;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'border-radius:14px;box-shadow:var(--card-shadow);">'
        f'{col(items[0])}'
        f'<div style="width:1px;border-left:2px dashed var(--card-border);'
        f'flex-shrink:0;margin:24px 0;"></div>'
        f'{col(items[1])}</div>'
    )


@register("comparison_panel", name="top_bottom_compare")
def _cmp_top_bottom_compare(elem, d, seg_id, _imgs) -> str:
    """上下两段 + 强 accent——杂志/对话风（新）。
    上面 item 用主色调标签 + 内容，下面 item 用次色调，强烈对比感。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    def section(item, accent, tag):
        return (
            f'<div style="position:relative;padding:30px 36px 26px 36px;'
            f'background:var(--card-bg);border-left:5px solid {accent};">'
            f'<div style="position:absolute;top:-12px;left:24px;'
            f'background:{accent};color:#fff;font-weight:800;font-size:{_fs(16)};'
            f'padding:4px 14px;border-radius:4px;letter-spacing:2px;">{tag}</div>'
            f'<div style="font-size:{_fs(26)};font-weight:800;color:{accent};'
            f'margin-bottom:10px;">{_esc(item.get("title"))}</div>'
            f'<div style="font-size:{_fs(22)};line-height:1.55;color:var(--text);">'
            f'{_esc(item.get("content"))}</div></div>'
        )
    return (
        f'<div class="anim anim-card {d}" style="display:flex;flex-direction:column;'
        f'gap:16px;max-width:1080px;width:100%;">'
        f'{section(items[0], "var(--primary)", "A")}'
        f'{section(items[1], "var(--secondary)", "B")}</div>'
    )


@register("comparison_panel", name="chart_bar")
def _cmp_chart_bar(elem, d, seg_id, _imgs) -> str:
    """横条对比柱——数据风（新）。
    两个 item 各用一条横向粗条，长度按内容字数估算（视觉强调）。"""
    items = elem.get("items", []) or []
    if len(items) < 2:
        return ""
    # 横条相对长度（简单按 content 字数：满字符 60 → 100%）
    lens = [min(100, max(60, len(str(it.get("content", ""))) * 2.5)) for it in items]
    def bar(item, accent, width_pct):
        return (
            f'<div style="display:flex;flex-direction:column;gap:8px;width:100%;">'
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:baseline;color:{accent};font-weight:800;">'
            f'<span style="font-size:{_fs(24)};">{_esc(item.get("title"))}</span>'
            f'</div>'
            f'<div style="position:relative;height:48px;background:rgba(127,127,127,0.1);'
            f'border-radius:24px;overflow:hidden;">'
            f'<div style="position:absolute;left:0;top:0;height:100%;width:{width_pct}%;'
            f'background:linear-gradient(90deg,{accent},{accent}cc);'
            f'border-radius:24px;"></div></div>'
            f'<div style="font-size:{_fs(20)};color:var(--text-dim);line-height:1.5;'
            f'padding:6px 8px 0;">{_esc(item.get("content"))}</div></div>'
        )
    return (
        f'<div class="anim anim-card {d}" style="display:flex;flex-direction:column;'
        f'gap:22px;max-width:1050px;width:100%;'
        f'padding:24px 30px;border-radius:14px;background:var(--card-bg);'
        f'border:1px solid var(--card-border);box-shadow:var(--card-shadow);">'
        f'{bar(items[0], "var(--primary)", lens[0])}'
        f'{bar(items[1], "var(--secondary)", lens[1])}</div>'
    )
