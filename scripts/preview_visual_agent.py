"""Real course source -> automatic visual selection, render, review and revisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from textbook2video.research.visual_tools import run_visual_agent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--segments", default="2,4,5")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="ecnu-plus")
    parser.add_argument("--source", type=Path, help="Actual textbook text, not generation prompts")
    parser.add_argument("--theme", default="dark-blue-academic")
    parser.add_argument(
        "--course-plan",
        action="store_true",
        help="Exercise the default course adapter and actual page renderer",
    )
    parser.add_argument(
        "--before-tts",
        action="store_true",
        help="Plan and split before measured audio alignment, as produce does",
    )
    args = parser.parse_args()
    data = args.storyboard.read_bytes()
    board = json.loads(data)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_path": str(args.storyboard.resolve()),
        "runs": [],
        "scope": "development, automatic selection, not original r5 artifacts",
        "source_scope": "provided-raw-text" if args.source else "narration-derived",
        "source_text_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest()
        if args.source else None,
    }
    try:
        for ident in args.segments.split(","):
            selected = [s for s in board["segments"] if str(s["id"]) == ident]
            if len(selected) != 1:
                raise ValueError("segment must resolve uniquely")
            segment = selected[0]
            if args.course_plan:
                from textbook2video.pipeline.course_visuals import generate_course_visuals

                print(f"Planning course page {ident}", flush=True)
                image_dir = args.storyboard.parent / "images"
                if not image_dir.is_dir():
                    image_dir = args.storyboard.parent.parent / "source" / "images"
                images = generate_course_visuals(
                    selected,
                    output_dir=args.output_dir,
                    model=args.model,
                    theme=args.theme,
                    rebuild_timing_before_tts=args.before_tts,
                    source_image_dir=image_dir,
                    source_text=args.source.read_text(encoding="utf-8") if args.source else None,
                )
                reports = []
                for planned_segment in selected:
                    reports.extend(
                        render_course_page(planned_segment, images, args.output_dir, args.theme)
                    )
                manifest["runs"].append(
                    {"segment_id": ident, "status": "COURSE_PAGE_RENDERED", "screenshots": reports}
                )
                continue
            source = (
                args.source.read_text(encoding="utf-8") if args.source else segment["narration"]
            )
            goal = next(
                (e["text"] for e in segment["elements"] if e["type"] == "heading"), source[:120]
            )
            print(f"Planning and reviewing segment {ident}", flush=True)
            run_path = run_visual_agent(
                source, goal, args.output_dir / f"page-{ident}", model=args.model, theme=args.theme,
                narration_text=segment["narration"],
            )
            result = json.loads(run_path.read_text(encoding="utf-8"))
            manifest["runs"].append(
                {"segment_id": ident, "run": str(run_path), "status": result["status"]}
            )
            print(f"Segment {ident}: {result['status']}", flush=True)
    finally:
        with (args.output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
    return 0


def render_course_page(segment: dict, images: dict, directory: Path, theme: str) -> list[dict]:
    from playwright.sync_api import sync_playwright

    from textbook2video.pipeline.visual_page_render import course_page_html

    selected_images = {
        key: value for key, value in images.items() if key.startswith(f"{segment['id']}:")
    }
    markup = course_page_html(segment, selected_images, theme=theme)
    path = directory / f"course-page-{segment['id']}.html"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(markup)
    with path.with_suffix(".json").open("x", encoding="utf-8") as stream:
        json.dump(segment, stream, ensure_ascii=False, indent=2)
    reports = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            page = browser.new_page()
            for width, height in ((1600, 900), (1366, 768)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(path.resolve().as_uri())
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                bounds = page.locator(".t2v-image-surface img").bounding_box()
                screenshot = directory / f"course-page-{segment['id']}-{width}.png"
                page.screenshot(path=str(screenshot))
                reports.append(
                    {
                        "viewport": [width, height],
                        "image_bounds": bounds,
                        "screenshot": str(screenshot.resolve()),
                    }
                )
                if bounds and (bounds["width"] < 780 or bounds["height"] < 480):
                    raise ValueError("final course image smaller than required surface")
        finally:
            browser.close()
    return reports


if __name__ == "__main__":
    raise SystemExit(main())
