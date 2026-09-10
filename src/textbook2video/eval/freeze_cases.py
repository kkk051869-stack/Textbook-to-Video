"""Apply explicit human approval to candidate Case manifests."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .case_audit import audit_case
from .dataset import discover_case_manifests, load_case, sha256_file
from .report import write_json


def _asset_entry(manifest: dict[str, Any], role: str) -> dict[str, Any]:
    values = list(manifest["source"]["files"])
    values.extend(manifest[key] for key in ("annotation", "heldout_questions") if key in manifest)
    for value in values:
        if value.get("role") == role:
            return value
    raise ValueError(f"case manifest does not declare asset role {role!r}")


def freeze_case(
    manifest_path: str | Path,
    artifacts_root: str | Path,
    *,
    reviewer: str,
    approval_note: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    if not reviewer.strip() or not approval_note.strip():
        raise ValueError("reviewer and approval_note must be non-empty")
    case = load_case(manifest_path)
    manifest = case.raw
    timestamp = reviewed_at or datetime.now(timezone.utc).isoformat()

    source_asset = _asset_entry(manifest, "source_manifest")
    source_path = case.root / source_asset["path"]
    source_manifest = json.loads(source_path.read_text(encoding="utf-8"))
    source_manifest["review_status"] = "frozen"
    source_manifest["review"] = {
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "approval_note": approval_note,
    }
    write_json(source_path, source_manifest)
    source_asset["sha256"] = sha256_file(source_path)

    annotation_asset = _asset_entry(manifest, "annotation")
    annotation_path = case.root / annotation_asset["path"]
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    annotation["annotation_status"] = "frozen"
    notes = list(annotation.get("review_notes", []))
    notes.append(f"Frozen by {reviewer} at {timestamp}: {approval_note}")
    annotation["review_notes"] = notes
    write_json(annotation_path, annotation)
    annotation_asset["sha256"] = sha256_file(annotation_path)
    annotation_asset["review_status"] = "frozen"
    _asset_entry(manifest, "heldout_questions")["review_status"] = "frozen"

    manifest["status"] = "frozen"
    manifest["review"] = {
        "annotation_status": "frozen",
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "notes": approval_note,
    }
    metadata = dict(manifest.get("metadata", {}))
    metadata["source_review_status"] = "frozen"
    metadata["freeze_blocked"] = False
    metadata["freeze_approval"] = {
        "reviewer": reviewer,
        "reviewed_at": timestamp,
        "basis": approval_note,
    }
    manifest["metadata"] = metadata
    write_json(case.manifest_path, manifest)

    frozen = load_case(case.manifest_path, require_frozen=True)
    audit = audit_case(frozen, artifacts_root)
    if not audit["ready_to_freeze"]:
        blockers = ", ".join(item["name"] for item in audit["blockers"])
        raise RuntimeError(f"case freeze verification failed: {blockers}")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze approved TextbookEval cases")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approval-note", required=True)
    parser.add_argument("--reviewed-at", default=None)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    reports = []
    for manifest_path in discover_case_manifests(args.dataset):
        case = load_case(manifest_path, verify_files=False)
        metadata = case.raw.get("metadata", {})
        subdir = metadata.get("artifacts_subdir") if isinstance(metadata, dict) else None
        case_artifacts = args.artifacts / str(subdir) if subdir else args.artifacts / case.lesson_id
        reports.append(
            freeze_case(
                manifest_path,
                case_artifacts,
                reviewer=args.reviewer,
                approval_note=args.approval_note,
                reviewed_at=args.reviewed_at,
            )
        )
    write_json(
        args.out,
        {
            "schema_version": "textbookeval-freeze-record-v0.1",
            "reviewer": args.reviewer,
            "approval_note": args.approval_note,
            "case_count": len(reports),
            "cases": reports,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
