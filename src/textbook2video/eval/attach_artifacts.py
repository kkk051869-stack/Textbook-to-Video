"""Attach a role-to-path artifact set and hashes to a prepared Case manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .dataset import load_case, sha256_file
from .report import write_json
from .schemas import validate_with_contract


def attach_artifacts(
    manifest_path: str | Path,
    artifacts_root: str | Path,
    declarations: Sequence[str],
    *,
    system_id: str,
    provenance: str | None = None,
) -> Path:
    case = load_case(manifest_path)
    root = Path(artifacts_root).resolve()
    existing = case.raw.get("baseline_artifacts", {})
    artifacts = dict(existing) if isinstance(existing, dict) else {}
    for declaration in declarations:
        if "=" not in declaration:
            raise ValueError(f"artifact declaration must be ROLE=PATH: {declaration}")
        role, raw_path = declaration.split("=", 1)
        relative = Path(raw_path)
        if not role or relative.is_absolute():
            raise ValueError(
                f"artifact declaration must use a role and relative path: {declaration}"
            )
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError(f"artifact escapes artifacts root: {declaration}")
        if not path.is_file():
            raise FileNotFoundError(f"artifact does not exist: {path}")
        artifacts[role] = {
            "path": relative.as_posix(),
            "sha256": sha256_file(path),
        }
    case.raw["baseline_artifacts"] = artifacts
    case.raw["systems"] = {
        "baseline": {
            "system_id": system_id,
            "run_config": artifacts.get("run_config"),
        }
    }
    metadata = case.raw.setdefault("metadata", {})
    metadata["baseline_attached"] = True
    if provenance:
        metadata["baseline_provenance"] = provenance
    validate_with_contract(
        case.raw,
        "case_manifest.schema.json",
        contracts_dir=Path(__file__).resolve().parents[3] / "contracts",
    )
    return write_json(case.manifest_path, case.raw)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach hashed artifacts to a candidate Case")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--artifacts-root", required=True, type=Path)
    parser.add_argument("--artifact", action="append", required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--provenance")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    path = attach_artifacts(
        args.manifest,
        args.artifacts_root,
        args.artifact,
        system_id=args.system_id,
        provenance=args.provenance,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
