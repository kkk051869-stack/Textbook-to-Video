"""变体库（template_variants）单元测试。

验证：
- 每个元素类型的所有 variant 都能渲染出非空字符串
- 同一 seg_id + element_type 稳定选同一 variant（可复现）
- 不同 seg_id 在多个 variant 间分布（轮换有效）
"""

from textbook2video.template_variants import (
    GROUP_VARIANTS,
    VARIANTS,
    pick_group_variant_html,
    pick_variant_html,
)


def _sample_elem(etype: str) -> dict:
    """每种 element 类型构造一个最小但有效的 sample。"""
    samples = {
        "subheading":       {"type": "subheading", "text": "副标题"},
        "text":             {"type": "text", "text": "正文"},
        "label":            {"type": "label", "text": "标注"},
        "quote":            {"type": "quote", "text": "金句"},
        "highlight_box":    {"type": "highlight_box", "text": "强调"},
        "badge":            {"type": "badge", "text": "标签"},
        "icon_group":       {"type": "icon_group", "items": ["A", "B", "C"]},
        "flow_step":        {"type": "flow_step", "steps": ["一", "二", "三"]},
        "activity_step":    {"type": "activity_step", "steps": ["一", "二"]},
        "comparison_panel": {"type": "comparison_panel", "items": [
            {"title": "A", "content": "x"}, {"title": "B", "content": "y"},
        ]},
        "table":            {"type": "table", "headers": ["H"], "rows": [["v"]]},
        "image":            {"type": "image", "id": "e1", "description": "图"},
    }
    return samples[etype]


def test_every_etype_has_at_least_two_variants():
    """全做完后，每种 etype 至少有 2 套版式。"""
    minimums = {
        "icon_group": 3, "flow_step": 3, "comparison_panel": 3,
        "quote": 3, "highlight_box": 3,
        "text": 3, "label": 3,
        "activity_step": 2, "table": 2, "image": 2,
        "badge": 2, "subheading": 2,
    }
    for etype, n in minimums.items():
        assert len(VARIANTS.get(etype, [])) >= n, \
            f"{etype} 变体数 {len(VARIANTS.get(etype, []))} < {n}"


def test_all_variants_render_non_empty():
    """所有 etype 的所有 variant 都应渲染出非空 HTML。"""
    for etype, fns in VARIANTS.items():
        elem = _sample_elem(etype)
        for vi in range(len(fns)):
            # 用不同 seg_id 强制走每一个 variant
            html = pick_variant_html(
                etype, elem, seg_id=vi + 1, delay_class="d3",
                available_image_keys={"1:e1"},  # 给 image 用
            )
            assert html, f"{etype} variant {vi} 渲染为空"


def test_variant_selection_is_deterministic():
    """同一 (etype, seg_id) 多次调用应返回完全相同的 HTML。"""
    elem = _sample_elem("icon_group")
    h1 = pick_variant_html("icon_group", elem, 1, "d3", set())
    h2 = pick_variant_html("icon_group", elem, 1, "d3", set())
    assert h1 == h2


def test_variant_selection_rotates_across_seg_ids():
    """seg_id 1/2/3 应分别命中 variant 0/1/2（3 变体场景）。"""
    elem = _sample_elem("flow_step")
    htmls = [
        pick_variant_html("flow_step", elem, sid, "d3", set())
        for sid in (1, 2, 3)
    ]
    # 三种应至少出现 2 种不同的 HTML（说明有轮换）
    assert len(set(htmls)) >= 2


def test_non_numeric_seg_id_falls_back_to_hash():
    """seg_id 是字符串时也应能选出 variant（不抛异常）。"""
    elem = _sample_elem("text")
    assert pick_variant_html("text", elem, "abc", "d3", set())


def test_unknown_etype_returns_none():
    """变体库未涵盖的 etype 应返回 None，让上游 fallback。"""
    assert pick_variant_html("unknown_xyz", {}, 1, "d1", set()) is None


def test_group_variants_have_options():
    """text_group / badge_row 都有多套合并版式。"""
    assert len(GROUP_VARIANTS["text_group"]) >= 3
    assert len(GROUP_VARIANTS["badge_row"]) >= 2


def test_group_variants_render():
    """段落组 / 徽章组按 seg_id 选出版式都能渲染。"""
    htmls = ["<p>a</p>", "<p>b</p>"]
    assert pick_group_variant_html("text_group", htmls, 1)
    assert pick_group_variant_html("text_group", htmls, 2)
    assert pick_group_variant_html("badge_row", htmls, 1)


def test_unknown_group_falls_back_to_join():
    """未知组名直接拼接。"""
    htmls = ["<p>a</p>", "<p>b</p>"]
    assert pick_group_variant_html("nope", htmls, 1) == "<p>a</p><p>b</p>"


def test_empty_inputs_return_empty_string():
    """空 items / 不足 items 的元素应返回空串（不是 None）。"""
    assert pick_variant_html("icon_group", {"items": []}, 1, "d1", set()) == ""
    assert pick_variant_html("flow_step", {"steps": []}, 1, "d1", set()) == ""
    assert pick_variant_html(
        "comparison_panel", {"items": [{"title": "A"}]}, 1, "d1", set()
    ) == ""
    assert pick_variant_html("table", {"rows": []}, 1, "d1", set()) == ""
