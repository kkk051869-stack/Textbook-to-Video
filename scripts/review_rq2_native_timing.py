"""Extract final video/PTS, execution and waveform evidence without model calls."""

from __future__ import annotations

import argparse
import array
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import extract_rendered_video_evidence as frames
import run_rq2_native_timing as control
from playwright.sync_api import sync_playwright


def probe(path, executable, entries):
    import json

    return json.loads(
        subprocess.check_output(
            [executable, "-v", "error", "-show_entries", entries, "-of", "json", str(path)]
        )
    )


def pcm(path, ffmpeg):
    samples = array.array("h")
    samples.frombytes(
        subprocess.check_output(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "8000",
                "-",
            ]
        )
    )
    return samples


def waveform_checks(source, actual, points):
    rows = []
    for point in points:
        center = int((point + 1) * 8000)
        reference = source[center : center + 6400]
        energy = sum(x * x for x in reference)
        best = (-1, None)
        for shift in range(-320, 321, 8):
            chunk = actual[center + shift : center + shift + len(reference)]
            if len(chunk) != len(reference) or not energy:
                continue
            denominator = math.sqrt(energy * sum(y * y for y in chunk))
            correlation = (
                sum(x * y for x, y in zip(reference, chunk)) / denominator if denominator else 0
            )
            if correlation > best[0]:
                best = correlation, shift / 8000
        rows.append(
            {
                "source_window_start_sec": center / 8000,
                "duration_sec": len(reference) / 8000,
                "best_correlation": best[0],
                "final_audio_lag_sec": best[1],
                "search_radius_sec": 0.04,
                "claim": (
                    "Decoded waveform agreement only; "
                    "not spoken-content or learning-effect verification"
                ),
            }
        )
    return rows


def review(out, destination, ffmpeg, ffprobe, static_only=False, modes=None):
    modes = modes or ("legacy", "simple_rule", "proposition_aware")
    control.verify(out)
    destination.mkdir(parents=True, exist_ok=False)
    cues = control.read(out / "audio/sentence_cues.json")["segments"][0]["cues"]
    source_audio = pcm(out / "audio/s1.wav", ffmpeg)
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        page = browser.new_page()
        for width, height in ((1600, 900), (1366, 768)):
            page.set_viewport_size({"width": width, "height": height})
            page.add_init_script("window.__t2vDeferPlayback=true")
            html = control.read(out / modes[-1] / "compiled.json")["html"]
            page.goto(Path(html).as_uri())
            page.evaluate("document.fonts.ready")
            page.evaluate("SlideController.startRecording()")
            page.add_style_tag(
                content="*{animation:none!important;transition:none!important}.slide.active,.anim{opacity:1!important;visibility:visible!important;transform:none!important}"
            )
            page.evaluate("document.querySelectorAll('.anim').forEach(e=>e.classList.add('show'))")
            page.screenshot(path=str(destination / f"static-{width}x{height}.png"))
            geometry = page.locator("[data-anim-id]").evaluate_all(
                "els=>els.map(e=>({id:e.dataset.animId,text:e.innerText,rect:e.getBoundingClientRect().toJSON(),opacity:getComputedStyle(e).opacity}))"
            )
            control.write(
                destination / f"static-{width}x{height}.json",
                {
                    "geometry": geometry,
                    "claim": "Forced static reference; not runtime or video visibility evidence",
                },
            )
        browser.close()
    if static_only:
        return
    for mode in modes:
        directory = out / mode
        video = directory / "voiced.mp4"
        target = destination / mode
        target.mkdir()
        compiled = control.read(directory / "compiled.json")
        runtime = control.read(directory / "runtime.json")
        clock = control.read(directory / "silent.clock.json")
        if clock["status"] != "CALIBRATED":
            raise ValueError("Uncalibrated media")
        actual_by_id = {event["event_id"]: event for event in runtime["events"]}
        links = []
        for event in compiled["events"]:
            actual = actual_by_id.get(event["event_id"])
            if actual is None:
                raise ValueError("Missing runtime event")
            links.append(
                {
                    "compiled": event,
                    "runtime": actual,
                    "runtime_error_ms": actual["actual_ms"] - event["start_ms"],
                }
            )
        metadata = probe(
            video, ffprobe, "format=duration:stream=index,codec_type,codec_name,start_time,duration"
        )
        import json

        video_pts = json.loads(
            subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "frame=best_effort_timestamp_time",
                    "-of",
                    "json",
                    str(video),
                ]
            )
        )
        timestamps = [float(f["best_effort_timestamp_time"]) for f in video_pts["frames"]]
        starts = {event["start_ms"] / 1000 for event in compiled["events"]}
        starts.update(cue["start_sec"] for cue in cues)
        requests = sorted(
            {max(0, t + delta) for t in starts for delta in (-0.2, 0.8)}
            | {cues[-1]["end_sec"] - 0.2}
        )
        windows = []
        for requested in requests:
            nearest = min(timestamps, key=lambda pts: abs((pts - timestamps[0]) - requested))
            windows.append(
                frames.window(
                    f"lesson={requested:.3f}", nearest, 0.0005, requested_lesson_sec=requested
                )
            )
        extracted = frames.extract(video, windows, target, ffmpeg=ffmpeg)
        frames.contact_sheets(extracted, target, "msedge")
        decoded = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "-"],
            capture_output=True,
            text=True,
        )
        (target / "decode.log").write_text(decoded.stderr, encoding="utf-8")
        decoded.check_returncode()
        results[mode] = {
            "video": str(video.resolve()),
            "video_sha256": control.sha(video),
            "html_sha256": compiled["html_sha256"],
            "clock": clock,
            "streams": metadata,
            "event_links": links,
            "frames": extracted,
            "sampling_windows": windows,
            "audio_waveform": waveform_checks(
                source_audio, pcm(video, ffmpeg), [cue["start_sec"] for cue in cues]
            ),
            "decode_returncode": decoded.returncode,
            "visual_review": "PENDING",
            "continuous_listening": "NOT_PERFORMED",
        }
        control.write(target / "evidence.json", results[mode])
    control.write(destination / "summary.json", results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--modes", nargs="+")
    args = parser.parse_args()
    review(
        args.output.resolve(),
        args.evidence.resolve(),
        args.ffmpeg,
        args.ffprobe,
        args.static_only,
        args.modes,
    )
