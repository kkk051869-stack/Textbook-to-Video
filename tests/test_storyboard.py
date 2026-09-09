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
    """类型重叠在生成阶段拆段（保信息 + 每页干净 + 瘦半交 LLM 改写填实）。"""

    def test_deterministic_split_when_both_halves_substantial(self, monkeypatch):
        # 两半都够实 → 确定性拆，不应调用 LLM
        def boom(*a, **k):
            raise RuntimeError("不应调用 LLM")
        monkeypatch.setattr("textbook2video.pipeline.storyboard.chat_with_system", boom)
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "先讲流程的四步。再讲三个要点与配图。",
            "visual_type": "process",
            "elements": [
                {"id": "e1", "type": "heading", "text": "H"},
                {"id": "e2", "type": "flow_step", "steps": ["1", "2", "3", "4"]},
                {"id": "e3", "type": "text", "text": "流程说明"},
                {"id": "e4", "type": "icon_group", "items": ["A", "B", "C"]},
                {"id": "e5", "type": "image", "description": "配图"},
                {"id": "e6", "type": "quote", "text": "金句"},
            ],
        }
        out = split_overlapping_segments([seg])
        assert len(out) == 2
        t0 = {e["type"] for e in out[0]["elements"]}
        t1 = {e["type"] for e in out[1]["elements"]}
        assert ("flow_step" in t0) != ("flow_step" in t1)   # 流程只在一页
        assert ("icon_group" in t0) != ("icon_group" in t1)  # 图标只在另一页
        assert [s["id"] for s in out] == [1, 2]

    def test_clean_segment_unchanged(self):
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "一段干净内容。", "visual_type": "comparison",
            "elements": [
                {"id": "e1", "type": "heading", "text": "对比"},
                {"id": "e2", "type": "comparison_panel", "items": [{"title": "a", "content": "b"}]},
                {"id": "e3", "type": "quote", "text": "x"},
            ],
        }
        assert len(split_overlapping_segments([seg])) == 1

    def test_thin_half_uses_llm_rewrite(self, monkeypatch):
        # 拆完会瘦（flow+icon 都轻）→ 交 LLM 改写成两页（各填正文）
        def fake(*a, **k):
            return json.dumps([
                {"narration": "甲页旁白", "visual_type": "process",
                 "elements": [{"id": "e1", "type": "flow_step", "steps": ["s1", "s2"]},
                              {"id": "e2", "type": "text", "text": "补充正文甲"}]},
                {"narration": "乙页旁白", "visual_type": "illustration",
                 "elements": [{"id": "e1", "type": "icon_group", "items": ["x", "y"]},
                              {"id": "e2", "type": "text", "text": "补充正文乙"}]},
            ], ensure_ascii=False)
        monkeypatch.setattr("textbook2video.pipeline.storyboard.chat_with_system", fake)
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "原旁白。", "visual_type": "process",
            "elements": [
                {"id": "e1", "type": "heading", "text": "H"},
                {"id": "e2", "type": "flow_step", "steps": ["1"]},
                {"id": "e3", "type": "icon_group", "items": ["A"]},
            ],
        }
        out = split_overlapping_segments([seg])
        assert len(out) == 2
        # 每页各只含一个列举 widget（LLM 改写后无重叠）
        for s in out:
            ts = {e["type"] for e in s["elements"]}
            assert not ({"flow_step", "icon_group"} <= ts)
        assert any("补充正文" in e.get("text", "") for s in out for e in s["elements"])

    def test_thin_half_llm_fail_keeps_merged(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("ECNU 挂了")
        monkeypatch.setattr("textbook2video.pipeline.storyboard.chat_with_system", boom)
        from textbook2video.pipeline.storyboard import split_overlapping_segments
        seg = {
            "id": 1, "narration": "原旁白。", "visual_type": "process",
            "elements": [
                {"id": "e1", "type": "heading", "text": "H"},
                {"id": "e2", "type": "flow_step", "steps": ["1"]},
                {"id": "e3", "type": "icon_group", "items": ["A"]},
            ],
        }
        assert len(split_overlapping_segments([seg])) == 1   # LLM 失败 → 不拆


def test_generate_storyboard_enriches_lesson_plan_teaching_pages(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "算法是一组明确步骤。",
                    "visual_type": "definition",
                    "elements": [{"id": "e1", "type": "heading", "text": "算法"}],
                    "animations": [],
                }
            ]
        }, ensure_ascii=False)

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    monkeypatch.setenv("T2V_NO_SPLIT", "1")
    monkeypatch.setenv("T2V_ENABLE_STORYBOARD_ENHANCER", "1")

    result = sb_mod.generate_storyboard(
        ["算法是一组明确步骤。"],
        lesson_title="算法",
        lesson_plan={
            "objectives": ["理解算法"],
            "knowledge_points": [{"id": "kp1", "name": "算法定义", "description": "明确步骤"}],
            "activities": ["举一个生活中的算法例子"],
            "assessment_questions": [{"question": "什么是算法？", "knowledge_point_ids": ["kp1"]}],
        },
    )

    roles = [seg.get("pedagogical_role") for seg in result["segments"]]
    assert roles[-3:] == ["reflection_activity", "knowledge_check", "lesson_summary"]
    assert result["metadata"]["total_slides"] == 4


def test_enhance_storyboard_quality_removes_title_echo_and_adds_structure():
    from textbook2video.pipeline.storyboard import enhance_storyboard_quality

    storyboard = {
        "segments": [
            {
                "id": 1,
                "visual_type": "definition",
                "knowledge_point_ids": ["kp1"],
                "narration": "A learning platform is useful only when it changes the learning activity.",
                "elements": [
                    {"id": "e1", "type": "heading", "text": "Learning platform"},
                    {"id": "e2", "type": "text", "text": "Learning platform"},
                ],
                "animations": [{"target": "e1", "effect": "fadeInUp"}, {"target": "e2", "effect": "fadeInUp"}],
            }
        ],
        "metadata": {"total_slides": 1},
    }
    plan = {
        "knowledge_points": [
            {
                "id": "kp1",
                "name": "Learning platform",
                "description": "A digital environment that supports resources, interaction, tracking, and feedback.",
            }
        ]
    }

    enhanced = enhance_storyboard_quality(storyboard, plan)
    seg = enhanced["segments"][0]
    elements = seg["elements"]

    assert not any(
        el.get("type") == "text" and el.get("text") == "Learning platform"
        for el in elements
    )
    assert any(el.get("type") == "comparison_panel" for el in elements)
    assert any(el.get("type") == "quote" for el in elements)
    assert enhanced["metadata"]["storyboard_quality_enhanced"] == 1
    assert {anim["target"] for anim in seg["animations"]} == {el["id"] for el in elements}


def test_enhance_storyboard_quality_removes_redundant_comparison_panel():
    from textbook2video.pipeline.storyboard import enhance_storyboard_quality

    storyboard = {
        "segments": [
            {
                "id": 1,
                "visual_type": "definition",
                "narration": "ABCDE elements describe educational technology.",
                "elements": [
                    {"id": "e1", "type": "heading", "text": "ABCDE"},
                    {"id": "e2", "type": "icon_group", "items": ["A", "B", "C", "D", "E"]},
                    {"id": "e3", "type": "comparison_panel", "items": [{"title": "A", "content": "B"}]},
                    {"id": "e4", "type": "text", "text": "A concise explanation."},
                    {"id": "e5", "type": "quote", "text": "Keep it focused."},
                ],
                "animations": [{"target": "e3", "effect": "fadeInUp"}],
            }
        ],
        "metadata": {"total_slides": 1},
    }

    enhanced = enhance_storyboard_quality(storyboard)
    seg = enhanced["segments"][0]

    assert not any(el.get("type") == "comparison_panel" for el in seg["elements"])
    assert any(el.get("type") == "icon_group" for el in seg["elements"])
    assert {anim["target"] for anim in seg["animations"]} == {el["id"] for el in seg["elements"]}


def test_generate_storyboard_runs_quality_enhancer(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "Cloud classrooms should be judged by interaction and feedback, not by devices alone.",
                    "visual_type": "definition",
                    "knowledge_point_ids": ["kp1"],
                    "elements": [
                        {"id": "e1", "type": "heading", "text": "Cloud classroom"},
                        {"id": "e2", "type": "text", "text": "Cloud classroom"},
                    ],
                    "animations": [],
                }
            ]
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    monkeypatch.setenv("T2V_NO_SPLIT", "1")
    monkeypatch.setenv("T2V_ENABLE_STORYBOARD_ENHANCER", "1")

    result = sb_mod.generate_storyboard(
        ["Cloud classrooms should change interaction and feedback."],
        lesson_title="Cloud classroom",
        lesson_plan={
            "knowledge_points": [
                {
                    "id": "kp1",
                    "name": "Cloud classroom",
                    "description": "A connected learning environment with resources, interaction, and feedback.",
                }
            ],
        },
    )

    seg = result["segments"][0]
    assert result["metadata"]["storyboard_quality_enhanced"] >= 1
    assert any(el.get("type") == "comparison_panel" for el in seg["elements"])
    assert not any(
        el.get("type") == "text" and el.get("text") == "Cloud classroom"
        for el in seg["elements"]
    )


def test_generate_storyboard_drops_hallucinated_image_src(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "Data can support learning diagnosis.",
                    "visual_type": "illustration",
                    "elements": [
                        {"id": "e1", "type": "heading", "text": "Learning diagnosis"},
                        {
                            "id": "e2",
                            "type": "image",
                            "src": "images/fake-local-file.png",
                            "description": "A dashboard showing learning diagnosis.",
                        },
                    ],
                    "animations": [],
                }
            ]
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    monkeypatch.setenv("T2V_NO_SPLIT", "1")

    result = sb_mod.generate_storyboard(
        ["Data can support learning diagnosis."],
        lesson_title="Learning diagnosis",
        available_images=[],
    )

    image = next(el for el in result["segments"][0]["elements"] if el.get("type") == "image")
    assert "src" not in image
    assert image["description"] == "A dashboard showing learning diagnosis."


def test_generate_storyboard_adds_description_for_empty_hallucinated_image(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "Data can support learning diagnosis.",
                    "visual_type": "illustration",
                    "elements": [
                        {"id": "e1", "type": "heading", "text": "Learning diagnosis"},
                        {"id": "e2", "type": "image", "src": "images/fake-local-file.png"},
                    ],
                    "animations": [],
                }
            ]
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    monkeypatch.setenv("T2V_NO_SPLIT", "1")

    result = sb_mod.generate_storyboard(
        ["Data can support learning diagnosis."],
        lesson_title="Learning diagnosis",
        available_images=[],
    )

    image = next(el for el in result["segments"][0]["elements"] if el.get("type") == "image")
    assert "src" not in image
    assert image["description"] == "Learning diagnosis"


def test_generate_storyboard_refreshes_stale_animation_targets(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "Data supports learning diagnosis.",
                    "visual_type": "definition",
                    "elements": [
                        {"id": "s1_e1", "type": "heading", "text": "Diagnosis"},
                        {"id": "s1_e2", "type": "text", "text": "A richer explanation."},
                    ],
                    "animations": [
                        {"target": "e1", "effect": "fadeInUp"},
                        {"target": "e2", "effect": "fadeInUp"},
                    ],
                }
            ]
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    monkeypatch.setenv("T2V_NO_SPLIT", "1")

    result = sb_mod.generate_storyboard(
        ["Data supports learning diagnosis."],
        lesson_title="Diagnosis",
    )

    seg = result["segments"][0]
    element_ids = {el["id"] for el in seg["elements"]}
    animation_targets = {anim["target"] for anim in seg["animations"]}
    assert animation_targets == element_ids


def test_generate_storyboard_refreshes_stale_timeline_targets(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "segments": [
                {
                    "id": 1,
                    "narration": "Data supports learning diagnosis.",
                    "visual_type": "definition",
                    "elements": [
                        {"id": "s1_e1", "type": "heading", "text": "Diagnosis"},
                        {"id": "s1_e2", "type": "text", "text": "A richer explanation."},
                    ],
                    "animations": [],
                    "timeline": [
                        {"at_sec": 0.0, "action": "show", "target": "e1"},
                        {"at_sec": 1.0, "action": "show", "target": "e2,e99"},
                    ],
                }
            ]
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    monkeypatch.setenv("T2V_NO_SPLIT", "1")

    result = sb_mod.generate_storyboard(
        ["Data supports learning diagnosis."],
        lesson_title="Diagnosis",
    )

    assert result["segments"][0]["timeline"] == [
        {"at_sec": 0.0, "action": "show", "target": "s1_e1"},
        {"at_sec": 1.0, "action": "show", "target": "s1_e2,e99"},
    ]


def test_storyboard_agent_review_pass_records_metadata(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        assert "Review Agent" in user_content
        return json.dumps({
            "pass": True,
            "severity": "pass",
            "issues": [],
            "summary": "ready",
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    storyboard = {
        "lesson_title": "Test",
        "segments": [
            {"id": 1, "narration": "n", "visual_type": "definition", "elements": [], "animations": []}
        ],
        "metadata": {"total_slides": 1},
    }

    result = sb_mod.run_storyboard_agent_review(storyboard, max_rounds=2)

    assert result["metadata"]["agent_review"]["status"] == "passed"
    assert result["metadata"]["agent_review"]["rounds"] == 1
    assert result["metadata"]["agent_review"]["reviews"][0]["summary"] == "ready"


def test_storyboard_agent_review_repairs_then_passes(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    calls = []

    def fake_chat_with_system(user_content, **kwargs):
        calls.append(user_content)
        if "Review Agent" in user_content and len(calls) == 1:
            return json.dumps({
                "pass": False,
                "severity": "major",
                "issues": [{"slide": 1, "type": "thin_page", "message": "too thin"}],
                "summary": "needs repair",
            })
        if "Repair Agent" in user_content:
            return json.dumps({
                "lesson_title": "Test",
                "segments": [
                    {
                        "id": 1,
                        "narration": "n",
                        "visual_type": "definition",
                        "elements": [
                            {"id": "e1", "type": "heading", "text": "Concept"},
                            {"id": "e2", "type": "text", "text": "A richer explanation."},
                            {"id": "e3", "type": "comparison_panel", "items": ["before", "after"]},
                        ],
                        "animations": [],
                    }
                ],
                "metadata": {"total_slides": 1},
            })
        return json.dumps({
            "pass": True,
            "severity": "pass",
            "issues": [],
            "summary": "fixed",
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    storyboard = {
        "lesson_title": "Test",
        "segments": [
            {
                "id": 1,
                "narration": "n",
                "visual_type": "definition",
                "elements": [{"id": "e1", "type": "heading", "text": "Concept"}],
                "animations": [],
            }
        ],
        "metadata": {"total_slides": 1},
    }

    result = sb_mod.run_storyboard_agent_review(storyboard, max_rounds=2)

    assert len(calls) == 3
    assert result["metadata"]["agent_review"]["status"] == "passed"
    assert result["metadata"]["agent_review"]["rounds"] == 2
    assert any(el.get("type") == "comparison_panel" for el in result["segments"][0]["elements"])


def test_storyboard_agent_review_strict_blocks_failed_review(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        return json.dumps({
            "pass": False,
            "severity": "blocker",
            "issues": [{"slide": 1, "type": "other", "message": "not ready"}],
            "summary": "blocked",
        })

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    storyboard = {
        "lesson_title": "Test",
        "segments": [
            {"id": 1, "narration": "n", "visual_type": "definition", "elements": [], "animations": []}
        ],
        "metadata": {"total_slides": 1},
    }

    with pytest.raises(RuntimeError, match="agent review failed"):
        sb_mod.run_storyboard_agent_review(storyboard, max_rounds=1, strict=True)


def test_storyboard_agent_review_keeps_storyboard_when_repair_json_is_bad(monkeypatch):
    from textbook2video.pipeline import storyboard as sb_mod

    def fake_chat_with_system(user_content, **kwargs):
        if "Review Agent" in user_content:
            return json.dumps({
                "pass": False,
                "severity": "major",
                "issues": [{"slide": 1, "type": "thin_page", "message": "too thin"}],
                "summary": "needs repair",
            })
        return '{"segments": ['

    monkeypatch.setattr(sb_mod, "chat_with_system", fake_chat_with_system)
    storyboard = {
        "lesson_title": "Test",
        "segments": [
            {"id": 1, "narration": "n", "visual_type": "definition", "elements": [], "animations": []}
        ],
        "metadata": {"total_slides": 1},
    }

    result = sb_mod.run_storyboard_agent_review(storyboard, max_rounds=2)

    review = result["metadata"]["agent_review"]["reviews"][0]
    assert result["metadata"]["agent_review"]["status"] == "failed"
    assert "repair_error" in review
    assert result["segments"] == storyboard["segments"]


def test_storyboard_review_prompt_allows_description_when_no_available_images():
    from textbook2video.pipeline.storyboard import _storyboard_review_prompt

    prompt = _storyboard_review_prompt(
        {
            "lesson_title": "Test",
            "segments": [],
            "metadata": {"available_images": []},
        },
        {"knowledge_points": [{"id": "kp1", "source_figures": ["fig8-5"]}]},
    )

    assert "available_images 为空" in prompt
    assert "不要因为 lesson plan 里提到 fig 编号就判 bad_image" in prompt
