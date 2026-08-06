"""Generate videos for the five chapter DOCX files with local Qwen3-32B vLLM.

This runner treats each DOCX file as one lesson. It writes all generated
artifacts outside the git worktree under /ai/data/textbook-to-video.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from docx import Document


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_.")
    return text or "lesson"


def read_docx_text(path: Path) -> str:
    doc = Document(str(path))
    chunks: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_one(docx_path: Path, output_root: Path, model: str) -> dict[str, Any]:
    from textbook2video.animation_gen import generate as animate
    from textbook2video.pipeline.compose import compose_video
    from textbook2video.pipeline.lesson_plan import generate_lesson_plan
    from textbook2video.pipeline.narrator import generate_audio, get_audio_duration
    from textbook2video.pipeline.recorder import record_html_to_video
    from textbook2video.pipeline.scriptwriter import generate_script
    from textbook2video.pipeline.storyboard import generate_storyboard
    from textbook2video.pipeline.subtitles import generate_srt
    from textbook2video.pipeline.timing import apply_timing, timed_storyboard_path

    title = docx_path.stem
    stem = slugify(title)
    out_dir = output_root / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "run_status.json"
    html_only = os.environ.get("T2V_HTML_ONLY") == "1"

    status: dict[str, Any] = {
        "input": str(docx_path),
        "title": title,
        "output_dir": str(out_dir),
        "model": model,
        "theme": "dark-blue-academic",
        "state": "running",
    }
    write_json(status_path, status)

    raw_path = out_dir / f"{stem}_raw.txt"
    if raw_path.exists():
        text = raw_path.read_text(encoding="utf-8")
    else:
        text = read_docx_text(docx_path)
        raw_path.write_text(text, encoding="utf-8")
    status["raw_path"] = str(raw_path)
    status["raw_chars"] = len(text)
    write_json(status_path, status)

    lesson_plan_path = out_dir / f"{stem}_lesson_plan.json"
    if lesson_plan_path.exists():
        lesson_plan = json.loads(lesson_plan_path.read_text(encoding="utf-8"))
    else:
        lesson_plan = generate_lesson_plan(text, lesson_title=title, model=model)
        write_json(lesson_plan_path, lesson_plan)
    status["lesson_plan_path"] = str(lesson_plan_path)
    write_json(status_path, status)

    script_path = out_dir / f"{stem}_script.txt"
    if script_path.exists():
        script_segments = [
            block.strip()
            for block in re.split(r"\n\s*\n", script_path.read_text(encoding="utf-8"))
            if block.strip()
        ]
        script_segments = [
            re.sub(r"^Segment\s+\d+\s*:\s*", "", s, flags=re.IGNORECASE).strip()
            for s in script_segments
        ]
    else:
        script_segments = generate_script(text, model=model, lesson_plan=lesson_plan)
        with script_path.open("w", encoding="utf-8") as f:
            for i, seg in enumerate(script_segments, 1):
                f.write(f"Segment {i}:\n{seg}\n\n")
    status["script_path"] = str(script_path)
    status["script_segments"] = len(script_segments)
    write_json(status_path, status)

    storyboard_path = out_dir / f"{stem}_storyboard.json"
    if storyboard_path.exists():
        storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    else:
        storyboard = generate_storyboard(
            script_segments,
            lesson_title=title,
            model=model,
            lesson_plan=lesson_plan,
        )
        write_json(storyboard_path, storyboard)
    status["storyboard_path"] = str(storyboard_path)
    status["slides"] = len(storyboard.get("segments", []))
    write_json(status_path, status)

    durations: list[float] = []
    audio_dir = out_dir / f"{stem}_audio"
    if not html_only:
        expected_audio = [audio_dir / f"s{i + 1}.mp3" for i in range(len(storyboard["segments"]))]
        if not all(p.exists() and p.stat().st_size > 0 for p in expected_audio):
            narrations = [seg["narration"] for seg in storyboard["segments"]]
            generate_audio(narrations, output_dir=str(audio_dir))

        durations = [round(get_audio_duration(str(p)), 1) for p in expected_audio]
        for i, seg in enumerate(storyboard["segments"]):
            seg["audio_duration_sec"] = durations[i]
        storyboard = apply_timing(storyboard)
        write_json(storyboard_path, storyboard)
        timed_path = timed_storyboard_path(storyboard_path)
        write_json(timed_path, storyboard)
        status["audio_dir"] = str(audio_dir)
        status["total_audio_sec"] = round(sum(durations), 1)
        write_json(status_path, status)

    html_path = out_dir / f"{stem}-pipeline-dark-blue-academic.html"
    if not html_path.exists():
        if html_only:
            os.environ.setdefault("T2V_SKIP_SVG", "1")
        html_path = animate(
            storyboard_path,
            output_dir=out_dir,
            model=model,
            batch_size=4,
            theme_id="dark-blue-academic",
            layout_repair_attempts=2,
            layout_browser_channel="",
            skip_image_gen=True,
        )
    status["html_path"] = str(html_path)
    if html_only:
        status["state"] = "done_html"
        write_json(status_path, status)
        return status
    write_json(status_path, status)

    final_mp4 = out_dir / f"{stem}.mp4"
    silent_mp4 = out_dir / f"{stem}_silent.mp4"
    subtitle_path = out_dir / f"{stem}.srt"
    if not final_mp4.exists():
        generate_srt(str(storyboard_path), subtitle_path)
        record_html_to_video(
            str(html_path),
            str(silent_mp4),
            duration=math.ceil(sum(durations)) + 1,
            fps=30,
            browser_channel="",
        )
        compose_video(silent_mp4, audio_dir, final_mp4, subtitle_path=subtitle_path)
    status["silent_mp4"] = str(silent_mp4)
    status["final_mp4"] = str(final_mp4)
    status["state"] = "done"
    write_json(status_path, status)
    return status


def main() -> int:
    input_dir = Path(
        os.environ.get(
            "T2V_INPUT_DIR",
            "/ai/data/textbook-to-video/inputs/presentagent-video-demo/"
            "extracted_utf8/计算机科学讲义-v2",
        )
    )
    output_root = Path(
        os.environ.get(
            "T2V_OUTPUT_ROOT",
            "/ai/data/textbook-to-video/outputs/textbook2video-qwen32b-blue",
        )
    )
    model = os.environ.get("T2V_MODEL", "qwen3-32b-awq")
    output_root.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    for docx_path in sorted(input_dir.glob("*.docx")):
        try:
            manifest.append(run_one(docx_path, output_root, model))
        except Exception as exc:  # noqa: BLE001
            failed_dir = output_root / slugify(docx_path.stem)
            failed_dir.mkdir(parents=True, exist_ok=True)
            status = {
                "input": str(docx_path),
                "title": docx_path.stem,
                "state": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            write_json(failed_dir / "run_status.json", status)
            manifest.append(status)
            print(f"FAILED {docx_path}: {status['error']}", file=sys.stderr)
    write_json(output_root / "manifest.json", manifest)
    success_states = {"done", "done_html"}
    return 0 if all(item.get("state") in success_states for item in manifest) else 1


if __name__ == "__main__":
    raise SystemExit(main())
