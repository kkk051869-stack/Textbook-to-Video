"""Small fail-closed validators for TextbookEval's required manifest fields.

The JSON Schema files in ``contracts/`` remain the public contract.  These
validators deliberately use only the standard library so loading a frozen case
does not depend on an optional schema package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SchemaValidationError(ValueError):
    """Raised when a manifest cannot satisfy the minimum runtime contract."""


def load_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(f"cannot read JSON object {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise SchemaValidationError(f"expected JSON object: {source}")
    return value


def require_fields(value: dict[str, Any], fields: tuple[str, ...], *, where: str) -> None:
    missing = [name for name in fields if name not in value]
    if missing:
        raise SchemaValidationError(f"{where} missing required fields: {', '.join(missing)}")


def validate_file_asset(value: object, *, where: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{where} must be an object")
    require_fields(value, ("role", "path", "sha256"), where=where)
    if not str(value["role"]).strip() or not str(value["path"]).strip():
        raise SchemaValidationError(f"{where} role and path must be non-empty")
    if not SHA256_RE.fullmatch(str(value["sha256"])):
        raise SchemaValidationError(f"{where}.sha256 must contain 64 hexadecimal characters")
    if "required" in value and not isinstance(value["required"], bool):
        raise SchemaValidationError(f"{where}.required must be boolean")


def validate_case_manifest(value: dict[str, Any]) -> None:
    require_fields(
        value,
        ("schema_version", "case_id", "lesson_id", "status", "dataset_version", "source"),
        where="case manifest",
    )
    if value["schema_version"] != "textbookeval-case-v0.1":
        raise SchemaValidationError("unsupported case manifest schema_version")
    if value["status"] not in {"candidate", "frozen", "retired"}:
        raise SchemaValidationError("case manifest status must be candidate, frozen, or retired")
    for name in ("case_id", "lesson_id", "dataset_version"):
        if not isinstance(value[name], str) or not value[name].strip():
            raise SchemaValidationError(f"case manifest {name} must be a non-empty string")
    source = value["source"]
    if not isinstance(source, dict) or not isinstance(source.get("files"), list):
        raise SchemaValidationError("case manifest source.files must be an array")
    for index, asset in enumerate(source["files"]):
        validate_file_asset(asset, where=f"source.files[{index}]")
    for name in ("annotation", "heldout_questions"):
        if name in value:
            validate_file_asset(value[name], where=name)
    if "review" in value and not isinstance(value["review"], dict):
        raise SchemaValidationError("case manifest review must be an object")


def validate_run_manifest(value: dict[str, Any]) -> None:
    require_fields(
        value,
        (
            "schema_version",
            "run_id",
            "dataset_version",
            "case_ids",
            "git_commit",
            "command",
            "environment",
            "artifacts_root",
            "started_at",
        ),
        where="run manifest",
    )
    if value["schema_version"] != "textbookeval-run-v0.1":
        raise SchemaValidationError("unsupported run manifest schema_version")
    if not isinstance(value["case_ids"], list) or not value["case_ids"]:
        raise SchemaValidationError("run manifest case_ids must be a non-empty array")
    if not isinstance(value["command"], list):
        raise SchemaValidationError("run manifest command must be an array")


def validate_with_contract(
    value: dict[str, Any], schema_name: str, *, contracts_dir: str | Path
) -> None:
    directory = Path(contracts_dir).resolve()
    schema = load_json_object(directory / schema_name)
    registry = Registry()
    for schema_path in directory.glob("*.schema.json"):
        document = load_json_object(schema_path)
        resource = Resource.from_contents(document)
        schema_id = document.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    try:
        Draft202012Validator(schema, registry=registry).validate(value)
    except Exception as exc:  # jsonschema exposes several validation subclasses
        raise SchemaValidationError(f"{schema_name} validation failed: {exc}") from exc
