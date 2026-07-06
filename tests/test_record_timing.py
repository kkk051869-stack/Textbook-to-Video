from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recorder_uses_injected_slide_durations_for_auto_advance():
    source = (ROOT / "src" / "textbook2video" / "pipeline" / "recorder.py").read_text(
        encoding="utf-8"
    )

    assert "window.slideDurations" in source
    assert "using slideDurations for auto-advance" in source
    assert "transitionLeadMs = 500" in source
    assert "duration - transitionLeadMs" in source


def test_slide_controller_exposes_duration_metadata():
    source = (
        ROOT / "src" / "textbook2video" / "templates" / "slide-controller.js"
    ).read_text(encoding="utf-8")

    assert "slideDurations: window.slideDurations || []" in source
    assert "slideTimelines: window.slideTimelines || []" in source
