"""Lineage-producing adapters around existing local Storyboard repairs."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from .lineage import RepairLineageWriter


def repair_storyboard_with_lineage(
    storyboard_path: str | Path,
    *,
    candidate_dir: str | Path,
    case_id: str,
    run_id: str,
    source_issue: dict[str, Any] | None = None,
    lesson_plan: dict[str, Any] | None = None,
    writer: RepairLineageWriter | None = None,
    repair_id: str | None = None,
    round: int = 1,
    before_eval_report: str | Path | dict[str, Any] | None = None,
    after_eval_report: str | Path | dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run the existing deterministic Storyboard enhancer in a candidate.

    The canonical storyboard is copied, never edited. The returned candidate
    and its lineage record are suitable for targeted re-evaluation by the
    Phase B orchestrator.
    """

    source = Path(storyboard_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    root = Path(candidate_dir).resolve()
    before_dir = root / "before"
    candidate_subdir = root / "candidate"
    before_dir.mkdir(parents=True, exist_ok=True)
    candidate_subdir.mkdir(parents=True, exist_ok=True)
    before = before_dir / source.name
    candidate = candidate_subdir / source.name
    shutil.copy2(source, before)
    shutil.copy2(source, candidate)

    started = time.monotonic()
    from textbook2video.pipeline.storyboard import enhance_storyboard_quality

    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("storyboard JSON must be an object")
    enhanced = enhance_storyboard_quality(data, lesson_plan)
    candidate.write_text(json.dumps(enhanced, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    changed = before.read_bytes() != candidate.read_bytes()

    lineage_path = root / "repair_lineage.json"
    lineage_writer = writer or RepairLineageWriter(lineage_path, case_id=case_id, run_id=run_id)
    issue = source_issue or {}
    issue_id = issue.get("issue_id")
    record = lineage_writer.append_record(
        repair_id=repair_id or lineage_writer.new_id("storyboard-repair"),
        case_id=case_id,
        run_id=run_id,
        source_issue_id=str(issue_id) if issue_id is not None else None,
        issue_type=str(issue.get("type") or issue.get("category") or "STORYBOARD_REPAIR"),
        stage=str(issue.get("stage") or "storyboard"),
        severity=str(issue.get("severity") or "warning"),
        repair_strategy="storyboard_repair",
        round=round,
        before_artifact=before,
        after_artifact=candidate,
        before_eval_report=before_eval_report,
        after_eval_report=after_eval_report,
        model="N/A",
        token=None,
        latency_sec=round_float(time.monotonic() - started),
        result="succeeded" if changed else "failed",
        provenance={
            "source": "textbook2video.pipeline.storyboard.enhance_storyboard_quality",
            "canonical_artifact": str(source),
        },
        candidate_dir=root,
    )
    return candidate, record


def round_float(value: float) -> float:
    return round(float(value), 6)


__all__ = ["repair_storyboard_with_lineage"]
