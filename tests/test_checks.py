"""validate / doctor / batch 解析测试（不依赖 LLM/网络）。"""

import pytest

from textbook2video.pipeline.checks import (
    parse_lesson_specs,
    parse_section_specs,
    validate_storyboard,
)


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
