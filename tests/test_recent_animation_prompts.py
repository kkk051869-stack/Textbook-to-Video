"""Prompt architecture regression tests."""

from pathlib import Path

from textbook2video.animation_gen import (
    COMPONENT_GUIDANCE_OMITTED,
    COMPONENTS_DIR,
    PROMPT_HARD_CHAR_LIMIT,
    PROMPTS_DIR,
    build_batch_prompt,
    build_component_guidance,
    build_layout_repair_prompt,
    build_slide_count_repair_prompt,
    load_component_guidance,
    load_prompt_template,
)
from textbook2video.themes import load_theme, theme_layout_prompt_section, theme_prompt_section


def _segment(visual_type: str = "network", narration: str = "unique narration") -> dict[str, object]:
    return {
        "id": 1,
        "visual_type": visual_type,
        "audio_duration_sec": 5,
        "narration": narration,
        "elements": [
            {"type": "heading", "text": "神经网络"},
            {"type": "text", "text": "输入、隐藏层和输出层协同工作。"},
        ],
        "animations": [{"target": "main", "effect": "fade in"}],
    }


def test_core_prompt_template_is_active_theme_neutral_and_compact():
    template = load_prompt_template("slide_content_core.md")

    assert len(template) <= 4500
    assert "{LESSON_TITLE}" in template
    assert "{LESSON_DESCRIPTION}" in template
    assert "{SCENES_DESCRIPTION}" in template
    assert "{COMPONENT_GUIDANCE}" in template
    for legacy_text in (
        "卡通趣味教育风",
        "糖果色系",
        "每页至少 8 个 `.anim` 元素",
        "所有内容必须包裹在 `.content-card`",
    ):
        assert legacy_text not in template


def test_storyboard_prompt_caps_total_element_types_at_four():
    prompt = (PROMPTS_DIR / "storyboard.md").read_text(encoding="utf-8")

    assert "1 种标题类 + 最多 3 种 body 类型" in prompt
    assert "补充信息优先写入 text" in prompt
    assert "最多 3-4 种不同 body 类型" not in prompt


def test_component_guidance_loads_summary_without_full_html():
    guidance = load_component_guidance("network")

    assert "network 组件参考" in guidance
    assert "<style>" not in guidance
    assert "<script>" not in guidance
    assert "<!DOCTYPE>" not in guidance


def test_component_guidance_dedupes_duplicate_visual_types():
    guidance = build_component_guidance([_segment("network"), _segment("network")])

    assert guidance.count("network 组件参考") == 1


def test_unknown_visual_type_uses_safe_fallback_in_batch_prompt():
    template = load_prompt_template("slide_content_core.md")
    prompt = build_batch_prompt(
        [_segment("unknown-type", "unknown visual narration")],
        template,
        "课程",
        "描述",
    )

    assert "visual_type=unknown-type: no component summary available" in prompt
    assert "unknown visual narration" in prompt


def test_batch_prompt_marks_narration_as_non_visible_reference():
    template = load_prompt_template("slide_content_core.md")
    prompt = build_batch_prompt(
        [_segment("network", "NON_VISIBLE_NARRATION_SENTINEL")],
        template,
        "课程",
        "描述",
    )

    assert "NON_VISIBLE_NARRATION_SENTINEL" in prompt
    assert "非可见参考旁白" in prompt
    assert "不得作为页面文字渲染" in prompt
    assert "不得作为任何可见 HTML 文本输出" in prompt
    assert "可见文字只能来自" in prompt


def test_core_prompt_prohibits_visible_narration_text():
    template = load_prompt_template("slide_content_core.md")

    assert "{SCENES_DESCRIPTION}" in template
    assert "旁白" in template
    assert "演讲稿" in template
    assert "非可见参考" in template
    assert "不得作为任何可见 HTML 文本输出" in template
    assert "可见文字只能来自" in template


def test_network_prompt_stays_under_hard_budget_with_theme_and_layout():
    theme = load_theme("dark-blue-academic")
    prompt = build_batch_prompt(
        [_segment("network", "network budget narration")],
        load_prompt_template("slide_content_core.md"),
        "AI 课程",
        "理解神经网络结构。",
        theme_prompt=theme_prompt_section(theme),
        layout_prompt=theme_layout_prompt_section(theme),
    )

    assert len(prompt) <= PROMPT_HARD_CHAR_LIMIT
    assert "network budget narration" in prompt
    assert "{COMPONENT_CODE}" not in prompt
    assert "{COMPONENT_GUIDANCE}" not in prompt
    assert (COMPONENTS_DIR / "network.html").read_text(encoding="utf-8").strip() not in prompt


def test_prompt_budget_preserves_scene_content_even_when_oversized():
    """With compression disabled (high limits), all content is preserved."""
    oversized_template = (
        load_prompt_template("slide_content_core.md")
        + "\n"
        + ("固定预算填充。" * 2500)
    )
    prompt = build_batch_prompt(
        [_segment("network", "must preserve this narration")],
        oversized_template,
        "预算测试",
        "描述",
    )

    assert "must preserve this narration" in prompt
    assert "神经网络" in prompt


def test_repair_template_is_compact_and_complete():
    template = load_prompt_template("slide_repair.md")

    assert len(template) <= 2200
    for placeholder in (
        "{SLIDE_COUNT}",
        "{LESSON_TITLE}",
        "{LESSON_DESCRIPTION}",
        "{SCENES_DESCRIPTION}",
        "{QA_SUMMARY}",
        "{FAILED_HTML}",
        "{PREVIOUS_BATCH_HTML}",
        "{THEME_PROMPT}",
        "{LAYOUT_PROMPT}",
    ):
        assert placeholder in template
    assert "{COMPONENT_CODE}" not in template
    assert "{COMPONENT_GUIDANCE}" not in template
    for forbidden_tag in ("markdown", "<!DOCTYPE>", "<html>", "<head>", "<body>", "<script>"):
        assert forbidden_tag in template


def test_layout_repair_prompt_is_compact_and_excludes_component_html():
    failed_html = '<div class="slide active"><div style="height:1200px">bad layout</div></div>'
    previous_html = [
        failed_html,
        '<div class="slide"><p>preserved slide</p></div>',
    ]
    prompt = build_layout_repair_prompt(
        lesson_title="课程",
        lesson_description="描述",
        batch=[_segment("network", "repair narration"), _segment("comparison", "second")],
        batch_start_index=0,
        batch_slides=previous_html,
        failed_global_indices=[1],
        qa_summary="QA 失败摘要: content_out_of_view",
        theme_prompt="## 当前风格约束\n- dark",
        layout_prompt="## 布局模式\n- fullscreen",
    )

    assert len(prompt) <= 4500
    assert "QA 失败摘要: content_out_of_view" in prompt
    assert failed_html in prompt
    assert "preserved slide" in prompt
    assert "## 当前风格约束" in prompt
    assert "## 布局模式" in prompt

    for component_html in Path(COMPONENTS_DIR).glob("*.html"):
        source = component_html.read_text(encoding="utf-8").strip()
        assert source not in prompt


def test_slide_count_repair_prompt_focuses_on_exact_batch_count():
    previous_html = (
        '<div class="slide"><p>kept style</p></div>'
        '<div class="slide"><p>extra page</p></div>'
    )
    prompt = build_slide_count_repair_prompt(
        lesson_title="课程",
        lesson_description="描述",
        batch=[_segment("network", "repair narration")],
        expected_count=1,
        actual_count=2,
        previous_batch_html=previous_html,
        theme_prompt="## 当前风格约束\n- dark",
        layout_prompt="## 布局模式\n- fullscreen",
    )

    assert "期望 slide 数量：1" in prompt
    assert "当前实际 slide 数量：2" in prompt
    assert "每个 segment 只能对应 1 个 slide" in prompt
    assert "不要静默删除内容" in prompt
    assert "repair narration" in prompt
    assert previous_html in prompt
    assert "## 当前风格约束" in prompt
    assert "## 布局模式" in prompt
    assert "不要输出 markdown、DOCTYPE、html、head、body、script" in prompt


def test_required_prompt_and_summary_files_exist():
    assert (PROMPTS_DIR / "slide_content_core.md").exists()
    assert (PROMPTS_DIR / "slide_repair.md").exists()
    for filename in (
        "network.summary.md",
        "comparison.summary.md",
        "flow.summary.md",
        "chart_line.summary.md",
    ):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 200 <= len(text) <= 600
