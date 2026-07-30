"""
Playwright 录制模块：HTML 动画页面 → MP4 视频

支持三种 slide 方案（自动检测）：
  1. 自写 SlideController + slideDurations（HTML 自带精确翻页，recorder 不干涉）
  2. 自写 SlideController 无 slideDurations（recorder 注入均匀翻页）
  3. Reveal.js（旧方案兼容）

用法：
  from textbook2video.pipeline.recorder import record_html_to_video
  record_html_to_video("output/demo.html", "output/demo.mp4", duration=35)

CLI:
  python -m textbook2video.pipeline.recorder input.html output.mp4 [duration]
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
    打开 HTML 动画页面，自动翻页，录制为 WebM，再转为 MP4。

    翻页策略（优先级从高到低）：
      1. HTML 自带 SlideController.slideDurations — recorder 完全不干涉，等 HTML 自己翻
      2. HTML 自带全局 SLIDE_TIMES 数组 — recorder 按精确时间驱动 SlideController.next()
      3. SlideController 无精确时长 — recorder 按总时长均匀分配
      4. Reveal.js — 用其 autoSlide 配置

    Args:
        html_path: HTML 文件路径
        output_path: 输出视频路径 (.mp4)
        duration: 总录制时长（秒）
        fps: 帧率
        browser_channel: Playwright 浏览器通道（默认使用系统 Edge）
        viewport_width: 视口宽度
        viewport_height: 视口高度
    """
    html_path = Path(html_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    webm_path = output_path.with_suffix(".webm")

    print(f"录制: {html_path}")
    print(f"输出: {output_path}")
    print(f"时长: {duration}s, 帧率: {fps}fps")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=browser_channel)
        except Exception as exc:  # noqa: BLE001 — 无对应 channel 浏览器时回退
            print(
                f"  ⚠️ 浏览器 channel={browser_channel} 不可用"
                f"（{type(exc).__name__}），回退内置 chromium"
            )
            browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            record_video_dir=str(webm_path.parent),
            record_video_size={"width": viewport_width, "height": viewport_height},
        )
        page = context.new_page()

        # 打开 HTML 文件
        page.goto(f"file:///{str(html_path).replace(chr(92), '/')}")
        page.wait_for_load_state("networkidle")
        print("页面加载完成")

        # 检测页面已有的翻页机制，按需注入自动翻页
        page.evaluate(
            """() => {
            const totalDuration = """
            + str(duration * 1000)
            + """;

            // 方式1: HTML 注入了逐页真实时长 — recorder 按真实音频时长精确翻页
            const preciseDurations =
                (window.slideDurations && window.slideDurations.length > 0)
                    ? window.slideDurations
                    : (
                        typeof SlideController !== 'undefined' &&
                        SlideController.slideDurations &&
                        SlideController.slideDurations.length > 0
                    )
                        ? SlideController.slideDurations
                        : null;
            if (preciseDurations && typeof SlideController !== 'undefined') {
                console.log('[recorder] using slideDurations for auto-advance', preciseDurations);
                (function () {
                    let idx = 0;
                    const transitionLeadMs = 500;
                    function advance() {
                        if (idx >= preciseDurations.length - 1) return;
                        const duration = Number(preciseDurations[idx]) || 0;
                        const delay = Math.max(duration - transitionLeadMs, 300);
                        setTimeout(() => {
                            SlideController.next();
                            idx++;
                            advance();
                        }, delay);
                    }
                    advance();
                })();
                return;
            }

            // 方式2: 全局 SLIDE_TIMES 数组（精确时长驱动）
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

            // 方式3: SlideController 无精确时长 — 均匀分配
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

            // 方式4: Reveal.js（旧方案兼容）
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

        # 等待录制完成
        page.wait_for_timeout(duration * 1000)

        # 关闭前获取 WebM 文件路径
        video_path = page.video.path()
        print(f"录制文件: {video_path}")

        context.close()
        browser.close()

    # 将录制文件重命名为目标路径
    if video_path and Path(video_path).exists():
        shutil.move(str(video_path), str(webm_path))
        print(f"WebM 已保存: {webm_path}")

    # WebM 转 MP4 (H.264)；无论成功与否都清理 WebM 临时文件，避免转码失败时泄露
    print("转换为 MP4...")
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
        print(f"MP4 已保存: {output_path}")
    finally:
        webm_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python -m textbook2video.pipeline.recorder <input.html> <output.mp4> [duration]")
        sys.exit(1)

    html_file = sys.argv[1]
    output_file = sys.argv[2]
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    record_html_to_video(html_file, output_file, duration)
