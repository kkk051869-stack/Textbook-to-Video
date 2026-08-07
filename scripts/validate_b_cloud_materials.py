from __future__ import annotations

import csv
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


def count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def main() -> None:
    issues: list[str] = []
    for lesson in LESSONS:
        source = EXP / "sources/frozen" / lesson / "source.pdf"
        annotation = EXP / "private_annotations/B" / lesson / "annotation.json"
        run_dir = EXP / "runs/presentagent" / lesson
        link = run_dir / "input.pdf"
        for path in [source, annotation, run_dir / "run_config.json", run_dir / "run_status.json"]:
            if not path.exists():
                issues.append(f"missing {path}")
        if not link.is_symlink():
            issues.append(f"input.pdf is not a symlink: {link}")
        elif link.resolve() != source.resolve():
            issues.append(f"bad symlink: {link} -> {link.resolve()}")

    leaks = list((EXP / "sources/frozen").rglob("annotation.json"))
    leaks += list((EXP / "sources/frozen").rglob("questions.json"))
    for leak in leaks:
        issues.append(f"private file leaked into generation input: {leak}")

    expected_counts = {
        "ratings/B/core_concept_scores.csv": 54,
        "ratings/B/heldout_question_scores.csv": 48,
        "ratings/B/image_scores.csv": 11,
        "ratings/B/misconception_checks.csv": 33,
        "ratings/B/video_quality_scores.csv": 8,
        "logs/presentagent/input_manifest.csv": 8,
        "logs/presentagent/run_manifest.csv": 8,
    }
    for rel_path, expected in expected_counts.items():
        actual = count_csv_rows(EXP / rel_path)
        if actual != expected:
            issues.append(f"row count mismatch {rel_path}: {actual} != {expected}")

    for rel_path in [
        "logs/presentagent/environment_check.md",
        "handoff/B_to_A/B_READY_STATUS.md",
        "reports/daily/2026-08-03-B-start.md",
    ]:
        if not (EXP / rel_path).exists():
            issues.append(f"missing {rel_path}")

    print(f"issues {len(issues)}")
    for issue in issues:
        print(issue)


if __name__ == "__main__":
    main()
