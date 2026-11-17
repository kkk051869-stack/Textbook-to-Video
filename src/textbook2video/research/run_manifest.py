"""Fail-closed run-manifest preparation and input-access auditing."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .experiment_config import (
    ExperimentConfigError,
    _content_hashes,
    validate_experiment_config,
)

RUN_MANIFEST_VERSION = "t2v-ab-run-manifest-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExperimentConfigError(f"expected JSON object: {path}")
    return value


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _repo_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ExperimentConfigError(f"path escapes repository root: {path}") from exc


def _llm_preflight_failures(snapshot: dict[str, Any], config: dict[str, Any]) -> list[str]:
    """Return credential failures only when the preflight declared LLM mandatory."""
    checks = snapshot.get("checks") or {}
    if not checks.get("llm_required"):
        return []
    llm = (snapshot.get("credentials") or {}).get("llm") or {}
    if not llm.get("present"):
        return ["preflight requires LLM credentials but none are present"]
    if llm.get("selected_provider") != config["model"]["provider"]:
        return ["preflight LLM provider is mismatched"]
    return []


def prepare_run_manifest(
    config_path: str | Path,
    preflight_snapshot_path: str | Path,
    *,
    repo_root: str | Path,
) -> Path:
    """Create a new output directory only after config, Git, and preflight agree."""
    root = Path(repo_root).resolve()
    result = validate_experiment_config(config_path, repo_root=root, require_runnable=True)
    config = result["config"]
    snapshot_path = Path(preflight_snapshot_path).resolve()
    snapshot = _read_object(snapshot_path)
    current_commit = _git(root, "rev-parse", "HEAD")
    current_branch = _git(root, "branch", "--show-current")
    status = _git(root, "status", "--porcelain")
    upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    counts = _git(root, "rev-list", "--left-right", "--count", f"{upstream}...HEAD").split()
    ahead, behind = int(counts[1]), int(counts[0])
    repository = snapshot.get("repository") or {}
    snapshot_config = snapshot.get("experiment_config") or {}
    checks = snapshot.get("checks") or {}
    failures: list[str] = []
    if snapshot.get("mode") != config["mode"]:
        failures.append("snapshot mode does not match config")
    if repository.get("commit") != current_commit:
        failures.append("snapshot commit does not match HEAD")
    if repository.get("branch") != current_branch or current_branch != config["git"]["branch"]:
        failures.append("snapshot/config branch does not match current branch")
    if repository.get("dirty") or status:
        failures.append("repository is not clean")
    if repository.get("upstream") != upstream or ahead or behind:
        failures.append("HEAD is not exactly synchronized with its upstream")
    if snapshot_config.get("config_sha256") != result["config_sha256"]:
        failures.append("snapshot config hash does not match validated config")
    if checks.get("draft202012_validator") != "PASS" or checks.get(
        "research_contract_tests"
    ) != "PASS":
        failures.append("preflight checks are incomplete")
    failures.extend(_llm_preflight_failures(snapshot, config))
    for item in result["verified_files"]:
        tracked = _git(root, "ls-files", "--error-unmatch", "--", item["path"])
        if not tracked:
            failures.append(f"verified input is not tracked: {item['path']}")
    if failures:
        raise ExperimentConfigError("run manifest refused: " + "; ".join(failures))

    output = Path(result["output_path"])
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "manifest.json"
    access_path = output / "access_log.jsonl"
    access_path.touch(exist_ok=False)
    manifest = {
        "schema_version": RUN_MANIFEST_VERSION,
        "status": "PREPARED",
        "prepared_at_utc": datetime.now(UTC).isoformat(),
        "study_id": config["study_id"],
        "run_id": config["run_id"],
        "mode": config["mode"],
        "repository": {
            "branch": current_branch,
            "commit": current_commit,
            "upstream": upstream,
            "ahead": ahead,
            "behind": behind,
        },
        "config": {
            "path": _repo_relative(root, Path(result["config_path"])),
            "sha256": result["config_sha256"],
        },
        "preflight_snapshot": {
            "path": _repo_relative(root, snapshot_path),
            "sha256": _sha256(snapshot_path),
        },
        "model": config["model"],
        "execution": config["execution"],
        "credentials": {
            "llm_required": bool(checks.get("llm_required")),
            "llm_present": bool(
                ((snapshot.get("credentials") or {}).get("llm") or {}).get("present")
            ),
            "selected_provider": (
                ((snapshot.get("credentials") or {}).get("llm") or {}).get(
                    "selected_provider"
                )
            ),
        },
        "conditions": config["conditions"],
        "declared_inputs": result["verified_files"],
        "gold_access_stage": config["frozen_inputs"]["gold_access_stage"],
        "output_root": _repo_relative(root, output),
        "access_log": _repo_relative(root, access_path),
        "package_versions": snapshot.get("python", {}).get("packages", {}),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def record_input_access(
    manifest_path: str | Path,
    input_path: str | Path,
    *,
    stage: str,
    operation: str = "read",
    repo_root: str | Path,
) -> None:
    """Append one verified access; generation can never access evaluation gold."""
    root = Path(repo_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    manifest = _read_object(manifest_file)
    relative = _repo_relative(root, Path(input_path))
    declared = [
        item
        for item in manifest["declared_inputs"]
        if str(item["path"]).replace("\\", "/") == relative
    ]
    if not declared:
        raise ExperimentConfigError(f"runtime access to undeclared input refused: {relative}")
    if any(item["label"] == "frozen_inputs.gold" for item in declared) and stage != "evaluation":
        raise ExperimentConfigError("gold may be accessed only during evaluation")
    accepted, comparison_digest = _content_hashes(root / relative)
    expected = {item["sha256"] for item in declared}
    if expected.isdisjoint(accepted | {comparison_digest}):
        raise ExperimentConfigError(f"runtime input hash mismatch: {relative}")
    log_path = root / manifest["access_log"]
    event = {
        "at_utc": datetime.now(UTC).isoformat(),
        "stage": stage,
        "operation": operation,
        "path": relative,
        "sha256": comparison_digest,
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("config")
    prepare.add_argument("snapshot")
    prepare.add_argument("--repo-root", default=".")
    access = subparsers.add_parser("record-access")
    access.add_argument("manifest")
    access.add_argument("input")
    access.add_argument("--stage", required=True)
    access.add_argument("--operation", default="read")
    access.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare_run_manifest(args.config, args.snapshot, repo_root=args.repo_root))
    else:
        record_input_access(
            args.manifest,
            args.input,
            stage=args.stage,
            operation=args.operation,
            repo_root=args.repo_root,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["RUN_MANIFEST_VERSION", "prepare_run_manifest", "record_input_access"]
