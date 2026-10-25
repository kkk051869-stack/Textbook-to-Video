import importlib.util
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from textbook2video.pipeline.recorder import _ffmpeg_executable, record_html_to_video

script = Path(__file__).resolve().parents[1] / "scripts/extract_rendered_video_evidence.py"
spec = importlib.util.spec_from_file_location("rendered_extraction_test", script)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


@pytest.fixture(scope="module")
def recording_browser():
    with sync_playwright() as pw:
        for channel in ("msedge", None):
            try:
                browser = pw.chromium.launch(channel=channel)
                browser.close()
                return channel
            except BrowserError:
                continue
    pytest.skip("No Chromium browser available for recording-content evidence")


@pytest.mark.parametrize("fps,requested", [(30, 1), (24, 1), (30, 2)])
def test_real_raw_recording_silent_and_voiced_content_are_linked_and_wrong_video_rejected(
    tmp_path, fps, requested, recording_browser
):
    controller = (script.parents[1] / "src/textbook2video/templates/slide-controller.js").read_text(
        encoding="utf-8"
    )
    html = tmp_path / "lesson.html"
    html.write_text(
        "<!doctype html><style>body{margin:0}.slide{position:absolute;inset:0;display:none;"
        "background:#214160;color:white}.slide.active{display:block}</style>"
        '<div class="slide active"><h1>Recording content fixture</h1></div>'
        "<script>window.slideDurations=[1000];window.slideTimelines=[[]];</script><script>"
        + controller
        + "</script>",
        encoding="utf-8",
    )
    silent, final = tmp_path / "silent.mp4", tmp_path / "voiced.mp4"
    record_html_to_video(
        str(html),
        str(silent),
        duration=requested,
        fps=fps,
        viewport_width=640,
        viewport_height=360,
        browser_channel=recording_browser,
    )
    clock = json.loads(silent.with_suffix(".clock.json").read_text(encoding="utf-8"))
    ffmpeg, ffprobe = _ffmpeg_executable(), shutil.which("ffprobe") or "ffprobe"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-n",
            "-i",
            str(silent),
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(final),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "linked"
    out.mkdir()
    result = evidence.verify_recording_content(
        clock, silent, final, out, ffmpeg=ffmpeg, ffprobe=ffprobe
    )
    assert result["verified_content"] is True
    assert result["encoded_fps"] == fps
    assert "NOT_ORIGIN_ATTESTATION_OR_TIMING_ACCEPTANCE" in result["scope"]
    assert result["raw_sha256"] == evidence.sha(clock["raw_video"])
    assert evidence.clock_association_issues(clock, html, 1, 1, result) == []
    if fps == 30 and requested == 1:
        altered = bytearray(final.read_bytes())
        avcc = altered.index(b"avcC")
        altered[avcc + 7] += 1  # AVCDecoderConfigurationRecord level, payload untouched.
        forged = tmp_path / "changed-decoder-config.mp4"
        forged.write_bytes(altered)
        original_stream = evidence.video_packet_hashes(
            final, out, "original-codec", ffprobe=ffprobe
        )
        changed_stream = evidence.video_packet_hashes(forged, out, "changed-codec", ffprobe=ffprobe)
        assert original_stream["packets"] == changed_stream["packets"]
        assert original_stream["decoder"] != changed_stream["decoder"]
        codec_out = tmp_path / "codec-evidence"
        codec_out.mkdir()
        with pytest.raises(ValueError, match="unchanged prefix"):
            evidence.verify_recording_content(
                clock, silent, forged, codec_out, ffmpeg=ffmpeg, ffprobe=ffprobe
            )
    wrong = tmp_path / "wrong.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            f"color=red:size=640x360:rate={fps}:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(wrong),
        ],
        check=True,
        capture_output=True,
    )
    wrong_out = tmp_path / "wrong-evidence"
    wrong_out.mkdir()
    with pytest.raises(ValueError, match="unchanged prefix"):
        evidence.verify_recording_content(
            clock, silent, wrong, wrong_out, ffmpeg=ffmpeg, ffprobe=ffprobe
        )


def test_merge_preserves_labels_and_handles_overlapping_windows():
    windows = [evidence.window("later", 1, 0.2), evidence.window("first", 0.5, 0.4)]
    assert evidence.merge_windows(windows) == [[pytest.approx(0.1), pytest.approx(1.2)]]
    assert windows[0]["label"] == "later"
    assert evidence.missing_samples(windows, [{"windows": ["first"]}]) == ["later"]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_sampling_times_are_rejected(value):
    with pytest.raises(ValueError):
        evidence.window("bad", value, 0.2)


def test_native_frame_pts_are_parsed_without_substituting_requested_times():
    assert evidence.read_frame_pts(
        "[Parsed_showinfo_1] n: 0 pts: 15360 pts_time:1.5 duration:1024"
    ) == [{"sample_index": 0, "pts": 15360, "pts_time": 1.5}]


def test_one_sided_boundary_and_truncated_tail_are_incomplete():
    pages = [{"page_index": 0, "begin": 0, "end": 1}, {"page_index": 1, "begin": 1, "end": 2}]
    frames = [{"pts_time": t} for t in (0, 0.9, 1.8)]
    assert evidence.boundary_coverage(pages, frames, 1 / 30) == ["page-2-after", "terminal-frame"]
    frames.extend({"pts_time": t} for t in (1, 1.99))
    assert evidence.boundary_coverage(pages, frames, 1 / 30) == []


@pytest.mark.parametrize("timelines", [[], [[]], [[], None]])
def test_missing_timeline_is_not_an_explicit_empty_event_list(timelines):
    with pytest.raises(ValueError):
        evidence.validate_timelines(timelines, 2)
    evidence.validate_timelines([[], []], 2)


def test_clock_from_another_recording_is_flagged(tmp_path):
    issues = evidence.clock_association_issues(
        {
            "html_path": str(tmp_path / "other.html"),
            "runtime": {"pages": []},
            "media": {"requested_sec": 9},
        },
        tmp_path / "current.html",
        2,
        10,
    )
    assert issues == [
        "clock_html_path_mismatch",
        "clock_page_count_mismatch",
        "clock_duration_mismatch",
        "raw_and_final_video_recording_association_not_verified",
    ]


def test_production_padding_and_audio_extent_are_checked_separately(tmp_path):
    html = tmp_path / "lesson.html"
    clock = {
        "html_path": str(html),
        "runtime": {"pages": [{"index": 0, "expected_ms": 0}, {"index": 1, "expected_ms": 1000}]},
        "media": {"requested_sec": 4},
    }
    linked = {"verified_content": True}
    assert evidence.clock_association_issues(clock, html, 2, 2.52, linked, [1000, 1500]) == []
    clock["media"]["requested_sec"] = 3.5
    assert "clock_duration_mismatch" in evidence.clock_association_issues(
        clock, html, 2, 2.52, linked, [1000, 1500]
    )
    clock["media"]["requested_sec"] = 2
    assert "clock_duration_mismatch" in evidence.clock_association_issues(
        clock, html, 2, 2.52, linked, [1000, 1500]
    )
    clock["media"]["requested_sec"] = 4
    clock["runtime"]["pages"][1]["expected_ms"] = 2000
    assert "clock_page_schedule_mismatch" in evidence.clock_association_issues(
        clock, html, 2, 2.52, linked, [1000, 1500]
    )


def test_recording_request_uses_original_durations_before_html_truncation(tmp_path):
    board = {"segments": [{"audio_duration_sec": 1.001}, {"audio_duration_sec": 1.001}]}
    basis = evidence.recording_lesson_seconds(board)
    assert basis == pytest.approx(2.002)
    html = tmp_path / "lesson.html"
    clock = {
        "html_path": str(html),
        "runtime": {"pages": [{"index": 0, "expected_ms": 0}, {"index": 1, "expected_ms": 1000}]},
        "media": {"requested_sec": 4},
    }
    linked = {"verified_content": True}
    assert (
        evidence.clock_association_issues(clock, html, 2, 2.002, linked, [1000, 1000], basis) == []
    )
    clock["media"]["requested_sec"] = 3
    assert "clock_duration_mismatch" in evidence.clock_association_issues(
        clock, html, 2, 2.002, linked, [1000, 1000], basis
    )


def test_real_extraction_keeps_native_pixels_and_boundary_pts(tmp_path):
    ffmpeg = _ffmpeg_executable()
    video = tmp_path / "red-blue.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:size=64x48:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "color=blue:size=64x48:rate=10:duration=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "evidence"
    out.mkdir()
    frames = evidence.extract(video, [evidence.window("boundary", 1, 0.15)], out, ffmpeg=ffmpeg)
    assert [f["pts_time"] for f in frames] == pytest.approx([0.9, 1, 1.1])
    for frame in frames:
        assert struct.unpack(">II", Path(frame["path"]).read_bytes()[16:24]) == (64, 48)

    def pixel(frame):
        return subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                frame["path"],
                "-vf",
                "scale=1:1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout

    assert pixel(frames[0])[0] > 240 and pixel(frames[0])[2] < 20
    assert pixel(frames[-1])[2] > 240 and pixel(frames[-1])[0] < 20
    assert not evidence.missing_samples([evidence.window("boundary", 1, 0.15)], frames)
