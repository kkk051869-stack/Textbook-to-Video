"""测试动画生成中的布局 QA 回流辅助逻辑。"""

from pathlib import Path

import pytest

from textbook2video.animation_gen import (
    DEFAULT_SLIDE_DURATION_MS,
    MAX_BATCH_COUNT_REPAIR_ATTEMPTS,
    _duration_ms_for_segment,
    _escape_css_selector_value,
    _extract_slide_divs,
    _extract_slide_durations,
    _validate_storyboard_segments,
    _validate_slide_count,
    build_scenes_description,
    build_slide_timelines,
    failing_slide_indices,
    generate_batch_slides,
    infer_transitions,
    layout_report_path,
    merge_html,
    parse_storyboard,
    split_slides_html,
    summarize_layout_failures,
    validate_output,
)


def test_storyboard_validation_rejects_placeholder_narration():
    segments = [{
        "id": 1,
        "visual_type": "none",
        "narration": "（无内容）",
        "elements": [{"type": "heading", "text": "x"}],
    }]

    with pytest.raises(ValueError, match="无效占位内容"):
        _validate_storyboard_segments(segments)


def test_storyboard_validation_rejects_empty_elements():
    segments = [{
        "id": 1,
        "visual_type": "title",
        "narration": "有效旁白",
        "elements": [],
    }]

    with pytest.raises(ValueError, match="拒绝生成空白页"):
        _validate_storyboard_segments(segments)


def _segment(segment_id: int = 1, narration: str = "narration") -> dict[str, object]:
    return {
        "id": segment_id,
        "visual_type": "text",
        "audio_duration_sec": 5,
        "narration": narration,
        "elements": [{"type": "heading", "text": f"Slide {segment_id}"}],
        "animations": [],
    }


def _slide(label: str) -> str:
    return f'<div class="slide"><p>{label}</p></div>'


def test_failing_slide_indices_only_returns_failed_slides():
    report = {
        "slides": [
            {"index": 1, "passed": True},
            {"index": 2, "passed": False},
            {"index": 3, "passed": False},
        ]
    }

    assert failing_slide_indices(report) == [2, 3]


def test_summarize_layout_failures_keeps_blocking_details():
    report = {
        "viewport": {"width": 1920, "height": 1080},
        "staticRisks": [
            {"type": "child_height_100vh_present", "message": "HTML contains height:100vh"}
        ],
        "slides": [
            {"index": 1, "passed": True, "issues": []},
            {
                "index": 2,
                "passed": False,
                "issues": [
                    {"severity": "warn", "type": "content_out_of_safe_area"},
                    {
                        "severity": "fail",
                        "type": "content_out_of_view",
                        "rect": {"top": -44, "bottom": 1124},
                    },
                ],
            },
        ],
    }

    summary = summarize_layout_failures(report)

    assert "Viewport: 1920x1080" in summary
    assert "child_height_100vh_present" in summary
    assert "Slide 2 failed" in summary
    assert "content_out_of_view" in summary
    assert "content_out_of_safe_area" not in summary


def test_layout_report_path_names_initial_and_repair_attempts():
    output = Path("output/lesson-pipeline.html")

    assert layout_report_path(output, 0) == Path("output/lesson-pipeline.layout.json")
    assert layout_report_path(output, 2) == Path("output/lesson-pipeline.layout-repair2.json")


def test_split_slides_html_preserves_nested_divs():
    html = """
<div class="slide"><div><p>one</p></div></div>
<div class="slide"><div><p>two</p></div></div>
"""

    slides = split_slides_html(html)

    assert len(slides) == 2
    assert "one" in slides[0]
    assert "two" in slides[1]


def test_parse_storyboard_rejects_missing_segment_fields(tmp_path):
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(
        '{"segments": [{"id": 1, "narration": "hello"}]}',
        encoding="utf-8",
    )

    try:
        parse_storyboard(storyboard_path)
    except ValueError as exc:
        assert "visual_type" in str(exc)
    else:
        raise AssertionError("parse_storyboard should reject incomplete segments")


def test_parse_storyboard_rejects_total_slide_mismatch(tmp_path):
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(
        """
{
  "segments": [
    {"id": 1, "visual_type": "title", "narration": "hello", "elements": [{"type": "heading", "text": "hello"}], "animations": []}
  ],
  "metadata": {"total_slides": 2}
}
""",
        encoding="utf-8",
    )

    try:
        parse_storyboard(storyboard_path)
    except ValueError as exc:
        assert "total_slides" in str(exc)
    else:
        raise AssertionError("parse_storyboard should reject mismatched total_slides")


def test_duration_ms_for_segment_defaults_missing_duration():
    assert _duration_ms_for_segment({"id": 1}) == 5000


def test_duration_ms_for_segment_rejects_invalid_duration():
    for value in (0, -1, None, "5", True):
        try:
            _duration_ms_for_segment({"id": 1, "audio_duration_sec": value})
        except ValueError:
            pass
        else:
            raise AssertionError(f"duration should reject {value!r}")


def test_duration_ms_for_segment_converts_seconds_to_ms():
    assert _duration_ms_for_segment({"id": 1, "audio_duration_sec": 1.25}) == 1250


def test_validate_slide_count_rejects_missing_or_extra_slides():
    for slides in ([], ["<div class=\"slide\"></div>", "<div class=\"slide\"></div>"]):
        try:
            _validate_slide_count(slides, 1, "batch 1")
        except ValueError as exc:
            assert "batch 1" in str(exc)
        else:
            raise AssertionError("slide count mismatch should be rejected")


def test_generate_batch_slides_does_not_repair_valid_count():
    calls: list[str] = []

    def fake_generate(prompt: str, *, model: str, max_tokens: int, timeout: float = 180) -> str:
        assert model == "fake-model"
        assert max_tokens == 100
        calls.append(prompt)
        return _slide("valid")

    slides, custom_css = generate_batch_slides(
        prompt="original prompt",
        batch=[_segment()],
        lesson_title="课程",
        lesson_description="描述",
        theme_prompt="theme",
        layout_prompt="layout",
        model="fake-model",
        max_tokens=100,
        generate_fn=fake_generate,
    )

    assert len(slides) == 1
    assert "valid" in slides[0]
    assert custom_css == ""
    assert calls == ["original prompt"]


def test_generate_batch_slides_repairs_extra_slide_count():
    calls: list[str] = []

    def fake_generate(prompt: str, *, model: str, max_tokens: int, timeout: float = 180) -> str:
        assert model == "fake-model"
        assert max_tokens == 100
        calls.append(prompt)
        if len(calls) == 1:
            return _slide("wanted") + _slide("extra")
        return "<style>.fixed{color:red}</style>" + _slide("repaired")

    slides, custom_css = generate_batch_slides(
        prompt="original prompt",
        batch=[_segment()],
        lesson_title="课程",
        lesson_description="描述",
        theme_prompt="theme constraints",
        layout_prompt="layout constraints",
        model="fake-model",
        max_tokens=100,
        generate_fn=fake_generate,
    )

    assert len(slides) == 1
    assert "repaired" in slides[0]
    assert ".fixed{color:red}" in custom_css
    assert calls[0] == "original prompt"
    assert "期望 slide 数量：1" in calls[1]
    assert "当前实际 slide 数量：2" in calls[1]


def test_generate_batch_slides_failed_repair_raises_at_final_validation():
    calls: list[str] = []

    def fake_generate(prompt: str, *, model: str, max_tokens: int, timeout: float = 180) -> str:
        assert model == "fake-model"
        assert max_tokens == 100
        calls.append(prompt)
        return _slide("one") + _slide("two")

    try:
        slides, _custom_css = generate_batch_slides(
            prompt="original prompt",
            batch=[_segment()],
            lesson_title="课程",
            lesson_description="描述",
            theme_prompt="theme",
            layout_prompt="layout",
            model="fake-model",
            max_tokens=100,
            generate_fn=fake_generate,
        )
        _validate_slide_count(slides, 1, "batch 1")
    except ValueError as exc:
        assert "期望 1, 实际 2" in str(exc)
    else:
        raise AssertionError("final slide count validation should reject failed repair")
    # 1 次初始生成 + MAX_BATCH_COUNT_REPAIR_ATTEMPTS 次数量修复（全部返回错误数量）
    assert len(calls) == 1 + MAX_BATCH_COUNT_REPAIR_ATTEMPTS


def test_extract_slide_durations_reads_template_assignment():
    html = "<script>var slideDurations = [1000, 2500];</script>"

    assert _extract_slide_durations(html) == [1000, 2500]


def test_validate_output_requires_exact_slide_count_and_duration_match():
    html = """
<body data-layout="card" style="background:#fef9f2;">
<div class="slide-container">
  <div class="slide active"><div class="anim show">one</div></div>
  <div class="slide"><div class="anim">two</div></div>
</div>
<script>function SlideController(){}; var slideDurations = [1000, 2000];</script>
</body>
"""

    passing = validate_output(html, 2, expected_durations_ms=[1000, 2000])
    extra_slide = validate_output(html, 1, expected_durations_ms=[1000])
    bad_duration = validate_output(html, 2, expected_durations_ms=[1000, 3000])

    assert passing["checks"]["slide数量"] is True
    assert passing["checks"]["slideDurations匹配"] is True
    assert extra_slide["checks"]["slide数量"] is False
    assert bad_duration["checks"]["slideDurations匹配"] is False


# ============================================================
# active class 注入测试
# ============================================================

def _minimal_shell():
    return "{{SLIDES}}"


def _call_merge(slides_html_list: list[str]) -> str:
    """用最简 shell 调用 merge_html，只关注 slides 部分的 active 处理。"""
    return merge_html(
        all_slides=slides_html_list,
        custom_css_list=[],
        shell_template=(
            "<body>{{THEME_CSS_VARS}}{{THEME_BG_COLOR}}{{LAYOUT_MODE}}"
            "{{CSS_FRAMEWORK}}{{CUSTOM_CSS}}{{SLIDES}}"
            "{{PARTICLE_CANVAS}}{{JS_CONTROLLER}}{{JS_PARTICLES}}"
            "{{SLIDE_DURATIONS}}{{LESSON_TITLE}}</body>"
        ),
        css_framework="",
        js_controller="",
        js_particles="",
        durations_ms=[5000],
        title="test",
        theme=None,
    )


def test_merge_html_sets_active_on_multiclass_slide():
    """LLM 给 slide 加了额外类名时，首页仍能拿到 active。"""
    html = _call_merge(['<div class="slide intro"><p>page1</p></div>'])

    assert 'class="slide active intro"' in html


def test_merge_html_removes_existing_active_and_sets_first_only():
    """LLM 给非首页也加了 active 时，最终只有第一页是 active。"""
    slides = [
        '<div class="slide"><p>first</p></div>',
        '<div class="slide active"><p>second</p></div>',
    ]
    html = _call_merge(slides)

    assert html.count("active") == 1
    # active 应在包含 "first" 的 slide 中，而不是 "second"
    active_pos = html.find("active")
    first_pos = html.find("first")
    second_pos = html.find("second")
    assert active_pos < first_pos < second_pos


def test_merge_html_handles_active_before_slide_class():
    """class 属性中 active 在 slide 前面的情况。"""
    slides = [
        '<div class="slide"><p>first</p></div>',
        '<div class="active slide"><p>second</p></div>',
    ]
    html = _call_merge(slides)

    assert html.count("active") == 1
    first_slide_pos = html.find("first")
    active_pos = html.find("active")
    assert active_pos < first_slide_pos


# ============================================================
# build_scenes_description 健壮性测试
# ============================================================

def test_build_scenes_description_tolerates_missing_fields():
    """element 缺少预期字段时不崩溃。"""
    segments = [{
        "id": 1,
        "visual_type": "text",
        "narration": "test narration",
        "elements": [
            {"type": "heading"},  # 缺 text
            {"type": "icon_group"},  # 缺 items
            {"type": "comparison_panel"},  # 缺 items
            {"type": "flow_step"},  # 缺 steps
        ],
        "animations": [],
    }]

    result = build_scenes_description(segments)
    assert "标题:" in result
    assert "图标组:" in result


def test_build_scenes_description_does_not_leak_dict_repr():
    """未知类型不应把整个 dict 泄漏进 prompt。"""
    segments = [{
        "id": 1,
        "visual_type": "text",
        "narration": "test narration",
        "elements": [
            {"type": "custom_widget", "text": "hello", "secret_field": "should_not_appear"},
        ],
        "animations": [],
    }]

    result = build_scenes_description(segments)
    assert "custom_widget: hello" in result
    assert "secret_field" not in result
    assert "{" not in result


# ============================================================
# slide 提取: HTML 注释不干扰
# ============================================================

def test_extract_slide_divs_ignores_commented_divs():
    """HTML 注释中的 <div 不应影响 slide 提取。"""
    html = """
<!-- <div class="slide"><p>ghost</p></div> -->
<div class="slide"><p>real1</p></div>
<!-- <div>nested comment</div> -->
<div class="slide"><p>real2</p></div>
"""
    slides = _extract_slide_divs(html)

    assert len(slides) == 2
    assert "real1" in slides[0]
    assert "real2" in slides[1]
    assert "ghost" not in slides[0]


# ============================================================
# build_slide_timelines 测试
# ============================================================

def test_build_slide_timelines_extracts_trigger_at_sec():
    segments = [
        {
            "id": 1,
            "visual_type": "text",
            "narration": "hello",
            "elements": [],
            "animations": [
                {"target": "e1", "effect": "bounceIn", "trigger_at_sec": 0},
                {"target": "e2", "effect": "fadeInUp", "trigger_at_sec": 3.5},
            ],
        },
        {
            "id": 2,
            "visual_type": "definition",
            "narration": "world",
            "elements": [],
            "animations": [
                {"target": "e3", "effect": "fadeIn"},
            ],
        },
    ]

    timelines = build_slide_timelines(segments)

    assert len(timelines) == 2
    assert timelines[0] == [
        {"selector": '[data-anim-id="e1"]', "at_ms": 0},
        {"selector": '[data-anim-id="e2"]', "at_ms": 3500},
    ]
    assert timelines[1] == []


def test_build_slide_timelines_skips_invalid_trigger_values():
    segments = [
        {
            "id": 1,
            "visual_type": "text",
            "narration": "test",
            "elements": [],
            "animations": [
                {"target": "e1", "effect": "fadeIn", "trigger_at_sec": "not_a_number"},
                {"target": "", "effect": "fadeIn", "trigger_at_sec": 2.0},
                {"target": "e2", "effect": "fadeIn", "trigger_at_sec": 1.5},
            ],
        },
    ]

    timelines = build_slide_timelines(segments)

    assert len(timelines[0]) == 1
    assert timelines[0][0] == {"selector": '[data-anim-id="e2"]', "at_ms": 1500}


# ============================================================
# infer_transitions 测试
# ============================================================

def test_infer_transitions_maps_visual_types():
    segments = [
        {"id": 1, "visual_type": "title", "narration": ""},
        {"id": 2, "visual_type": "definition", "narration": ""},
        {"id": 3, "visual_type": "process", "narration": ""},
        {"id": 4, "visual_type": "unknown_type", "narration": ""},
    ]

    transitions = infer_transitions(segments)

    assert transitions == ["zoom", "dissolve", "push-left", "push-left"]


# ============================================================
# merge_html 注入 timelines/transitions 测试
# ============================================================

def test_merge_html_injects_timelines_and_transitions():
    shell = (
        "<body>{{THEME_CSS_VARS}}{{THEME_BG_COLOR}}{{LAYOUT_MODE}}"
        "{{CSS_FRAMEWORK}}{{CUSTOM_CSS}}{{SLIDES}}"
        "{{PARTICLE_CANVAS}}{{JS_CONTROLLER}}{{JS_PARTICLES}}"
        "{{SLIDE_DURATIONS}}{{SLIDE_TIMELINES}}{{SLIDE_TRANSITIONS}}"
        "{{LESSON_TITLE}}</body>"
    )
    timelines = [[{"selector": '[data-anim-id="e1"]', "at_ms": 500}], []]
    transitions = ["zoom", "push-left"]

    html = merge_html(
        all_slides=['<div class="slide"><p>one</p></div>'],
        custom_css_list=[],
        shell_template=shell,
        css_framework="",
        js_controller="",
        js_particles="",
        durations_ms=[5000],
        title="test",
        theme=None,
        timelines=timelines,
        transitions=transitions,
    )

    assert '"at_ms": 500' in html
    assert '"selector"' in html
    assert '["zoom", "push-left"]' in html


# ============================================================
# _escape_css_selector_value 测试
# ============================================================

def test_escape_css_selector_allows_safe_chars():
    assert _escape_css_selector_value("e1") == "e1"
    assert _escape_css_selector_value("elem-2") == "elem-2"
    assert _escape_css_selector_value("my_element") == "my_element"


def test_escape_css_selector_strips_dangerous_chars():
    assert _escape_css_selector_value('a"]') == "a"
    assert _escape_css_selector_value("e1;DROP") == "e1DROP"
    assert _escape_css_selector_value('<script>') == "script"


# ============================================================
# DEFAULT_SLIDE_DURATION_MS 常量一致性
# ============================================================

def test_default_duration_constant_matches_fallback():
    seg = {"id": 1, "narration": "test", "visual_type": "text", "elements": []}
    # 无 audio_duration_sec 时应返回 DEFAULT_SLIDE_DURATION_MS
    assert _duration_ms_for_segment(seg) == DEFAULT_SLIDE_DURATION_MS


# ============================================================
# build_slide_timelines 净化 selector 测试
# ============================================================

def test_build_slide_timelines_sanitizes_target():
    segments = [
        {
            "id": 1,
            "visual_type": "text",
            "narration": "test",
            "elements": [],
            "animations": [
                {"target": 'e1"]{color:red}', "effect": "fadeIn", "trigger_at_sec": 1.0},
            ],
        },
    ]

    timelines = build_slide_timelines(segments)

    # 危险字符被剥离
    assert timelines[0][0]["selector"] == '[data-anim-id="e1colorred"]'
