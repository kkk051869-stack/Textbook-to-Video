"""确定性 slide 渲染器测试（F5）。"""

from textbook2video.template_renderer import render_slide


def _seg(visual_type, elements):
    return {"id": 1, "visual_type": visual_type, "elements": elements}


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
        {"type": "stat_card", "id": "e2", "value": "100", "label": "个"},
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
        {"type": "stat_card", "id": "e2", "value": "100", "label": "个"},
    ])
    html = render_slide(seg, 0, set())
    assert "clamp(" in html
    assert ",24px)" in html      # text 上限仍是 24px（1920 观感不变）


def test_many_elements_use_space_evenly():
    """内容行多（≥4）时仍用 space-evenly 均衡分布。"""
    seg = _seg("definition", [
        {"type": "heading", "id": "e1", "text": "标题"},
        {"type": "text", "id": "e2", "text": "一"},
        {"type": "text", "id": "e3", "text": "二"},
        {"type": "text", "id": "e4", "text": "三"},
        {"type": "text", "id": "e5", "text": "四"},
        {"type": "text", "id": "e6", "text": "五"},
    ])
    html = render_slide(seg, 0, set())
    assert "justify-content:space-evenly" in html
