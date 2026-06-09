"""
Playwright recording module: HTML animation page -> MP4 video
Supports three slide advance mechanisms (auto-detected):
  1. Built-in SlideController + slideDurations: HTML self-manages paging, recorder doesn't interfere
  2. Built-in SlideController with global SLIDE_TIMES: recorder drives based on precise timings
  3. Reveal.js: uses its autoSlide config

Usage:
  from textbook2video.pipeline.recorder import record_html_to_video
  record_html_to_video("output/demo.html", "output/demo.mp4", duration=35)
"""

import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def record_html_to_video(
    html_path: str,
    output_path: str,
    duration: int = 30,
    fps: int = 30,
    *,
    browser_channel: str = "msedge",
    viewport_width: int = 1920,
    viewport_height: int = 1080,
):
    """
    Open HTML animation page, auto-page through slides, and record to WebM then MP4.

    Page advance strategy (priority high to low):
      1. HTML built-in SlideController.slideDurations -> recorder fully hands-off
      2. HTML global SLIDE_TIMES array -> recorder drives via precise timings
      3. SlideController without precise times -> recorder distributes uniformly
      4. Reveal.js -> uses its autoSlide config

    Args:
        html_path: Path to HTML file
        output_path: Output video path (.mp4)
        duration: Total recording duration in seconds
        fps: Frame rate
        browser_channel: Playwright browser channel (defaults to system Edge)
        viewport_width: Viewport width
        viewport_height: Viewport height
    """
    html_path = Path(html_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    webm_path = output_path.with_suffix(".webm")
    init_bg = "#0c0c88"

    print(f"Recording: {html_path}")
    print(f"Output: {output_path}")
    print(f"Duration: {duration}s, FPS: {fps}fps")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=browser_channel)
        except Exception:
            print(f"  Browser channel={browser_channel} unavailable, falling back to chromium")
            browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            record_video_dir=str(webm_path.parent),
            record_video_size={"width": viewport_width, "height": viewport_height},
        )
        page = context.new_page()

        # Inject dark background early to prevent white flash on page load
        page.add_init_script(
            f"""
            (() => {{
                const bg = {init_bg!r};
                const apply = () => {{
                    document.documentElement.style.background = bg;
                    document.documentElement.style.backgroundColor = bg;
                    if (document.body) {{
                        document.body.style.background = bg;
                        document.body.style.backgroundColor = bg;
                    }}
                }};
                const style = document.createElement('style');
                style.textContent = 'html, body {{ background: ' + bg + ' !important; background-color: ' + bg + ' !important; }}';
                document.documentElement.appendChild(style);
                apply();
                window.addEventListener('DOMContentLoaded', apply, {{ once: true }});
                window.addEventListener('load', apply, {{ once: true }});
            }})();
            """
        )

        # Open HTML file
        page.goto(f"file:///{str(html_path).replace(chr(92), '/')}")
        page.wait_for_load_state("networkidle")
        print("Page loaded")

        # Inject page advance logic
        page.evaluate(
            """() => {
            const totalDuration = """
            + str(duration * 1000)
            + """;

            // Method 1: SlideController with slideDurations -> completely hands-off
            if (typeof SlideController !== 'undefined' &&
                SlideController.slideDurations &&
                SlideController.slideDurations.length > 0) {
                console.log('[recorder] SlideController.slideDurations found, NOT injecting auto-advance');
                return;
            }

            // Method 2: Global SLIDE_TIMES array -> precise timing-driven
            if (typeof SLIDE_TIMES !== 'undefined' && SLIDE_TIMES.length > 0) {
                console.log('[recorder] SLIDE_TIMES found, using precise timings', SLIDE_TIMES);
                (function () {
                    let idx = 0;
                    function advance() {
                        if (idx >= SLIDE_TIMES.length - 1) return;
                        const delay = SLIDE_TIMES[idx] || 3000;
                        setTimeout(() => {
                            if (typeof SlideController !== 'undefined' && SlideController.next) {
                                SlideController.next();
                            } else if (typeof next === 'function') {
                                next();
                            }
                            idx++;
                            advance();
                        }, delay);
                    }
                    advance();
                })();
                return;
            }

            // Method 3: SlideController without precise times -> uniform distribution
            if (typeof SlideController !== 'undefined') {
                const total = typeof SlideController.total === 'function'
                    ? SlideController.total()
                    : (SlideController.total || 1);
                const interval = Math.max(totalDuration / total, 1000);
                console.log('[recorder] SlideController: uniform interval=' + interval + 'ms, total=' + total);
                let step = 0;
                const timer = setInterval(() => {
                    step++;
                    if (step >= total) {
                        clearInterval(timer);
                    } else {
                        SlideController.next();
                    }
                }, interval);
                return;
            }

            // Method 4: Reveal.js (legacy compatibility)
            if (typeof Reveal !== 'undefined') {
                let totalSteps = 0;
                document.querySelectorAll('.reveal .slides > section').forEach(slide => {
                    const subSlides = slide.querySelectorAll('section');
                    if (subSlides.length > 0) {
                        subSlides.forEach(sub => {
                            totalSteps += sub.querySelectorAll('.fragment').length + 1;
                        });
                    } else {
                        totalSteps += slide.querySelectorAll('.fragment').length + 1;
                    }
                });
                const interval = Math.max(totalDuration / totalSteps, 500);
                console.log('[recorder] Reveal.js: totalSteps=' + totalSteps + ' interval=' + interval + 'ms');
                Reveal.configure({
                    autoSlide: interval,
                    autoSlideStoppable: false,
                });
                Reveal.slide(0, 0, 0);
            }
        }"""
        )

        # Wait for recording to complete
        page.wait_for_timeout(duration * 1000)

        # Get video path before closing context
        video_path = page.video.path()
        print(f"Recording file: {video_path}")

        context.close()
        browser.close()

    # Move recorded file to target path
    if video_path and Path(video_path).exists():
        shutil.move(str(video_path), str(webm_path))
        print(f"WebM saved: {webm_path}")

    # Convert WebM to MP4 (H.264)
    print("Converting to MP4...")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(webm_path),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
        )
        print(f"MP4 saved: {output_path}")
    finally:
        webm_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m textbook2video.pipeline.recorder <input.html> <output.mp4> [duration]")
        sys.exit(1)

    html_file = sys.argv[1]
    output_file = sys.argv[2]
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    record_html_to_video(html_file, output_file, duration)
