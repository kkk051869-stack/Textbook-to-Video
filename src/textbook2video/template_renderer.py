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

from __future__ import annotations

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
    "focus_box", "callout", "quiz_card",
}

_MAX_DELAY = 12
_OVERLAY_TYPES = {"focus_box", "callout"}
_WIDE_TYPES = {"comparison_panel", "table", "flow_step", "activity_step", "quiz_card"}
_MAX_BODY_TYPES = 3
_COVER_LAYOUTS = {"concept", "hub", "timeline", "hero"}


def _esc(text: Any) -> str:
    """HTML 转义，并把换行转成 <br>。"""
    return _html.escape(str(text or "")).replace("\n", "<br>")


def _fs(px: int, floor_ratio: float = 0.78) -> str:
    """流式字号 clamp：上限=px（保持 1920 现状不变），首选=等效 vw（1920 下 1vw=19.2px），
    下限≈px×floor_ratio。小视口/窄容器下优雅缩小，避免溢出；大屏维持原观感。
    见 docs/研究/自适应页面布局方案.md §4.2(d)。"""
    vw = round(px / 19.2, 2)
    floor = max(12, int(px * floor_ratio))
    return f"clamp({floor}px,{vw}vw,{px}px)"


def _cover_layout(segment: Segment, title: str) -> str:
    """Choose a stable cover composition; explicit storyboard intent wins."""
    explicit = str(segment.get("cover_layout") or "").lower()
    if explicit in _COVER_LAYOUTS:
        return explicit
    if any(word in title for word in ("\u786c\u4ef6", "\u7ec4\u6210", "\u7ed3\u6784")):
        return "hub"
    if any(word in title for word in ("\u5386\u53f2", "\u53d1\u5c55", "\u6f14\u8fdb")):
        return "timeline"
    if any(word in title for word in ("\u4eba\u7269", "\u4f20\u5947", "\u540d\u4eba")):
        return "hero"
    return "concept"


def _render_title_slide(
    heading: dict | None,
    subheading: dict | None,
    elements: list[dict],
    active: str,
    cover_layout: str,
) -> str:
    """Render a sparse opening slide around one lesson topic and a hub diagram."""
    title = _esc((heading or {}).get("text"))
    eyebrow = _esc((subheading or {}).get("text"))
    icon_group = next((e for e in elements if e.get("type") == "icon_group"), None)
    items = list((icon_group or {}).get("items") or [])[:6]
    node_list = [
        f'<span style="padding:10px 18px;border:1px solid var(--card-border);border-radius:6px;'
        f'background:rgba(255,255,255,0.035);font-size:{_fs(20)};font-weight:650;color:var(--text);">'
        f'{_esc(item)}</span>'
        for item in items
    ]
    visual = ''
    if cover_layout == "hub" and node_list:
        upper = "".join(node_list[:3])
        lower = "".join(node_list[3:])
        visual = (
            '<div class="anim anim-up d3" style="display:flex;flex-direction:column;gap:20px;align-items:center;">'
            f'<div style="display:flex;gap:28px;justify-content:center;flex-wrap:wrap;">{upper}</div>'
            '<div aria-hidden="true" style="width:132px;height:132px;border:2px solid var(--accent);border-radius:50%;'
            'background:rgba(255,255,255,0.045);box-shadow:0 0 30px var(--glow-primary);"></div>'
            f'<div style="display:flex;gap:28px;justify-content:center;flex-wrap:wrap;">{lower}</div>'
            '</div>'
        )
    elif cover_layout == "timeline" and node_list:
        visual = (
            '<div class="anim anim-up d3" style="display:flex;align-items:center;gap:0;width:min(980px,100%);">'
            + ''.join(
                f'<div style="flex:1;min-width:0;text-align:center;"><div style="width:12px;height:12px;margin:0 auto 14px;'
                f'border-radius:50%;background:var(--accent);box-shadow:0 0 14px var(--glow-primary);"></div>{node}</div>'
                for node in node_list[:5]
            )
            + '</div>'
        )
    elif cover_layout == "concept":
        visual = '<div class="anim anim-up d3" aria-hidden="true" style="width:136px;height:3px;background:var(--accent);"></div>'
    elif cover_layout == "hero":
        visual = ('<div class="anim anim-up d3" aria-hidden="true" style="display:flex;gap:14px;align-items:center;">'
                  '<span style="width:72px;height:2px;background:var(--accent);"></span>'
                  '<span style="width:12px;height:12px;border:2px solid var(--accent);transform:rotate(45deg);"></span>'
                  '<span style="width:72px;height:2px;background:var(--accent);"></span></div>')
    return (
        f'<div class="slide{active}">\n'
        '  <div style="position:absolute;inset:0;display:flex;flex-direction:column;'
        'align-items:center;justify-content:center;gap:26px;padding:56px 72px;box-sizing:border-box;'
        'text-align:center;overflow:hidden;">\n'
        f'    <p class="anim anim-up d1" style="margin:0;color:var(--accent);font-size:{_fs(18)};'
        f'font-weight:700;letter-spacing:1px;">{eyebrow}</p>\n'
        f'    <h1 class="slide-title anim anim-anticipate-up d2" style="margin:0;font-size:clamp(42px,3.3vw,64px);'
        f'line-height:1.2;">{title}</h1>\n'
        f'    {visual}\n'
        '  </div>\n'
        '</div>'
    )


def _delay_class(n: int) -> str:
    return f"d{min(n, _MAX_DELAY)}"


def render_slide(
    segment: Segment,
    slide_index: int = 0,
    available_image_keys: set[str] | None = None,
    theme_preferences: dict[str, list[str]] | None = None,
) -> str | None:
    """把一个 storyboard segment 渲染为 slide HTML；不支持则返回 None。

    `theme_preferences`：主题的 preferred_variants 字段，形如
        {"icon_group": ["minimal_squares", "bordered_minimal"], ...}
    传入后 pick_variant_html 在子集内 hash 选；为空 / 全无匹配时走全库轮换。
    """
    pref = theme_preferences or {}
    def _pref(etype: str) -> list[str] | None:
        return pref.get(etype)
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

    # 没有真实教材图、AI 图或 SVG 时，图片描述卡及其 overlay 只会制造假视觉重心。
    # 直接跳过整组，让无图 HTML 测试退化成干净的文字/信息图页面。
    unavailable_images = {
        str(e.get("id") or "")
        for e in body_elems
        if isinstance(e, dict)
        and e.get("type") == "image"
        and f"{seg_id}:{e.get('id') or ''}" not in available_image_keys
    }
    if unavailable_images:
        body_elems = [
            e for e in body_elems
            if not (
                isinstance(e, dict)
                and (
                    (e.get("type") == "image" and str(e.get("id") or "") in unavailable_images)
                    or (
                        e.get("type") in _OVERLAY_TYPES
                        and str(e.get("target") or e.get("target_image") or e.get("image_id") or "")
                        in unavailable_images
                    )
                )
            )
        ]

    body_elems = _compact_body_elements(body_elems)
    overlays_by_image = _collect_image_overlays(body_elems)
    overlay_ids = {id(elem) for items in overlays_by_image.values() for elem in items}

    blocks: list[tuple[str, str]] = []  # (etype, html)
    delay = 3 if subheading else 2  # d1 留给标题，d2 留给副标题（若有）
    for elem in body_elems:
        if not isinstance(elem, dict):
            return None
        if id(elem) in overlay_ids:
            continue
        etype = elem.get("type", "")
        if etype not in SUPPORTED_ELEMENT_TYPES:
            return None  # 含不支持元素，整页交回 LLM
        block = _render_element(
            elem,
            seg_id,
            delay,
            available_image_keys,
            pref,
            overlays=overlays_by_image.get(str(elem.get("id") or "")),
        )
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
        if vtype_l == "title":
            return _render_title_slide(
                heading, subheading, elements, active,
                _cover_layout(segment, str((heading or {}).get("text") or "")),
            )
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
        # heading 锁定主题 preferred 的第 0 个版式——整片标题保持一致，不随 seg_id 轮换。
        title_bar = pick_variant_html(
            "heading", heading, seg_id, "d1", available_image_keys,
            preferred=_pref("heading"), lock_first=True,
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
        # content-box 作为溢出测量容器（flex:1 占满 title_bar 以下空间，但无卡片外壳——
        # 不画 bg/border/shadow）；.fit-scale 是其普通子元素，按内容自然高度排版，
        # 内容超高时由 slide-controller 的 scale-to-fit 对 .fit-scale 整体等比缩小塞进框
        # （保丰富、不裁切）。见 docs/研究/自适应页面布局方案.md §4.3。
        # 关键：.fit-scale 不能是 flex:1，否则 offsetHeight 被 flex 钉死，缩放探测失效。
        f'      <div class="t2v-content-box" style="flex:1;min-height:0;width:100%;'
        f'display:flex;flex-direction:column;align-items:center;justify-content:center;'
        f'overflow:hidden;">\n'
        f'        <div class="fit-scale" style="width:100%;box-sizing:border-box;'
        f'padding:38px 54px;display:flex;flex-direction:column;align-items:center;'
        f'justify-content:{("flex-start" if subheading_html else cb_justify)};'
        f'gap:{cb_gap};transform-origin:center;">\n'
        + (
            # subheading 顶部居中，剩余空间留给主内容
            f'          {subheading_html}\n'
            f'          <div style="width:100%;flex:1;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:{cb_justify};gap:{cb_gap};">\n'
            f'            {body}\n'
            f'          </div>\n'
            if subheading_html else
            f'          {body}\n'
        ) +
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


def _compact_body_elements(elements: list[dict]) -> list[dict]:
    """Keep one title class plus at most three body element types.

    Image annotations are treated as part of their target image.  When a fourth
    body type carries unique wording, preserve that wording in a compact text
    block instead of silently dropping the teaching point.
    """
    valid = [e for e in elements if isinstance(e, dict)]
    types = [str(e.get("type") or "") for e in valid if e.get("type") not in _OVERLAY_TYPES]
    distinct_types = list(dict.fromkeys(types))
    type_overloaded = len(distinct_types) > _MAX_BODY_TYPES
    overloaded = len(valid) > 5 or type_overloaded
    has_table = "table" in types
    has_comparison = "comparison_panel" in types
    has_structured_steps = bool({"flow_step", "activity_step"}.intersection(types))
    if not overloaded:
        return valid

    allowed_types = set(distinct_types)
    if type_overloaded:
        # Reserve one of the three body types for readable prose.  Keep the
        # first main visual and first compatible supporting type in storyboard
        # order; later widget types are summarized into text below.
        allowed_types = {"text"}
        hero_selected = False
        for etype in distinct_types:
            if etype == "text":
                continue
            if has_table and etype in {"icon_group", "label"}:
                continue
            if (has_comparison or has_structured_steps) and etype == "icon_group":
                continue
            if etype in _WIDE_TYPES and hero_selected:
                continue
            allowed_types.add(etype)
            hero_selected = hero_selected or etype in _WIDE_TYPES
            if len(allowed_types) >= _MAX_BODY_TYPES:
                break

    limits = {"text": 2, "quote": 1, "icon_group": 1, "label": 2}
    if has_table:
        limits.update({"icon_group": 0, "label": 0})
    elif has_comparison or has_structured_steps:
        limits["icon_group"] = 0

    kept: list[dict] = []
    counts: dict[str, int] = {}
    body_types: set[str] = set()
    hero_kept = False
    type_dropped: list[dict] = []
    for elem in valid:
        etype = str(elem.get("type") or "")
        if etype in _OVERLAY_TYPES:
            kept.append(elem)
            continue
        if etype not in allowed_types:
            type_dropped.append(elem)
            continue
        if etype in _WIDE_TYPES:
            if hero_kept:
                continue
            hero_kept = True
        limit = limits.get(etype, 1)
        if counts.get(etype, 0) >= limit:
            continue
        if etype not in body_types and len(body_types) >= _MAX_BODY_TYPES:
            continue
        if len([e for e in kept if e.get("type") not in _OVERLAY_TYPES]) >= 5:
            continue
        kept.append(elem)
        counts[etype] = counts.get(etype, 0) + 1
        body_types.add(etype)

    summary_candidates = [
        elem for elem in type_dropped
        if not (
            (has_table and elem.get("type") in {"icon_group", "label"})
            or (
                (has_comparison or has_structured_steps)
                and elem.get("type") == "icon_group"
            )
        )
    ]
    summary = _summarize_elements_as_text(summary_candidates)
    if summary:
        text_indexes = [i for i, elem in enumerate(kept) if elem.get("type") == "text"]
        if text_indexes:
            index = text_indexes[-1]
            merged = dict(kept[index])
            merged["text"] = f'{str(merged.get("text") or "").rstrip()}\n{summary}'
            kept[index] = merged
        else:
            kept.append({"type": "text", "id": "compacted-summary", "text": summary})
    return kept


def _summarize_elements_as_text(elements: list[dict], max_chars: int = 220) -> str:
    """Extract concise visible wording from widget types removed by compaction."""
    fragments: list[str] = []

    def add(value: Any) -> None:
        text = " ".join(str(value or "").split())
        if text and text not in fragments:
            fragments.append(text)

    for elem in elements:
        if elem.get("type") in {"badge", "label"}:
            continue
        for key in ("text", "title", "content", "description"):
            add(elem.get(key))
        for key in ("items", "steps", "rows"):
            values = elem.get(key) or []
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, dict):
                    parts = [value.get(k) for k in ("title", "text", "content", "description")]
                    add("：".join(str(part) for part in parts if part))
                elif isinstance(value, (list, tuple)):
                    add(" / ".join(str(part) for part in value if part is not None))
                else:
                    add(value)

    summary = "；".join(fragments)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip("；，、 ") + "…"
    return f"补充说明：{summary}" if summary else ""


# 图文构图与 _LIGHT_WEIGHT 已迁到 variants/layouts.py（compose_image_text / light_weight）


def _layout_content_area(
    blocks: list[tuple[str, str]], seg_id: Any = "",
) -> tuple[str, int]:
    """决定内容区布局：图 + 非宽元素 → 左右分栏（图左文右）；否则垂直堆叠。

    含宽元素（对比面板/流程/表格/活动步骤，需整宽展示）时不分栏，避免被压窄。

    返回 (html, row_count)：row_count 是内容区顶层行数，供 render_slide 决定
    content-box 的 justify-content——行少时居中成组（避免 space-evenly 把少量
    元素拉散成空旷），行多时均衡分布。见 docs/研究/自适应页面布局方案.md。
    """
    # 三类元素：
    #   visual（图）— 视觉重心
    #   wide（数据/流程）— 整宽独占
    #   light（要点/金句/说明）— 成组靠右
    # 布局：[左图 + 右文成组] → [下方整宽数据]
    # subheading 已在 render_slide 中提到 title_bar 置顶，不进此处的居中内容区。
    wide_types = _WIDE_TYPES
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
    elem: dict, seg_id: Any, delay: int, available_image_keys: set[str],
    theme_preferences: dict[str, list[str]] | None = None,
    *,
    overlays: list[dict] | None = None,
) -> str | None:
    """渲染单个 element 为框架类 HTML。返回 None=不支持，空串=跳过。

    优先委派给 `variants.pick_variant_html`（变体库，每个 etype 多个版式按 seg_id
    稳定轮换；theme_preferences 限定时在子集内选）；仅 heading 在封面布局走专用版式。
    """
    etype = elem.get("type", "")
    d = _delay_class(delay)
    pref = (theme_preferences or {}).get(etype)

    if etype == "heading":
        # heading 在封面 / 分隔布局这里走旧实现；content 版式的 heading 由 render_slide
        # 的 title_bar 分支用 pick_variant_html 选 5 套变体之一。
        return (
            f'<h1 class="slide-title anim anim-anticipate-up {d}" '
            f'style="margin:0;">{_esc(elem.get("text"))}</h1>'
        )

    if etype == "quiz_card":
        return _render_quiz_card(elem, d)

    if etype == "image" and overlays:
        return _render_image_with_overlays(
            elem, seg_id, d, available_image_keys, overlays,
        )

    # 变体库覆盖的元素类型
    html = pick_variant_html(
        etype, elem, seg_id, d, available_image_keys, preferred=pref,
    )
    if html is not None:
        return html

    # 变体库未涵盖的 etype
    return None


def _render_quiz_card(elem: dict, d: str) -> str:
    questions = elem.get("questions", []) or []
    if not questions:
        return ""

    cards: list[str] = []
    for i, q in enumerate(questions[:3], 1):
        if not isinstance(q, dict):
            continue
        question = str(q.get("question") or "").strip()
        if not question:
            continue
        answer = str(q.get("answer") or "").strip()
        explanation = str(q.get("explanation") or "").strip()
        kp_ids = (
            q.get("knowledge_point_ids")
            if isinstance(q.get("knowledge_point_ids"), list)
            else []
        )
        kp_label = " / ".join(str(kid) for kid in kp_ids if str(kid).strip())
        answer_html = (
            f'<div style="margin-top:14px;padding:14px 18px;border-radius:12px;'
            f'background:color-mix(in srgb,var(--primary) 12%,transparent);'
            f'border:1px solid var(--card-border);">'
            f'<div style="font-size:{_fs(18)};font-weight:800;color:var(--accent);'
            f'margin-bottom:6px;">参考答案</div>'
            f'<div style="font-size:{_fs(20)};line-height:1.45;color:var(--text);">'
            f'{_esc(answer)}</div></div>'
        ) if answer else ""
        explanation_html = (
            f'<div style="margin-top:10px;font-size:{_fs(18)};line-height:1.55;'
            f'color:var(--text-dim);text-align:left;">{_esc(explanation)}</div>'
        ) if explanation else ""
        kp_html = (
            f'<div style="margin-top:10px;font-size:{_fs(16)};font-weight:700;'
            f'color:var(--gold);">关联知识点：{_esc(kp_label)}</div>'
        ) if kp_label else ""
        reveal_inner = answer_html + explanation_html + kp_html
        reveal_html = (
            f'<button type="button" class="quiz-reveal-btn" data-quiz-action="reveal" '
            f'style="margin-top:16px;padding:10px 18px;border-radius:999px;'
            f'border:1px solid var(--card-border);background:var(--card-bg);'
            f'color:var(--text);font-size:{_fs(16)};font-weight:800;cursor:pointer;'
            f'box-shadow:var(--card-shadow);">显示答案</button>'
            f'<div class="quiz-reveal anim anim-up" data-step="1" '
            f'data-quiz-reveal="1" aria-hidden="true" '
            f'style="margin-top:8px;">{reveal_inner}</div>'
        ) if reveal_inner else ""
        cards.append(
            f'<div class="quiz-card" data-quiz-card="1" '
            f'style="flex:1;min-width:250px;padding:24px 26px;border-radius:18px;'
            f'background:var(--card-bg);border:1px solid var(--card-border);'
            f'box-shadow:var(--card-shadow);text-align:left;">'
            f'<div style="display:flex;align-items:center;gap:14px;">'
            f'<div style="width:42px;height:42px;border-radius:50%;flex-shrink:0;'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:18px;font-weight:900;color:#fff;'
            f'background:linear-gradient(135deg,var(--primary),var(--secondary));">'
            f'Q{i}</div>'
            f'<div style="font-size:{_fs(22)};font-weight:800;line-height:1.35;'
            f'color:var(--text);">{_esc(question)}</div></div>'
            f'{reveal_html}</div>'
        )

    if not cards:
        return ""
    return (
        f'<div class="anim anim-card {d}" style="display:flex;gap:22px;'
        f'align-items:stretch;justify-content:center;width:100%;max-width:1180px;'
        f'flex-wrap:wrap;">{"".join(cards)}</div>'
    )


def _render_image_with_overlays(
    elem: dict,
    seg_id: Any,
    d: str,
    available_image_keys: set[str],
    overlays: list[dict],
) -> str:
    elem_id = elem.get("id", "")
    key = f"{seg_id}:{elem_id}"
    overlay_html = _render_image_overlays(overlays)
    if elem_id and key in available_image_keys:
        return (
            f'<div class="anim anim-card {d}" data-anim-id="{_esc(elem_id)}" '
            f'style="position:relative;max-width:620px;height:330px;display:flex;'
            f'align-items:center;justify-content:center;overflow:hidden;">'
            f'{{{{IMG_{elem_id}}}}}{overlay_html}</div>'
        )
    return ""


def _collect_image_overlays(elements: list[dict]) -> dict[str, list[dict]]:
    """Group focus_box/callout elements by their target image id."""
    out: dict[str, list[dict]] = {}
    for elem in elements:
        if not isinstance(elem, dict):
            continue
        if elem.get("type") not in ("focus_box", "callout"):
            continue
        target = str(
            elem.get("target")
            or elem.get("target_image")
            or elem.get("image_id")
            or ""
        ).strip()
        if not target:
            continue
        out.setdefault(target, []).append(elem)
    return out


def _pct(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1.0:
        number = number / 100.0
    return max(0.0, min(number, 1.0))


def _bbox_style(elem: dict) -> str:
    bbox = elem.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        x, y, w, h = [_pct(v) for v in bbox[:4]]
    else:
        x = _pct(elem.get("x"), 0.1)
        y = _pct(elem.get("y"), 0.1)
        w = _pct(elem.get("w") or elem.get("width"), 0.25)
        h = _pct(elem.get("h") or elem.get("height"), 0.18)
    return (
        f"left:{x * 100:.2f}%;top:{y * 100:.2f}%;"
        f"width:{max(w, 0.02) * 100:.2f}%;height:{max(h, 0.02) * 100:.2f}%;"
    )


def _render_image_overlays(overlays: list[dict] | None) -> str:
    if not overlays:
        return ""
    parts: list[str] = []
    for idx, elem in enumerate(overlays, start=1):
        elem_id = _esc(elem.get("id") or f"overlay-{idx}")
        style = _bbox_style(elem)
        d = _delay_class(idx + 1)
        if elem.get("type") == "callout":
            label = _esc(elem.get("label") or elem.get("text") or elem.get("title") or "标注")
            parts.append(
                f'<div class="anim anim-scale {d}" data-anim-id="{elem_id}" '
                f'style="position:absolute;{style}pointer-events:none;">'
                f'<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);'
                f'padding:7px 12px;border-radius:999px;background:var(--accent);'
                f'color:#111827;font-size:14px;font-weight:800;white-space:nowrap;'
                f'box-shadow:0 6px 18px rgba(0,0,0,.22);">{label}</div>'
                f'</div>'
            )
        else:
            label = _esc(elem.get("label") or elem.get("text") or "")
            caption = (
                f'<div style="position:absolute;left:0;bottom:calc(100% + 6px);'
                f'padding:4px 8px;border-radius:6px;background:var(--accent);'
                f'color:#111827;font-size:12px;font-weight:800;white-space:nowrap;">'
                f'{label}</div>'
                if label else ""
            )
            parts.append(
                f'<div class="anim anim-scale {d}" data-anim-id="{elem_id}" '
                f'style="position:absolute;{style}border:3px solid var(--accent);'
                f'border-radius:10px;box-shadow:0 0 0 999px rgba(0,0,0,.18),'
                f'0 0 18px var(--glow-primary);pointer-events:none;">{caption}</div>'
            )
    return "".join(parts)
