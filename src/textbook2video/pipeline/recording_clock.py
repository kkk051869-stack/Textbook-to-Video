"""Calibrate media time using visible start/end slates, never time stretching."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

# Four quadrant colors. Reversing the order distinguishes the terminal slate.
START_COLORS = ((255, 0, 255), (0, 255, 255), (255, 255, 0), (0, 255, 0))

PLAYBACK_JS = """async ({durationMs, slateMs}) => {
    const controller = window.SlideController;
    if (!controller || typeof controller.startRecording !== 'function' ||
        typeof controller.recordingGo !== 'function') {
        throw new Error('HTML lacks deferred recording API; ' +
            'regenerate HTML with current templates');
    }
    const durations = window.slideDurations || controller.slideDurations;
    if (!Array.isArray(durations) || durations.length !== controller.total() ||
        durations.some(d => !Number.isFinite(d) || d <= 0) ||
        durations.reduce((a, b) => a + b, 0) > durationMs + 1) {
        throw new Error('Invalid recording slide durations or truncated requested duration');
    }
    await document.fonts.ready;
    await Promise.all(Array.from(document.images).map(img => img.decode()));
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed!important;inset:0!important;' +
        'z-index:2147483647!important;' +
        'display:block!important;opacity:1!important;transform:none!important';
    const shadow = host.attachShadow({mode:'closed'});
    const colors = ['#ff00ff','#00ffff','#ffff00','#00ff00'];
    const tiles = colors.map((color, i) => {
        const tile = document.createElement('div');
        tile.style.cssText = `position:absolute;width:50%;height:50%;left:${i%2*50}%;` +
            `top:${Math.floor(i/2)*50}%;background:${color}`;
        shadow.appendChild(tile);
        return tile;
    });
    document.documentElement.appendChild(host);
    // Let the video encoder observe an unambiguous slate before playback starts.
    await new Promise(resolve => setTimeout(resolve, slateMs));
    const schedule = window.__t2vRecordingClock = {pages:[], done:false};
    controller.startRecording();
    const origin = window.__t2vRecordingOrigin;
    host.remove();
    schedule.pages.push({index:0, expected_ms:0, actual_ms:performance.now()-origin});
    let cumulative = 0;
    for (let i = 1; i < durations.length; i++) {
        cumulative += durations[i-1];
        const expected = cumulative;
        setTimeout(() => controller.recordingGo(i),
            Math.max(0, origin+expected-performance.now()));
        const observe = () => {
            if (controller.current() === i) {
                schedule.pages.push({index:i, expected_ms:expected,
                    actual_ms:performance.now()-origin});
            } else if (performance.now()-origin < expected+1000) {
                setTimeout(observe, 10);
            }
        };
        setTimeout(observe, Math.max(0, origin+expected-performance.now()));
    }
    setTimeout(() => {
        schedule.events = window.exportAnimationTrace();
        tiles.forEach((tile, i) => {tile.style.background = colors[3-i];});
        document.documentElement.appendChild(host);
        schedule.actual_end_ms = performance.now()-origin;
        schedule.done = true;
    }, Math.max(0, origin+durationMs-performance.now()));
    return {duration_ms:durationMs, expected_pages:durations.length};
}"""


def _slate(frame: bytes, colors: tuple) -> bool:
    if len(frame) != 192:
        return False
    # Sample well inside each quadrant of the 8x8 diagnostic thumbnail.
    for (x, y), expected in zip(((1, 1), (6, 1), (1, 6), (6, 6)), colors):
        pixel = frame[(y * 8 + x) * 3 : (y * 8 + x) * 3 + 3]
        high = [a for a, b in zip(pixel, expected) if b == 255]
        low = [a for a, b in zip(pixel, expected) if b == 0]
        # VP8's first frame can desaturate flat colors. Recognize channel
        # dominance rather than exact RGB, while rejecting gray/white/black.
        if min(high) < 150 or max(low) > 130 or min(high) - max(low) < 70:
            return False
    return True


def media_interval(raw_path: Path, *, ffmpeg: str, duration: float, fps: int) -> dict:
    """Measure visible slates in decoded pixels; reject missing/ambiguous spans."""
    sampling_fps = max(30, fps)
    decoded = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(raw_path),
            "-vf",
            f"fps={sampling_fps},scale=8:8:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    if len(decoded) % 192:
        raise ValueError("Truncated calibration decode; raw video preserved")
    frames = [decoded[i : i + 192] for i in range(0, len(decoded), 192)]
    labels = [
        "start"
        if _slate(f, START_COLORS)
        else "end"
        if _slate(f, START_COLORS[::-1])
        else "content"
        for f in frames
    ]
    starts = [i for i, label in enumerate(labels) if label == "start"]
    ends = [i for i, label in enumerate(labels) if label == "end"]
    if (
        not starts
        or not ends
        or min(ends) <= max(starts) + 1
        or starts != list(range(min(starts), max(starts) + 1))
        or ends != list(range(min(ends), max(ends) + 1))
    ):
        raise ValueError("Missing or invalid recorded calibration slates; raw video preserved")
    start, end = (max(starts) + 1) / sampling_fps, min(ends) / sampling_fps
    measured = end - start
    if abs(measured - duration) > 0.12:
        raise ValueError(f"Media clock mismatch: requested {duration}s, measured {measured}s")
    return {
        "content_start_sec": start,
        "content_end_sec": end,
        "measured_content_sec": measured,
        "requested_sec": duration,
        "sampling_fps": sampling_fps,
        "time_stretch": False,
    }


def validate_runtime(schedule: dict, *, expected_pages: int, duration: float) -> None:
    if (
        not schedule.get("done")
        or len(schedule.get("pages", [])) != expected_pages
        or abs(schedule.get("actual_end_ms", 0) - duration * 1000) > 100
    ):
        raise ValueError("Incomplete or late recording runtime; raw video preserved")
    if any(abs(p["actual_ms"] - p["expected_ms"]) > 100 for p in schedule["pages"]):
        raise ValueError("Late slide entry during recording; raw video preserved")
    for event in schedule.get("events", []):
        actual, planned = event.get("actual_ms"), event.get("planned_ms")
        if (
            event.get("status") != "executed"
            or actual is None
            or planned is None
            or not math.isfinite(actual)
            or abs(actual - planned) > 100
        ):
            raise ValueError("Late or incomplete animation during recording; raw video preserved")


def save_clock(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_options(duration: float, fps: int) -> None:
    if (
        isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration <= 0
        or isinstance(fps, bool)
        or not isinstance(fps, int)
        or not 1 <= fps <= 120
    ):
        raise ValueError("Recording requires positive finite duration and integer fps in [1,120]")
