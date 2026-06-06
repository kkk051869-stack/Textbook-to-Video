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
        with pytest.raises(ValueError, match="无法解析"):
            _parse_storyboard("这不是JSON", "test")

    def test_missing_segments_raises(self):
        """缺失 segments 字段抛 ValueError"""
        with pytest.raises(ValueError, match="未找到 segments"):
            _parse_storyboard(json.dumps({"title": "test"}), "test")


class TestTruncationRepair:
    """测试截断 JSON 的自动修复"""

    def test_truncated_mid_string(self):
        """模拟 max_tokens 截断：在字符串值中间被切断"""
        full = json.dumps({
            "lesson_title": "测试课",
            "segments": [
                {"id": 1, "narration": "第一段完整", "visual_type": "title",
                 "elements": [{"id": "e1", "type": "heading", "text": "标题"}],
                 "animations": []},
                {"id": 2, "narration": "第二段被截断的内容...", "visual_type": "definition",
                 "elements": [{"id": "e2", "type": "text", "text": "正在写"}],
                 "animations": []},
            ]
        }, ensure_ascii=False)
        # 在第二个 segment 的 elements 后面、animations 之前截断
        marker = '"e2"'
        marker_pos = full.rfind(marker)
        cut_after = full.find("}", marker_pos)
        cut = full[:cut_after + 1]
        result = _parse_storyboard(cut, "测试课")
        # 应该只保留第一个完整 segment
        assert len(result["segments"]) == 1
        assert result["segments"][0]["id"] == 1

    def test_truncated_mid_segment(self):
        """在 segment 的 elements 数组中间截断"""
        full = json.dumps({
            "lesson_title": "测试课",
            "segments": [
                {"id": 1, "narration": "第一段", "visual_type": "title",
                 "elements": [{"id": "e1", "type": "heading", "text": "标题"}],
                 "animations": []},
                {"id": 2, "narration": "第二段", "visual_type": "definition",
                 "elements": [{"id": "e2", "type": "heading", "text": "概念"},
                              {"id": "e3", "type": "text", "text": "解释"}],
                 "animations": []},
            ]
        }, ensure_ascii=False)
        # 在第二个 segment 的 elements 中间截断：找 e3 的位置，截到它之前
        marker = '"e3"'
        marker_pos = full.rfind(marker)
        # 往前找到上一个 }, 那是 e2 这个 element 的结尾
        cut_pos = full.rfind("}", 0, marker_pos)
        cut = full[:cut_pos + 1]
        result = _parse_storyboard(cut, "测试课")
        assert len(result["segments"]) == 1
        assert result["segments"][0]["id"] == 1

    def test_unrepairable_json_raises(self):
        """完全无法修复的 JSON 仍抛 ValueError"""
        raw = '{ "garbage": true '
        with pytest.raises(ValueError, match="无法解析"):
            _parse_storyboard(raw, "测试课")


class TestBatchGeneration:
    """测试分批生成的合并逻辑（mock LLM 调用）"""

    def test_batch_merges_segments(self, monkeypatch):
        """超过 3 段时应分批调用并合并结果"""
        from textbook2video.pipeline import storyboard as sb_mod
        original_batch_size = sb_mod._BATCH_SIZE
        sb_mod._BATCH_SIZE = 2  # 用更小的 batch 方便测试

        call_count = 0

        def mock_chat_with_system(user_content, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps({"segments": [
                    {"id": 1, "narration": "段1", "visual_type": "title",
                     "elements": [], "animations": []},
                    {"id": 2, "narration": "段2", "visual_type": "definition",
                     "elements": [], "animations": []},
                ]})
            else:
                return json.dumps({"segments": [
                    {"id": 3, "narration": "段3", "visual_type": "process",
                     "elements": [], "animations": []},
                ]})

        monkeypatch.setattr(sb_mod, "chat_with_system", mock_chat_with_system)

        result = sb_mod.generate_storyboard(
            ["段1内容", "段2内容", "段3内容"],
            lesson_title="测试课",
        )
        assert call_count == 2
        assert len(result["segments"]) == 3
        assert result["segments"][0]["narration"] == "段1"
        assert result["segments"][2]["narration"] == "段3"
        assert result["metadata"]["total_slides"] == 3

        sb_mod._BATCH_SIZE = original_batch_size

    def test_single_batch_no_split(self, monkeypatch):
        """段数 <= batch_size 时只调一次"""
        from textbook2video.pipeline import storyboard as sb_mod

        call_count = 0

        def mock_chat_with_system(user_content, **kwargs):
            nonlocal call_count
            call_count += 1
            return json.dumps({"segments": [
                {"id": 1, "narration": "段1", "visual_type": "title",
                 "elements": [], "animations": []},
            ]})

        monkeypatch.setattr(sb_mod, "chat_with_system", mock_chat_with_system)

        result = sb_mod.generate_storyboard(
            ["只有一段"],
            lesson_title="测试课",
        )
        assert call_count == 1
        assert len(result["segments"]) == 1

class TestSplitOverlapping:
    """类型重叠在生成阶段拆段（保信息 + 每页干净）。"""

    def test_list_group_overlap_splits(self):
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "先讲四次革命的历程。再讲第四次革命的三大影响。",
            "visual_type": "process",
            "elements": [
                {"id": "e1", "type": "heading", "text": "工业革命"},
                {"id": "e2", "type": "flow_step", "steps": ["1", "2", "3", "4"]},
                {"id": "e3", "type": "icon_group", "items": ["A", "B", "C"]},
            ],
        }
        out = split_overlapping_segments([seg])
        assert len(out) == 2                       # 拆成两段
        # 每段各只含一个列举 widget
        t0 = {e["type"] for e in out[0]["elements"]}
        t1 = {e["type"] for e in out[1]["elements"]}
        assert "flow_step" in t0 and "icon_group" not in t0
        assert "icon_group" in t1 and "flow_step" not in t1
        # 续页保留标题；id 重新编号
        assert any(e["type"] == "heading" for e in out[1]["elements"])
        assert [s["id"] for s in out] == [1, 2]
        # 旁白被切分（两段都非空，且不等于原文）
        assert out[0]["narration"] and out[1]["narration"]

    def test_clean_segment_unchanged(self):
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "一段干净内容。", "visual_type": "comparison",
            "elements": [
                {"id": "e1", "type": "heading", "text": "对比"},
                {"id": "e2", "type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
                {"id": "e3", "type": "stat_card", "value": "50%", "label": "x"},
            ],
        }
        out = split_overlapping_segments([seg])
        assert len(out) == 1                       # 无重叠，不拆

    def test_no_info_lost(self):
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "甲。乙。", "visual_type": "process",
            "elements": [
                {"id": "e1", "type": "heading", "text": "H"},
                {"id": "e2", "type": "flow_step", "steps": ["s"]},
                {"id": "e3", "type": "text", "text": "中间说明"},
                {"id": "e4", "type": "icon_group", "items": ["x"]},
            ],
        }
        out = split_overlapping_segments([seg])
        # 除复制的 heading 外，所有原始 body 元素都还在（无丢失）
        all_texts = []
        for s in out:
            for e in s["elements"]:
                all_texts.append(e.get("text") or str(e.get("steps") or e.get("items")))
        assert "中间说明" in all_texts
        assert any("flow" in str(e.get("type")) for s in out for e in s["elements"])
        assert any(e.get("type") == "icon_group" for s in out for e in s["elements"])
