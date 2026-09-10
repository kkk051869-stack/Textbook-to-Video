from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from textbook2video.animation_ids import normalize_element_ids, resolve_element_targets
from textbook2video.animation_gen import build_slide_timelines
from textbook2video.animation_metrics import compute_animation_metrics
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
    assert resolve_element_targets("e1,e4", elements) == ["e2", "e4"]
    assert resolve_element_targets("e2", elements) == ["e2"]


def test_source_id_wins_over_legacy_positional_target():
    elements = normalize_element_ids([
        {"id": "e2", "type": "text"},
        {"id": "foo", "type": "text"},
    ])

    assert resolve_element_targets("e2", elements) == ["e2"]


def test_legacy_positional_target_is_used_after_custom_ids():
    elements = normalize_element_ids([
        {"id": "foo", "type": "text"},
        {"id": "bar", "type": "text"},
    ])

    assert resolve_element_targets("e2", elements) == ["bar"]


def test_repeated_normalize_preserves_original_source_id_mapping():
    elements = normalize_element_ids([{"id": "unsafe id", "type": "text"}])
    renormalized = normalize_element_ids(elements)

    assert renormalized[0]["_source_id"] == "unsafe id"
    assert resolve_element_targets("unsafe id", renormalized) == ["unsafeid"]


def test_original_unsafe_target_resolves_to_normalized_id():
    elements = normalize_element_ids([
        {"id": "unsafe id", "type": "text"},
        {"id": "safe", "type": "text"},
    ])

    assert [element["id"] for element in elements] == ["unsafeid", "safe"]
    assert resolve_element_targets("unsafe id", elements) == ["unsafeid"]
    assert resolve_element_targets('unsafe id"]{color:red}', elements, preserve_unresolved=True) == [
        "unsafeidcolorred"
    ]


def test_sanitize_collision_and_duplicate_original_ids_stay_deterministic():
    elements = normalize_element_ids([
        {"id": "a b", "type": "text"},
        {"id": "ab", "type": "text"},
        {"id": "same", "type": "text"},
        {"id": "same", "type": "text"},
    ])

    assert [element["id"] for element in elements] == ["ab", "e2", "same", "e4"]
    assert resolve_element_targets("a b", elements) == ["ab"]
    assert resolve_element_targets("ab", elements) == ["e2"]
    assert resolve_element_targets("same", elements) == ["same"]
    assert resolve_element_targets('ab"]{color:red}', elements, preserve_unresolved=True) == [
        "abcolorred"
    ]


def test_compiler_maps_unsafe_original_target_to_safe_dom_id():
    timelines = build_slide_timelines([{
        "id": "s04-unsafe",
        "elements": [{"id": "unsafe id", "type": "text", "text": "one"}],
        "timeline": [{"target": "unsafe id", "action": "show", "at_ms": 100}],
    }])

    assert timelines[0][0]["target"] == "unsafeid"
    assert timelines[0][0]["selector"] == '[data-anim-id="unsafeid"]'


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


def test_deterministic_renderer_does_not_claim_flip_move_support():
    html = render_slide(
        {
            "id": "move-template",
            "visual_type": "definition",
            "elements": [
                {"id": "heading", "type": "heading", "text": "Move"},
                {"id": "card", "type": "text", "text": "Position A"},
            ],
        },
        0,
        set(),
    )

    assert html is not None
    assert 'data-anim-id="card"' in html
    assert "data-flip-id" not in html
    assert "data-step" not in html


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


def test_stagger_zero_is_preserved_when_explicitly_requested():
    timelines = build_slide_timelines([{
        "id": "s03-zero",
        "elements": [
            {"id": "e1", "type": "text", "text": "one"},
            {"id": "e2", "type": "text", "text": "two"},
        ],
        "timeline": [{
            "at_ms": 100,
            "target": "e1,e2",
            "action": "show",
            "stagger": True,
            "stagger_ms": 0,
        }],
    }])

    assert [event["start_ms"] for event in timelines[0]] == [100, 100]


def test_unresolved_targets_are_retained_for_runtime_trace():
    timelines = build_slide_timelines([{
        "id": "s04",
        "elements": [{"id": "e1", "type": "text", "text": "one"}],
        "timeline": [
            {"target": "e9", "action": "show", "at_ms": 100},
            {"target": 'e1\"]', "action": "show", "at_ms": 200},
        ],
    }])

    assert [event["target"] for event in timelines[0]] == ["e9", "unresolved-e1"]
    assert all(event["selector"].startswith('[data-anim-id="') for event in timelines[0])


def test_compiler_rejects_action_outside_animation_event_schema(capsys):
    timelines = build_slide_timelines([{
        "id": "s05",
        "elements": [{"id": "e1", "type": "text", "text": "one"}],
        "timeline": [{"target": "e1", "action": "transform", "at_ms": 0}],
    }])

    assert timelines == [[]]
    assert "unsupported action rejected" in capsys.readouterr().out


def test_compiler_reports_overlapping_same_target_events_without_dropping_them(capsys):
    timelines = build_slide_timelines([{
        "id": "s07",
        "elements": [{"id": "e1", "type": "text", "text": "one"}],
        "timeline": [
            {"event_id": "first", "target": "e1", "action": "show", "at_ms": 100,
             "duration_ms": 300},
            {"event_id": "second", "target": "e1", "action": "highlight", "at_ms": 250,
             "duration_ms": 100},
        ],
    }])

    assert [event["event_id"] for event in timelines[0]] == ["first", "second"]
    assert "animation target time conflict" in capsys.readouterr().out


def test_compiler_suffixes_duplicate_event_ids_deterministically():
    timelines = build_slide_timelines([{
        "id": "s08",
        "elements": [{"id": "e1", "type": "text", "text": "one"}],
        "timeline": [
            {"event_id": "same", "target": "e1", "action": "show", "at_ms": 0},
            {"event_id": "same", "target": "e1", "action": "highlight", "at_ms": 100},
        ],
    }])

    assert [event["event_id"] for event in timelines[0]] == ["same", "same-2"]


def test_legacy_actions_are_normalized_to_schema_actions():
    timelines = build_slide_timelines([{
        "id": "s06",
        "elements": [{"id": "e1", "type": "text", "text": "one"}],
        "timeline": [
            {"target": "e1", "action": "pulse", "at_ms": 0},
            {"target": "e1", "action": "fadeOut", "at_ms": 100},
        ],
    }])

    assert [(event["action"], event["effect"]) for event in timelines[0]] == [
        ("highlight", "pulse"),
        ("show", "fadeOut"),
    ]


def test_animation_metrics_are_computable_from_plan_and_trace():
    planned = [
        {
            "event_id": "s1-a01",
            "action": "show",
            "effect": "fadeInUp",
            "start_ms": 100,
        },
        {
            "event_id": "s1-a02",
            "action": "highlight",
            "effect": "pulse",
            "start_ms": 200,
        },
        {
            "event_id": "s1-a03",
            "action": "show",
            "effect": "fadeInUp",
            "start_ms": 300,
        },
    ]
    trace = [
        {
            "event_id": "s1-a01", "status": "executed", "planned_ms": 100, "actual_ms": 110,
            "action": "show", "effect": "fadeInUp",
        },
        {"event_id": "s1-a02", "status": "target_missing", "planned_ms": 200, "actual_ms": 205},
        {"event_id": "s1-a03", "status": "cancelled", "planned_ms": 300, "actual_ms": 40},
    ]

    metrics = compute_animation_metrics(planned, trace)

    assert metrics["target_resolution_rate"] == 1 / 3
    assert metrics["effect_realization_rate"] == 1 / 3
    assert metrics["timing_mae_ms"] == 10
    assert metrics["unobserved_event_count"] == 0


def test_animation_metrics_deduplicate_repeated_trace_and_plan_ids():
    planned = [
        {"event_id": "same", "action": "show", "effect": "fadeInUp", "start_ms": 0},
        {"event_id": "same", "action": "show", "effect": "fadeInUp", "start_ms": 0},
    ]
    trace = [
        {"event_id": "same", "status": "executed", "planned_ms": 0, "actual_ms": 2,
         "action": "show", "effect": "fadeInUp"},
        {"event_id": "same", "status": "executed", "planned_ms": 0, "actual_ms": 3,
         "action": "show", "effect": "fadeInUp"},
    ]

    metrics = compute_animation_metrics(planned, trace)

    assert metrics["target_resolution_rate"] == 1.0
    assert metrics["effect_realization_rate"] == 1.0
    assert metrics["duplicate_planned_event_count"] == 1
    assert metrics["duplicate_trace_event_count"] == 1


def test_animation_metrics_scope_event_identity_by_slide_id():
    planned = [
        {"slide_id": "s1", "event_id": "event", "action": "show", "effect": "fadeInUp"},
        {"slide_id": "s2", "event_id": "event", "action": "show", "effect": "fadeInUp"},
    ]
    trace = [
        {"slide_id": "s1", "event_id": "event", "status": "executed",
         "planned_ms": 0, "actual_ms": 2, "action": "show", "effect": "fadeInUp"},
        {"slide_id": "s1", "event_id": "event", "status": "executed",
         "planned_ms": 0, "actual_ms": 3, "action": "show", "effect": "fadeInUp"},
        {"slide_id": "s2", "event_id": "event", "status": "executed",
         "planned_ms": 0, "actual_ms": 4, "action": "show", "effect": "fadeInUp"},
    ]

    metrics = compute_animation_metrics(planned, trace)

    assert metrics["target_total"] == 2
    assert metrics["target_resolution_rate"] == 1.0
    assert metrics["effect_realization_rate"] == 1.0
    assert metrics["duplicate_planned_event_count"] == 0
    assert metrics["duplicate_trace_event_count"] == 1
    assert metrics["unobserved_event_count"] == 0


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
        "downloadAnimationTrace",
        "target_missing",
        "unsupported_action",
        "runtime_error",
        "clearAnimationTimers",
        "start_ms",
        "duration_ms",
        "easing",
    ):
        assert marker in controller
