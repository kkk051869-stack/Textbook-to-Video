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

from textbook2video.template_variants import (
    pick_group_variant_html,
    pick_variant_html,
)

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

    # content 版式：左上徽章标题 + 分隔线 + 副标题（如有）+ 内容区（居中）
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
    # 副标题：紧贴 title_bar 之后、独立成行、flex-shrink:0 保持置顶（不进 content-box 居中）
    if subheading:
        sub_html = (
            f'<p class="anim anim-up d2" style="margin:6px 0 0;font-size:{_fs(26)};'
            f'font-weight:600;color:var(--text-dim);flex-shrink:0;text-align:left;">'
            f'{_esc(subheading.get("text"))}</p>'
        )
        title_bar = (title_bar + "\n      " + sub_html) if title_bar else sub_html
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
        f'justify-content:{cb_justify};gap:{cb_gap};transform-origin:center;">\n'
        f'            {body}\n'
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


# 轻元素的视觉重量（用于估算分栏右侧填充度）。
# 比 checks.py::_ELEMENT_WEIGHT 更细——这里关注"在右窄栏里占多少纵向"。
_LIGHT_WEIGHT: dict[str, float] = {
    "text": 1.0,
    "label": 0.5,
    "quote": 1.3,
    "highlight_box": 1.3,
    "badge": 0.4,
    "icon_group": 1.8,  # 卡片网格，N 项视为整体重
    # subheading 已被提到分栏上方独立 strip，不进光重
}


def _light_weight(types: list[str]) -> float:
    return sum(_LIGHT_WEIGHT.get(t, 1.0) for t in types)


def _compose_image_text(
    image_html: list[str], light_html: list[str], weight: float,
    seg_id: Any,
) -> str:
    """图 + 轻元素的构图——按"轻元素数 + 视觉重量"自动选版式：

      n ≤2 且 重量 <3.5      → 经典图左文右
      n = 3 或 重量 3.5-5.5  → 图左文右 + 末位元素横跨底栏
      n ≥4 或 重量 ≥5.5     → 图顶 + 全宽文字下方

    重量来自 _LIGHT_WEIGHT（text 1 / quote 1.3 / icon_group 1.8 等）。
    """
    n = len(light_html)
    w = weight

    def _gap(k: int) -> str:
        return "36px" if k <= 2 else "28px" if k == 3 else "22px" if k == 4 else "16px"

    if n >= 4 or w >= 5.5:
        # 很满 → 图顶 + 文居中下（让文字拿满 1100 宽）
        top = "\n".join(image_html)
        bot = "\n".join(light_html)
        return (
            '<div style="display:flex;flex-direction:column;gap:28px;'
            'align-items:center;width:100%;">'
            f'<div style="display:flex;justify-content:center;align-items:center;'
            f'width:100%;max-width:760px;">{top}</div>'
            f'<div style="display:flex;flex-direction:column;gap:{_gap(n)};'
            f'align-items:center;justify-content:center;width:100%;max-width:1100px;'
            f'text-align:center;">{bot}</div>'
            '</div>'
        )

    if n >= 3 or w >= 3.5:
        # 比较满 → 图左文右 + 末位元素横跨底栏
        right_top = light_html[:-1]
        spanning = light_html[-1]
        left = "\n".join(image_html)
        right_join = "\n".join(right_top)
        return (
            '<div style="display:flex;flex-direction:column;gap:24px;width:100%;">'
            '<div style="display:flex;gap:46px;align-items:center;width:100%;">'
            '<div style="flex:1.15;min-width:0;display:flex;flex-direction:column;'
            'gap:18px;align-items:center;justify-content:center;">'
            f'{left}</div>'
            '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
            f'gap:{_gap(len(right_top))};align-items:stretch;justify-content:center;'
            f'text-align:left;">{right_join}</div></div>'
            f'<div style="width:100%;display:flex;justify-content:center;'
            f'align-items:center;">{spanning}</div>'
            '</div>'
        )

    # ≤3：经典图左文右
    left = "\n".join(image_html)
    right = "\n".join(light_html)
    return (
        '<div style="display:flex;gap:46px;align-items:center;width:100%;">'
        '<div style="flex:1.15;min-width:0;display:flex;flex-direction:column;'
        'gap:18px;align-items:center;justify-content:center;">'
        f'{left}</div>'
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;'
        f'gap:{_gap(n)};align-items:stretch;justify-content:center;text-align:left;">'
        f'{right}</div></div>'
    )


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
    light_weight = _light_weight([t for t, _ in light_blocks])
    light_html = _group_inline_cards(light_blocks, seg_id)

    parts: list[str] = []
    if image_html and light_html:
        # 图 + 轻元素：按 _compose_image_text 内"密度 + 重量"自动选 4 种版式
        parts.append(
            _compose_image_text(image_html, light_html, light_weight, seg_id)
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
