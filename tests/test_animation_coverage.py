from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from textbook2video.animation_ids import normalize_element_ids, resolve_element_targets
from textbook2video.animation_gen import build_slide_timelines
from textbook2video.template_renderer import render_slide


class _AnimIdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key == "data-anim-id" and value is not None:
                self.ids.append(value)


def _rendered_ids(html: str) -> list[str]:
    parser = _AnimIdParser()
    parser.feed(html)
    return parser.ids


def test_normalize_element_ids_fills_and_deduplicates_deterministically():
    elements = normalize_element_ids([
        {"type": "text"},
        {"id": "e1", "type": "text"},
        {"id": "unsafe id", "type": "text"},
        {"id": "e1", "type": "text"},
    ])

    assert [element["id"] for element in elements] == ["e1", "e2", "unsafeid", "e4"]
    assert resolve_element_targets("e1,e4", elements) == ["e1", "e4"]
    assert resolve_element_targets("e2", elements) == ["e2"]


def test_common_element_types_emit_unique_data_anim_ids():
    samples = {
        "heading": {"type": "heading", "id": "e1", "text": "标题"},
        "subheading": {"type": "subheading", "id": "e1", "text": "副标题"},
        "text": {"type": "text", "id": "e1", "text": "正文"},
        "quote": {"type": "quote", "id": "e1", "text": "金句"},
        "icon_group": {"type": "icon_group", "id": "e1", "items": ["A", "B"]},
        "flow_step": {"type": "flow_step", "id": "e1", "steps": ["一", "二"]},
        "activity_step": {"type": "activity_step", "id": "e1", "steps": ["一", "二"]},
        "comparison_panel": {
            "type": "comparison_panel", "id": "e1",
            "items": [{"title": "A", "content": "x"}, {"title": "B", "content": "y"}],
        },
        "table": {"type": "table", "id": "e1", "headers": ["H"], "rows": [["v"]]},
        "badge": {"type": "badge", "id": "e1", "text": "标签"},
        "label": {"type": "label", "id": "e1", "text": "标注"},
        "highlight_box": {"type": "highlight_box", "id": "e1", "text": "强调"},
        "quiz_card": {
            "type": "quiz_card", "id": "e1",
            "questions": [{"question": "Q", "answer": "A"}],
        },
    }

    for element_type, element in samples.items():
        elements = [] if element_type == "heading" else [
            {"type": "heading", "id": "heading", "text": "标题"},
        ]
        elements.append(element)
        html = render_slide(
            {"id": 1, "visual_type": "definition", "elements": elements},
            0,
            set(),
        )
        assert html is not None, element_type
        ids = _rendered_ids(html)
        assert "e1" in ids, element_type
        assert len(ids) == len(set(ids)), element_type


def test_image_and_overlay_types_resolve_to_distinct_dom_ids():
    html = render_slide(
        {
            "id": 1,
            "visual_type": "illustration",
            "elements": [
                {"type": "image", "id": "img", "description": "图"},
                {"type": "focus_box", "id": "focus", "target": "img", "bbox": [0, 0, 1, 1]},
                {"type": "callout", "id": "callout", "target": "img", "bbox": [0, 0, 1, 1]},
            ],
        },
        0,
        {"1:img"},
    )
    assert html is not None
    assert _rendered_ids(html) == ["img", "focus", "callout"]


def test_timeline_compiler_preserves_structured_event_fields_and_stagger():
    timelines = build_slide_timelines([{
        "id": "s03",
        "elements": [
            {"id": "e1", "type": "text", "text": "one"},
            {"id": "e2", "type": "text", "text": "two"},
            {"id": "e3", "type": "text", "text": "three"},
        ],
        "timeline": [{
            "at_sec": 1.5,
            "target": "e2,e3",
            "action": "highlight",
            "effect": "pulse",
            "duration_ms": 900,
            "easing": "linear",
            "stagger": True,
        }],
    }])

    assert timelines[0] == [
        {
            "event_id": "s03-a01-1",
            "slide_id": "s03",
            "target": "e2",
            "selector": '[data-anim-id="e2"]',
            "action": "highlight",
            "effect": "pulse",
            "start_ms": 1500,
            "duration_ms": 900,
            "easing": "linear",
        },
        {
            "event_id": "s03-a01-2",
            "slide_id": "s03",
            "target": "e3",
            "selector": '[data-anim-id="e3"]',
            "action": "highlight",
            "effect": "pulse",
            "start_ms": 1700,
            "duration_ms": 900,
            "easing": "linear",
        },
    ]


def test_runtime_has_trace_and_explicit_failure_states():
    controller = (
        Path(__file__).parents[1]
        / "src"
        / "textbook2video"
        / "templates"
        / "slide-controller.js"
    ).read_text(encoding="utf-8")

    for marker in (
        "window.animationTrace",
        "target_missing",
        "unsupported_action",
        "runtime_error",
        "clearAnimationTimers",
        "start_ms",
        "duration_ms",
        "easing",
    ):
        assert marker in controller
