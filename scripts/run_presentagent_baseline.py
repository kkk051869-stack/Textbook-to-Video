from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_one(backend, lesson_id: str, args: argparse.Namespace) -> int:
    experiment = Path(args.experiment_root)
    source_pdf = experiment / "sources" / "frozen" / lesson_id / "source.pdf"
    lesson_out = experiment / "runs" / "presentagent" / lesson_id
    lesson_out.mkdir(parents=True, exist_ok=True)

    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)

    pdf_md5 = file_md5(source_pdf)
    runs_dir = Path(backend.RUNS_DIR)
    pdf_dir = runs_dir / "pdf" / pdf_md5
    pptx_dir = runs_dir / "pptx" / "default_template"
    task_id = f"textbookeval-v1/{lesson_id}"

    pdf_dir.mkdir(parents=True, exist_ok=True)
    pptx_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, pdf_dir / "source.pdf")
    shutil.copy2(Path(args.template), pptx_dir / "source.pptx")

    backend.active_connections[task_id] = None
    backend.progress_store[task_id] = {
        "numberOfPages": args.slides,
        "pptx": "default_template",
        "pdf": pdf_md5,
    }

    status = {
        "lesson_id": lesson_id,
        "status": "running",
        "source_pdf": str(source_pdf),
        "source_pdf_sha256": file_sha256(source_pdf),
        "slides": args.slides,
        "presentagent_runs_dir": str(runs_dir / task_id),
    }
    write_json(lesson_out / "run_status.json", status)

    await backend.ppt_gen(task_id)

    final_pptx = runs_dir / task_id / "final.pptx"
    if final_pptx.exists():
        shutil.copy2(final_pptx, lesson_out / "generated.pptx")
        status["status"] = "completed"
        status["generated_pptx"] = str(lesson_out / "generated.pptx")
        status["generated_pptx_sha256"] = file_sha256(lesson_out / "generated.pptx")
        write_json(lesson_out / "run_status.json", status)
        return 0

    status["status"] = "failed"
    status["error"] = "PresentAgent did not produce final.pptx"
    write_json(lesson_out / "run_status.json", status)
    return 1


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment-root",
        default="/ai/data/textbook-to-video/experiments/presentagent-comparison-v1",
    )
    parser.add_argument("--presentagent-repo", default="/ai/data/repos/PresentAgent")
    parser.add_argument(
        "--template",
        default="/ai/data/repos/PresentAgent/resource/templates/default_template.pptx",
    )
    parser.add_argument("--slides", type=int, default=7)
    parser.add_argument("--lessons", nargs="*", default=None)
    args = parser.parse_args()

    repo = Path(args.presentagent_repo)
    sys.path.insert(0, str(repo))
    os.chdir(repo)

    import presentagent.backend as backend

    if args.lessons:
        lessons = args.lessons
    else:
        source_root = Path(args.experiment_root) / "sources" / "frozen"
        lessons = sorted(p.name for p in source_root.iterdir() if (p / "source.pdf").exists())

    failures = 0
    for lesson_id in lessons:
        print(f"=== {lesson_id} ===", flush=True)
        failures += await run_one(backend, lesson_id, args)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
