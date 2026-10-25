"""Decode actual MP4 pixels; browser observations alone cannot prove media time."""

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error, sync_playwright

from textbook2video.pipeline import recorder, recording_clock
from textbook2video.pipeline.recorder import (
    _ffmpeg_executable,
    _record_calibrated,
    record_html_to_video,
)
from textbook2video.pipeline.recording_clock import (
    START_COLORS,
    _slate,
    media_interval,
    validate_options,
    validate_runtime,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser_channel():
    with sync_playwright() as pw:
        for channel in ("msedge", None):
            try:
                browser = pw.chromium.launch(channel=channel)
                browser.close()
                return channel
            except Error:
                continue
    pytest.skip("No Chromium browser available")


def lesson_html(*, load_delay=False, block=False, event_ms=700):
    controller = (ROOT / "src/textbook2video/templates/slide-controller.js").read_text(
        encoding="utf-8"
    )
    delay = (
        "const until=performance.now()+750;while(performance.now()<until){};" if load_delay else ""
    )
    blocker = (
        """setTimeout(() => {
        const until=performance.now()+350;while(performance.now()<until){};
    }, BLOCK_AT);""".replace("BLOCK_AT", "600" if block == "element" else "1900")
        if block
        else ""
    )
    return (
        """<!doctype html><meta charset="utf-8"><style>
    body{margin:0;background:black}.slide{display:none;position:absolute;inset:0}
    .slide.active,.slide.transition-exit{display:block}
    .anim{opacity:0;position:absolute;left:0;top:0;width:80px;height:80px;background:white}
    .anim.show{opacity:1;animation:probeReveal 50ms}
    @keyframes probeReveal{from{opacity:0}to{opacity:1}}
    </style><div class="slide active" style="background:red">
    <div class="anim" data-anim-id="e0"></div></div>
    <div class="slide" style="background:lime"></div>
    <div class="slide" style="background:blue"></div>
    <script>"""
        + delay
        + """
    window.slideDurations=[2000,2000,2000];
    window.slideTimelines=[[{selector:'[data-anim-id="e0"]',at_ms:EVENT_MS}],[],[]];
    </script><script>"""
        + controller
        + """</script><script>
    const originalStart=SlideController.startRecording;
    SlideController.startRecording=() => {originalStart();"""
        + blocker
        + """};
    </script>"""
    ).replace("EVENT_MS", str(event_ms))


def decode(video, crop):
    return subprocess.run(
        [
            _ffmpeg_executable(),
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps=30,{crop},scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout


@pytest.mark.parametrize("load_delay,event_ms", [(False, 700), (True, 1800)])
def test_actual_mp4_page_and_element_times(tmp_path, browser_channel, load_delay, event_ms):
    html, video = tmp_path / "lesson.html", tmp_path / "lesson.mp4"
    html.write_text(lesson_html(load_delay=load_delay, event_ms=event_ms), encoding="utf-8")
    record_html_to_video(
        str(html),
        str(video),
        duration=6,
        fps=30,
        browser_channel=browser_channel,
        viewport_width=320,
        viewport_height=180,
        trace_path=str(tmp_path / "runtime.json"),
    )
    raw = decode(video, "crop=10:10:150:100")
    pixels = [raw[i : i + 3] for i in range(0, len(raw), 3)]
    assert abs(len(pixels) / 30 - 6) <= 0.12
    for channel, expected in ((1, 2), (2, 4)):
        first = next(
            i / 30 for i, p in enumerate(pixels) if p[channel] > 200 and sum(p) - p[channel] < 60
        )
        assert abs(first - expected) <= 0.12
    assert pixels[0][0] > 200 and pixels[-1][2] > 200
    element = decode(video, "crop=10:10:20:20")
    first_white = next(i / 90 for i in range(0, len(element), 3) if min(element[i : i + 3]) > 220)
    assert abs(first_white - event_ms / 1000) <= 0.12
    report = json.loads(video.with_suffix(".clock.json").read_text())
    assert report["status"] == "CALIBRATED"
    assert report["media"]["time_stretch"] is False
    assert video.with_suffix(".raw.webm").is_file()


@pytest.mark.parametrize("block", ["page", "element"])
def test_runtime_stall_is_rejected_and_raw_is_preserved(tmp_path, browser_channel, block):
    html, video = tmp_path / "stall.html", tmp_path / "stall.mp4"
    html.write_text(lesson_html(block=block), encoding="utf-8")
    with pytest.raises(ValueError, match="Late"):
        record_html_to_video(
            str(html),
            str(video),
            duration=6,
            browser_channel=browser_channel,
            viewport_width=320,
            viewport_height=180,
        )
    assert not video.exists()
    assert video.with_suffix(".raw.webm").is_file()
    assert json.loads(video.with_suffix(".clock.json").read_text())["status"] == "FAILED"


@pytest.mark.parametrize("duration,fps", [(0, 30), (float("nan"), 30), (2, 0), (2, True)])
def test_invalid_recording_options(duration, fps):
    with pytest.raises(ValueError):
        validate_options(duration, fps)


def test_missing_runtime_page_cannot_be_published():
    with pytest.raises(ValueError):
        validate_runtime(
            {"done": True, "pages": [], "actual_end_ms": 6000}, expected_pages=3, duration=6
        )


def test_slate_recognizes_vp8_desaturation_but_rejects_blank_and_incomplete():
    colors = [(253, 0, 252), (90, 211, 211), (251, 252, 0), (75, 198, 77)]
    frame = bytearray(192)
    for (x, y), color in zip(((1, 1), (6, 1), (1, 6), (6, 6)), colors):
        frame[(y * 8 + x) * 3 : (y * 8 + x) * 3 + 3] = bytes(color)
    assert _slate(bytes(frame), START_COLORS)
    assert not _slate(bytes([255] * 192), START_COLORS)
    assert not _slate(b"", START_COLORS)


def test_existing_result_is_never_overwritten(tmp_path):
    video = tmp_path / "old.mp4"
    video.write_bytes(b"previous evidence")
    with pytest.raises(FileExistsError):
        record_html_to_video("not-needed.html", str(video), duration=6)
    assert video.read_bytes() == b"previous evidence"


@pytest.mark.parametrize("fail_report", [False, True])
def test_cleanup_failure_still_saves_raw_and_preserves_primary_error(
    tmp_path, monkeypatch, fail_report
):
    capture = tmp_path / "browser.webm"
    capture.write_bytes(b"raw recording")
    closed = []

    def playback(*args):
        raise ValueError("primary playback failure")

    def close_context():
        raise RuntimeError("secondary cleanup failure")

    page = SimpleNamespace(video=SimpleNamespace(path=lambda: str(capture)), evaluate=playback)
    if fail_report:

        def unwritable(*args):
            raise OSError("report write failed")

        monkeypatch.setattr(recorder, "save_clock", unwritable)
    with pytest.raises(ValueError, match="primary playback failure") as caught:
        _record_calibrated(
            page,
            SimpleNamespace(close=close_context),
            SimpleNamespace(close=lambda: closed.append(True)),
            tmp_path / "lesson.mp4",
            duration=6,
            fps=30,
            html_path=tmp_path / "lesson.html",
            trace_path=None,
        )
    assert closed == [True]
    assert (tmp_path / "lesson.raw.webm").read_bytes() == b"raw recording"
    if fail_report:
        assert any("report could not be written" in note for note in caught.value.__notes__)
    else:
        assert json.loads((tmp_path / "lesson.clock.json").read_text())["cleanup_errors"]


def test_loading_failure_also_closes_and_saves_evidence(tmp_path, monkeypatch):
    capture = tmp_path / "browser.webm"
    capture.write_bytes(b"partial load")
    closed = []

    def goto(*args):
        raise ValueError("load failed")

    page = SimpleNamespace(
        video=SimpleNamespace(path=lambda: str(capture)),
        goto=goto,
        add_init_script=lambda *a: None,
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: closed.append("context"))
    browser = SimpleNamespace(
        new_context=lambda **kw: context, close=lambda: closed.append("browser")
    )
    pw = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: browser))
    monkeypatch.setattr(recorder, "sync_playwright", lambda: nullcontext(pw))
    with pytest.raises(ValueError, match="load failed"):
        record_html_to_video("unused.html", str(tmp_path / "lesson.mp4"), duration=6)
    assert closed == ["context", "browser"]
    assert (tmp_path / "lesson.raw.webm").read_bytes() == b"partial load"
    assert json.loads((tmp_path / "lesson.clock.json").read_text())["stage"] == "load"


def test_low_output_fps_cannot_weaken_media_duration_gate(tmp_path, monkeypatch):
    def frame(colors):
        return bytes(v for y in range(8) for x in range(8) for v in colors[(y // 4) * 2 + x // 4])

    raw = frame(START_COLORS) * 30 + bytes(192) * 90 + frame(START_COLORS[::-1]) * 30

    def decode(*args, **kwargs):
        assert "fps=30,scale=8:8:flags=area" in args[0]
        return SimpleNamespace(stdout=raw)

    monkeypatch.setattr(recording_clock.subprocess, "run", decode)
    with pytest.raises(ValueError, match="Media clock mismatch"):
        media_interval(tmp_path / "raw.webm", ffmpeg="ffmpeg", duration=6, fps=1)
