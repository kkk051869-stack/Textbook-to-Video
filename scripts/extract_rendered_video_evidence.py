"""Extract native final-MP4 frames and static HTML references, never infer visibility from DOM."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

from textbook2video.pipeline.artifact_integrity import verify_render_bundle
from textbook2video.pipeline.recorder import _ffmpeg_executable


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def window(label, center, radius, **metadata):
    if not all(math.isfinite(n) for n in (center, radius)) or radius < 0:
        raise ValueError("finite sampling times required")
    return {"label": label, "begin": max(0, center - radius), "end": center + radius, **metadata}


def merge_windows(windows):
    merged = []
    for item in sorted(windows, key=lambda w: w["begin"]):
        if merged and item["begin"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], item["end"])
        else:
            merged.append([item["begin"], item["end"]])
    return merged


def read_frame_pts(log):
    return [
        {"sample_index": int(m[0]), "pts": int(m[1]), "pts_time": float(m[2])}
        for m in re.findall(r"\bn:\s*(\d+).*?\bpts:\s*(-?\d+).*?\bpts_time:([^\s]+)", log)
    ]


def missing_samples(windows, frames):
    found = {label for frame in frames for label in frame["windows"]}
    return [w["label"] for w in windows if w["label"] not in found]


def boundary_coverage(pages, frames, frame_sec):
    """Require both sides of internal cuts and the expected first/last media frame."""
    times = sorted(f["pts_time"] for f in frames)
    missing = []
    for page in pages[1:]:
        cut = page["begin"]
        if not any(cut - 0.2 <= t < cut for t in times):
            missing.append(f"page-{page['page_index'] + 1}-before")
        if not any(cut <= t <= cut + 0.2 for t in times):
            missing.append(f"page-{page['page_index'] + 1}-after")
    if not times or times[0] > pages[0]["begin"] + frame_sec * 1.5:
        missing.append("initial-frame")
    if not times or times[-1] < pages[-1]["end"] - frame_sec * 1.5:
        missing.append("terminal-frame")
    return missing


def validate_timelines(timelines, page_count):
    if not isinstance(timelines, list) or len(timelines) != page_count:
        raise ValueError("explicit timeline required for every page, including empty event lists")
    if any(not isinstance(events, list) for events in timelines):
        raise ValueError("every page timeline must be a list")


def clock_association_issues(clock, html_path, pages, duration):
    issues = []
    if Path(clock.get("html_path", "")).resolve() != html_path.resolve():
        issues.append("clock_html_path_mismatch")
    if len(clock.get("runtime", {}).get("pages", [])) != pages:
        issues.append("clock_page_count_mismatch")
    if abs(float(clock.get("media", {}).get("requested_sec", -1)) - duration) > 0.12:
        issues.append("clock_duration_mismatch")
    # Current recorder does not bind content hashes to its report. Never imply it does.
    issues.append("raw_and_final_video_recording_association_not_verified")
    return issues


def extract(video, windows, output, *, ffmpeg):
    destination = output / "native"
    destination.mkdir()
    selections = "+".join(f"between(t,{a:.9f},{b:.9f})" for a, b in merge_windows(windows))
    command = [
        ffmpeg,
        "-hide_banner",
        "-copyts",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"select='{selections}',showinfo",
        "-vsync",
        "0",
        str(destination / "frame-%05d.png"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    (output / "native-pts.log").write_text(result.stderr, encoding="utf-8")
    (output / "extract-command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    result.check_returncode()
    frames, files = read_frame_pts(result.stderr), sorted(destination.glob("frame-*.png"))
    if not frames or len(frames) != len(files):
        raise ValueError("native frame/PTS count mismatch; evidence remains incomplete")
    for frame, path in zip(frames, files, strict=True):
        frame.update(
            path=str(path.resolve()),
            sha256=sha(path),
            windows=[
                w["label"]
                for w in windows
                if w["begin"] - 1e-6 <= frame["pts_time"] <= w["end"] + 1e-6
            ],
        )
    return frames


def references(html_path, segments, output, width, height, browser):
    directory = output / "references"
    directory.mkdir()
    references, timelines = [], []
    with sync_playwright() as pw:
        instance = pw.chromium.launch(channel=browser, headless=True)
        try:
            page = instance.new_page(viewport={"width": width, "height": height})
            page.add_init_script("window.__t2vDeferPlayback = true;")
            page.goto(html_path.resolve().as_uri())
            page.evaluate("document.fonts.ready")
            page.evaluate("Promise.all(Array.from(document.images).map(img => img.decode()))")
            if page.locator(".slide").count() != len(segments):
                raise ValueError("DOM/storyboard page count mismatch")
            timelines = page.evaluate(
                "window.slideTimelines || SlideController.slideTimelines || []"
            )
            validate_timelines(timelines, len(segments))
            if page.locator("[data-step]").count():
                raise ValueError("data-step fallback events require separate sampling support")
            page.add_style_tag(content="*{animation:none!important;transition:none!important}")
            page.evaluate("SlideController.startRecording()")
            for index, segment in enumerate(segments):
                if index:
                    page.evaluate("(i) => SlideController.recordingGo(i)", index)
                page.evaluate(
                    """(i) => document.querySelectorAll('.slide')[i]
                    .querySelectorAll('.anim').forEach(el => {
                        el.classList.add('show');
                        el.style.setProperty('opacity','1','important');
                        el.style.setProperty('visibility','visible','important');
                        el.style.setProperty('transform','none','important');
                    })""",
                    index,
                )
                path = directory / f"page-{index + 1:03}.png"
                page.screenshot(path=str(path))
                inventory = page.evaluate(
                    """(i) => {
                    const slide=document.querySelectorAll('.slide')[i];
                    return {
                        headings:Array.from(slide.querySelectorAll('h1,h2')).map(e=>e.innerText),
                        elements:Array.from(slide.querySelectorAll('[data-anim-id]')).map(e=>{
                            const b=e.getBoundingClientRect();
                            return {id:e.dataset.animId,text:e.innerText,
                                bounds:{x:b.x,y:b.y,width:b.width,height:b.height}};
                        })
                    };
                }""",
                    index,
                )
                references.append(
                    {
                        "page_index": index,
                        "segment_id": segment["id"],
                        "path": str(path.resolve()),
                        "sha256": sha(path),
                        **inventory,
                        "scope": "STATIC_REFERENCE_FORCED_VISIBILITY_NOT_VIDEO_EVIDENCE",
                    }
                )
        finally:
            instance.close()
    return references, timelines


def contact_sheets(frames, output, browser):
    # Every original PNG and its PTS remain available; sheets are viewing aids.
    with sync_playwright() as pw:
        instance = pw.chromium.launch(channel=browser, headless=True)
        try:
            page = instance.new_page(viewport={"width": 1480, "height": 1000})
            for offset in range(0, len(frames), 6):
                cards = "".join(
                    "<figure><figcaption>"
                    + html.escape(f"PTS {f['pts_time']:.6f}s | {','.join(f['windows'])}")
                    + "</figcaption>"
                    + f'<img src="{Path(f["path"]).as_uri()}"></figure>'
                    for f in frames[offset : offset + 6]
                )
                markup = (
                    '<!doctype html><meta charset="utf-8"><style>'
                    "body{margin:8px;background:#eee;font:16px Arial;display:grid;"
                    "grid-template-columns:1fr 1fr;gap:8px}figure{margin:0}"
                    "figcaption{min-height:36px}img{width:100%;display:block}</style>" + cards
                )
                path = output / f"sheet-{offset // 6 + 1:03}.html"
                path.write_text(markup, encoding="utf-8")
                page.goto(path.resolve().as_uri())
                page.evaluate("Promise.all(Array.from(document.images).map(i=>i.decode()))")
                page.screenshot(path=str(path.with_suffix(".png")), full_page=True)
        finally:
            instance.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("video", "storyboard", "html", "audio-dir", "clock", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--browser", default="msedge")
    parser.add_argument("--window-sec", type=float, default=0.2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    bundle = verify_render_bundle(args.storyboard, args.html, audio_dir=args.audio_dir)
    clock = json.loads(args.clock.read_text(encoding="utf-8"))
    if clock.get("status") != "CALIBRATED":
        raise ValueError("recording clock is not calibrated")
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(args.video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    metadata = json.loads(probe.stdout)
    (args.output / "ffprobe.json").write_text(probe.stdout, encoding="utf-8")
    video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    audio = next(s for s in metadata["streams"] if s["codec_type"] == "audio")
    origin = float(audio.get("start_time", "0"))
    board = json.loads(args.storyboard.read_text(encoding="utf-8"))
    refs, timelines = references(
        args.html, board["segments"], args.output, video["width"], video["height"], args.browser
    )
    windows, pages, elapsed = [], [], 0.0
    for index, (segment, measured) in enumerate(
        zip(board["segments"], bundle["audio_duration_sec_by_page"], strict=True)
    ):
        begin, end = origin + elapsed, origin + elapsed + measured
        pages.append(
            {
                "page_index": index,
                "segment_id": segment["id"],
                "begin": begin,
                "end": end,
                "audio_file": bundle["audio_files"][index],
                "reference": refs[index],
                "observed_page_identity": None,
                "status": "NOT_REVIEWED",
            }
        )
        windows.extend(
            [
                window(f"page-{index + 1}-begin", begin, args.window_sec),
                window(f"page-{index + 1}-middle", (begin + end) / 2, 0.04),
                window(f"page-{index + 1}-end", end, args.window_sec),
            ]
        )
        for event_index, event in enumerate(timelines[index]):
            local_ms = event.get("start_ms", event.get("at_ms"))
            if not isinstance(local_ms, (float, int)):
                raise ValueError("timeline event has no explicit start time")
            start = begin + local_ms / 1000
            windows.append(
                window(
                    f"p{index + 1}-e{event_index + 1}-start",
                    start,
                    args.window_sec,
                    event=event,
                    expected_page_index=index,
                    observed_visible_start=None,
                    status="NOT_REVIEWED",
                )
            )
            if isinstance(event.get("duration_ms"), (float, int)):
                windows.append(
                    window(
                        f"p{index + 1}-e{event_index + 1}-after",
                        start + event["duration_ms"] / 1000 + 0.1,
                        args.window_sec,
                        event=event,
                    )
                )
        elapsed += measured
    frame_rows = extract(args.video, windows, args.output, ffmpeg=_ffmpeg_executable())
    missing = missing_samples(windows, frame_rows)
    numerator, denominator = video["avg_frame_rate"].split("/")
    frame_sec = float(denominator) / float(numerator)
    missing_boundaries = boundary_coverage(pages, frame_rows, frame_sec)
    association = clock_association_issues(clock, args.html, len(pages), elapsed)
    audio_inputs = [
        {"path": str((args.audio_dir / name).resolve()), "sha256": sha(args.audio_dir / name)}
        for name in bundle["audio_files"]
    ]
    image_dir = args.storyboard.parent / "images"
    assets = (
        [
            {"path": str(p.resolve()), "sha256": sha(p)}
            for p in sorted(image_dir.rglob("*"))
            if p.is_file()
        ]
        if image_dir.is_dir()
        else []
    )
    raw_path = Path(clock["raw_video"]) if clock.get("raw_video") else None
    missing_inputs = [] if raw_path and raw_path.is_file() else ["raw_video"]
    report = {
        "status": "INCOMPLETE_SAMPLING"
        if missing or missing_inputs or missing_boundaries or association
        else "EXTRACTED_PENDING_VISUAL_REVIEW",
        "human_review": "NOT_REVIEWED",
        "claim": (
            "Native final-MP4 pixels/PTS extracted; no visibility inferred from DOM or runtime"
        ),
        "limitations": [
            "Finite windows do not cover unsampled intervals",
            "Static references force visibility and are not video observations",
        ],
        "inputs": {
            name: {"path": str(getattr(args, name).resolve()), "sha256": sha(getattr(args, name))}
            for name in ("video", "storyboard", "html", "clock")
        },
        "render_bundle": bundle,
        "audio_inputs": audio_inputs,
        "assets": assets,
        "raw_video": {"path": str(raw_path), "sha256": sha(raw_path)}
        if raw_path and raw_path.is_file()
        else None,
        "missing_windows": missing,
        "missing_boundary_evidence": missing_boundaries,
        "unverified_associations": association,
        "missing_inputs": missing_inputs,
        "frame_index_basis": (
            "sample_index is selected-frame order; pts/pts_time are native input timestamps"
        ),
        "streams": metadata["streams"],
        "clock_runtime": clock.get("runtime"),
        "pages": pages,
        "windows": windows,
        "frames": frame_rows,
    }
    (args.output / "evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    contact_sheets(frame_rows, args.output, args.browser)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "pages": len(pages),
                "native_frames": len(frame_rows),
                "status": report["status"],
            },
            ensure_ascii=False,
        )
    )
    return 2 if missing or missing_inputs or missing_boundaries or association else 0


if __name__ == "__main__":
    raise SystemExit(main())
