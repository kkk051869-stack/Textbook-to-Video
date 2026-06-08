"""元素变体库（Variant Library）

对每种 storyboard element 提供多套渲染版式（variant），通过
`hash(seg_id, element_type) % N` 稳定分桶轮换，避免同主题不同页视觉重复。

公共 API：
    pick_variant_html(etype, elem, seg_id, delay_class, available_image_keys)
        → str | None
    render_text_group(htmls, seg_id) → str
        多段 text/label 合并时的段落组变体
    render_badge_row(htmls, seg_id) → str
        多个 badge 横排合并时的变体

每种元素的 variant 数：
    icon_group         3    flow_step          3    comparison_panel    3
    quote/highlight    3    text/label (single) 3    text-group         3
    activity_step      2    table              2    image              2
    badge              2    subheading         2    badge-row          2

新增变体：写一个 `_render_X_Y(elem, d, seg_id, imgs)` 函数 + 加到
对应类型的 `VARIANTS[X]` 列表即可。
"""

from __future__ import annotations

import html as _html
from typing import Any, Callable

Segment = dict[str, Any]
RenderFn = Callable[[dict, str, Any, set[str]], str]


def _esc(text: Any) -> str:
    return _html.escape(str(text or "")).replace("\n", "<br>")


def _fs(px: int, floor_ratio: float = 0.78) -> str:
    vw = round(px / 19.2, 2)
    floor = max(12, int(px * floor_ratio))
    return f"clamp({floor}px,{vw}vw,{px}px)"


def _pick_index(n: int, seg_id: Any) -> int:
    """稳定分桶：数字 seg_id 走模运算，非数字走 hash。"""
    if n <= 1:
        return 0
    try:
        return (int(str(seg_id)) - 1) % n
    except (ValueError, TypeError):
        return abs(hash(str(seg_id))) % n


# ============================================================
# subheading
# ============================================================
def _sh_muted(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(30)};'
        f'font-weight:600;color:var(--text-dim);">{_esc(elem.get("text"))}</p>'
    )


def _sh_bracketed(elem, d, seg_id, _imgs) -> str:
    return (
        f'<p class="anim anim-up {d}" style="margin:0;font-size:{_fs(30)};'
        f'font-weight:700;color:var(--accent);letter-spacing:2px;">'
        f'— {_esc(elem.get("text"))} —</p>'
    )


# ============================================================
# text / label（单个出现时）
# ============================================================
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


# ============================================================
# quote / highlight_box
# ============================================================
def _q_highlight(elem, d, seg_id, _imgs) -> str:
    return (
        f'<div class="highlight-box anim anim-card {d}" '
        f'style="max-width:1000px;font-size:{_fs(26)};">'
        f'{_esc(elem.get("text"))}</div>'
    )


def _q_big_mark(elem, d, seg_id, _imgs) -> str:
    return (
        f'<div class="anim anim-card {d}" style="position:relative;'
        f'max-width:980px;padding:32px 56px 32px 80px;'
        f'background:var(--card-bg);border-radius:18px;'
        f'box-shadow:var(--card-shadow);">'
        f'<span style="position:absolute;top:-8px;left:14px;'
        f'font-family:Georgia,serif;font-size:96px;line-height:1;'
        f'color:var(--accent);opacity:0.55;">&ldquo;</span>'
        f'<div style="font-size:{_fs(26)};font-style:italic;line-height:1.55;'
        f'color:var(--text);">{_esc(elem.get("text"))}</div></div>'
    )


def _q_double_frame(elem, d, seg_id, _imgs) -> str:
    return (
        f'<div class="anim anim-card {d}" style="max-width:980px;'
        f'padding:26px 42px;text-align:center;font-size:{_fs(26)};'
        f'color:var(--text);background:transparent;'
        f'border-top:3px double var(--accent);border-bottom:3px double var(--accent);">'
        f'{_esc(elem.get("text"))}</div>'
    )


# ============================================================
# badge（单个）
# ============================================================
def _bd_pill(elem, d, seg_id, _imgs) -> str:
    return (
        f'<span class="badge primary anim anim-scale {d}">'
        f'{_esc(elem.get("text"))}</span>'
    )


def _bd_tag(elem, d, seg_id, _imgs) -> str:
    # 旗帜/标签形（左尖角）
    return (
        f'<span class="anim anim-scale {d}" style="position:relative;'
        f'display:inline-flex;align-items:center;padding:8px 22px 8px 30px;'
        f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'color:#fff;font-weight:700;font-size:{_fs(20)};'
        f'clip-path:polygon(14px 0,100% 0,100% 100%,14px 100%,0 50%);">'
        f'{_esc(elem.get("text"))}</span>'
    )


# ============================================================
# icon_group（3 variants — 沿用原实现）
# ============================================================
def _ig_badge_grid(elem, d, seg_id, _imgs) -> str:
    items = elem.get("items", []) or []
    cards = "".join(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'gap:16px;padding:30px 26px;border-radius:20px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="width:66px;height:66px;border-radius:50%;display:flex;'
        f'align-items:center;justify-content:center;font-size:28px;font-weight:800;'
        f'color:#fff;background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'box-shadow:0 4px 14px var(--glow-primary);">{i + 1}</div>'
        f'<div style="font-size:{_fs(24)};font-weight:700;color:var(--text);'
        f'text-align:center;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:grid;'
        f'grid-template-columns:repeat(auto-fit,minmax(170px,1fr));'
        f'gap:24px;width:100%;max-width:1150px;">{cards}</div>'
    )


def _ig_number_list(elem, d, seg_id, _imgs) -> str:
    items = elem.get("items", []) or []
    rows = "".join(
        f'<div style="display:flex;align-items:center;gap:24px;'
        f'padding:18px 28px;border-radius:14px;'
        f'background:var(--card-bg);border-left:4px solid var(--primary);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="font-size:{_fs(42)};font-weight:800;'
        f'color:var(--gold);min-width:64px;text-align:right;'
        f'font-variant-numeric:tabular-nums;letter-spacing:-1px;">'
        f'{i + 1:02d}</div>'
        f'<div style="flex:1;font-size:{_fs(24)};font-weight:600;'
        f'color:var(--text);line-height:1.4;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;'
        f'flex-direction:column;gap:14px;width:100%;max-width:900px;">{rows}</div>'
    )


def _ig_pill_row(elem, d, seg_id, _imgs) -> str:
    items = elem.get("items", []) or []
    pills = "".join(
        f'<div style="display:inline-flex;align-items:center;gap:18px;'
        f'padding:20px 34px;border-radius:999px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);">'
        f'<div style="font-size:{_fs(26)};font-weight:800;letter-spacing:1px;'
        f'color:var(--gold);font-variant-numeric:tabular-nums;">{i + 1:02d}</div>'
        f'<div style="width:1px;height:30px;background:var(--card-border);"></div>'
        f'<div style="font-size:{_fs(26)};font-weight:700;color:var(--text);'
        f'line-height:1.3;">{_esc(it)}</div></div>'
        for i, it in enumerate(items)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;'
        f'flex-wrap:wrap;gap:20px;justify-content:center;'
        f'width:100%;max-width:1150px;">{pills}</div>'
    )


# ============================================================
# flow_step（3 variants）
# ============================================================
def _fs_h_arrows(elem, d, seg_id, _imgs) -> str:
    steps = elem.get("steps", []) or []
    parts = []
    for i, step in enumerate(steps):
        parts.append(
            f'<div style="display:flex;align-items:center;gap:16px;'
            f'padding:18px 30px;border-radius:16px;background:var(--card-bg);'
            f'border:1px solid var(--card-border);box-shadow:var(--card-shadow);">'
            f'<div style="width:44px;height:44px;border-radius:50%;flex-shrink:0;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:20px;font-weight:800;color:#fff;'
            f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
            f'box-shadow:0 3px 10px var(--glow-primary);">{i + 1}</div>'
            f'<div style="font-size:{_fs(23)};font-weight:700;color:var(--text);">'
            f'{_esc(step)}</div></div>'
        )
        if i < len(steps) - 1:
            parts.append(
                '<div style="font-size:30px;color:var(--accent);'
                'align-self:center;font-weight:700;">&rarr;</div>'
            )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;gap:16px;'
        f'justify-content:center;align-items:center;flex-wrap:wrap;">'
        f'{"".join(parts)}</div>'
    )


def _fs_v_timeline(elem, d, seg_id, _imgs) -> str:
    steps = elem.get("steps", []) or []
    rows = []
    for i, step in enumerate(steps):
        is_last = i == len(steps) - 1
        rows.append(
            f'<div style="display:flex;align-items:stretch;gap:24px;">'
            # 左侧：圆点 + 连线
            f'<div style="display:flex;flex-direction:column;align-items:center;'
            f'flex-shrink:0;width:48px;">'
            f'<div style="width:36px;height:36px;border-radius:50%;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:18px;font-weight:800;color:#fff;'
            f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
            f'box-shadow:0 0 0 4px var(--glow-primary);">{i + 1}</div>'
            + (
                f'<div style="width:2px;flex:1;background:var(--accent);'
                f'margin-top:6px;opacity:0.5;"></div>'
                if not is_last else ""
            )
            + "</div>"
            # 右侧：文字卡
            f'<div style="flex:1;font-size:{_fs(23)};font-weight:600;'
            f'color:var(--text);padding:6px 0 22px 0;text-align:left;">'
            f'{_esc(step)}</div></div>'
        )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;flex-direction:column;'
        f'width:100%;max-width:900px;">{"".join(rows)}</div>'
    )


def _fs_numbered_cards(elem, d, seg_id, _imgs) -> str:
    steps = elem.get("steps", []) or []
    cards = "".join(
        f'<div style="position:relative;flex:1;min-width:170px;max-width:240px;'
        f'padding:36px 22px 22px 22px;border-radius:18px;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'box-shadow:var(--card-shadow);text-align:center;">'
        f'<div style="position:absolute;top:-22px;left:50%;transform:translateX(-50%);'
        f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
        f'width:46px;height:46px;border-radius:50%;color:#fff;'
        f'font-size:20px;font-weight:800;display:flex;align-items:center;'
        f'justify-content:center;box-shadow:0 4px 14px var(--glow-primary);">'
        f'{i + 1}</div>'
        f'<div style="font-size:{_fs(22)};font-weight:700;color:var(--text);'
        f'line-height:1.4;margin-top:8px;">{_esc(step)}</div></div>'
        for i, step in enumerate(steps)
    )
    return (
        f'<div class="anim anim-up {d}" style="display:flex;'
        f'gap:24px;justify-content:center;align-items:stretch;'
        f'flex-wrap:wrap;width:100%;max-width:1150px;margin-top:26px;">'
        f'{cards}</div>'
    )


# ============================================================
# activity_step（2 variants）
# ============================================================
def _as_numbered_list(elem, d, seg_id, _imgs) -> str:
    # 沿用 flow_step 的横排（保持兼容感）
    return _fs_h_arrows(elem, d, seg_id, _imgs)


def _as_checklist(elem, d, seg_id, _imgs) -> str:
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


# ============================================================
# comparison_panel（3 variants）
# ============================================================
def _cp_panel(item: dict, accent: str) -> str:
    return (
        f'<div style="flex:1;padding:28px 34px;border-radius:18px;'
        f'background:var(--card-bg);border:1px solid {accent};'
        f'box-shadow:var(--card-shadow);text-align:center;">'
        f'<div style="font-size:{_fs(27)};font-weight:800;color:{accent};'
        f'margin-bottom:14px;">{_esc(item.get("title"))}</div>'
        f'<div style="font-size:{_fs(22)};line-height:1.6;color:var(--text-dim);">'
        f'{_esc(item.get("content"))}</div></div>'
    )


def _cmp_vs_centered(elem, d, seg_id, _imgs) -> str:
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


def _cmp_side_by_side(elem, d, seg_id, _imgs) -> str:
    """无 VS 分隔的并排版（更克制）。"""
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


def _cmp_stacked_rows(elem, d, seg_id, _imgs) -> str:
    """上下叠放，每栏带左侧色条。"""
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


# ============================================================
# table（2 variants）
# ============================================================
def _tb_bordered(elem, d, seg_id, _imgs) -> str:
    headers = elem.get("headers", []) or []
    rows = elem.get("rows", []) or []
    if not rows:
        return ""
    thead = ""
    if headers:
        ths = "".join(
            f'<th style="padding:11px 18px;font-weight:800;color:var(--text);'
            f'border-bottom:2px solid var(--accent);text-align:left;'
            f'white-space:nowrap;">{_esc(h)}</th>'
            for h in headers
        )
        thead = f"<thead><tr>{ths}</tr></thead>"
    trs = []
    for ridx, row in enumerate(rows):
        cells = row if isinstance(row, list) else [row]
        bg = "background:rgba(255,255,255,0.03);" if ridx % 2 else ""
        tds = "".join(
            f'<td style="padding:9px 18px;color:var(--text-dim);'
            f'border-bottom:1px solid var(--border);">{_esc(c)}</td>'
            for c in cells
        )
        trs.append(f'<tr style="{bg}">{tds}</tr>')
    return (
        f'<div class="anim anim-card {d}" style="max-width:1100px;width:100%;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'border-radius:14px;padding:14px 20px;overflow:auto;'
        f'box-shadow:var(--card-shadow);">'
        f'<table style="width:100%;border-collapse:collapse;font-size:18px;">'
        f'{thead}<tbody>{"".join(trs)}</tbody></table></div>'
    )


def _tb_minimal_zebra(elem, d, seg_id, _imgs) -> str:
    """极简：无外框，仅 header 下加粗线 + 行间 zebra。"""
    headers = elem.get("headers", []) or []
    rows = elem.get("rows", []) or []
    if not rows:
        return ""
    thead = ""
    if headers:
        ths = "".join(
            f'<th style="padding:14px 22px;font-weight:800;color:var(--accent);'
            f'border-bottom:3px solid var(--accent);text-align:left;'
            f'text-transform:uppercase;letter-spacing:1px;font-size:14px;'
            f'white-space:nowrap;">{_esc(h)}</th>'
            for h in headers
        )
        thead = f"<thead><tr>{ths}</tr></thead>"
    trs = []
    for ridx, row in enumerate(rows):
        cells = row if isinstance(row, list) else [row]
        bg = "background:rgba(127,127,127,0.06);" if ridx % 2 else ""
        tds = "".join(
            f'<td style="padding:13px 22px;color:var(--text);font-size:19px;">'
            f'{_esc(c)}</td>'
            for c in cells
        )
        trs.append(f'<tr style="{bg}">{tds}</tr>')
    return (
        f'<div class="anim anim-card {d}" style="max-width:1100px;width:100%;'
        f'overflow:auto;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'{thead}<tbody>{"".join(trs)}</tbody></table></div>'
    )


# ============================================================
# image（2 variants）
# ============================================================
def _img_framed(elem, d, seg_id, imgs) -> str:
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        # max-height:38vh 确保高度 < viewport*0.45（QA 阈值），避免被判"大视觉"
        # 触发"文字距离不足"误报，进而触发 LLM repair 重写整页。
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:580px;max-height:38vh;display:flex;'
            f'align-items:center;justify-content:center;overflow:hidden;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:760px;padding:18px 28px;border-radius:16px;'
        f'background:rgba(127,127,127,0.08);font-size:20px;'
        f'color:var(--text-dim);">🖼️ {_esc(desc)}</div>'
    )


def _img_borderless(elem, d, seg_id, imgs) -> str:
    """无框无阴影，纯图，靠尺寸主导（仍保持 < 45vh 防 QA 触发）。"""
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    if elem_id and key in imgs:
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:680px;max-height:42vh;display:flex;'
            f'align-items:center;justify-content:center;overflow:hidden;'
            f'border-radius:6px;">'
            f'{{{{IMG_{elem_id}}}}}</div>'
        )
    desc = elem.get("description", "")
    if not desc:
        return ""
    return (
        f'<div class="anim anim-card {d}" '
        f'style="max-width:760px;padding:14px 24px;font-size:20px;'
        f'color:var(--text-dim);border-bottom:2px dashed var(--border);">'
        f'🖼️ {_esc(desc)}</div>'
    )


# ============================================================
# 段落组 variants（多段 text/label 合并时使用）
# ============================================================
def _grp_centered_column(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:14px;'
        'align-items:center;width:100%;">' + "".join(htmls) + "</div>"
    )


def _grp_left_accent(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:12px;'
        'align-items:stretch;width:100%;max-width:1000px;'
        'border-left:3px solid var(--accent);padding-left:24px;text-align:left;">'
        + "".join(htmls) + "</div>"
    )


def _grp_indent_blocks(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;flex-direction:column;gap:16px;'
        'align-items:stretch;width:100%;max-width:1050px;text-align:left;'
        'text-indent:1.8em;">' + "".join(htmls) + "</div>"
    )


def _badge_row_pills(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;gap:24px;justify-content:center;'
        'align-items:stretch;flex-wrap:wrap;width:100%;">'
        + "".join(htmls) + "</div>"
    )


def _badge_row_chips(htmls: list[str], _seg_id) -> str:
    return (
        '<div style="display:flex;gap:12px;justify-content:center;'
        'align-items:center;flex-wrap:wrap;width:100%;padding:12px 24px;'
        'border-radius:18px;background:rgba(127,127,127,0.05);">'
        + "".join(htmls) + "</div>"
    )


# ============================================================
# 主注册表
# ============================================================
VARIANTS: dict[str, list[RenderFn]] = {
    "subheading":       [_sh_muted, _sh_bracketed],
    "text":             [_tx_centered, _tx_left_border, _tx_indented],
    "label":            [_tx_centered, _tx_left_border, _tx_indented],
    "quote":            [_q_highlight, _q_big_mark, _q_double_frame],
    "highlight_box":    [_q_highlight, _q_big_mark, _q_double_frame],
    "badge":            [_bd_pill, _bd_tag],
    "icon_group":       [_ig_badge_grid, _ig_number_list, _ig_pill_row],
    "flow_step":        [_fs_h_arrows, _fs_v_timeline, _fs_numbered_cards],
    "activity_step":    [_as_numbered_list, _as_checklist],
    "comparison_panel": [_cmp_vs_centered, _cmp_side_by_side, _cmp_stacked_rows],
    "table":            [_tb_bordered, _tb_minimal_zebra],
    "image":            [_img_framed, _img_borderless],
}

# 段落组（多段 text/label 合并时）的 variants 单独注册
GROUP_VARIANTS: dict[str, list[Callable[[list[str], Any], str]]] = {
    "text_group":  [_grp_centered_column, _grp_left_accent, _grp_indent_blocks],
    "badge_row":   [_badge_row_pills, _badge_row_chips],
}


def pick_variant_html(
    etype: str, elem: dict, seg_id: Any, delay_class: str,
    available_image_keys: set[str],
) -> str | None:
    """渲染元素：根据 (etype, seg_id) 稳定选择 variant。

    返回 None 表示该 etype 不在变体库（调用方应进入 fallback 或返回 None）。
    """
    fns = VARIANTS.get(etype)
    if not fns:
        return None
    idx = _pick_index(len(fns), seg_id)
    items_ok = True
    if etype == "icon_group" and not (elem.get("items") or []):
        return ""
    if etype in ("flow_step", "activity_step") and not (elem.get("steps") or []):
        return ""
    if etype == "comparison_panel" and len(elem.get("items") or []) < 2:
        return ""
    if etype == "table" and not (elem.get("rows") or []):
        return ""
    return fns[idx](elem, delay_class, seg_id, available_image_keys)


def pick_group_variant_html(
    group_name: str, htmls: list[str], seg_id: Any,
) -> str:
    """合并组（text_group / badge_row）按 seg_id 选变体。"""
    fns = GROUP_VARIANTS.get(group_name, [])
    if not fns:
        return "".join(htmls)
    idx = _pick_index(len(fns), seg_id)
    return fns[idx](htmls, seg_id)
