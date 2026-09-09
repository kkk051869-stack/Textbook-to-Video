from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


EXP_ROOT = Path("/ai/data/textbook-to-video/experiments/presentagent-comparison-v1")
INVENTORY = EXP_ROOT / "metrics/statistics/formal_video_inventory_24.csv"
OUTPUT_ROOT = EXP_ROOT / "metrics/vlm/judge_inputs"
FFMPEG = Path("/ai/data/repos/Textbook-to-Video/.venv/bin/ffmpeg")


LESSON_IDS = [
    "lesson_001",
    "lesson_002",
    "lesson_004",
    "lesson_005",
    "lesson_007",
    "lesson_008",
    "lesson_011",
    "lesson_012",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_if_exists(src: Path, dst: Path) -> str:
    if not src.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def select_existing_frames(paths: list[Path], limit: int = 7) -> list[Path]:
    paths = [p for p in sorted(paths) if p.exists()]
    if len(paths) <= limit:
        return paths
    if limit <= 1:
        return [paths[0]]
    picks = []
    for i in range(limit):
        idx = round(i * (len(paths) - 1) / (limit - 1))
        picks.append(paths[idx])
    return picks


def extract_keyframes(video: Path, out_dir: Path, duration_sec: str, count: int = 5) -> list[str]:
    if not FFMPEG.exists() or not video.exists():
        return []
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for idx, ratio in enumerate([0.10, 0.30, 0.50, 0.70, 0.90][:count], start=1):
        ts = max(0.2, min(duration - 0.2, duration * ratio))
        out = out_dir / f"keyframe_{idx:02d}.jpg"
        cmd = [
            str(FFMPEG),
            "-y",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
            frame_paths.append(str(out))
    return frame_paths


def internal_paths(lesson_id: str, system: str) -> dict[str, Path]:
    if system == "internal_C01":
        branch, condition = "P0", "C01"
    elif system == "internal_C11":
        branch, condition = "P1", "C11"
    else:
        raise ValueError(system)
    formal = EXP_ROOT / "runs/internal_a16_20260808" / lesson_id / branch / "formal"
    run = formal / condition
    content = formal / "content"
    return {
        "run_dir": run,
        "content_dir": content,
        "script": content / "script.txt",
        "subtitles": run / "subtitles.srt",
        "storyboard": run / "storyboard.json",
        "content_storyboard": content / "storyboard.json",
        "timed_storyboard": content / "storyboard_timed.json",
        "run_status": run / "run_status.json",
        "run_config": run / "run_config.json",
        "render_manifest": run / "animation.manifest.json",
        "quality_report": run / "quality_report.json",
        "animation_html": run / "animation.html",
    }


def presentagent_paths(lesson_id: str) -> dict[str, Path]:
    run = EXP_ROOT / "runs/presentagent" / lesson_id
    task = run / "presentagent_video_task"
    return {
        "run_dir": run,
        "task_dir": task,
        "notes": run / "notes.json",
        "slide_plan": run / "qwen32b_slide_plan.json",
        "task_json": run / "task.json",
        "history": run / "history.json",
        "run_status": run / "run_status.json",
        "run_config": run / "run_config.json",
        "presentagent_log": run / "presentagent.log",
        "pptx": run / "generated_full_presentagent.pptx",
        "frames_dir": task / "frames_fontfix",
    }


def build_generated_text(row: dict[str, str], paths: dict[str, Path]) -> str:
    system = row["system"]
    if system.startswith("internal_"):
        parts = []
        script = read_text(paths["script"])
        subtitles = read_text(paths["subtitles"])
        if script:
            parts.append("# script.txt\n\n" + script)
        if subtitles:
            parts.append("# subtitles.srt\n\n" + subtitles)
        return "\n\n".join(parts)

    notes = read_json(paths["notes"])
    if isinstance(notes, list):
        return "\n\n".join(f"[slide {i + 1}] {text}" for i, text in enumerate(notes))
    if notes is not None:
        return json.dumps(notes, ensure_ascii=False, indent=2)
    return ""


def build_one(row: dict[str, str]) -> dict[str, object]:
    lesson_id = row["lesson_id"]
    video_id = row["video_id"]
    system = row["system"]
    video = Path(row["cloud_path"])
    lesson_source = EXP_ROOT / "sources/frozen" / lesson_id
    annotation = EXP_ROOT / "private_annotations/B" / lesson_id / "annotation.json"
    out_dir = OUTPUT_ROOT / lesson_id / video_id

    out_dir.mkdir(parents=True, exist_ok=True)
    copied_source_md = copy_if_exists(lesson_source / "source.md", out_dir / "source.md")
    copied_source_json = copy_if_exists(lesson_source / "source.json", out_dir / "source.json")
    copied_annotation = copy_if_exists(annotation, out_dir / "annotation.json")

    if system.startswith("internal_"):
        paths = internal_paths(lesson_id, system)
        existing_frames = list(paths["run_dir"].glob("*.png")) + list(paths["run_dir"].glob("*.jpg"))
        extra_artifacts = {
            "script_path": str(paths["script"]),
            "subtitles_path": str(paths["subtitles"]),
            "storyboard_path": str(paths["storyboard"]),
            "timed_storyboard_path": str(paths["timed_storyboard"]),
            "animation_html_path": str(paths["animation_html"]),
            "run_status_path": str(paths["run_status"]),
            "run_config_path": str(paths["run_config"]),
            "render_manifest_path": str(paths["render_manifest"]),
            "quality_report_path": str(paths["quality_report"]),
        }
        structured_outputs = {
            "run_status": read_json(paths["run_status"]),
            "run_config": read_json(paths["run_config"]),
            "render_manifest": read_json(paths["render_manifest"]),
            "quality_report": read_json(paths["quality_report"]),
            "storyboard": read_json(paths["storyboard"]),
        }
    else:
        paths = presentagent_paths(lesson_id)
        existing_frames = list(paths["frames_dir"].glob("*.jpg")) + list(paths["frames_dir"].glob("*.png"))
        extra_artifacts = {
            "notes_path": str(paths["notes"]),
            "slide_plan_path": str(paths["slide_plan"]),
            "task_json_path": str(paths["task_json"]),
            "history_path": str(paths["history"]),
            "run_status_path": str(paths["run_status"]),
            "run_config_path": str(paths["run_config"]),
            "pptx_path": str(paths["pptx"]),
            "presentagent_log_path": str(paths["presentagent_log"]),
            "frames_dir": str(paths["frames_dir"]),
        }
        structured_outputs = {
            "notes": read_json(paths["notes"]),
            "slide_plan": read_json(paths["slide_plan"]),
            "task": read_json(paths["task_json"]),
            "run_status": read_json(paths["run_status"]),
            "run_config": read_json(paths["run_config"]),
        }

    generated_text = build_generated_text(row, paths)
    generated_text_path = out_dir / "generated_text.txt"
    generated_text_path.write_text(generated_text, encoding="utf-8")

    extracted_frames = extract_keyframes(video, out_dir / "frames", row.get("duration_sec", ""), count=5)
    selected_existing_frames = []
    for i, src in enumerate(select_existing_frames(existing_frames, limit=7), start=1):
        suffix = src.suffix.lower() or ".jpg"
        dst = out_dir / "existing_frames" / f"frame_{i:02d}{suffix}"
        selected_existing_frames.append(copy_if_exists(src, dst))

    bundle = {
        "video_id": video_id,
        "lesson_id": lesson_id,
        "system": system,
        "judge_input_version": "v1",
        "video": {
            "path": str(video),
            "exists": video.exists(),
            "duration_sec": row.get("duration_sec", ""),
            "size_bytes": row.get("size_bytes", ""),
            "sha256": row.get("sha256", sha256(video) if video.exists() else ""),
            "status": row.get("status", ""),
            "quality_ok": row.get("quality_ok", ""),
            "notes": row.get("notes", ""),
        },
        "source": {
            "source_dir": str(lesson_source),
            "source_md": copied_source_md,
            "source_json": copied_source_json,
            "source_pdf": str(lesson_source / "source.pdf"),
            "manifest": str(lesson_source / "manifest.json"),
        },
        "annotation": {
            "path": copied_annotation,
            "source_path": str(annotation),
        },
        "generated_text": {
            "path": str(generated_text_path),
            "char_count": len(generated_text),
        },
        "frames": {
            "extracted_keyframes": extracted_frames,
            "selected_existing_frames": [p for p in selected_existing_frames if p],
        },
        "artifacts": extra_artifacts,
        "structured_outputs": structured_outputs,
        "recommended_judge_tasks": [
            "core_concept_coverage",
            "heldout_question_answerability",
            "image_usage",
            "video_quality",
            "error_detection",
        ],
    }

    bundle_path = out_dir / "input_bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "video_id": video_id,
        "lesson_id": lesson_id,
        "system": system,
        "input_bundle": str(bundle_path),
        "generated_text": str(generated_text_path),
        "frame_count": str(len(extracted_frames) + len([p for p in selected_existing_frames if p])),
        "extracted_keyframes": str(len(extracted_frames)),
        "existing_frames": str(len([p for p in selected_existing_frames if p])),
        "video_path": str(video),
        "video_exists": str(video.exists()),
    }


def main() -> None:
    rows = read_csv(INVENTORY)
    expected = {f"{lesson}__{system}" for lesson in LESSON_IDS for system in ["internal_C01", "internal_C11", "presentagent"]}
    actual = {row["video_id"] for row in rows}
    missing = sorted(expected - actual)
    if missing:
        raise SystemExit(f"Inventory is missing expected videos: {missing}")

    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    manifest_rows = [build_one(row) for row in rows if row["video_id"] in expected]
    manifest_path = OUTPUT_ROOT / "judge_input_manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    summary = {
        "judge_input_root": str(OUTPUT_ROOT),
        "inventory": str(INVENTORY),
        "total_videos": len(manifest_rows),
        "total_lessons": len({r["lesson_id"] for r in manifest_rows}),
        "systems": sorted({r["system"] for r in manifest_rows}),
        "missing_video_files": [r["video_id"] for r in manifest_rows if r["video_exists"] != "True"],
        "manifest": str(manifest_path),
    }
    (OUTPUT_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
