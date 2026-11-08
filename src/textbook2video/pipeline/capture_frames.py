"""Chromium frame ingestion, with monotonic capture time before CFR encoding.

This is a recording adapter, not a teaching timeline. The browser's JPEGs and
timestamps are authoritative; late older frames cannot rewind the encoder.
"""
from __future__ import annotations

import base64
import json
import math
import subprocess
import sys


class TimestampFrames:
    """Hold the most recent captured pixels on a fixed 25 Hz sampling grid."""

    fps = 25  # Same capture grid as Playwright's built-in video recorder.

    def __init__(self, stream, journal, *, max_span):
        self.stream, self.journal = stream, journal
        self.max_span = max_span
        self.first = self.last = self.frame_number = None
        self.held = None
        self.count = self.dropped = self.written = 0

    def add(self, pixels, timestamp):
        if not pixels or not math.isfinite(timestamp):
            raise ValueError("Invalid screencast pixels or capture timestamp")
        self.count += 1
        if self.last is not None and timestamp <= self.last:
            self.dropped += 1
            self.journal.write(json.dumps({"timestamp_sec": timestamp,
                "disposition": "late_non_monotonic_capture", "emitted_frames": 0}) + "\n")
            return
        if self.first is None:
            self.first = timestamp
        if timestamp - self.first > self.max_span:
            raise ValueError("Capture timestamp span exceeds recording bound")
        number = math.floor((timestamp - self.first) * self.fps)
        emitted = 0 if self.frame_number is None else number - self.frame_number
        for _ in range(emitted):
            self.stream.write(self.held)
        self.written += emitted
        self.journal.write(json.dumps({"timestamp_sec": timestamp,
            "disposition": "accepted", "sample_number": number,
            "emitted_frames": emitted}) + "\n")
        self.last, self.frame_number, self.held = timestamp, number, pixels

    def finish(self):
        if self.held is None:
            raise ValueError("No screencast frames received")
        self.stream.write(self.held)
        self.written += 1
        return {"backend": "chromium_cdp_monotonic_capture", "sampling_fps": self.fps,
                "received_frames": self.count, "late_frames_dropped": self.dropped,
                "encoded_frames": self.written,
                "first_capture_timestamp_sec": self.first,
                "last_capture_timestamp_sec": self.last,
                "time_stretch": False}


class ChromiumCapture:
    def __init__(self, page, raw_path, *, ffmpeg, duration):
        self.raw_path, self.ffmpeg = raw_path, ffmpeg
        self.frames_path = raw_path.with_suffix(".frames.mjpeg")
        self.journal_path = raw_path.with_suffix(".capture.jsonl")
        self.stream = self.frames_path.open("xb")
        try:
            self.journal = self.journal_path.open("x", encoding="utf-8")
        except Exception:
            self.stream.close()
            raise
        self.frames = TimestampFrames(self.stream, self.journal, max_span=duration + 40)
        self.error = None
        self.stopping = False
        self.session = None
        try:
            self.session = page.context.new_cdp_session(page)
            self.session.on("Page.screencastFrame", self._frame)
            viewport = page.viewport_size
            self.session.send("Page.startScreencast", {"format": "jpeg", "quality": 90,
                "maxWidth": viewport["width"], "maxHeight": viewport["height"],
                "everyNthFrame": 1})
        except Exception:
            self.stream.close()
            self.journal.close()
            raise

    def _frame(self, payload):
        if self.stopping:
            return
        try:
            if self.error is None:
                self.frames.add(base64.b64decode(payload["data"], validate=True),
                                float(payload["metadata"]["timestamp"]))
        except Exception as error:
            self.error = error
        finally:
            try:
                self.session.send("Page.screencastFrameAck", {"sessionId": payload["sessionId"]})
            except Exception as error:
                # A synchronous acknowledgement can still be waiting when
                # stop/detach finishes. Only that shutdown race is benign.
                if not self.stopping and self.error is None:
                    self.error = error

    def close(self):
        self.stopping = True
        self.session.remove_listener("Page.screencastFrame", self._frame)
        try:
            self.session.send("Page.stopScreencast")
            if self.error is not None:
                raise self.error
            report = self.frames.finish()
        finally:
            self.stream.close()
            self.journal.close()
            primary = sys.exception()
            try:
                self.session.detach()
            except Exception as error:
                if primary is None:
                    raise
                primary.add_note(f"Capture session detach failed: {type(error).__name__}")
        # Encoding happens after capture, so encoder pipe backpressure cannot
        # delay ingestion. Memory holds only one JPEG; the source spool is kept.
        encode_capture(self.frames_path, self.raw_path, ffmpeg=self.ffmpeg)
        return {**report, "source_frames": str(self.frames_path),
                "timestamp_journal": str(self.journal_path)}


def encode_capture(frames_path, raw_path, *, ffmpeg):
    """Keep captured detail in the intermediate; final H.264 is encoded later."""
    subprocess.run([ffmpeg, "-v", "error", "-n", "-f", "mjpeg",
        "-framerate", str(TimestampFrames.fps), "-i", str(frames_path),
        "-vf", "scale=in_range=full:out_range=tv", "-color_range", "tv",
        "-c:v", "libvpx-vp9", "-lossless", "1", "-deadline", "good", "-cpu-used", "4",
        "-row-mt", "1", "-b:v", "0", "-pix_fmt", "yuv420p", str(raw_path)],
        check=True, capture_output=True)
