"""Slide 提取鲁棒性测试（F1：栈匹配快路径 + 浏览器 DOM 兜底）。

覆盖 docs/fix-plan-json-to-html.md 根因 1 / 问题 P1·P4·P5：
- 平衡 HTML 走零开销栈匹配快路径，不启动浏览器；
- div 开闭不平衡（栈匹配返回空）时，浏览器 DOM 兜底补齐并提取；
- 浏览器不可用时优雅降级返回 []，不抛异常。
"""

import pytest

from textbook2video.animation_gen import (
    _EXTRACT_BROWSER_CHANNEL,
    _extract_slide_divs,
    _extract_slide_divs_browser,
    _extract_slide_divs_stack,
)


def _browser_available() -> bool:
    """用与兜底相同的 channel 探测浏览器可用性。"""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            launch_kwargs = {"headless": True}
            if _EXTRACT_BROWSER_CHANNEL:
                launch_kwargs["channel"] = _EXTRACT_BROWSER_CHANNEL
            browser = pw.chromium.launch(**launch_kwargs)
            browser.close()
        return True
    except Exception:
        return False


_HAS_BROWSER = _browser_available()
requires_browser = pytest.mark.skipif(
    not _HAS_BROWSER, reason="浏览器不可用，跳过浏览器兜底测试"
)


# 平衡的两页 slide
BALANCED = (
    '<div class="slide active"><div class="content-card"><h1>第一页</h1></div></div>'
    '<div class="slide"><div class="content-card"><h1>第二页</h1></div></div>'
)

# 单页 slide，但内部 4 层装饰 div 全部漏闭合——模拟报告中的 25 open / 21 close。
# 栈匹配会因 depth 永远到不了 0 而返回空列表。
UNBALANCED_SINGLE = (
    '<div class="slide active">'
    '<div class="a"><div class="b"><div class="c">'
    "<h1>标题文本</h1><p>正文内容</p>"
)


def test_balanced_html_uses_stack_fast_path():
    """平衡 HTML 由栈匹配直接提取，结果与组合入口一致。"""
    stack_slides = _extract_slide_divs_stack(BALANCED)
    assert len(stack_slides) == 2
    assert "第一页" in stack_slides[0]
    assert "第二页" in stack_slides[1]
    # 组合入口在快路径成功时返回相同结果
    assert _extract_slide_divs(BALANCED) == stack_slides


def test_unbalanced_html_returns_empty_on_stack_path():
    """不平衡 HTML 下栈匹配返回空——这正是 P1/P4 的故障点。"""
    assert _extract_slide_divs_stack(UNBALANCED_SINGLE) == []


@requires_browser
def test_unbalanced_html_recovered_by_browser_fallback():
    """栈匹配失败时，浏览器 DOM 兜底补齐并还原出 slide。"""
    slides = _extract_slide_divs(UNBALANCED_SINGLE)
    assert len(slides) == 1, f"期望 1 个 slide，实际 {len(slides)}"
    assert "标题文本" in slides[0]
    assert "正文内容" in slides[0]


@requires_browser
def test_browser_fallback_returns_top_level_slides_only():
    """浏览器兜底只返回顶层 slide，不因嵌套重复计数。"""
    slides = _extract_slide_divs_browser(BALANCED)
    assert len(slides) == 2


def test_browser_fallback_degrades_gracefully_when_browser_unavailable():
    """浏览器无法启动时返回 []，不抛异常（CI 无浏览器场景）。"""
    slides = _extract_slide_divs_browser(
        UNBALANCED_SINGLE, browser_channel="nonexistent-channel-xyz"
    )
    assert slides == []
