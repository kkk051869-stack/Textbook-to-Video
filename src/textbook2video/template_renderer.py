"""确定性 slide 渲染器（F5）

把 storyboard 的结构化 elements 直接用框架类渲染成整齐、统一、配色协调的
slide HTML，绕开"让弱模型自由写 inline style"导致的布局乱 / 审美简陋 / 配色不协调。

公共 API:
    render_slide(segment, slide_index, available_image_keys) -> str | None
        返回完整 <div class="slide">...</div>；visual_type 或某个 element 不支持
        时返回 None，由调用方 fallback 到 LLM 生成。

设计要点:
- 统一的居中 flex column 布局 + 安全边距 → 对齐一致，不再参差。
- 元素一律走 base.css 框架类（.icon-card/.flow-step/.comparison-panel/.highlight-box…）
  与主题 CSS 变量 → 审美统一、配色跟随主题。
- 每个块按出现顺序加 .anim + 递增 .dN → 确定性入场动画。
- image 元素复用 {{IMG_<id>}} 占位 + inject_generated_images 注入机制。
"""

import html as _html
from typing import Any

Segment = dict[str, Any]

# 这些 visual_type 的布局较特殊（节点/连线等），暂不支持，交回 LLM 生成
UNSUPPORTED_VISUAL_TYPES = {"network", "tree"}

# 封面/分隔类用整体居中布局；其余用"左上徽章标题 + 内容区"的学术版式（参考数字素养 PPT）
TITLE_LAYOUT_TYPES = {"title", "closing", "section_divider"}

# 这些 element 类型暂不支持，遇到则整页 fallback（保守，避免渲染出不完整的页）
SUPPORTED_ELEMENT_TYPES = {
    "heading", "subheading", "text", "quote",
    "icon_group", "stat_card", "flow_step", "comparison_panel",
    "activity_step", "image", "highlight_box", "badge", "label", "table",
}

_MAX_DELAY = 12


def _esc(text: Any) -> str:
    """HTML 转义，并把换行转成 <br>。"""
    return _html.escape(str(text or "")).replace("\n", "<br>")


def _delay_class(n: int) -> str:
    return f"d{min(n, _MAX_DELAY)}"


def render_slide(
    segment: Segment,
    slide_index: int = 0,
    available_image_keys: set[str] | None = None,
) -> str | None:
    """把一个 storyboard segment 渲染为 slide HTML；不支持则返回 None。"""
    vtype = str(segment.get("visual_type", ""))
    if vtype in UNSUPPORTED_VISUAL_TYPES:
        return None

    elements = segment.get("elements", [])
    if not isinstance(elements, list) or not elements:
        return None

    available_image_keys = available_image_keys or set()
    seg_id = segment.get("id", "")

    # 分离主标题：content 版式把标题放在左上徽章栏，封面版式则居中大标题
    heading = next(
        (e for e in elements if isinstance(e, dict) and e.get("type") == "heading"),
        None,
    )
    body_elems = [e for e in elements if e is not heading]

    blocks: list[tuple[str, str]] = []  # (etype, html)
    delay = 2  # d1 预留给标题
    for elem in body_elems:
        if not isinstance(elem, dict):
            return None
        etype = elem.get("type", "")
        if etype not in SUPPORTED_ELEMENT_TYPES:
            return None  # 含不支持元素，整页交回 LLM
        block = _render_element(elem, seg_id, delay, available_image_keys)
        if block is None:
            return None
        if block:  # 跳过空串（如无图可注入的 image）
            blocks.append((etype, block))
            delay += 1

    if not blocks and heading is None:
        return None

    active = " active" if slide_index == 0 else ""
    vtype_l = vtype  # already str

    # fullscreen 主题下 .slide 是 stretch/flex-start，且 .content-card 是全屏透明画布。
    # 容器用 position:absolute;inset:0 自己撑满，绕开 .slide 的 fullscreen flex 行为。
    if vtype_l in TITLE_LAYOUT_TYPES:
        # 封面/分隔：整体居中大标题
        parts = []
        if heading:
            parts.append(
                f'<h1 class="slide-title anim anim-anticipate-up d1" '
                f'style="margin:0;font-size:2.4em;">{_esc(heading.get("text"))}</h1>'
            )
        parts.extend(h for _, h in blocks)
        body = "\n      ".join(parts)
        return (
            f'<div class="slide{active}">\n'
            f'  <div style="position:absolute;inset:0;display:flex;'
            f'flex-direction:column;align-items:center;justify-content:center;'
            f'gap:20px;padding:48px 72px;box-sizing:border-box;text-align:center;'
            f'overflow:hidden;">\n'
            f'      {body}\n'
            f'  </div>\n'
            f'</div>'
        )

    # content 版式：左上徽章标题 + 分隔线 + 内容区（居中）
    title_bar = ""
    if heading:
        title_bar = (
            f'<div class="anim anim-left d1" style="display:flex;align-items:center;'
            f'flex-shrink:0;">'
            f'<span style="display:inline-flex;align-items:center;gap:13px;'
            f'padding:12px 30px;border-radius:12px;'
            f'background:linear-gradient(135deg,var(--primary),var(--secondary));'
            f'box-shadow:0 6px 18px var(--glow-primary);">'
            f'<span style="width:6px;height:1.25em;background:var(--accent);'
            f'border-radius:3px;"></span>'
            f'<span style="font-size:1.55em;font-weight:800;color:#fff;'
            f'font-family:var(--font-heading);letter-spacing:1px;">'
            f'{_esc(heading.get("text"))}</span></span></div>\n'
            f'      <div style="height:2px;margin:8px 0 0;flex-shrink:0;'
            f'background:linear-gradient(to right,var(--accent),var(--border) 40%,transparent);'
            f'"></div>'
        )
    body = _layout_content_area(blocks)
    return (
        f'<div class="slide{active}">\n'
        f'  <div style="position:absolute;inset:0;display:flex;'
        f'flex-direction:column;padding:36px 56px;box-sizing:border-box;'
        f'gap:14px;overflow:hidden;">\n'
        f'      {title_bar}\n'
        f'      <div style="flex:1;min-height:0;display:flex;width:100%;">\n'
        f'        <div class="t2v-content-box" style="flex:1;display:flex;'
        f'flex-direction:column;align-items:center;justify-content:space-evenly;'
        f'gap:20px;background:var(--card-bg);border:1px solid var(--card-border);'
        f'border-radius:24px;box-shadow:var(--card-shadow);'
        f'padding:38px 54px;overflow:hidden;text-align:center;">\n'
        f'          {body}\n'
        f'        </div>\n'
        f'      </div>\n'
        f'  </div>\n'
        f'</div>'
    )


def _layout_content_area(blocks: list[tuple[str, str]]) -> str:
    """决定内容区布局：图 + 非宽元素 → 左右分栏（图左文右）；否则垂直堆叠。

    含宽元素（对比面板/流程/表格/活动步骤，需整宽展示）时不分栏，避免被压窄。
    """
    # 三类元素：visual（图/示意图，做视觉重心）、wide（数据/流程，整宽独占）、
    # light（要点/金句/数字/说明，成组靠右）。布局：左图 + 右文成组 + 下方整宽数据，
    # 形成有重心、有结构、左对齐的版式，而非一条中线全居中。
    wide_types = {"comparison_panel", "table", "flow_step", "activity_step"}
    image_html = [h for t, h in blocks if t == "image" and "{{IMG_" in h]
    wide_html = [h for t, h in blocks if t in wide_types]
    light_html = [
        h for t, h in blocks
        if t not in wide_types and not (t == "image" and "{{IMG_" in h)
    ]

    parts: list[str] = []
    if image_html and light_html:
        # 左图（视觉重心，略宽）+ 右侧要点成组（左对齐）
        left = "\n".join(image_html)
        right = "\n".join(light_html)
        parts.append(
            '<div style="display:flex;gap:46px;align-items:center;width:100%;">'
            '<div style="flex:1.15;min-width:0;display:flex;flex-direction:column;'
            'gap:18px;align-items:center;justify-content:center;">'
            f'{left}</div>'
            '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
            'gap:15px;align-items:stretch;justify-content:center;text-align:left;">'
            f'{right}</div></div>'
        )
    elif image_html:
        parts.extend(image_html)
        parts.extend(light_html)
    else:
        parts.extend(light_html)
    # 数据 / 流程整宽独占一行
    parts.extend(wide_html)
    return "\n".join(parts)


def _render_element(
    elem: dict, seg_id: Any, delay: int, available_image_keys: set[str]
) -> str | None:
    """渲染单个 element 为框架类 HTML。返回 None=不支持，空串=跳过。"""
    etype = elem.get("type", "")
    d = _delay_class(delay)

    if etype == "heading":
        return (
            f'<h1 class="slide-title anim anim-anticipate-up {d}" '
            f'style="margin:0;">{_esc(elem.get("text"))}</h1>'
        )

    if etype == "subheading":
        return (
            f'<p class="anim anim-up {d}" style="margin:0;font-size:30px;'
            f'font-weight:600;color:var(--text-dim);">{_esc(elem.get("text"))}</p>'
        )

    if etype in ("text", "label"):
        return (
            f'<p class="anim anim-up {d}" style="margin:0;font-size:24px;'
            f'line-height:1.6;color:var(--text-dim);max-width:1100px;">'
            f'{_esc(elem.get("text"))}</p>'
        )

    if etype in ("quote", "highlight_box"):
        return (
            f'<div class="highlight-box anim anim-card {d}" '
            f'style="max-width:1000px;font-size:26px;">{_esc(elem.get("text"))}</div>'
        )

    if etype == "badge":
        return (
            f'<span class="badge primary anim anim-scale {d}">'
            f'{_esc(elem.get("text"))}</span>'
        )

    if etype == "icon_group":
        items = elem.get("items", []) or []
        if not items:
            return ""
        cards = "".join(
            f'<div style="display:flex;flex-direction:column;align-items:center;'
            f'gap:16px;min-width:200px;padding:30px 26px;border-radius:20px;'
            f'background:var(--card-bg);border:1px solid var(--card-border);'
            f'box-shadow:var(--card-shadow);">'
            f'<div style="width:66px;height:66px;border-radius:50%;display:flex;'
            f'align-items:center;justify-content:center;font-size:28px;font-weight:800;'
            f'color:#fff;background:linear-gradient(135deg,var(--primary),var(--secondary));'
            f'box-shadow:0 4px 14px var(--glow-primary);">{i + 1}</div>'
            f'<div style="font-size:24px;font-weight:700;color:var(--text);">'
            f'{_esc(it)}</div></div>'
            for i, it in enumerate(items)
        )
        return (
            f'<div class="anim anim-up {d}" style="display:flex;gap:28px;'
            f'justify-content:center;flex-wrap:wrap;">{cards}</div>'
        )

    if etype == "stat_card":
        return (
            f'<div class="anim anim-card {d}" '
            f'style="padding:22px 40px;border-radius:18px;text-align:center;'
            f'min-width:200px;background:var(--card-bg);'
            f'border:1px solid var(--card-border);box-shadow:var(--card-shadow);">'
            f'<div style="font-size:40px;font-weight:800;color:var(--gold);">'
            f'{_esc(elem.get("value"))}</div>'
            f'<div style="font-size:20px;color:var(--text-dim);margin-top:6px;">'
            f'{_esc(elem.get("label"))}</div></div>'
        )

    if etype in ("flow_step", "activity_step"):
        steps = elem.get("steps", []) or []
        if not steps:
            return ""
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
                f'<div style="font-size:23px;font-weight:700;color:var(--text);">'
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

    if etype == "comparison_panel":
        items = elem.get("items", []) or []
        if len(items) < 2:
            return ""
        left, right = items[0], items[1]

        def _panel(item: dict, accent: str) -> str:
            return (
                f'<div style="flex:1;padding:28px 34px;border-radius:18px;'
                f'background:var(--card-bg);border:1px solid {accent};'
                f'box-shadow:var(--card-shadow);text-align:center;">'
                f'<div style="font-size:27px;font-weight:800;color:{accent};'
                f'margin-bottom:14px;">{_esc(item.get("title"))}</div>'
                f'<div style="font-size:22px;line-height:1.6;color:var(--text-dim);">'
                f'{_esc(item.get("content"))}</div></div>'
            )

        return (
            f'<div class="anim anim-card {d}" style="display:flex;align-items:stretch;'
            f'gap:0;max-width:1150px;width:100%;">'
            f'{_panel(left, "var(--primary)")}'
            f'<div style="display:flex;align-items:center;justify-content:center;'
            f'width:64px;flex-shrink:0;font-size:26px;font-weight:900;'
            f'color:var(--accent);">VS</div>'
            f'{_panel(right, "var(--secondary)")}</div>'
        )

    if etype == "table":
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

    if etype == "image":
        elem_id = elem.get("id", "")
        key = f"{seg_id}:{elem_id}"
        # 只有确实有图可注入（教材原图 / 已生成 AI 图）时才放占位，避免 {{IMG}} 残留
        if elem_id and key in available_image_keys:
            return (
                f'<div class="anim anim-card {d}" '
                f'style="max-width:620px;max-height:45vh;display:flex;'
                f'align-items:center;justify-content:center;overflow:hidden;">'
                f'{{{{IMG_{elem_id}}}}}</div>'
            )
        # 无图可注入：渲染一个带描述的占位卡，保持版面不空
        desc = elem.get("description", "")
        if not desc:
            return ""
        return (
            f'<div class="anim anim-card {d}" '
            f'style="max-width:760px;padding:18px 28px;border-radius:16px;'
            f'background:rgba(127,127,127,0.08);font-size:20px;'
            f'color:var(--text-dim);">🖼️ {_esc(desc)}</div>'
        )

    return None
