"""测试 AI 图片生成模块（分类 + 生成 + 批处理 + 注入）。"""

import json
from unittest.mock import MagicMock, patch

import pytest

from textbook2video.llm.image_gen import (
    classify_image_elements,
    generate_image,
    generate_images_for_storyboard,
)
from textbook2video.animation_gen import (
    build_scenes_description,
    inject_generated_images,
)


# ── classify_image_elements ──


class TestClassifyImageElements:

    def test_parses_valid_json(self):
        """Mock LLM 返回合法 JSON → 正确解析。"""
        mock_response = json.dumps([
            {"id": "e4", "category": "figurative"},
            {"id": "e3", "category": "abstract"},
        ])
        elements = [
            {"id": "e4", "description": "马拉松运动员冲过终点线"},
            {"id": "e3", "description": "简单的流程图"},
        ]
        with patch("textbook2video.llm.image_gen.chat_with_system", return_value=mock_response):
            result = classify_image_elements(elements)
        assert result == {"e4": "figurative", "e3": "abstract"}

    def test_falls_back_on_malformed(self):
        """Mock LLM 返回垃圾 → 全部默认 abstract。"""
        elements = [
            {"id": "e1", "description": "城市全景"},
            {"id": "e2", "description": "箭头连线"},
        ]
        with patch(
            "textbook2video.llm.image_gen.chat_with_system",
            return_value="this is not json at all",
        ):
            result = classify_image_elements(elements)
        assert result == {"e1": "abstract", "e2": "abstract"}

    def test_empty_input(self):
        """空列表 → 返回空 dict，不调用 LLM。"""
        with patch("textbook2video.llm.image_gen.chat_with_system") as mock_chat:
            result = classify_image_elements([])
        assert result == {}
        mock_chat.assert_not_called()

    def test_invalid_category_defaults_to_abstract(self):
        """未知分类值 → 默认 abstract。"""
        mock_response = json.dumps([
            {"id": "e1", "category": "unknown_type"},
        ])
        elements = [{"id": "e1", "description": "test"}]
        with patch("textbook2video.llm.image_gen.chat_with_system", return_value=mock_response):
            result = classify_image_elements(elements)
        assert result == {"e1": "abstract"}


# ── generate_image ──


class TestGenerateImage:

    def test_success(self):
        """Mock API → 返回 base64 字符串。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [{"b64_json": "iVBORw0KGgo..."}],
        }
        with patch("textbook2video.llm.image_gen.requests.post", return_value=mock_response):
            result = generate_image("一个快乐的机器人")
        assert result == "iVBORw0KGgo..."

    def test_failure_returns_none(self):
        """Mock API 抛异常 → 返回 None。"""
        with patch(
            "textbook2video.llm.image_gen.requests.post",
            side_effect=Exception("API error"),
        ):
            result = generate_image("test description")
        assert result is None


# ── generate_images_for_storyboard ──


class TestGenerateImagesForStoryboard:

    def test_mixed_elements(self):
        """混合元素：2 个 image 并列触发降级，都不生成 AI 图片。"""
        segments = [
            {
                "id": 1,
                "visual_type": "text",
                "narration": "test",
                "elements": [
                    {"type": "image", "id": "e1", "description": "马拉松运动员"},
                    {"type": "image", "id": "e2", "description": "简单箭头图"},
                    {"type": "heading", "text": "标题"},
                ],
                "animations": [],
            },
        ]
        classify_result = {"e1": "figurative", "e2": "abstract"}

        with patch(
            "textbook2video.llm.image_gen.classify_image_elements",
            return_value=classify_result,
        ):
            result = generate_images_for_storyboard(segments)

        # 2 个 image 并列 → 整页降级为 SVG，都不生成 AI 图片
        assert result == {}

    def test_no_image_elements(self):
        """无 image 元素 → 空 dict，0 API 调用。"""
        segments = [
            {
                "id": 1,
                "visual_type": "text",
                "narration": "test",
                "elements": [{"type": "heading", "text": "标题"}],
                "animations": [],
            },
        ]
        with patch("textbook2video.llm.image_gen.classify_image_elements") as mock_cls:
            result = generate_images_for_storyboard(segments)
        assert result == {}
        mock_cls.assert_not_called()


# ── build_scenes_description with generated_images ──


class TestBuildScenesDescriptionImages:

    def _segment(self, seg_id=1):
        return {
            "id": seg_id,
            "visual_type": "text",
            "audio_duration_sec": 5,
            "narration": "旁白内容",
            "elements": [
                {"type": "image", "id": "e4", "description": "马拉松运动员冲线"},
            ],
            "animations": [],
        }

    def test_with_generated_images(self):
        """有生成图片 → 输出含 {{IMG_eN}} 占位指令。"""
        seg = self._segment()
        generated = {"1:e4": "data:image/png;base64,FAKE"}
        result = build_scenes_description([seg], generated_images=generated)
        assert "已生成AI图片" in result
        assert "{{IMG_e4}}" in result

    def test_without_generated_images(self):
        """无生成图片 → 保持 '插图:' 原样。"""
        seg = self._segment()
        result = build_scenes_description([seg])
        assert "插图:" in result
        assert "已生成AI图片" not in result

    def test_with_empty_dict(self):
        """传空 dict → 保持 '插图:' 原样。"""
        seg = self._segment()
        result = build_scenes_description([seg], generated_images={})
        assert "插图:" in result


# ── inject_generated_images ──


class TestInjectGeneratedImages:

    def test_replaces_placeholder(self):
        """HTML 中的 {{IMG_e4}} 被替换为 <img>。"""
        slides = ['<div class="slide"><div class="anim">{{IMG_e4}}</div></div>']
        batch = [
            {
                "id": 1,
                "elements": [
                    {"type": "image", "id": "e4", "description": "运动员"},
                ],
            },
        ]
        generated = {"1:e4": "data:image/png;base64,FAKEDATA"}
        result = inject_generated_images(slides, batch, generated)
        assert len(result) == 1
        assert "<img src=" in result[0]
        assert "FAKEDATA" in result[0]
        assert "{{IMG_e4}}" not in result[0]

    def test_no_images_passthrough(self):
        """空 dict → slides 不变。"""
        slides = ['<div class="slide"><p>content</p></div>']
        batch = [{"id": 1, "elements": []}]
        result = inject_generated_images(slides, batch, {})
        assert result == slides

    def test_missing_placeholder_prints_warning(self, capsys):
        """占位符不在 HTML 中 → 打印警告，slide 不变。"""
        slides = ['<div class="slide"><p>no placeholder here</p></div>']
        batch = [
            {
                "id": 1,
                "elements": [
                    {"type": "image", "id": "e5", "description": "test"},
                ],
            },
        ]
        generated = {"1:e5": "data:image/png;base64,FAKEDATA"}
        result = inject_generated_images(slides, batch, generated)
        assert "{{IMG_e5}}" not in result[0]
        assert "FAKEDATA" not in result[0]
        captured = capsys.readouterr()
        assert "未找到占位符" in captured.out
