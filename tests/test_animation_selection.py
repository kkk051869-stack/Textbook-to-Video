import sys
import types
from pathlib import Path


sys.modules.setdefault(
    "textbook2video.llm.client",
    types.SimpleNamespace(chat=lambda *a, **k: ""),
)
sys.modules.setdefault(
    "textbook2video.pipeline.config",
    types.SimpleNamespace(
        DEFAULT_OUTPUT_DIR=Path("output"),
        LLM_DEFAULT_MODEL="test-model",
        RECORD_BROWSER_CHANNEL="chromium",
    ),
)
sys.modules.setdefault(
    "textbook2video.themes",
    types.SimpleNamespace(
        load_theme=lambda *_a, **_k: {
            "theme_id": "bright",
            "name": "Bright",
            "tokens": {},
            "layout": {"mode": "card"},
        },
        theme_to_css_vars=lambda *_a, **_k: "",
        theme_to_particle_config=lambda *_a, **_k: {},
        theme_prompt_section=lambda *_a, **_k: "",
        theme_layout_prompt_section=lambda *_a, **_k: "",
        theme_layout_mode=lambda *_a, **_k: "card",
    ),
)

from textbook2video.animation_gen import page_selection_suffix, select_segments_by_pages


def _segment(segment_id):
    return {"id": segment_id, "narration": f"slide {segment_id}"}


def test_select_segments_by_pages_preserves_order_and_dedupes():
    segments = [_segment(1), _segment(2), _segment(3)]

    selected = select_segments_by_pages(segments, [3, 1, 3])

    assert [seg["id"] for seg in selected] == [3, 1]


def test_select_segments_by_pages_rejects_out_of_range():
    segments = [_segment(1), _segment(2)]

    try:
        select_segments_by_pages(segments, [2, 4])
    except ValueError as exc:
        assert "有效范围 1-2" in str(exc)
    else:
        raise AssertionError("out-of-range page should be rejected")


def test_page_selection_suffix_is_stable():
    assert page_selection_suffix(None) == ""
    assert page_selection_suffix([3]) == "-p3"
    assert page_selection_suffix([2, 4, 4, 6]) == "-p2_4_6"
