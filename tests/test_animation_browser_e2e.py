from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from textbook2video.animation_gen import build_slide_timelines, merge_html
from textbook2video.template_renderer import render_slide
from textbook2video.themes import load_theme


ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "src" / "textbook2video" / "templates"


def _browser_executable(playwright) -> str | None:
    configured = os.environ.get("T2V_PLAYWRIGHT_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured

    default = Path(playwright.chromium.executable_path)
    if default.is_file():
        return str(default)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    cached = sorted(
        Path(local_app_data).glob("ms-playwright/chromium-*/chrome-win/chrome.exe"),
        reverse=True,
    )
    return str(cached[0]) if cached else None


@pytest.fixture(scope="module")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright is not installed")

    with sync_playwright() as playwright:
        executable = _browser_executable(playwright)
        if not executable:
            pytest.skip("No Chromium executable is available for Playwright")
        instance = playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            yield instance
        finally:
            instance.close()


def _segment(segment_id: str = "s1") -> dict:
    return {
        "id": segment_id,
        "visual_type": "definition",
        "elements": [
            {"id": "e1", "type": "heading", "text": "Runtime"},
            {"id": "e2", "type": "text", "text": "Browser trace"},
            {"id": "e3", "type": "text", "text": "Dim"},
            {"id": "e4", "type": "text", "text": "Focus"},
            {"id": "e5", "type": "text", "text": "Grow"},
            {"id": "e6", "type": "text", "text": "Draw"},
            {"id": "e7", "type": "text", "text": "Move"},
            {"id": "e8", "type": "text", "text": "Multi target"},
        ],
        "timeline": [
            {"event_id": "show-event", "target": "e1", "action": "show", "start_ms": 0,
             "duration_ms": 80, "easing": "linear"},
            {"event_id": "highlight-event", "target": "e2", "action": "highlight", "start_ms": 60,
             "duration_ms": 120, "easing": "ease-in"},
            {"event_id": "dim-event", "target": "e3", "action": "dim", "start_ms": 120},
            {"event_id": "focus-event", "target": "e4", "action": "focus", "start_ms": 180},
            {"event_id": "grow-event", "target": "e5", "action": "grow", "start_ms": 240},
            {"event_id": "draw-event", "target": "e6", "action": "draw", "start_ms": 300},
            {"event_id": "multi-event", "target": "e7,e8", "action": "show", "start_ms": 360,
             "stagger": True, "stagger_ms": 80},
            {"event_id": "move-event", "target": "e7", "action": "move", "effect": "legacy",
             "start_ms": 500, "duration_ms": 140, "easing": "linear"},
            {"event_id": "unsupported-move", "target": "e8", "action": "move", "effect": "legacy",
             "start_ms": 560},
            {"event_id": "unsupported-event", "target": "e1", "action": "show",
             "effect": "unsupportedEffect", "start_ms": 700},
        ],
    }


def _append_runtime_elements(slide_html: str) -> str:
    extra = """
    <div class="anim anim-card" data-anim-id="e3">dim</div>
    <div class="anim anim-card" data-anim-id="e4">focus</div>
    <div class="anim anim-card" data-anim-id="e5">grow</div>
    <div class="anim anim-card" data-anim-id="e6">
      <svg viewBox="0 0 100 40" width="100" height="40">
        <path class="svg-draw" style="--path-length:120" d="M2 35 L50 5 L98 35" stroke="black" fill="none" />
      </svg>
    </div>
    <div class="anim anim-card" data-anim-id="e7" data-flip-id="move-card" data-step="1">move</div>
    <div class="anim anim-card" data-anim-id="e8">multi</div>
    """
    insertion = slide_html.rfind("</div>")
    assert insertion >= 0
    return slide_html[:insertion] + extra + slide_html[insertion:]


def _runtime_html() -> str:
    segment = _segment()
    # Keep e1/e2 in the deterministic template and append the remaining
    # targets explicitly so the browser test does not introduce duplicate IDs.
    render_segment = {**segment, "elements": segment["elements"][:2]}
    rendered = render_slide(render_segment, 0, set())
    assert rendered is not None
    rendered = _append_runtime_elements(rendered)
    timeline = build_slide_timelines([segment])[0]
    timeline.append({
        "event_id": "missing-event",
        "slide_id": "s1",
        "target": "missing",
        "selector": '[data-anim-id="missing"]',
        "action": "show",
        "effect": "fadeInUp",
        "start_ms": 620,
        "duration_ms": 100,
        "easing": "ease-out",
    })
    return merge_html(
        [rendered],
        [],
        (TEMPLATES / "base-template.html").read_text(encoding="utf-8"),
        (TEMPLATES / "base.css").read_text(encoding="utf-8"),
        (TEMPLATES / "slide-controller.js").read_text(encoding="utf-8"),
        "",
        [1400],
        "animation browser e2e",
        theme=load_theme("bright"),
        timelines=[timeline],
        transitions=["push-left"],
    )


def _cancellation_html() -> str:
    first = _segment("cancel-1")
    first["timeline"] = [
        {"event_id": "already-executed", "target": "e1", "action": "show", "start_ms": 0},
        {"event_id": "cancel-me", "target": "e2", "action": "show", "start_ms": 1200},
    ]
    second = {
        "id": "cancel-2",
        "visual_type": "definition",
        "elements": [{"id": "e9", "type": "heading", "text": "Next slide"}],
    }
    first_html = render_slide(first, 0, set())
    second_html = render_slide(second, 1, set())
    assert first_html is not None and second_html is not None
    first_html = (
        first_html[:first_html.rfind("</div>")]
        + '<div class="anim anim-card" data-step="1" data-flip-id="legacy-step">step</div>'
        + first_html[first_html.rfind("</div"):]
    )
    return merge_html(
        [first_html, second_html],
        [],
        (TEMPLATES / "base-template.html").read_text(encoding="utf-8"),
        (TEMPLATES / "base.css").read_text(encoding="utf-8"),
        (TEMPLATES / "slide-controller.js").read_text(encoding="utf-8"),
        "",
        [2000, 1000],
        "animation cancellation e2e",
        theme=load_theme("bright"),
        timelines=[build_slide_timelines([first])[0], []],
        transitions=["push-left", "push-left"],
    )


def _trace_by_id(page) -> dict[str, dict]:
    trace = page.evaluate("window.animationTrace")
    return {entry["event_id"]: entry for entry in trace}


def test_real_browser_executes_compiled_animation_trace(browser):
    page = browser.new_page()
    try:
        page.set_content(_runtime_html(), wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        trace = _trace_by_id(page)
        expected_executed = {
            "show-event", "highlight-event", "dim-event", "focus-event", "grow-event",
            "draw-event", "multi-event-1", "multi-event-2", "move-event",
        }
        assert expected_executed <= trace.keys()
        assert all(trace[event_id]["status"] == "executed" for event_id in expected_executed)
        assert trace["show-event"]["duration_ms"] == 80
        assert trace["show-event"]["easing"] == "linear"
        assert trace["missing-event"]["status"] == "target_missing"
        assert trace["unsupported-event"]["status"] == "unsupported_action"
        assert trace["unsupported-move"]["status"] == "unsupported_action"

        assert page.locator('[data-anim-id="e1"]').evaluate("e => e.classList.contains('show')")
        assert page.locator('[data-anim-id="e2"]').evaluate(
            "e => e.classList.contains('event-highlight')"
        )
        assert page.locator('[data-anim-id="e3"]').evaluate("e => e.classList.contains('event-dim')")
        assert page.locator('[data-anim-id="e4"]').evaluate("e => e.classList.contains('event-focus')")
        assert page.locator('[data-anim-id="e5"]').evaluate("e => e.classList.contains('event-grow')")
        assert page.locator('[data-anim-id="e6"] .svg-draw').evaluate(
            "e => e.classList.contains('active-draw')"
        )
        assert page.locator('[data-anim-id="e7"]').evaluate("e => e.classList.contains('event-move')")
        assert page.locator('[data-anim-id="e7"]').evaluate("e => e.classList.contains('show')")
    finally:
        page.close()


def test_real_browser_exports_animation_trace_json(browser, tmp_path):
    page = browser.new_page()
    try:
        page.set_content(_runtime_html(), wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        with page.expect_download() as download_info:
            assert page.evaluate("window.downloadAnimationTrace()") == "animation_trace.json"
        download = download_info.value
        output = tmp_path / "animation_trace.json"
        download.save_as(str(output))

        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload == page.evaluate("window.animationTrace")
        assert payload and {"event_id", "planned_ms", "actual_ms", "status"} <= payload[0].keys()
    finally:
        page.close()


def test_free_html_without_anim_id_reports_target_missing(browser):
    page = browser.new_page()
    try:
        html = _runtime_html().replace(' data-anim-id="e1"', "", 1)
        page.set_content(html, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        trace = _trace_by_id(page)
        assert trace["show-event"]["status"] == "target_missing"
        assert "data-anim-id=\"e1\"" in trace["show-event"]["error"]
    finally:
        page.close()


def test_real_browser_cancels_pending_events_on_slide_switch(browser):
    page = browser.new_page()
    try:
        page.set_content(_cancellation_html(), wait_until="domcontentloaded")
        page.wait_for_timeout(100)
        page.evaluate("window.SlideController.go(1)")
        page.wait_for_timeout(750)

        trace = _trace_by_id(page)
        assert trace["already-executed"]["status"] == "executed"
        assert trace["cancel-me"]["status"] == "cancelled"
        assert trace["cancel-me"]["error"] == "Animation timer cancelled"
        assert trace["legacy-step-0-1"]["status"] == "cancelled"
        assert page.evaluate("window.SlideController.current()") == 1
        assert page.locator('[data-anim-id="e2"]').evaluate("e => e.classList.contains('show')") is False
        assert page.locator('[data-anim-id="e9"]').evaluate("e => e.classList.contains('show')")
    finally:
        page.close()
