import importlib.util
import struct
import subprocess
from pathlib import Path

import pytest

from textbook2video.pipeline.recorder import _ffmpeg_executable

script = Path(__file__).resolve().parents[1] / "scripts/extract_rendered_video_evidence.py"
spec = importlib.util.spec_from_file_location("rendered_extraction_test", script)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


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
