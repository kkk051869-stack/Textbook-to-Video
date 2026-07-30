#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local Flask interface for the Textbook-to-Video pipeline."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "output" / "web_demo"
ALLOWED_SUFFIXES = {".docx", ".pdf"}
DEFAULT_THEME = "dark-blue-academic"
DEFAULT_MODEL = "ecnu-plus"
PAGE_VERSION = "web-v3"
PREFERRED_PYTHONS = [
    Path(r"D:\anaconda3\envs\textbook2video\python.exe"),
    ROOT / ".venv" / "Scripts" / "python.exe",
]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

jobs: dict[str, dict[str, Any]] = {}


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def cli_python() -> str:
    env_python = os.environ.get("T2V_WEB_PYTHON")
    if env_python and Path(env_python).exists():
        return env_python
    for candidate in PREFERRED_PYTHONS:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def cli_env() -> dict[str, str]:
    env = dict(os.environ)
    src = str(ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not existing else f"{src};{existing}"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def cli_command(*args: str) -> list[str]:
    t2v = shutil.which("t2v")
    if t2v:
        return [t2v, *args]
    return [cli_python(), "-m", "textbook2video.cli", *args]


def parse_lesson_line(line: str, suffix: str) -> dict[str, Any] | None:
    is_pdf = suffix.lower() == ".pdf"

    chapter_section = re.search(r"Chapter\s+(\d+)\s*,\s*Section\s+(\d+)", line, re.I)
    if chapter_section:
        chapter = int(chapter_section.group(1))
        section = int(chapter_section.group(2))
        return {"mode": "pdf" if is_pdf else "docx", "lesson": chapter + 1, "chapter": chapter, "section": section, "label": line.strip()}

    chapter_only = re.search(r"Chapter\s+(\d+)", line, re.I)
    if chapter_only:
        chapter = int(chapter_only.group(1))
        return {"mode": "pdf" if is_pdf else "docx", "lesson": chapter + 1, "chapter": chapter, "section": 0, "label": line.strip()}

    lesson = re.search(r"Lesson\s*(\d+)", line, re.I)
    if lesson:
        lesson_num = int(lesson.group(1))
        return {"mode": "pdf", "lesson": lesson_num, "chapter": max(lesson_num - 1, 0), "section": 0, "label": line.strip()}

    section_only = re.search(r"Section\s+(\d+)", line, re.I)
    if section_only:
        chapter = max(int(section_only.group(1)) - 1, 0)
        return {"mode": "pdf" if is_pdf else "docx", "lesson": chapter + 1, "chapter": chapter, "section": 0, "label": line.strip()}

    return None


def list_docx_sections(path: Path) -> list[dict[str, Any]]:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from textbook2video.pipeline.parser import list_sections_from_docx

        sections = list_sections_from_docx(str(path))
    except Exception:
        return []

    parsed: list[dict[str, Any]] = []
    chapter_numbers: dict[str, int] = {}
    section_counts: dict[str, int] = {}
    for index, item in enumerate(sections, start=1):
        chapter_title = str(item.get("chapter") or "DOCX")
        section_title = str(item.get("section") or f"Section {index}")
        if chapter_title not in chapter_numbers:
            chapter_numbers[chapter_title] = len(chapter_numbers)
            section_counts[chapter_title] = 0
        chapter = chapter_numbers[chapter_title]
        section = section_counts[chapter_title]
        section_counts[chapter_title] += 1
        parsed.append(
            {
                "mode": "docx",
                "lesson": index,
                "chapter": chapter,
                "section": section,
                "label": f"{chapter_title} / {section_title}",
            }
        )
    return parsed


def list_lessons(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".docx":
        return list_docx_sections(path)

    try:
        result = subprocess.run(
            cli_command("list-lessons", str(path)),
            cwd=str(ROOT),
            env=cli_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    parsed: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for line in result.stdout.splitlines():
        item = parse_lesson_line(line, path.suffix)
        if not item:
            continue
        key = (item["mode"], item.get("lesson") or 0, item["chapter"], item["section"])
        if key in seen:
            continue
        seen.add(key)
        parsed.append(item)
    return parsed


def latest_uploaded_file() -> Path | None:
    files = [p for p in UPLOAD_DIR.iterdir() if p.suffix.lower() in ALLOWED_SUFFIXES]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def progress_from_line(line: str, current: int) -> int:
    lower = line.lower()
    checkpoints = [
        (15, ("script", "讲稿")),
        (30, ("storyboard", "故事板")),
        (45, ("review", "审核")),
        (58, ("tts", "narrat", "配音")),
        (72, ("html", "animat", "渲染", "动画")),
        (86, ("record", "录制")),
        (94, ("compose", "mux", "合成")),
    ]
    for value, keywords in checkpoints:
        if any(keyword in lower for keyword in keywords):
            return max(current, value)
    return current


def run_job(job_id: str, input_file: Path, mode: str, lesson: int | None, chapter: int, section: int, theme: str, model: str) -> None:
    output_dir = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    jobs[job_id].update({"status": "running", "progress": 3, "output": [], "output_dir": str(output_dir)})

    cmd = cli_command("produce", str(input_file))
    mode = "pdf" if input_file.suffix.lower() == ".pdf" else "docx"
    if mode == "pdf":
        cmd.extend(["--lesson", str(lesson or 1)])
    else:
        cmd.extend(["--chapter", str(chapter), "--section", str(section)])
    cmd.extend(["--theme", theme, "--model", model, "-o", str(output_dir)])
    jobs[job_id]["command"] = " ".join(cmd)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=cli_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            output = jobs[job_id]["output"]
            output.append(line)
            del output[:-120]
            jobs[job_id]["progress"] = progress_from_line(line, jobs[job_id]["progress"])

        return_code = process.wait()
        if return_code != 0:
            jobs[job_id].update({"status": "failed", "error": "生成命令执行失败"})
            return

        videos = sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not videos:
            jobs[job_id].update({"status": "failed", "error": "未找到生成的视频文件"})
            return

        jobs[job_id].update(
            {
                "status": "completed",
                "progress": 100,
                "video_path": str(videos[0]),
                "completed_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    except Exception as exc:
        jobs[job_id].update({"status": "failed", "error": str(exc)})


@app.route("/")
def index():
    return render_template("index.html", page_version=PAGE_VERSION)


@app.route("/api/upload", methods=["POST"])
def upload():
    upload_file = request.files.get("file")
    if not upload_file or not upload_file.filename:
        return jsonify({"success": False, "error": "请选择 DOCX 或 PDF 文件"}), 400

    suffix = Path(upload_file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return jsonify({"success": False, "error": "仅支持 DOCX 或 PDF 文件"}), 400

    filename = f"{datetime.now():%Y%m%d_%H%M%S}_{secure_filename(upload_file.filename)}"
    filepath = UPLOAD_DIR / filename
    upload_file.save(filepath)
    lessons = list_lessons(filepath)
    return jsonify(
        {
            "success": True,
            "filename": upload_file.filename,
            "filepath": str(filepath),
            "lessons": lessons,
        }
    )


@app.route("/api/lessons", methods=["GET"])
def lessons():
    path = latest_uploaded_file()
    if not path:
        return jsonify({"success": False, "error": "暂无已上传教材"}), 404
    return jsonify({"success": True, "filename": path.name, "filepath": str(path), "lessons": list_lessons(path)})


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    try:
        filepath = Path(str(data["filepath"])).resolve()
        suffix = filepath.suffix.lower()
        mode = "pdf" if suffix == ".pdf" else "docx"
        lesson = data.get("lesson")
        lesson = int(lesson) if lesson is not None else None
        chapter = data.get("chapter")
        chapter = int(chapter) if chapter is not None else None
        section = data.get("section")
        section = int(section) if section is not None else None
        theme = str(data.get("theme") or DEFAULT_THEME)
        model = str(data.get("model") or DEFAULT_MODEL)
    except Exception:
        return jsonify({"success": False, "error": "生成参数不完整"}), 400

    try:
        filepath.relative_to(ROOT)
    except ValueError:
        return jsonify({"success": False, "error": "文件路径不在项目目录内"}), 400

    if not filepath.exists() or filepath.suffix.lower() not in ALLOWED_SUFFIXES:
        return jsonify({"success": False, "error": "教材文件不存在或格式不支持"}), 400

    if mode == "pdf" and lesson is None:
        return jsonify({"success": False, "error": "PDF material requires lesson"}), 400
    if mode == "docx" and (chapter is None or section is None):
        return jsonify({"success": False, "error": "DOCX material requires chapter and section"}), 400

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "output": [],
        "error": None,
        "video_path": None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    thread = threading.Thread(target=run_job, args=(job_id, filepath, mode, lesson, chapter, section, theme, model), daemon=True)
    thread.start()
    return jsonify({"success": True, "job_id": job_id})


@app.route("/api/job/<job_id>", methods=["GET"])
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    return jsonify(
        {
            "success": True,
            "status": job["status"],
            "progress": job["progress"],
            "output": "\n".join(job["output"][-80:]),
            "error": job["error"],
            "video_path": job["video_path"],
            "command": job.get("command"),
        }
    )


@app.route("/api/download/<job_id>", methods=["GET"])
def download(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    if job["status"] != "completed" or not job["video_path"]:
        return jsonify({"success": False, "error": "视频尚未生成完成"}), 400
    video = Path(job["video_path"])
    if not video.exists():
        return jsonify({"success": False, "error": "视频文件不存在"}), 404
    return send_file(video, mimetype="video/mp4", as_attachment=True, download_name=f"{job_id}.mp4")


if __name__ == "__main__":
    print("=" * 64)
    print("Textbook-to-Video Web")
    print("http://127.0.0.1:5000")
    print("=" * 64)
    app.run(host="127.0.0.1", port=5000, debug=False)
