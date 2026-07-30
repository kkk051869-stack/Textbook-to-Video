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


def test_validate_quiz_card_requires_question_but_warns_answer_explanation():
    rep = validate_storyboard(_one_seg([
        {"type": "quiz_card", "questions": [{"question": "什么是算法？"}]},
    ]))

    assert rep.ok
    assert any("缺少 answer" in w for w in rep.warnings)
    assert any("缺少 explanation" in w for w in rep.warnings)


def test_validate_quiz_card_missing_question_is_error():
    rep = validate_storyboard(_one_seg([
        {"type": "quiz_card", "questions": [{"answer": "是"}]},
    ]))

    assert any("缺少 question" in err for err in rep.errors)


def test_validate_missing_required_field_is_error():
    sb = _good_storyboard()
    sb["segments"][0]["elements"].append({"type": "table", "headers": ["a"]})  # 缺 rows
    rep = validate_storyboard(sb)
    assert any("rows" in e for e in rep.errors)


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


def test_validate_focus_box_and_callout_ok():
    sb = {"segments": [{
        "id": 1, "narration": "x", "visual_type": "illustration",
        "audio_duration_sec": 3.0,
        "elements": [
            {"type": "image", "id": "img1", "description": "教材图"},
            {"type": "focus_box", "id": "f1", "target": "img1", "bbox": [0.1, 0.2, 0.3, 0.2]},
            {"type": "callout", "id": "c1", "target": "img1", "bbox": [10, 20, 30, 20], "label": "重点"},
        ],
    }]}

    rep = validate_storyboard(sb)

    assert rep.ok


def test_validate_focus_box_target_must_reference_image():
    sb = {"segments": [{
        "id": 1, "narration": "x", "visual_type": "illustration",
        "audio_duration_sec": 3.0,
        "elements": [
            {"type": "image", "id": "img1", "description": "教材图"},
            {"type": "focus_box", "id": "f1", "target": "missing", "bbox": [0.1, 0.2, 0.3, 0.2]},
        ],
    }]}

    rep = validate_storyboard(sb)

    assert any("未指向本页 image id" in e for e in rep.errors)


def test_validate_callout_requires_label_or_text():
    sb = {"segments": [{
        "id": 1, "narration": "x", "visual_type": "illustration",
        "audio_duration_sec": 3.0,
        "elements": [
            {"type": "image", "id": "img1", "description": "教材图"},
            {"type": "callout", "id": "c1", "target": "img1", "bbox": [0.1, 0.2, 0.3, 0.2]},
        ],
    }]}

    rep = validate_storyboard(sb)

    assert any("callout 缺少 label 或 text" in e for e in rep.errors)


def test_textbook_image_utilization_low_warns(tmp_path):
    """提取了 5 张教材图但只引用 1 张（20%）→ 应警告利用率偏低。"""
    (tmp_path / "images").mkdir()
    for i in range(1, 6):
        (tmp_path / "images" / f"fig{i}.png").write_bytes(b"x")
    sb = {"segments": [{
        "id": 1, "narration": "x", "visual_type": "illustration",
        "audio_duration_sec": 3.0,
        "elements": [{"type": "image", "src": "fig1.png", "description": "图"}],
    }]}
    rep = validate_storyboard(sb, base_dir=tmp_path)
    assert any("利用率" in w and "偏低" in w for w in rep.warnings)


def test_textbook_image_utilization_high_no_warn(tmp_path):
    """提取 2 张教材图都被引用（100%）→ 不应警告利用率。"""
    (tmp_path / "images").mkdir()
    for i in range(1, 3):
        (tmp_path / "images" / f"fig{i}.png").write_bytes(b"x")
    sb = {"segments": [
        {"id": 1, "narration": "x", "visual_type": "illustration",
         "audio_duration_sec": 3.0,
         "elements": [{"type": "heading", "text": "T"},
                      {"type": "image", "src": "fig1.png", "description": "图1"}]},
        {"id": 2, "narration": "y", "visual_type": "illustration",
         "audio_duration_sec": 3.0,
         "elements": [{"type": "heading", "text": "T2"},
                      {"type": "image", "src": "fig2.png", "description": "图2"}]},
    ]}
    rep = validate_storyboard(sb, base_dir=tmp_path)
    assert not any("利用率" in w and "偏低" in w for w in rep.warnings)


def test_textbook_image_utilization_no_extracted_no_warn(tmp_path):
    """没提取任何教材图（images/ 不存在或为空）→ 不应警告。"""
    sb = {"segments": [{
        "id": 1, "narration": "x", "visual_type": "definition",
        "audio_duration_sec": 3.0,
        "elements": [{"type": "heading", "text": "T"}, {"type": "text", "text": "x"}],
    }]}
    rep = validate_storyboard(sb, base_dir=tmp_path)
    assert not any("利用率" in w for w in rep.warnings)


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


def test_too_many_body_types_warns():
    # 6 种 body 类型 → 告警（heading 不计）
    w = _warns([
        {"type": "heading", "text": "t"},
        {"type": "image", "description": "x"},
        {"type": "table", "headers": ["h"], "rows": [[1]]},
        {"type": "icon_group", "items": ["a"]},
        {"type": "badge", "text": "x"},
        {"type": "quote", "text": "q"},
        {"type": "text", "text": "t"},
    ])
    assert any("类型过多" in x for x in w)


def test_few_body_types_no_type_warning():
    # 3 种 body 类型，即使多放实例也不告警
    w = _warns([
        {"type": "heading", "text": "t"},
        {"type": "image", "description": "x"},
        {"type": "icon_group", "items": ["a", "b", "c"]},
        {"type": "text", "text": "正文"},
    ])
    assert not any("类型过多" in x for x in w)


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
    assert any("重叠" in x for x in w)


def test_duplicate_type_warns():
    w = _warns([
        {"type": "image", "description": "x"},
        {"type": "image", "description": "y"},
        {"type": "text", "text": "t"},
    ])
    assert any("重复的元素类型" in x for x in w)


def test_well_formed_page_no_density_role_warning():
    # 1 主元素(comparison=3) + 2 轻元素(quote 1 + text 1) = 5，无重复/互斥/多主元素
    w = _warns([
        {"type": "heading", "text": "标题"},
        {"type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
        {"type": "quote", "text": "金句"},
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
