"""validate / doctor / batch 解析测试（不依赖 LLM/网络）。"""

import pytest

from textbook2video.pipeline.checks import (
    parse_lesson_specs,
    parse_section_specs,
    segment_weight,
    validate_storyboard,
)


def _one_seg(elements):
    """单页 storyboard，narration/时长齐全，便于只验密度/角色 warning。"""
    return {"segments": [{
        "id": 1, "narration": "旁白", "visual_type": "definition",
        "audio_duration_sec": 5.0, "elements": elements,
    }]}


def _warns(elements):
    return validate_storyboard(_one_seg(elements)).warnings


def _good_storyboard():
    return {
        "segments": [
            {
                "id": 1, "narration": "旁白一", "visual_type": "definition",
                "audio_duration_sec": 5.0,
                "elements": [
                    {"type": "heading", "text": "标题"},
                    {"type": "icon_group", "items": ["A", "B"]},
                    {"type": "comparison_panel",
                     "items": [{"title": "左", "content": "x"}]},
                    {"type": "image", "description": "示意图"},
                ],
            },
        ],
    }


def test_validate_good_storyboard_ok():
    rep = validate_storyboard(_good_storyboard())
    assert rep.ok
    assert rep.errors == []


def test_validate_missing_segments():
    rep = validate_storyboard({"segments": []})
    assert not rep.ok
    assert any("segments" in e for e in rep.errors)


def test_validate_missing_narration_is_error():
    sb = _good_storyboard()
    sb["segments"][0]["narration"] = "   "
    rep = validate_storyboard(sb)
    assert not rep.ok
    assert any("narration" in e for e in rep.errors)


def test_validate_unknown_element_type_is_error():
    sb = _good_storyboard()
    sb["segments"][0]["elements"].append({"type": "hologram", "text": "x"})
    rep = validate_storyboard(sb)
    assert any("hologram" in e for e in rep.errors)


def test_validate_missing_required_field_is_error():
    sb = _good_storyboard()
    sb["segments"][0]["elements"].append({"type": "stat_card", "value": "100"})  # 缺 label
    rep = validate_storyboard(sb)
    assert any("label" in e for e in rep.errors)


def test_validate_image_without_src_or_desc_is_error():
    sb = _good_storyboard()
    sb["segments"][0]["elements"] = [{"type": "image"}]
    rep = validate_storyboard(sb)
    assert any("image" in e for e in rep.errors)


def test_validate_image_src_missing_file(tmp_path):
    sb = {
        "segments": [{
            "id": 1, "narration": "x", "visual_type": "timeline",
            "audio_duration_sec": 3.0,
            "elements": [{"type": "image", "src": "ghost.png", "description": "图"}],
        }],
    }
    rep = validate_storyboard(sb, base_dir=tmp_path)
    assert any("不存在" in e for e in rep.errors)
    # 图片存在时则通过
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "ghost.png").write_bytes(b"x")
    rep2 = validate_storyboard(sb, base_dir=tmp_path)
    assert rep2.ok


def test_validate_bad_duration_is_error():
    sb = _good_storyboard()
    sb["segments"][0]["audio_duration_sec"] = -2
    rep = validate_storyboard(sb)
    assert any("audio_duration_sec" in e for e in rep.errors)


def test_validate_missing_duration_is_warning_not_error():
    sb = _good_storyboard()
    del sb["segments"][0]["audio_duration_sec"]
    rep = validate_storyboard(sb)
    assert rep.ok
    assert any("audio_duration_sec" in w for w in rep.warnings)


def test_validate_unknown_visual_type_is_warning():
    sb = _good_storyboard()
    sb["segments"][0]["visual_type"] = "hologram"
    rep = validate_storyboard(sb)
    assert rep.ok
    assert any("visual_type" in w for w in rep.warnings)


def test_validate_duplicate_segment_id_is_error():
    sb = _good_storyboard()
    sb["segments"].append({
        "id": 1, "narration": "另一段", "visual_type": "title",
        "audio_duration_sec": 3.0,
        "elements": [{"type": "heading", "text": "h"}],
    })  # id=1 与首段重复
    rep = validate_storyboard(sb)
    assert not rep.ok
    assert any("id 重复" in e for e in rep.errors)


def test_validate_script_count_mismatch_is_warning(tmp_path):
    sb = _good_storyboard()                      # 1 页
    script = tmp_path / "ch3_s0_script.txt"
    script.write_text("第1段：\n一\n\n第2段：\n二\n\n第3段：\n三\n\n",
                      encoding="utf-8")           # 3 段讲稿
    rep = validate_storyboard(sb, script_path=script)
    assert rep.ok                                 # 仅告警，不致命
    assert any("不一致" in w for w in rep.warnings)


def test_validate_script_count_match_no_warning(tmp_path):
    sb = _good_storyboard()                      # 1 页
    script = tmp_path / "x_script.txt"
    script.write_text("第1段：\n只有一段\n\n", encoding="utf-8")   # 1 段
    rep = validate_storyboard(sb, script_path=script)
    assert not any("不一致" in w for w in rep.warnings)


def test_validate_no_script_file_skips_consistency(tmp_path):
    sb = _good_storyboard()
    rep = validate_storyboard(sb, script_path=tmp_path / "missing_script.txt")
    assert rep.ok
    assert not any("不一致" in w for w in rep.warnings)


def test_segment_weight_basic_and_table():
    assert segment_weight([{"type": "heading"}, {"type": "image"}]) == 3.0      # 0 + 3
    assert segment_weight([{"type": "icon_group"}, {"type": "quote"}]) == 2.5   # 1.5 + 1
    # table 按行数：1 + 0.5×4 = 3
    assert segment_weight([{"type": "table", "rows": [1, 2, 3, 4]}]) == 3.0


def test_dense_page_warns():
    # image(3)+comparison(3)+table(3行=2.5)+icon(1.5)+text(1)=11 > 8
    w = _warns([
        {"type": "heading", "text": "t"},
        {"type": "image", "description": "x"},
        {"type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
        {"type": "table", "headers": ["h"], "rows": [[1], [2], [3]]},
        {"type": "icon_group", "items": ["a"]},
        {"type": "text", "text": "正文"},
    ])
    assert any("过密" in x for x in w)


def test_sparse_page_warns():
    # 只有 quote(1) → 偏空
    assert any("偏空" in x for x in _warns([{"type": "quote", "text": "金句"}]))


def test_multiple_heroes_warns():
    w = _warns([
        {"type": "image", "description": "x"},
        {"type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
        {"type": "text", "text": "t"},
    ])
    assert any("多个主元素" in x for x in w)


def test_mutex_pair_warns():
    w = _warns([
        {"type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
        {"type": "table", "headers": ["h"], "rows": [[1]]},
    ])
    assert any("互斥" in x for x in w)


def test_duplicate_type_warns():
    w = _warns([
        {"type": "image", "description": "x"},
        {"type": "image", "description": "y"},
        {"type": "text", "text": "t"},
    ])
    assert any("重复的元素类型" in x for x in w)


def test_well_formed_page_no_density_role_warning():
    # 1 主元素(comparison=3) + 2 轻元素(stat 1 + text 1) = 5，无重复/互斥/多主元素
    w = _warns([
        {"type": "heading", "text": "标题"},
        {"type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
        {"type": "stat_card", "value": "1", "label": "个"},
        {"type": "text", "text": "说明"},
    ])
    assert not any(k in x for x in w for k in ("过密", "偏空", "多个主元素", "互斥", "重复"))


def test_parse_section_specs():
    assert parse_section_specs("3:0,3:1,4:0") == [(3, 0), (3, 1), (4, 0)]
    assert parse_section_specs(" 2:1 ") == [(2, 1)]


def test_parse_section_specs_bad_format():
    with pytest.raises(ValueError):
        parse_section_specs("3-0")


def test_parse_lesson_specs():
    assert parse_lesson_specs("1,2,4") == [1, 2, 4]
    with pytest.raises(ValueError):
        parse_lesson_specs("  ")
