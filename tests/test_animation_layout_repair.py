"""测试动画生成中的布局 QA 回流辅助逻辑。"""

from pathlib import Path

from textbook2video.animation_gen import (
    _duration_ms_for_segment,
    _extract_slide_durations,
    _validate_slide_count,
    failing_slide_indices,
    generate_batch_slides,
    layout_report_path,
    parse_storyboard,
    split_slides_html,
    summarize_layout_failures,
    validate_output,
)


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
    {"id": 1, "visual_type": "title", "narration": "hello", "elements": [], "animations": []}
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

    def fake_generate(prompt: str, *, model: str, max_tokens: int) -> str:
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

    def fake_generate(prompt: str, *, model: str, max_tokens: int) -> str:
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

    def fake_generate(prompt: str, *, model: str, max_tokens: int) -> str:
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
    assert len(calls) == 2


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
