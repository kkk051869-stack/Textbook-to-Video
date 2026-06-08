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

from textbook2video.variants import (
    pick_group_variant_html,
    pick_variant_html,
)
from textbook2video.variants.layouts import compose_image_text, light_weight

Segment = dict[str, Any]

# 这些 visual_type 的布局较特殊（节点/连线等），暂不支持，交回 LLM 生成
UNSUPPORTED_VISUAL_TYPES = {"network", "tree"}

# 封面/分隔类用整体居中布局；其余用"左上徽章标题 + 内容区"的学术版式（参考数字素养 PPT）
TITLE_LAYOUT_TYPES = {"title", "closing", "section_divider"}

# 这些 element 类型暂不支持，遇到则整页 fallback（保守，避免渲染出不完整的页）
SUPPORTED_ELEMENT_TYPES = {
    "heading", "subheading", "text", "quote",
    "icon_group", "flow_step", "comparison_panel",
    "activity_step", "image", "highlight_box", "badge", "label", "table",
}

_MAX_DELAY = 12


def _esc(text: Any) -> str:
    """HTML 转义，并把换行转成 <br>。"""
    return _html.escape(str(text or "")).replace("\n", "<br>")


def _fs(px: int, floor_ratio: float = 0.78) -> str:
    """流式字号 clamp：上限=px（保持 1920 现状不变），首选=等效 vw（1920 下 1vw=19.2px），
    下限≈px×floor_ratio。小视口/窄容器下优雅缩小，避免溢出；大屏维持原观感。
    见 docs/research/adaptive-slide-layout.md §4.2(d)。"""
    vw = round(px / 19.2, 2)
    floor = max(12, int(px * floor_ratio))
    return f"clamp({floor}px,{vw}vw,{px}px)"


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

    # 分离主标题 + 副标题：content 版式把它们都钉在顶部 title_bar 区域
    # （副标题被放进居中 content-box 时会被挤到 slide 中部，不符合"小节副题"语义）
    heading = next(
        (e for e in elements if isinstance(e, dict) and e.get("type") == "heading"),
        None,
    )
    subheading = next(
        (e for e in elements if isinstance(e, dict) and e.get("type") == "subheading"),
        None,
    )
    body_elems = [e for e in elements if e is not heading and e is not subheading]

    blocks: list[tuple[str, str]] = []  # (etype, html)
    delay = 3 if subheading else 2  # d1 留给标题，d2 留给副标题（若有）
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

    # content 版式：title_bar（5 variants 按 seg_id 轮换）+ 内容区（居中）
    # 副标题不放在外部 title_bar，而是放在 content-box 内顶部居中。
    title_bar = ""
    if heading:
        # heading variants 由 variants/heading.py 提供，pick_variant_html 选其一
        title_bar = pick_variant_html(
            "heading", heading, seg_id, "d1", available_image_keys,
        ) or ""
    # 副标题：将在 fit-scale 内的顶部居中独立成行（剩余空间留给主内容居中）。
    subheading_html = ""
    if subheading:
        subheading_html = (
            f'<p class="anim anim-up d2" style="margin:0;font-size:{_fs(26)};'
            f'font-weight:600;color:var(--text-dim);flex-shrink:0;text-align:center;'
            f'align-self:center;letter-spacing:0.5px;">'
            f'{_esc(subheading.get("text"))}</p>'
        )
    body, row_count = _layout_content_area(blocks, seg_id)
    # 元素少 → 大间距让画面呼吸；元素多 → 紧凑均衡分布。
    # 注：row_count 是"顶层块数"（图文分栏算 1 行），不是元素总数。
    if row_count <= 2:
        cb_justify, cb_gap = "center", "64px"
    elif row_count == 3:
        cb_justify, cb_gap = "center", "48px"
    elif row_count == 4:
        cb_justify, cb_gap = "center", "36px"
    else:
        cb_justify, cb_gap = "space-evenly", "24px"
    return (
        f'<div class="slide{active}">\n'
        f'  <div style="position:absolute;inset:0;display:flex;'
        f'flex-direction:column;padding:36px 56px;box-sizing:border-box;'
        f'gap:14px;overflow:hidden;">\n'
        f'      {title_bar}\n'
        f'      <div style="flex:1;min-height:0;display:flex;width:100%;">\n'
        # content-box 作为溢出测量容器（居中 .fit-scale）；.fit-scale 承载排版+padding，
        # 内容超高时由运行时脚本对 .fit-scale 整体等比缩小塞进框（保丰富、不裁切）。
        # 见 docs/research/adaptive-slide-layout.md §4.3。
        f'        <div class="t2v-content-box" style="flex:1;display:flex;'
        f'align-items:center;justify-content:center;overflow:hidden;'
        f'background:var(--card-bg);border:1px solid var(--card-border);'
        f'border-radius:24px;box-shadow:var(--card-shadow);text-align:center;">\n'
        f'          <div class="fit-scale" style="width:100%;box-sizing:border-box;'
        f'padding:38px 54px;display:flex;flex-direction:column;align-items:center;'
        f'justify-content:{("flex-start" if subheading_html else cb_justify)};'
        f'gap:{cb_gap};transform-origin:center;">\n'
        + (
            # subheading 在 content-box 顶部居中，剩余空间留给主内容
            f'            {subheading_html}\n'
            f'            <div style="width:100%;flex:1;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:{cb_justify};gap:{cb_gap};">\n'
            f'              {body}\n'
            f'            </div>\n'
            if subheading_html else
            f'            {body}\n'
        ) +
        f'          </div>\n'
        f'        </div>\n'
        f'      </div>\n'
        f'  </div>\n'
        f'</div>'
    )


def _group_inline_cards(
    light_blocks: list[tuple[str, str]], seg_id: Any = "",
) -> list[str]:
    """合并相邻同类轻元素，让外层间距规则按"概念块"而非"元素行"分发。

    - 连续 badge → 横排（badge_row 2 套 variants 按 seg_id 选）
    - 连续 text/label → 段落组（text_group 3 套 variants 按 seg_id 选）

    单个元素不合并、直接透传，保留 _render_element 自己的 variant。
    """
    inline_types = {"badge"}
    para_types = {"text", "label"}
    out: list[str] = []
    i, n = 0, len(light_blocks)
    while i < n:
        t, h = light_blocks[i]
        if t in inline_types:
            run = [h]
            i += 1
            while i < n and light_blocks[i][0] in inline_types:
                run.append(light_blocks[i][1])
                i += 1
            if len(run) >= 2:
                out.append(pick_group_variant_html("badge_row", run, seg_id))
            else:
                out.append(run[0])
        elif t in para_types:
            run = [h]
            i += 1
            while i < n and light_blocks[i][0] in para_types:
                run.append(light_blocks[i][1])
                i += 1
            if len(run) >= 2:
                out.append(pick_group_variant_html("text_group", run, seg_id))
            else:
                out.append(run[0])
        else:
            out.append(h)
            i += 1
    return out


# 图文构图与 _LIGHT_WEIGHT 已迁到 variants/layouts.py（compose_image_text / light_weight）


def _layout_content_area(
    blocks: list[tuple[str, str]], seg_id: Any = "",
) -> tuple[str, int]:
    """决定内容区布局：图 + 非宽元素 → 左右分栏（图左文右）；否则垂直堆叠。

    含宽元素（对比面板/流程/表格/活动步骤，需整宽展示）时不分栏，避免被压窄。

    返回 (html, row_count)：row_count 是内容区顶层行数，供 render_slide 决定
    content-box 的 justify-content——行少时居中成组（避免 space-evenly 把少量
    元素拉散成空旷），行多时均衡分布。见 docs/research/adaptive-slide-layout.md。
    """
    # 三类元素：
    #   visual（图）— 视觉重心
    #   wide（数据/流程）— 整宽独占
    #   light（要点/金句/说明）— 成组靠右
    # 布局：[左图 + 右文成组] → [下方整宽数据]
    # subheading 已在 render_slide 中提到 title_bar 置顶，不进此处的居中内容区。
    wide_types = {"comparison_panel", "table", "flow_step", "activity_step"}
    image_html = [h for t, h in blocks if t == "image" and "{{IMG_" in h]
    wide_html = [h for t, h in blocks if t in wide_types]
    light_blocks = [
        (t, h) for t, h in blocks
        if t not in wide_types
        and not (t == "image" and "{{IMG_" in h)
    ]
    # 重量在合并前计算（多 text 合并成 1 段后会丢粒度）；n 用合并后 light_html
    weight = light_weight([t for t, _ in light_blocks])
    light_html = _group_inline_cards(light_blocks, seg_id)

    parts: list[str] = []
    if image_html and light_html:
        # 图 + 轻元素：按 variants/layouts.py 内"密度 + 重量"自动选 3 种版式
        parts.append(
            compose_image_text(image_html, light_html, weight, seg_id)
        )
    elif image_html:
        parts.extend(image_html)
        parts.extend(light_html)
    else:
        parts.extend(light_html)
    # 数据 / 流程整宽独占一行
    parts.extend(wide_html)
    return "\n".join(parts), len(parts)


def _render_element(
    elem: dict, seg_id: Any, delay: int, available_image_keys: set[str]
) -> str | None:
    """渲染单个 element 为框架类 HTML。返回 None=不支持，空串=跳过。

    优先委派给 `template_variants.pick_variant_html`（变体库，每个 etype 多个版式按 seg_id
    稳定轮换）；仅 heading 仍走专用版式（在 render_slide 中处理 title bar）。
    """
    etype = elem.get("type", "")
    d = _delay_class(delay)

    if etype == "heading":
        # heading 不进变体库——render_slide 已专门处理 title bar
        return (
            f'<h1 class="slide-title anim anim-anticipate-up {d}" '
            f'style="margin:0;">{_esc(elem.get("text"))}</h1>'
        )

    # 变体库覆盖的元素类型：subheading/text/label/quote/highlight_box/badge/
    # icon_group/flow_step/activity_step/comparison_panel/table/image
    html = pick_variant_html(etype, elem, seg_id, d, available_image_keys)
    if html is not None:
        return html

    # 变体库未涵盖的 etype
    return None
