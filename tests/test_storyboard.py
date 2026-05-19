"""测试画面大纲生成模块（仅测试 JSON 解析，不调LLM）"""

import json
import pytest
from textbook2video.pipeline.storyboard import _parse_storyboard


class TestParseStoryboard:
    """测试 LLM 返回 JSON 的解析逻辑"""

    def test_parse_clean_json(self):
        """标准 JSON 格式（无 markdown 包裹）"""
        raw = json.dumps({
            "lesson_title": "第4课",
            "segments": [
                {
                    "id": 1,
                    "narration": "同学们好！",
                    "visual_type": "title",
                    "elements": [
                        {"id": "e1", "type": "heading", "text": "标题"}
                    ],
                    "animations": [
                        {"target": "e1", "effect": "bounceIn"}
                    ]
                }
            ]
        })
        result = _parse_storyboard(raw, "第4课")
        assert result["lesson_title"] == "第4课"
        assert len(result["segments"]) == 1
        assert result["segments"][0]["narration"] == "同学们好！"
        assert result["metadata"]["total_slides"] == 1

    def test_parse_json_in_codeblock(self):
        """```json ... ``` 包裹的 JSON"""
        raw = """```json
{
  "lesson_title": "第4课",
  "segments": [
    {
      "id": 1,
      "narration": "同学们好！",
      "visual_type": "title",
      "elements": [
        {"id": "e1", "type": "heading", "text": "标题"}
      ],
      "animations": [
        {"target": "e1", "effect": "bounceIn"}
      ]
    }
  ]
}
```"""
        result = _parse_storyboard(raw, "第4课")
        assert len(result["segments"]) == 1
        assert result["segments"][0]["id"] == 1

    def test_parse_json_in_codeblock_no_lang(self):
        """``` ... ``` 不带 json 标签"""
        raw = """```
{"segments": [{"id": 1, "narration": "test", "visual_type": "title", "elements": [], "animations": []}]}
```"""
        result = _parse_storyboard(raw, "test")
        assert len(result["segments"]) == 1

    def test_parse_multiple_segments(self):
        """多个 segment"""
        raw = json.dumps({
            "segments": [
                {"id": 1, "narration": "第一段", "visual_type": "title", "elements": [], "animations": []},
                {"id": 2, "narration": "第二段", "visual_type": "definition", "elements": [], "animations": []},
                {"id": 3, "narration": "第三段", "visual_type": "summary", "elements": [], "animations": []},
            ]
        })
        result = _parse_storyboard(raw, "test")
        assert len(result["segments"]) == 3
        assert result["metadata"]["total_slides"] == 3

    def test_full_element_types(self):
        """完整的 element 和 animation 结构"""
        raw = json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "测试页面",
                    "visual_type": "illustration",
                    "elements": [
                        {"id": "e1", "type": "heading", "text": "标题"},
                        {"id": "e2", "type": "subheading", "text": "副标题"},
                        {"id": "e3", "type": "text", "text": "正文"},
                        {"id": "e4", "type": "icon_group", "items": ["A", "B", "C"]},
                        {"id": "e5", "type": "image", "description": "一张示意图"},
                    ],
                    "animations": [
                        {"target": "e1", "effect": "bounceIn"},
                        {"target": "e4", "effect": "fadeInUp", "stagger": True},
                    ]
                }
            ]
        })
        result = _parse_storyboard(raw, "test")
        seg = result["segments"][0]
        assert len(seg["elements"]) == 5
        assert len(seg["animations"]) == 2
        assert seg["animations"][1]["stagger"] is True

    def test_lesson_title_override(self):
        """强制使用传入的标题"""
        raw = json.dumps({
            "lesson_title": "LLM自己发挥的标题",
            "segments": [{"id": 1, "narration": "test", "visual_type": "title", "elements": [], "animations": []}]
        })
        result = _parse_storyboard(raw, "第4课")
        assert result["lesson_title"] == "第4课"  # 不应该是 LLM 发挥的标题

    def test_missing_lesson_title(self):
        """JSON 中没有 lesson_title 时用传入的"""
        raw = json.dumps({
            "segments": [{"id": 1, "narration": "test", "visual_type": "title", "elements": [], "animations": []}]
        })
        result = _parse_storyboard(raw, "第4课")
        assert result["lesson_title"] == "第4课"

    def test_json_array_directly(self):
        """LLM 直接返回数组"""
        raw = json.dumps([
            {"id": 1, "narration": "test", "visual_type": "title", "elements": [], "animations": []}
        ])
        result = _parse_storyboard(raw, "test")
        assert len(result["segments"]) == 1

    def test_invalid_json_raises(self):
        """无效 JSON 抛 ValueError"""
        with pytest.raises(ValueError, match="未能找到 JSON"):
            _parse_storyboard("这不是JSON", "test")

    def test_missing_segments_raises(self):
        """缺失 segments 字段抛 ValueError"""
        with pytest.raises(ValueError, match="未找到 segments"):
            _parse_storyboard(json.dumps({"title": "test"}), "test")