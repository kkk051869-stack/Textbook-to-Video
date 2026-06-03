"""教材原图加载测试（修复 storyboard src 在 animate 阶段被忽略的断链）。"""

import base64

from textbook2video.animation_gen import load_textbook_images

# 最小合法 1x1 PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
    "2mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_loads_referenced_textbook_image(tmp_path):
    """有 src 的 image 元素被读出并编码为 base64 data URI。"""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "fig1-1.png").write_bytes(_PNG)

    segments = [
        {
            "id": 3,
            "elements": [
                {"type": "image", "id": "e2", "src": "fig1-1.png", "description": "x"},
            ],
        }
    ]
    result = load_textbook_images(segments, img_dir)

    assert "3:e2" in result
    assert result["3:e2"].startswith("data:image/png;base64,")


def test_missing_image_file_is_skipped(tmp_path):
    """src 指向不存在的文件时跳过，不抛异常。"""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    segments = [{"id": 1, "elements": [{"type": "image", "id": "e1", "src": "nope.png"}]}]

    assert load_textbook_images(segments, img_dir) == {}


def test_nonexistent_dir_returns_empty(tmp_path):
    """image_dir 不存在时返回空字典。"""
    segments = [{"id": 1, "elements": [{"type": "image", "id": "e1", "src": "a.png"}]}]

    assert load_textbook_images(segments, tmp_path / "does-not-exist") == {}


def test_image_without_src_is_ignored(tmp_path):
    """无 src（AI 生成）的 image 元素不被本函数处理。"""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    segments = [{"id": 1, "elements": [{"type": "image", "id": "e1", "description": "ai 图"}]}]

    assert load_textbook_images(segments, img_dir) == {}
