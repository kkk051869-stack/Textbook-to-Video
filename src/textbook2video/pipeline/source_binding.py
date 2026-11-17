"""Attach textbook text to an existing storyboard through its same-case manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from textbook2video.research.experiment_config import _verify_file_reference


def bind_storyboard_source(storyboard: Path, *, repo_root: Path | None = None) -> dict | None:
    """Do not infer source.md from filenames or fall back to generated narration.

    Only ancestor dataset manifests inside this repository are eligible. External
    ordinary storyboards retain their existing raw.txt discovery behavior.
    """
    root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
    board = storyboard.resolve()
    if not board.is_relative_to(root):
        return None
    for parent in board.parents:
        if not parent.is_relative_to(root):
            break
        manifest_path = parent / "dataset_manifest.json"
        if not manifest_path.exists():
            continue
        if not manifest_path.resolve().is_relative_to(root):
            raise ValueError("source binding manifest escapes repository")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema = json.loads(
            (root / "contracts/ab_dataset_manifest_v1.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(manifest)
        if manifest["split"] != "dev":
            raise ValueError("automatic storyboard source binding is limited to development inputs")
        matches = [
            entry
            for entry in manifest["files"]
            if entry["role"] == "storyboard" and (root / entry["path"]).resolve() == board
        ]
        if len(matches) != 1:
            raise ValueError("manifest must identify the storyboard exactly once")
        board_entry = matches[0]
        case_id = board_entry["case_id"]
        if case_id not in manifest["case_ids"]:
            raise ValueError("storyboard case is not declared by manifest")
        if Path(case_id).name != case_id or case_id in {".", ".."}:
            raise ValueError("unsafe source binding case ID")
        case_root = (parent / "cases" / case_id).resolve()
        if not case_root.is_relative_to(parent.resolve()) or not board.is_relative_to(case_root):
            raise ValueError("storyboard must remain inside its declared case")
        sources = [
            entry
            for entry in manifest["files"]
            if entry["case_id"] == case_id
            and entry["role"] == "source"
            and Path(entry["path"]).suffix.lower() in {".md", ".txt"}
        ]
        if len(sources) != 1:
            raise ValueError("manifest needs exactly one same-case textbook text source")
        verified_board, _ = _verify_file_reference(root, board_entry, label="storyboard")
        source, _ = _verify_file_reference(root, sources[0], label="textbook source")
        if not source.is_relative_to(case_root):
            raise ValueError("textbook source must remain inside the storyboard case")
        if not source.read_text(encoding="utf-8").strip():
            raise ValueError("textbook source is empty")
        return {
            "producer": "same-case-dataset-manifest",
            "dataset_id": manifest["dataset_id"],
            "case_id": case_id,
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "storyboard_path": str(verified_board),
            "storyboard_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
            "source_path": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "declared_source_sha256": sources[0]["sha256"],
        }
    return None
