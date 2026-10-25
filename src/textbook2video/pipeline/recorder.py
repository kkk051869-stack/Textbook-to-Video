"""
Playwright 录制模块：HTML 动画页面 → MP4 视频

支持现代 SlideController 的像素标记校准录制，以及无时长控制器/Reveal.js 的旧兼容录制。
现代路径统一动画起点、按绝对页边界切页，核对实际录制区间后删除校准段；
原始 WebM 与 clock.json 保留。旧兼容路径不具备校准证明。

用法：
  from textbook2video.pipeline.recorder import record_html_to_video
  record_html_to_video("output/demo.html", "output/demo.mp4", duration=35)

CLI:
  python -m textbook2video.pipeline.recorder input.html output.mp4 [duration]
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from textbook2video.pipeline.recording_clock import (
    PLAYBACK_JS,
    media_interval,
    save_clock,
    validate_options,
    validate_runtime,
)


def record_html_to_video(
    html_path: str,
    output_path: str,
    duration: int = 30,
    fps: int = 30,
    *,
    browser_channel: str = "msedge",
    viewport_width: int = 1920,
    viewport_height: int = 1080,
    trace_path: str | None = None,
):
    """
    打开 HTML 动画页面，自动翻页，录制为 WebM，再转为 MP4。

    翻页策略（优先级从高到低）：
      1. SlideController + slideDurations — 统一起点、绝对时刻切页、实际媒体校准
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

    已有结果或证据文件不会覆盖；请选择新输出路径。带时长的旧控制器缺少
    录制接口时明确失败，需要用当前模板重新生成 HTML。
    """
    html_path = Path(html_path).resolve()
    output_path = Path(output_path).resolve()
    validate_options(duration, fps)
    if any(path.exists() for path in (
        output_path, output_path.with_suffix(".raw.webm"), output_path.with_suffix(".clock.json"),
        output_path.with_suffix(".partial.mp4"),
    )):
        raise FileExistsError("Recording output already exists; choose a new output path")
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
            executable = os.getenv("T2V_BROWSER_EXECUTABLE", "").strip() or None
            browser = p.chromium.launch(executable_path=executable)
        context = browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            record_video_dir=str(webm_path.parent),
            record_video_size={"width": viewport_width, "height": viewport_height},
        )
        page = context.new_page()
        try:
            page.add_init_script("window.__t2vDeferPlayback = true;")
            page.goto(html_path.as_uri())
            page.wait_for_load_state("networkidle")
            print("页面加载完成")
            has_timing = page.evaluate("""() => Boolean(window.SlideController &&
                (window.slideDurations || window.SlideController.slideDurations || []).length)""")
        except Exception as error:
            _close_capture(page, context, browser, output_path, {
                "status": "FAILED", "stage": "load", "failure_type": type(error).__name__,
                "html_path": str(html_path),
            })
            raise
        if has_timing:
            _record_calibrated(
                page, context, browser, output_path, duration=duration, fps=fps,
                html_path=html_path, trace_path=trace_path,
            )
            return
        page.evaluate("""() => {
            if (window.SlideController && window.SlideController.startRecording)
                window.SlideController.startRecording();
        }""")

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
                            // ``next`` keeps the incoming slide in its transition for
                            // transitionLeadMs. Start the next page's audio clock only
                            // after that transition has completed, otherwise every page
                            // after the first is shortened by the transition duration.
                            setTimeout(advance, transitionLeadMs);
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
                console.log('[recorder] uniform interval=' + interval + 'ms, total=' + total);
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
                console.log('[recorder] Reveal.js: steps=' + totalSteps + ' interval=' + interval);
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

        # The controller owns the animation clock.  Read its browser-side
        # observation before closing the context; a planned storyboard time
        # alone is not evidence that a target was resolved and executed.
        # This remains optional so frozen baseline invocations retain their
        # historical output surface.
        if trace_path:
            trace_destination = Path(trace_path).resolve()
            trace_destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                runtime_events = page.evaluate(
                    """() => typeof window.exportAnimationTrace === 'function'
                        ? window.exportAnimationTrace() : []"""
                )
                payload = {
                    "schema_version": "t2v-browser-runtime-trace-v0.2",
                    "html_path": str(html_path),
                    "recording_duration_sec": duration,
                    "viewport": {"width": viewport_width, "height": viewport_height},
                    "events": runtime_events if isinstance(runtime_events, list) else [],
                    "claim": (
                        "Browser-observed event execution on the rendered HTML; "
                        "this is distinct from frame-level MP4 visibility verification."
                    ),
                }
                trace_destination.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"运行时动画 trace: {trace_destination}")
            except Exception as exc:  # noqa: BLE001 - recording itself is still valid
                print(f"  ⚠️ 无法导出浏览器动画 trace: {type(exc).__name__}: {exc}")

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
                _ffmpeg_executable(),
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


def _record_calibrated(
    page, context, browser, output_path, *, duration, fps, html_path, trace_path,
):
    raw_path = output_path.with_suffix(".raw.webm")
    report_path = output_path.with_suffix(".clock.json")
    report = {"status": "FAILED", "html_path": str(html_path), "raw_video": str(raw_path),
              "claim": "Media interval calibration and browser timing, not course frame acceptance"}
    try:
        slate_ms = max(600, 3000 / fps)
        expected = page.evaluate(PLAYBACK_JS, {"durationMs": duration * 1000, "slateMs": slate_ms})
        page.wait_for_function("window.__t2vRecordingClock.done", timeout=duration * 1000 + 30000)
        page.wait_for_timeout(slate_ms)  # Let the encoder observe the terminal slate.
        report["runtime"] = page.evaluate("window.__t2vRecordingClock")
        if trace_path:
            trace_destination = Path(trace_path).resolve()
            trace_destination.parent.mkdir(parents=True, exist_ok=True)
            save_clock(trace_destination, {
                "schema_version": "t2v-browser-runtime-trace-v0.2",
                "html_path": str(html_path), "recording_duration_sec": duration,
                "viewport": page.viewport_size,
                "events": report["runtime"]["events"],
                "claim": "Browser execution only; distinct from MP4 visibility verification",
            })
    finally:
        _close_capture(page, context, browser, output_path, report)
    try:
        validate_runtime(
            report["runtime"], expected_pages=expected["expected_pages"], duration=duration
        )
        interval = media_interval(raw_path, ffmpeg=_ffmpeg_executable(), duration=duration, fps=fps)
        report["media"] = interval
        partial_path = output_path.with_suffix(".partial.mp4")
        subprocess.run([
            _ffmpeg_executable(), "-y", "-i", str(raw_path),
            "-ss", str(interval["content_start_sec"]),
            "-t", str(interval["measured_content_sec"]),
            "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial_path),
        ], check=True, capture_output=True)
        partial_path.replace(output_path)
        report["status"] = "CALIBRATED"
    finally:
        _save_clock_preserving_error(report_path, report)


def _save_clock_preserving_error(path, report):
    primary = sys.exception()
    try:
        save_clock(path, report)
    except Exception as error:
        if primary is None:
            raise
        primary.add_note(f"Clock report could not be written ({type(error).__name__}): {path}")


def _close_capture(page, context, browser, output_path, report):
    primary = sys.exception()
    cleanup_errors = []
    capture_path = None
    try:
        capture_path = Path(page.video.path()) if page.video else None
    except Exception as error:
        cleanup_errors.append(type(error).__name__)
    for close in (context.close, browser.close):
        try:
            close()
        except Exception as error:
            cleanup_errors.append(type(error).__name__)
    try:
        if capture_path and capture_path.exists():
            shutil.move(str(capture_path), str(output_path.with_suffix(".raw.webm")))
    except Exception as error:
        cleanup_errors.append(type(error).__name__)
    report["cleanup_errors"] = cleanup_errors
    _save_clock_preserving_error(output_path.with_suffix(".clock.json"), report)
    if cleanup_errors:
        if primary is not None:
            primary.add_note(f"Recording cleanup errors: {', '.join(cleanup_errors)}")
        else:
            raise RuntimeError("Recording cleanup failed; inspect clock report and raw video")


def _ffmpeg_executable() -> str:
    """Resolve system ffmpeg or imageio-ffmpeg's bundled binary."""
    import os

    configured = os.getenv("T2V_FFMPEG")
    if configured:
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return "ffmpeg"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python -m textbook2video.pipeline.recorder "
              "<input.html> <output.mp4> [duration]")
        sys.exit(1)
    record_html_to_video(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 30)
