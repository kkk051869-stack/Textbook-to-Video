"""Load and verify versioned TextbookEval case manifests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .schemas import (
    SchemaValidationError,
    load_json_object,
    validate_case_manifest,
    validate_with_contract,
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FileAsset:
    role: str
    path: str
    sha256: str
    required: bool = True
    review_status: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FileAsset":
        return cls(
            role=str(value["role"]),
            path=str(value["path"]),
            sha256=str(value["sha256"]).lower(),
            required=bool(value.get("required", True)),
            review_status=value.get("review_status"),
        )


@dataclass(frozen=True)
class CaseManifest:
    manifest_path: Path
    raw: dict[str, Any]

    @property
    def root(self) -> Path:
        return self.manifest_path.parent

    @property
    def case_id(self) -> str:
        return str(self.raw["case_id"])

    @property
    def lesson_id(self) -> str:
        return str(self.raw["lesson_id"])

    @property
    def dataset_version(self) -> str:
        return str(self.raw["dataset_version"])

    @property
    def status(self) -> str:
        return str(self.raw["status"])

    def assets(self) -> Iterable[FileAsset]:
        for item in self.raw["source"]["files"]:
            yield FileAsset.from_dict(item)
        for key in ("annotation", "heldout_questions"):
            if key in self.raw:
                yield FileAsset.from_dict(self.raw[key])

    def resolve_asset(self, asset: FileAsset) -> Path:
        relative = Path(asset.path)
        if relative.is_absolute():
            raise SchemaValidationError(
                f"case {self.case_id} asset {asset.role} must use a relative path: {asset.path}"
            )
        resolved = (self.root / relative).resolve()
        root = self.root.resolve()
        if resolved != root and root not in resolved.parents:
            raise SchemaValidationError(
                f"case {self.case_id} asset {asset.role} escapes the case directory: {asset.path}"
            )
        return resolved

    def verify_assets(self) -> None:
        for asset in self.assets():
            path = self.resolve_asset(asset)
            if not path.is_file():
                if asset.required:
                    raise FileNotFoundError(
                        f"case {self.case_id} required asset missing: {asset.role} -> {path}"
                    )
                continue
            actual = sha256_file(path)
            if actual != asset.sha256:
                raise SchemaValidationError(
                    f"case {self.case_id} hash mismatch for {asset.role}: "
                    f"expected {asset.sha256}, got {actual}, path={path}"
                )

    def verify_frozen_contract(self) -> None:
        roles = {asset.role for asset in self.assets()}
        required_source_roles = {"source_json", "source_pdf", "source_manifest"}
        missing = sorted(required_source_roles - roles)
        if missing:
            raise SchemaValidationError(
                f"case {self.case_id} frozen source roles missing: {', '.join(missing)}"
            )
        for key in ("annotation", "heldout_questions"):
            value = self.raw.get(key)
            if not isinstance(value, dict):
                raise SchemaValidationError(f"case {self.case_id} frozen case requires {key}")
            if value.get("review_status") != "frozen":
                raise SchemaValidationError(
                    f"case {self.case_id} {key}.review_status must be 'frozen'"
                )
        review = self.raw.get("review")
        if not isinstance(review, dict):
            raise SchemaValidationError(f"case {self.case_id} frozen case requires review")
        for field in ("reviewer", "reviewed_at"):
            if not isinstance(review.get(field), str) or not review[field].strip():
                raise SchemaValidationError(
                    f"case {self.case_id} review.{field} must be a non-empty string"
                )
        if review.get("annotation_status") != "frozen":
            raise SchemaValidationError(
                f"case {self.case_id} review.annotation_status must be 'frozen'"
            )


def load_case(
    manifest_path: str | Path,
    *,
    verify_files: bool = True,
    require_frozen: bool = False,
) -> CaseManifest:
    path = Path(manifest_path).resolve()
    raw = load_json_object(path)
    validate_case_manifest(raw)
    validate_with_contract(
        raw,
        "case_manifest.schema.json",
        contracts_dir=Path(__file__).resolve().parents[3] / "contracts",
    )
    case = CaseManifest(manifest_path=path, raw=raw)
    if require_frozen and case.status != "frozen":
        raise SchemaValidationError(
            f"case {case.case_id} is {case.status!r}; a formal run requires status='frozen'"
        )
    if require_frozen:
        case.verify_frozen_contract()
    if verify_files:
        case.verify_assets()
    return case


def discover_case_manifests(dataset_dir: str | Path) -> list[Path]:
    root = Path(dataset_dir).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"dataset directory does not exist: {root}")
    manifests = sorted(root.rglob("case_manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"no case_manifest.json files found under {root}")
    return manifests
