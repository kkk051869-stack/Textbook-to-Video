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

# 这些 element 类型暂不支持，遇到则整页 fallback（保守，避免渲染出不完整的页）
SUPPORTED_ELEMENT_TYPES = {
    "heading", "subheading", "text", "quote",
    "icon_group", "stat_card", "flow_step", "comparison_panel",
    "activity_step", "image", "highlight_box", "badge", "label",
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

    blocks: list[str] = []
    delay = 1
    for elem in elements:
        if not isinstance(elem, dict):
            return None
        etype = elem.get("type", "")
        if etype not in SUPPORTED_ELEMENT_TYPES:
            return None  # 含不支持元素，整页交回 LLM
        block = _render_element(elem, seg_id, delay, available_image_keys)
        if block is None:
            return None
        if block:  # 跳过空串（如无图可注入的 image）
            blocks.append(block)
            delay += 1

    if not blocks:
        return None

    active = " active" if slide_index == 0 else ""
    body = "\n      ".join(blocks)
    # fullscreen 主题下 .slide 是 align-items:stretch / justify-content:flex-start（不居中），
    # 且 .content-card 被改成撑满全屏的透明画布。这里用 position:absolute;inset:0 让容器
    # 自己撑满 .slide 并居中，绕开 .slide 的 fullscreen flex 行为；style 带 position:absolute
    # 也能避开 fullscreen 给 .slide>div 强加 width:100% 的规则。
    return (
        f'<div class="slide{active}">\n'
        f'  <div style="position:absolute;inset:0;display:flex;'
        f'flex-direction:column;align-items:center;justify-content:center;'
        f'gap:18px;padding:40px 64px;box-sizing:border-box;text-align:center;'
        f'overflow:hidden;">\n'
        f'      {body}\n'
        f'  </div>\n'
        f'</div>'
    )


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
            f'<div class="icon-card" style="min-width:180px;">'
            f'<div class="emoji-circle" style="font-size:28px;font-weight:800;'
            f'color:var(--primary);">{i + 1}</div>'
            f'<div class="card-label">{_esc(it)}</div></div>'
            for i, it in enumerate(items)
        )
        return (
            f'<div class="anim anim-up {d}" style="display:flex;gap:24px;'
            f'justify-content:center;flex-wrap:wrap;">{cards}</div>'
        )

    if etype == "stat_card":
        return (
            f'<div class="anim anim-card {d}" '
            f'style="padding:22px 40px;border-radius:18px;text-align:center;'
            f'min-width:200px;background:rgba(127,127,127,0.06);'
            f'box-shadow:0 4px 16px rgba(0,0,0,0.06);">'
            f'<div style="font-size:40px;font-weight:800;color:var(--primary);">'
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
                f'<div class="flow-step"><div class="step-number">{i + 1}</div>'
                f'<div class="step-content">{_esc(step)}</div></div>'
            )
            if i < len(steps) - 1:
                parts.append(
                    '<div style="font-size:28px;color:var(--accent);'
                    'align-self:center;">→</div>'
                )
        return (
            f'<div class="anim anim-up {d}" style="display:flex;gap:18px;'
            f'justify-content:center;align-items:center;flex-wrap:wrap;">'
            f'{"".join(parts)}</div>'
        )

    if etype == "comparison_panel":
        items = elem.get("items", []) or []
        if len(items) < 2:
            return ""
        left, right = items[0], items[1]

        def _panel(side: str, item: dict) -> str:
            return (
                f'<div class="panel-{side}">'
                f'<div style="font-size:26px;font-weight:800;color:var(--text);'
                f'margin-bottom:12px;">{_esc(item.get("title"))}</div>'
                f'<div style="font-size:22px;line-height:1.5;color:var(--text-dim);">'
                f'{_esc(item.get("content"))}</div></div>'
            )

        return (
            f'<div class="comparison-panel anim anim-card {d}" '
            f'style="max-width:1100px;">'
            f'{_panel("left", left)}'
            f'<div class="vs-badge">VS</div>'
            f'{_panel("right", right)}</div>'
        )

    if etype == "image":
        elem_id = elem.get("id", "")
        key = f"{seg_id}:{elem_id}"
        # 只有确实有图可注入（教材原图 / 已生成 AI 图）时才放占位，避免 {{IMG}} 残留
        if elem_id and key in available_image_keys:
            return (
                f'<div class="anim anim-card {d}" '
                f'style="max-width:620px;max-height:300px;display:flex;'
                f'justify-content:center;">{{{{IMG_{elem_id}}}}}</div>'
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
