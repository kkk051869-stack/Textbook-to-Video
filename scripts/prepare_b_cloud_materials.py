from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


EXP = Path("/ai/data/textbook-to-video/experiments/presentagent-comparison-v1")
LESSONS = [
    "lesson_001",
    "lesson_002",
    "lesson_004",
    "lesson_005",
    "lesson_007",
    "lesson_008",
    "lesson_011",
    "lesson_012",
]
PRESENTAGENT_COMMIT = "b9990e990c86c3709e18e9979bc36ac959d3b4d4"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_start_docs() -> None:
    (EXP / "handoff").mkdir(parents=True, exist_ok=True)
    (EXP / "handoff/B_START_HERE.md").write_text(
        f"""# B Start Here

B focuses on PresentAgent and evaluation.

## Code

```text
/ai/data/repos/PresentAgent
```

Textbook-to-Video docs and helper scripts:

```text
/ai/data/repos/Textbook-to-Video
```

## Input

PresentAgent input lessons:

```text
{EXP}/sources/frozen/{{lesson_id}}/source.pdf
```

Private annotations for evaluation:

```text
{EXP}/private_annotations
```

## Output

Write outputs to:

```text
{EXP}/runs/presentagent
{EXP}/logs/presentagent/run_manifest.csv
{EXP}/ratings/B
{EXP}/handoff/B_to_A
```

Important: do not pass `private_annotations/` to any generation system.
""",
        encoding="utf-8",
    )

    (EXP / "EXPERIMENT_PATHS.md").write_text(
        f"""# PresentAgent Comparison v1 Cloud Paths

Experiment root:

```text
{EXP}
```

Shared frozen generation input:

```text
{EXP}/sources/frozen
```

Private evaluation annotations:

```text
{EXP}/private_annotations
```

A workspace:

```text
Code: /ai/data/repos/Textbook-to-Video
Internal runs: {EXP}/runs/internal
Internal logs: {EXP}/logs/internal
Automatic metrics: {EXP}/metrics/automatic
Handoff to B: {EXP}/handoff/A_to_B
```

B workspace:

```text
Code: /ai/data/repos/PresentAgent
PresentAgent runs: {EXP}/runs/presentagent
PresentAgent logs: {EXP}/logs/presentagent
Ratings: {EXP}/ratings/B
Handoff to A: {EXP}/handoff/B_to_A
```

Shared outputs:

```text
Resolved ratings: {EXP}/ratings/resolved
Statistics: {EXP}/metrics/statistics
Daily reports: {EXP}/reports/daily
Paper tables: {EXP}/reports/tables
Paper figures: {EXP}/reports/figures
```

Important rule: generation systems may read only `sources/frozen/{{lesson_id}}`.
Do not pass `private_annotations` to Textbook-to-Video, PresentAgent, or any generation prompt.
""",
        encoding="utf-8",
    )


def prepare_presentagent_inputs() -> None:
    run_manifest_rows = []
    input_rows = []
    for lesson in LESSONS:
        source_dir = EXP / "sources/frozen" / lesson
        ann_path = EXP / "private_annotations/B" / lesson / "annotation.json"
        pdf_path = source_dir / "source.pdf"
        source_json = source_dir / "source.json"
        pdf_sha = sha256(pdf_path)
        src = json.loads(source_json.read_text(encoding="utf-8"))

        out_dir = EXP / "runs/presentagent" / lesson
        out_dir.mkdir(parents=True, exist_ok=True)
        link = out_dir / "input.pdf"
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(pdf_path, link)

        config = {
            "lesson_id": lesson,
            "source_pdf": str(pdf_path),
            "source_pdf_sha256": pdf_sha,
            "private_annotation": str(ann_path),
            "output_dir": str(out_dir),
            "presentagent_repo": "/ai/data/repos/PresentAgent",
            "presentagent_commit": PRESENTAGENT_COMMIT,
            "status": "pending_environment",
            "generation_visibility_rule": (
                "Only source.pdf may be passed to PresentAgent; annotation is evaluation-only."
            ),
        }
        (out_dir / "run_config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "run_status.json").write_text(
            json.dumps(
                {
                    "status": "pending_environment",
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        input_rows.append(
            {
                "lesson_id": lesson,
                "title": src.get("title", ""),
                "source_pdf": str(pdf_path),
                "source_pdf_sha256": pdf_sha,
                "presentagent_output_dir": str(out_dir),
                "annotation_path": str(ann_path),
            }
        )
        run_manifest_rows.append(
            {
                "lesson_id": lesson,
                "presentagent_commit": PRESENTAGENT_COMMIT,
                "model": "TBD",
                "input_pdf_sha256": pdf_sha,
                "start_time": "",
                "end_time": "",
                "duration_sec": "",
                "status": "pending_environment",
                "failure_reason": (
                    "PresentAgent Python 3.11 environment not installed yet; "
                    "conda repo access timed out."
                ),
                "output_path": str(out_dir),
            }
        )

    write_csv(EXP / "logs/presentagent/input_manifest.csv", input_rows)
    write_csv(EXP / "logs/presentagent/run_manifest.csv", run_manifest_rows)


def expand_rating_templates() -> dict[str, int]:
    core_rows = []
    question_rows = []
    image_rows = []
    misconception_rows = []
    video_rows = []

    for lesson in LESSONS:
        ann = json.loads(
            (EXP / "private_annotations/B" / lesson / "annotation.json").read_text(
                encoding="utf-8"
            )
        )
        for cc in ann.get("core_concepts", []):
            core_rows.append(
                {
                    "lesson_id": lesson,
                    "concept_id": cc.get("id", ""),
                    "importance": cc.get("importance", ""),
                    "statement": cc.get("statement", ""),
                    "evidence_paragraphs": "|".join(cc.get("evidence_paragraphs", [])),
                    "must_mention_terms": "|".join(cc.get("must_mention_terms", [])),
                    "video_id": "",
                    "system": "",
                    "condition": "",
                    "repeat": "",
                    "rater": "B",
                    "score_0_2": "",
                    "evidence_in_video": "",
                    "notes": "",
                }
            )
        for q in ann.get("heldout_questions", []):
            answer = q.get("answer", "")
            if isinstance(answer, list):
                answer = "|".join(answer)
            question_rows.append(
                {
                    "lesson_id": lesson,
                    "question_id": q.get("id", ""),
                    "type": q.get("type", ""),
                    "question": q.get("question", ""),
                    "expected_answer": answer,
                    "targets": "|".join(q.get("targets", [])),
                    "evidence_paragraphs": "|".join(q.get("evidence_paragraphs", [])),
                    "scoring_rule": q.get("scoring", ""),
                    "video_id": "",
                    "system": "",
                    "condition": "",
                    "repeat": "",
                    "rater": "B",
                    "score_0_2": "",
                    "answer_supported_by_video": "",
                    "notes": "",
                }
            )
        for img in ann.get("required_images", []):
            image_rows.append(
                {
                    "lesson_id": lesson,
                    "image_id": img.get("image_id", ""),
                    "filename": img.get("filename", ""),
                    "necessity": img.get("necessity", ""),
                    "caption": img.get("caption", ""),
                    "evidence_paragraphs": "|".join(img.get("evidence_paragraphs", [])),
                    "expected_use": img.get("expected_use", ""),
                    "video_id": "",
                    "system": "",
                    "condition": "",
                    "repeat": "",
                    "rater": "B",
                    "score_0_2": "",
                    "appears": "",
                    "used_correctly": "",
                    "notes": "",
                }
            )
        for mis in ann.get("misconceptions", []):
            misconception_rows.append(
                {
                    "lesson_id": lesson,
                    "misconception_id": mis.get("id", ""),
                    "wrong_claim": mis.get("wrong_claim", ""),
                    "why_wrong": mis.get("why_wrong", ""),
                    "evidence_paragraphs": "|".join(mis.get("evidence_paragraphs", [])),
                    "video_id": "",
                    "system": "",
                    "condition": "",
                    "repeat": "",
                    "rater": "B",
                    "appears_in_video": "",
                    "severity_if_appears": "",
                    "notes": "",
                }
            )
        video_rows.append(
            {
                "lesson_id": lesson,
                "video_id": "",
                "system": "",
                "condition": "",
                "repeat": "",
                "rater": "B",
                "content_coverage_0_2": "",
                "faithfulness_0_2": "",
                "image_use_0_2": "",
                "teaching_structure_0_2": "",
                "visual_quality_0_2": "",
                "sync_quality_0_2": "",
                "completeness_0_2": "",
                "major_errors_count": "",
                "moderate_errors_count": "",
                "minor_errors_count": "",
                "notes": "",
            }
        )

    write_csv(EXP / "ratings/B/core_concept_scores.csv", core_rows)
    write_csv(EXP / "ratings/B/heldout_question_scores.csv", question_rows)
    write_csv(EXP / "ratings/B/image_scores.csv", image_rows)
    write_csv(EXP / "ratings/B/misconception_checks.csv", misconception_rows)
    write_csv(EXP / "ratings/B/video_quality_scores.csv", video_rows)
    write_csv(
        EXP / "ratings/B/error_log.csv",
        [
            {
                "error_id": "",
                "lesson_id": "",
                "video_id": "",
                "system": "",
                "condition": "",
                "repeat": "",
                "rater": "B",
                "severity": "",
                "category": "",
                "description": "",
                "source_evidence": "",
                "video_time": "",
                "resolution": "",
            }
        ],
    )
    return {
        "core_rows": len(core_rows),
        "question_rows": len(question_rows),
        "image_rows": len(image_rows),
        "misconception_rows": len(misconception_rows),
        "video_rows": len(video_rows),
    }


def write_status_docs(counts: dict[str, int]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    (EXP / "logs/presentagent/environment_check.md").write_text(
        f"""# PresentAgent Environment Check

Date: {now}

## Repository

```text
/ai/data/repos/PresentAgent
commit: {PRESENTAGENT_COMMIT}
```

## Current Status

Status: `blocked_environment_install`

Conda environment creation attempted:

```text
conda create -p /ai/data/tools/envs/presentagent python=3.11 -y
```

Result: failed because cloud access to `repo.anaconda.com` timed out while fetching package metadata.

A provisional Python 3.10 smoke-test venv was created at:

```text
/ai/data/tools/envs/presentagent-py310-smoke
```

Minimal pip dependency installation was attempted with the Tsinghua PyPI mirror and also failed because the cloud connection timed out.

## Available Runtime

```text
system python: /usr/bin/python3, Python 3.8.10
AI env base python: /ai/data/tools/anaconda3/bin/python, Python 3.13.9
existing langgraph env: /ai/data/tools/envs/langgraph-env/bin/python, Python 3.10.16
smoke-test env: /ai/data/tools/envs/presentagent-py310-smoke/bin/python, Python 3.10.16
```

PresentAgent README requests Python 3.11, so the above runtimes are not treated as the formal baseline environment.

## Additional Missing Runtime Assets

- No cached Python 3.11 conda package was found under the checked conda package caches.
- No MegaTTS3 checkpoint directory was found under `/ai/data/repos/PresentAgent/presentagent/MegaTTS3`, `/ai/data/models`, or `/ai/data/model-cache`.
- PresentAgent templates are present under `/ai/data/repos/PresentAgent/resource/templates`.

## Next Options

1. Configure conda/pip mirror on cloud and retry environment creation.
2. Build a Python 3.11 environment locally or elsewhere, package it, and upload to `/ai/data/tools/envs/presentagent`.
3. If A/B agree, test with Python 3.10 as a provisional smoke test, but do not use it as the frozen formal baseline without recording the deviation.
""",
        encoding="utf-8",
    )

    (EXP / "handoff/B_to_A/B_READY_STATUS.md").write_text(
        f"""# B-Line Status

Date: {now}

## Completed

- Verified 8 formal lesson inputs under `sources/frozen`.
- Verified private annotations are separated from generation input.
- Created PresentAgent per-lesson run directories under `runs/presentagent`.
- Created symlinked `input.pdf` for each PresentAgent run directory.
- Created `logs/presentagent/input_manifest.csv`.
- Created `logs/presentagent/run_manifest.csv` with all 8 lessons marked `pending_environment`.
- Expanded private annotation into B rating CSV templates:
  - `ratings/B/core_concept_scores.csv` ({counts["core_rows"]} rows)
  - `ratings/B/heldout_question_scores.csv` ({counts["question_rows"]} rows)
  - `ratings/B/image_scores.csv` ({counts["image_rows"]} rows)
  - `ratings/B/misconception_checks.csv` ({counts["misconception_rows"]} rows)
  - `ratings/B/video_quality_scores.csv` ({counts["video_rows"]} rows)
  - `ratings/B/error_log.csv`

## Blocked

PresentAgent execution is blocked by Python 3.11 environment setup. Cloud conda could not reach `repo.anaconda.com`.

## Ready For

- A can continue internal generation using `sources/frozen`.
- B can start manual/VLM scoring template review now.
- PresentAgent formal runs should wait until the environment is resolved.
""",
        encoding="utf-8",
    )

    (EXP / "reports/daily/2026-08-03-B-start.md").write_text(
        f"""# 2026-08-03 B Start

## Done

- Checked dataset separation.
- Prepared PresentAgent input manifest and run directories.
- Generated B rating templates from annotation.
- Attempted PresentAgent Python 3.11 environment creation.

## Rating Template Counts

- Core concept rows: {counts["core_rows"]}
- Heldout question rows: {counts["question_rows"]}
- Image rows: {counts["image_rows"]}
- Misconception rows: {counts["misconception_rows"]}
- Video summary rows: {counts["video_rows"]}

## Blocker

Conda environment creation failed due cloud network timeout to `repo.anaconda.com`.

## Next

Set conda/pip mirror or upload a prebuilt Python 3.11 environment, then run `lesson_001` PresentAgent smoke test.
""",
        encoding="utf-8",
    )


def main() -> None:
    write_start_docs()
    prepare_presentagent_inputs()
    counts = expand_rating_templates()
    write_status_docs(counts)
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
