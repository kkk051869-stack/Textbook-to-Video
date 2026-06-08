"""确定性 slide 渲染器测试（F5）。"""

from textbook2video.template_renderer import render_slide


def _seg(visual_type, elements, id_=1):
    return {"id": id_, "visual_type": visual_type, "elements": elements}


def test_renders_common_elements_with_framework_classes():
    seg = _seg("definition", [
        {"type": "heading", "id": "e1", "text": "标题"},
        {"type": "text", "id": "e2", "text": "说明"},
        {"type": "icon_group", "id": "e3", "items": ["A", "B", "C"]},
        {"type": "comparison_panel", "id": "e4", "items": [
            {"title": "左", "content": "a"}, {"title": "右", "content": "b"},
        ]},
    ])
    html = render_slide(seg, 0, set())
    assert html is not None
    assert 'class="slide active"' in html
    assert "标题" in html and "说明" in html
    # icon_group 各项与对比面板标题都被渲染出来
    assert "A" in html and "B" in html and "C" in html
    assert "左" in html and "右" in html
    assert "VS" in html                 # 对比面板分隔徽标


def test_unsupported_visual_type_returns_none():
    seg = _seg("network", [{"type": "heading", "id": "e1", "text": "x"}])
    assert render_slide(seg, 0, set()) is None


def test_unsupported_element_returns_none():
    # node 不在支持列表 → 整页 fallback
    seg = _seg("illustration", [
        {"type": "heading", "id": "e1", "text": "x"},
        {"type": "node", "id": "e2", "text": "n"},
    ])
    assert render_slide(seg, 0, set()) is None


def test_textbook_image_uses_placeholder_when_available():
    seg = _seg("timeline", [
        {"type": "image", "id": "e2", "src": "fig1-1.png", "description": "图"},
    ])
    html = render_slide(seg, 1, {"1:e2"})
    assert html is not None
    assert "{{IMG_e2}}" in html          # 走占位 → 后续注入真实图


def test_image_without_available_key_falls_back_to_desc_card():
    seg = _seg("title", [
        {"type": "image", "id": "e2", "description": "抽象背景"},
    ])
    html = render_slide(seg, 1, set())   # 无可注入图
    assert html is not None
    assert "{{IMG_" not in html          # 不残留占位
    assert "抽象背景" in html


def test_does_not_misuse_content_card_class():
    """渲染产物不应给小元素套 .content-card（fullscreen 下它是全屏画布，会撑爆）。"""
    seg = _seg("illustration", [
        {"type": "heading", "id": "e1", "text": "t"},
        {"type": "quote", "id": "e2", "text": "示例引言"},
        {"type": "image", "id": "e3", "description": "x"},
    ])
    html = render_slide(seg, 0, set())
    assert html is not None
    assert "content-card" not in html


def test_non_first_slide_has_no_active_class():
    seg = _seg("title", [{"type": "heading", "id": "e1", "text": "x"}])
    html = render_slide(seg, 2, set())
    assert 'class="slide"' in html and "active" not in html


def test_few_elements_use_center_not_space_evenly():
    """内容行少（≤3）时 content-box 用 justify-content:center，避免被拉散成空旷。"""
    seg = _seg("definition", [
        {"type": "heading", "id": "e1", "text": "标题"},   # 进标题栏，不计内容行
        {"type": "text", "id": "e2", "text": "一"},
        {"type": "text", "id": "e3", "text": "二"},
    ])
    html = render_slide(seg, 0, set())
    assert "justify-content:center" in html
    assert "space-evenly" not in html


def test_icon_group_uses_autofit_grid():
    """icon_group 用 auto-fit 网格自动排布填宽，不再用 flex-wrap + 固定 min-width。"""
    seg = _seg("definition", [
        {"type": "icon_group", "id": "e1", "items": ["甲", "乙", "丙", "丁"]},
    ])
    html = render_slide(seg, 0, set())
    assert "repeat(auto-fit,minmax(" in html
    assert "min-width:200px" not in html   # 旧的固定卡宽已移除


def test_fonts_use_fluid_clamp():
    """正文/数字等字号改用 clamp 流式缩放（上限保持原 px）。"""
    seg = _seg("definition", [
        {"type": "text", "id": "e1", "text": "正文"},
        {"type": "quote", "id": "e2", "text": "示例引言"},
    ])
    html = render_slide(seg, 0, set())
    assert "clamp(" in html
    assert ",24px)" in html      # text 上限仍是 24px（1920 观感不变）


def test_many_top_level_rows_use_space_evenly():
    """顶层 row_count ≥5 时（异类元素多）才用 space-evenly 均衡分布。
    连续同类元素（如 6 个 text）会被合成 1 段 paragraph 组，只占 1 行。
    """
    seg = _seg("definition", [
        {"type": "heading", "id": "e1", "text": "标题"},
        {"type": "icon_group", "id": "e2", "items": ["a", "b"]},
        {"type": "quote", "id": "e3", "text": "金句"},
        {"type": "text", "id": "e4", "text": "正文一"},
        {"type": "comparison_panel", "id": "e5", "items": [
            {"title": "A", "content": "x"}, {"title": "B", "content": "y"}
        ]},
        {"type": "flow_step", "id": "e6", "steps": ["1", "2"]},
        {"type": "table", "id": "e7", "headers": ["h"], "rows": [["v"]]},
    ])
    html = render_slide(seg, 0, set())
    assert "justify-content:space-evenly" in html


def _img_text_seg(sid, n_light):
    """构造一个含 image + N 个轻元素（quote）的 illustration 段。"""
    light = [{"type": "quote", "id": f"q{i}", "text": f"金句{i}"} for i in range(n_light)]
    return _seg("illustration", [
        {"type": "heading", "id": "h", "text": "标题"},
        {"type": "image", "id": "i", "src": "x.png", "description": "图"},
        *light,
    ], id_=sid)


def test_image_text_layout_classic_when_truly_light():
    """轻量 2 个 text（n=1 合并段落组, weight=2）→ 经典图左文右。"""
    seg = _seg("illustration", [
        {"type": "heading", "id": "h", "text": "标题"},
        {"type": "image", "id": "i", "src": "x.png", "description": "图"},
        {"type": "text", "id": "t1", "text": "x"},
        {"type": "text", "id": "t2", "text": "y"},
    ], id_=1)
    html = render_slide(seg, 0, available_image_keys={"1:i"})
    assert "flex:1.15" in html


def test_image_text_layout_spans_bottom_when_3_elems():
    """3 quote (n=3) → 图左文右 + 末位横跨底栏。"""
    seg = _img_text_seg(1, 3)
    html = render_slide(seg, 0, available_image_keys={"1:i"})
    assert "flex:1.15" in html
    span_strip = html.find("width:100%;display:flex;justify-content:center;align-items:center")
    assert span_strip > 0


def test_image_text_layout_full_stack_when_4plus_elems():
    """4+ quote (n≥4) → 图顶 + 文居中下全宽。"""
    seg = _img_text_seg(2, 4)
    html = render_slide(seg, 0, available_image_keys={"2:i"})
    assert "max-width:760px" in html
    assert "max-width:1100px" in html
    assert "flex:1.15" not in html


def test_subheading_pinned_in_title_bar_area():
    """subheading 应钉在 title_bar 顶部（heading 之后、内容区之前），
    而不是塞进居中的 content-box（之前会被挤到 slide 中部）。"""
    seg = _seg("illustration", [
        {"type": "heading", "id": "e1", "text": "标题"},
        {"type": "subheading", "id": "e2", "text": "本节副标题"},
        {"type": "image", "id": "e3", "src": "x.png", "description": "图"},
        {"type": "text", "id": "e4", "text": "正文要点"},
        {"type": "quote", "id": "e5", "text": "金句"},
    ])
    html = render_slide(seg, 0, available_image_keys={"1:e3"})
    sub_pos = html.find("本节副标题")
    content_box_pos = html.find("t2v-content-box")
    # 副标题必须在 content-box 之前出现（说明在 title_bar 区域，flex-shrink:0 置顶）
    assert 0 < sub_pos < content_box_pos
    # 副标题 HTML 应包含 flex-shrink:0（确保不被压缩）
    assert "flex-shrink:0" in html[sub_pos - 200 : sub_pos + 300]


def test_consecutive_text_collapses_to_one_block():
    """连续多个 text/label 应合并成一段 paragraph 组（gap 14px），
    对外只算 1 个 row → 触发大间距 center 布局。"""
    seg = _seg("definition", [
        {"type": "heading", "id": "e1", "text": "标题"},
        {"type": "text", "id": "e2", "text": "段一"},
        {"type": "text", "id": "e3", "text": "段二"},
        {"type": "text", "id": "e4", "text": "段三"},
    ])
    html = render_slide(seg, 0, set())
    # 三段 text 合并 → 外层 row_count=1 → 进 ≤2 档（64px）
    assert "gap:64px" in html
    # 内部 paragraph 组容器（gap:14px）出现
    assert "flex-direction:column;gap:14px" in html
