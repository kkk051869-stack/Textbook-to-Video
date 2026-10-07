"""Render an isolated presentation candidate through the existing video stack.

This adapter is deliberately outside the production pipeline.  It consumes the
candidate emitted by :mod:`presentation_compiler`, writes standalone HTML,
runs browser-layout checks with a bounded CSS repair attempt, and can record a
mock MP4.  The mock path supplies silent audio only to exercise composition;
it does not claim TTS, subtitles, or rendered semantic alignment.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from base64 import b64encode
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textbook2video.animation_gen import (
    TEMPLATES_DIR,
    build_slide_timelines,
    infer_transitions,
    merge_html,
)
from textbook2video.pipeline.compose import mux_audio_video
from textbook2video.pipeline.recorder import record_html_to_video
from textbook2video.template_renderer import render_slide

LayoutRunner = Callable[[Path, Path], dict[str, Any]]


def _duration_ms(segment: dict[str, Any]) -> int:
    duration = float(segment.get("audio_duration_sec") or 0.0)
    return max(1_000, round(max(duration, 1.0) * 1_000))


def build_candidate_html(candidate: dict[str, Any], *, title: str = "Research candidate") -> str:
    """Build standalone HTML using the existing deterministic renderer.

    Planned animation trigger times are passed to the existing slide runtime.
    This function does not convert them into measured object-visibility times.
    """
    segments = candidate.get("renderer_segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("candidate requires non-empty renderer_segments")
    image_data: dict[str, str] = {}
    image_keys: set[str] = set()
    for segment in segments:
        for element in segment.get("elements", []) or []:
            source = element.get("src") if isinstance(element, dict) else None
            if not source or element.get("type") != "image":
                continue
            path = Path(str(source))
            if not path.is_file():
                continue
            key = f"{segment.get('id')}:{element.get('id')}"
            image_keys.add(key)
            suffix = path.suffix.lower().lstrip(".") or "png"
            image_data[str(element.get("id"))] = (
                f"data:image/{suffix};base64,{b64encode(path.read_bytes()).decode('ascii')}"
            )
    rendered = [
        render_slide(segment, slide_index=index, available_image_keys=image_keys)
        for index, segment in enumerate(segments)
    ]
    if any(slide is None for slide in rendered):
        raise ValueError("candidate contains a renderer segment that cannot be rendered")
    filled_slides: list[str] = []
    for slide in rendered:
        assert slide is not None
        for element_id, uri in image_data.items():
            image_tag = (
                f'<img src="{uri}" alt="candidate visual" '
                'style="max-width:100%;max-height:100%;object-fit:contain;border-radius:12px;">'
            )
            slide = slide.replace(
                "{{IMG_" + element_id + "}}",
                image_tag,
            )
        filled_slides.append(slide)
    shell_template = (TEMPLATES_DIR / "base-template.html").read_text(encoding="utf-8")
    css_framework = (TEMPLATES_DIR / "base.css").read_text(encoding="utf-8")
    js_controller = (TEMPLATES_DIR / "slide-controller.js").read_text(encoding="utf-8")
    js_particles = (TEMPLATES_DIR / "particle-canvas.js").read_text(encoding="utf-8")
    return merge_html(
        filled_slides,
        [],
        shell_template,
        css_framework,
        js_controller,
        js_particles,
        [_duration_ms(segment) for segment in segments],
        title,
        timelines=build_slide_timelines(segments),
        transitions=infer_transitions(segments),
    )


def write_candidate_html(candidate: dict[str, Any], output_path: str | Path) -> Path:
    """Write an isolated candidate HTML file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_candidate_html(candidate), encoding="utf-8")
    return output


def run_layout_check(html_path: Path, report_path: Path) -> dict[str, Any]:
    """Run the repository browser geometry checker and return its JSON report."""
    script = Path(__file__).resolve().parents[3] / "scripts" / "check_layout.py"
    command = [sys.executable, str(script), str(html_path), "--json", str(report_path)]
    browser_channel = os.getenv("T2V_LAYOUT_BROWSER_CHANNEL", "").strip()
    if browser_channel:
        command.extend(["--browser-channel", browser_channel])
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if not report_path.exists():
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(
            f"layout checker did not produce a report: exit={completed.returncode}; stderr={stderr}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["checker_exit_code"] = completed.returncode
    return report


def _layout_passed(report: dict[str, Any]) -> bool:
    if report.get("checker_exit_code", 0) != 0:
        return False
    risks = [
        risk
        for risk in [*(report.get("staticRisks") or []), *(report.get("risks") or [])]
        if isinstance(risk, dict) and risk.get("severity") in {"error", "fail"}
    ]
    slides = report.get("slides") or []
    return not risks and all(
        slide.get("passed", False) for slide in slides if isinstance(slide, dict)
    )


def _apply_candidate_layout_hotfix(html_path: Path) -> None:
    """Apply one conservative, candidate-local overflow repair."""
    css = """
/* candidate-local bounded repair; baseline templates remain unchanged */
.slide .content-box, .slide .content-grid, .slide .content-area { overflow: hidden; }
.slide [data-anim-id] { max-width: 100%; box-sizing: border-box; }
""".strip()
    source = html_path.read_text(encoding="utf-8")
    if css in source:
        return
    if "</head>" in source:
        source = source.replace("</head>", f"<style>{css}</style></head>", 1)
    else:
        source = f"<style>{css}</style>{source}"
    html_path.write_text(source, encoding="utf-8")


def check_and_repair_layout(
    html_path: str | Path,
    output_dir: str | Path,
    *,
    max_attempts: int = 3,
    layout_runner: LayoutRunner = run_layout_check,
) -> list[dict[str, Any]]:
    """Check candidate layout and allow at most one stateful CSS repair.

    The applied-state set prevents an HTML/CSS repair loop.  The reports are
    browser-layout evidence only, not a pedagogical or visibility measurement.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    html = Path(html_path)
    reports_dir = Path(output_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    applied_states: set[str] = set()
    for attempt in range(1, max_attempts + 1):
        report_path = reports_dir / f"layout_attempt_{attempt}.json"
        report = layout_runner(html, report_path)
        result = {
            "attempt": attempt,
            "report_path": str(report_path),
            "passed": _layout_passed(report),
        }
        results.append(result)
        if result["passed"]:
            break
        state = "overflow_hotfix_v0.1"
        if state in applied_states:
            result["stopped_reason"] = "repair_state_repeated"
            break
        applied_states.add(state)
        _apply_candidate_layout_hotfix(html)
        result["repair_applied"] = state
    return results


def _write_silent_audio(output_path: Path, duration_sec: float) -> Path:
    """Generate silent AAC solely for exercising mock video composition."""
    _ensure_ffmpeg_on_path()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            f"{max(duration_sec, 1.0):.3f}",
            "-c:a",
            "aac",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def _ensure_ffmpeg_on_path() -> None:
    """Make an installed imageio-ffmpeg binary visible to existing pipeline code."""
    if shutil.which("ffmpeg") is not None:
        return
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("ffmpeg is required to compose a candidate MP4") from exc
    executable = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not executable.exists():
        raise RuntimeError("imageio-ffmpeg did not provide an executable")
    shim_dir = Path(tempfile.gettempdir()) / "textbook2video-research-ffmpeg"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    shim = shim_dir / shim_name
    if not shim.exists():
        try:
            os.link(executable, shim)
        except OSError:
            shutil.copy2(executable, shim)
    os.environ["PATH"] = f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def render_candidate_mp4(
    candidate_path: str | Path,
    output_dir: str | Path,
    *,
    max_layout_attempts: int = 3,
    layout_runner: LayoutRunner = run_layout_check,
) -> dict[str, Any]:
    """Render a mock candidate MP4 in an isolated output directory."""
    candidate_file = Path(candidate_path)
    candidate = json.loads(candidate_file.read_text(encoding="utf-8"))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _ensure_ffmpeg_on_path()
    html_path = write_candidate_html(candidate, output / "candidate.html")
    layout_results = check_and_repair_layout(
        html_path, output / "layout", max_attempts=max_layout_attempts, layout_runner=layout_runner
    )
    duration_sec = sum(_duration_ms(segment) for segment in candidate["renderer_segments"]) / 1_000
    silent_video = output / "candidate_silent.mp4"
    record_html_to_video(str(html_path), str(silent_video), duration=max(1, round(duration_sec)))
    silent_audio = _write_silent_audio(output / "candidate_mock_silence.m4a", duration_sec)
    final_video = mux_audio_video(silent_video, silent_audio, output / "candidate_mock.mp4")
    manifest = {
        "candidate_path": str(candidate_file),
        "html_path": str(html_path),
        "video_path": str(final_video),
        "layout_results": layout_results,
        "audio_kind": "generated_silence_for_mock_only",
        "baseline_mutated": False,
        "rendered_visibility_claim": "not_measured_by_this_run",
    }
    (output / "render_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


__all__ = [
    "build_candidate_html",
    "check_and_repair_layout",
    "render_candidate_mp4",
    "run_layout_check",
    "write_candidate_html",
]
