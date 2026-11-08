"""Capture ordering is distinct from teaching events and media calibration."""
import io
import json
import subprocess

import pytest

from textbook2video.pipeline.capture_frames import TimestampFrames, encode_capture
from textbook2video.pipeline.recorder import _ffmpeg_executable


def test_late_capture_does_not_rewind_or_add_encoded_duration():
    stream, journal = io.BytesIO(), io.StringIO()
    frames = TimestampFrames(stream, journal, max_span=10)
    # Built-in ingestion rewinds to frame 1 on the third callback, adding a
    # second interval when frame 3 arrives. The late pixels must never replace
    # already observed newer pixels, nor change the sampling grid.
    for pixels, time in [(b"a", 1000), (b"b", 1000.08),
                         (b"late", 1000.04), (b"c", 1000.12)]:
        frames.add(pixels, time)
    report = frames.finish()
    assert stream.getvalue() == b"aabc"
    assert report["encoded_frames"] == 4
    assert report["late_frames_dropped"] == 1
    assert json.loads(journal.getvalue().splitlines()[2])["emitted_frames"] == 0


def test_same_grid_sample_uses_latest_pixels_without_duplicate_time():
    stream, journal = io.BytesIO(), io.StringIO()
    frames = TimestampFrames(stream, journal, max_span=10)
    for pixels, time in [(b"a", 0), (b"b", .01), (b"c", .08)]:
        frames.add(pixels, time)
    assert frames.finish()["encoded_frames"] == 3
    assert stream.getvalue() == b"bbc"


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), 100])
def test_invalid_or_excessive_capture_time_fails(timestamp):
    frames = TimestampFrames(io.BytesIO(), io.StringIO(), max_span=10)
    frames.add(b"a", 0)
    with pytest.raises(ValueError):
        frames.add(b"b", timestamp)


def test_intermediate_preserves_light_card_contrast_and_color_range(tmp_path):
    ffmpeg = _ffmpeg_executable()
    levels = [236, 244, 250, 32]
    source = bytes(v for _y in range(64) for x in range(64)
                   for v in (levels[x // 16],) * 3)
    spool, raw = tmp_path / "frames.mjpeg", tmp_path / "raw.webm"
    subprocess.run([ffmpeg, "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "64x64", "-i", "-", "-frames:v", "1", "-c:v", "mjpeg", "-q:v", "2",
        "-f", "mjpeg", str(spool)], input=source, check=True, capture_output=True)
    encode_capture(spool, raw, ffmpeg=ffmpeg)
    decoded = subprocess.run([ffmpeg, "-v", "error", "-i", str(raw), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    measured = [decoded[(32 * 64 + x) * 3] for x in (8, 24, 40, 56)]
    assert all(abs(a - b) <= 4 for a, b in zip(levels, measured))
    assert measured[1] - measured[0] >= 4  # card/background contrast survives
