"""Fail-closed validation for versioned A/B research run configurations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_RELATIVE_PATH = Path("contracts/ab_experiment_config_v1.schema.json")
DATASET_MANIFEST_SCHEMA_PATH = Path("contracts/ab_dataset_manifest_v1.schema.json")
FROZEN_FILE_MANIFEST_SCHEMA_PATH = Path("contracts/ab_frozen_file_manifest_v1.schema.json")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_RE = re.compile(
    r"(?:replace|placeholder|change[_-]?me|fill[_-]?me(?:[_-]?in)?|set[_-]?me|todo|tbd|fixme|xxx)",
    re.IGNORECASE,
)
_MAX_JOINABLE_STRINGS_PER_OBJECT = 64
_MAX_JOINED_PATH_CANDIDATES_PER_FILE = 10_000


class ExperimentConfigError(ValueError):
    """Raised when a run configuration is unsafe or not reproducible."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentConfigError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExperimentConfigError(f"JSON root must be an object: {path}")
    return value


def _load_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentConfigError(f"cannot read JSON {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hashes(path: Path) -> tuple[set[str], str]:
    """Return accepted byte hashes plus a cross-platform comparison hash.

    Historical frozen manifests were produced from a mix of fresh LF files and
    Windows ``core.autocrlf`` checkouts.  Their declared SHA-256 therefore may
    describe LF or CRLF bytes even when the textual content is identical.  For
    UTF-8 text, accept only those two line-ending representations and compare
    generation/evaluation content using canonical LF bytes.  Binary files keep
    strict byte-for-byte hashing.
    """
    raw = path.read_bytes()
    raw_digest = hashlib.sha256(raw).hexdigest()
    if b"\x00" in raw:
        return {raw_digest}, raw_digest
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {raw_digest}, raw_digest
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lf_bytes = normalized.encode("utf-8")
    crlf_bytes = normalized.replace("\n", "\r\n").encode("utf-8")
    lf_digest = hashlib.sha256(lf_bytes).hexdigest()
    return {
        raw_digest,
        lf_digest,
        hashlib.sha256(crlf_bytes).hexdigest(),
    }, lf_digest


def _walk_strings(value: Any, location: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{location}[{index}]")


def _resolve_repo_file(repo_root: Path, raw_path: str, *, label: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ExperimentConfigError(f"{label} must be repository-relative, got {raw_path!r}")
    resolved = (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ExperimentConfigError(f"{label} escapes repository root: {raw_path!r}") from exc
    if not resolved.is_file():
        raise ExperimentConfigError(f"{label} does not exist as a file: {raw_path!r}")
    return resolved


def _verify_file_reference(
    repo_root: Path,
    reference: dict[str, Any],
    *,
    label: str,
) -> tuple[Path, str]:
    expected = str(reference.get("sha256") or "").lower()
    if not _SHA256_RE.fullmatch(expected):
        raise ExperimentConfigError(f"{label}.sha256 must be a lowercase 64-character SHA-256")
    resolved = _resolve_repo_file(repo_root, str(reference.get("path") or ""), label=label)
    accepted, comparison_digest = _content_hashes(resolved)
    if expected not in accepted:
        actual = _sha256(resolved)
        raise ExperimentConfigError(
            f"{label} SHA-256 mismatch: expected {expected}, actual {actual}"
        )
    return resolved, comparison_digest


def _file_references(config: dict[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    """Return (label, reference, role), where role is generation/evaluation/audit."""
    frozen = config["frozen_inputs"]
    references: list[tuple[str, dict[str, Any], str]] = [
        ("dataset.manifest", config["dataset"]["manifest"], "generation"),
        ("frozen_inputs.research_schema", frozen["research_schema"], "generation"),
    ]
    references.extend(
        (f"frozen_inputs.prompts[{index}]", reference, "generation")
        for index, reference in enumerate(frozen["prompts"])
    )
    for key in (
        "candidate_universe",
        "candidate_subset",
        "narration_manifest",
        "audio_manifest",
    ):
        reference = frozen[key]
        if reference is not None:
            references.append((f"frozen_inputs.{key}", reference, "generation"))
    if frozen["gold"] is not None:
        references.append(("frozen_inputs.gold", frozen["gold"], "evaluation"))
    authorization = config["locked_test_authorization"]
    if authorization is not None:
        references.append(
            ("locked_test_authorization.evidence", authorization["evidence"], "audit")
        )
    return references


def _validate_document(document: Any, schema: dict[str, Any], *, label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ExperimentConfigError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def _path_like_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _path_like_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _path_like_strings(item)


def _joined_string_candidates(
    value: Any, *, _budget: list[int] | None = None
) -> Iterator[str]:
    """Yield same-object string pairs that could form a local file path."""
    if _budget is None:
        _budget = [0]
    if isinstance(value, dict):
        strings = [
            item.strip()
            for item in value.values()
            if isinstance(item, str) and item.strip()
        ]
        if len(strings) > _MAX_JOINABLE_STRINGS_PER_OBJECT:
            raise ExperimentConfigError(
                "generation JSON object has too many string fields for safe path analysis"
            )
        _budget[0] += len(strings) * max(0, len(strings) - 1)
        if _budget[0] > _MAX_JOINED_PATH_CANDIDATES_PER_FILE:
            raise ExperimentConfigError(
                "generation JSON exceeds the safe path-assembly candidate budget"
            )
        for left in strings:
            for right in strings:
                if left != right:
                    yield str(Path(left) / right)
        for item in value.values():
            yield from _joined_string_candidates(item, _budget=_budget)
    elif isinstance(value, list):
        for item in value:
            yield from _joined_string_candidates(item, _budget=_budget)


def _extend_path_candidates(target: set[str], values: Iterator[str]) -> None:
    for value in values:
        if value in target:
            continue
        if len(target) >= _MAX_JOINED_PATH_CANDIDATES_PER_FILE:
            raise ExperimentConfigError(
                "generation input exceeds the safe local-path candidate budget"
            )
        target.add(value)


def _validate_semantics(config: dict[str, Any]) -> None:
    placeholders = [
        location for location, value in _walk_strings(config) if _PLACEHOLDER_RE.search(value)
    ]
    if placeholders:
        raise ExperimentConfigError(f"unresolved placeholder(s): {', '.join(placeholders[:8])}")

    condition_ids = [str(item["condition_id"]) for item in config["conditions"]]
    if len(condition_ids) != len(set(condition_ids)):
        raise ExperimentConfigError("condition_id values must be unique")

    enabled_modules = {
        str(module) for condition in config["conditions"] for module in condition["enabled_modules"]
    }
    frozen = config["frozen_inputs"]
    non_baseline = any(
        str(item["treatment"]).lower() != "baseline" for item in config["conditions"]
    )
    if non_baseline and not frozen["prompts"]:
        raise ExperimentConfigError("non-baseline conditions require at least one frozen prompt")
    if "visual-decision" in enabled_modules and frozen["candidate_universe"] is None:
        raise ExperimentConfigError("visual-decision requires a frozen candidate_universe")
    if {"dynamic-alignment", "signaling"} & enabled_modules:
        for key in ("candidate_subset", "narration_manifest", "audio_manifest"):
            if frozen[key] is None:
                raise ExperimentConfigError(f"dynamic B-track conditions require {key}")
    if config["mode"] != "development" and frozen["gold"] is None:
        raise ExperimentConfigError(
            f"mode={config['mode']} requires a frozen evaluation gold reference"
        )
    authorization = config["locked_test_authorization"]
    if authorization is not None and authorization["run_id"] != config["run_id"]:
        raise ExperimentConfigError("locked-test authorization must be bound to this run_id")


def validate_experiment_config(
    config_path: str | Path,
    *,
    repo_root: str | Path,
    expected_mode: str | None = None,
    require_runnable: bool = True,
) -> dict[str, Any]:
    """Validate schema, hashes, path isolation, mode, and no-overwrite rules."""
    root = Path(repo_root).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = root / config_file
    config_file = config_file.resolve()
    try:
        config_file.relative_to(root)
    except ValueError as exc:
        raise ExperimentConfigError(
            "experiment config must be stored inside the repository"
        ) from exc
    schema = _load_json(root / SCHEMA_RELATIVE_PATH)
    Draft202012Validator.check_schema(schema)
    config = _load_json(config_file)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ExperimentConfigError(f"schema validation failed at {location}: {error.message}")
    if require_runnable and config["config_status"] != "RUNNABLE":
        raise ExperimentConfigError("formal preflight requires config_status=RUNNABLE")
    if (
        expected_mode is not None
        and config["config_status"] == "RUNNABLE"
        and config["mode"] != expected_mode
    ):
        raise ExperimentConfigError(
            f"config mode {config['mode']!r} does not match requested mode {expected_mode!r}"
        )
    if config["config_status"] == "TEMPLATE":
        return {"config": config, "config_path": str(config_file), "verified_files": []}

    _validate_semantics(config)
    if config["model"]["provider"] not in {"ecnu", "generic", "openai"}:
        raise ExperimentConfigError("model.provider must be one of: ecnu, generic, openai")
    dataset_manifest_schema = _load_json(root / DATASET_MANIFEST_SCHEMA_PATH)
    frozen_file_manifest_schema = _load_json(root / FROZEN_FILE_MANIFEST_SCHEMA_PATH)
    Draft202012Validator.check_schema(dataset_manifest_schema)
    Draft202012Validator.check_schema(frozen_file_manifest_schema)
    verified: list[dict[str, str]] = []
    role_paths: dict[str, set[Path]] = {"generation": set(), "evaluation": set(), "audit": set()}
    role_hashes: dict[str, set[str]] = {"generation": set(), "evaluation": set(), "audit": set()}
    direct_paths: dict[str, Path] = {}
    direct_digests: dict[str, str] = {}
    for label, reference, role in _file_references(config):
        resolved, digest = _verify_file_reference(root, reference, label=label)
        role_paths[role].add(resolved)
        role_hashes[role].add(digest)
        verified.append({"label": label, "path": str(resolved.relative_to(root)), "sha256": digest})
        direct_paths[label] = resolved
        direct_digests[label] = digest

    dataset_manifest = _load_json(direct_paths["dataset.manifest"])
    _validate_document(
        dataset_manifest,
        dataset_manifest_schema,
        label="dataset.manifest",
    )
    if dataset_manifest["dataset_id"] != config["dataset"]["dataset_id"]:
        raise ExperimentConfigError("dataset_id does not match the frozen dataset manifest")
    if dataset_manifest["split"] != config["dataset"]["split"]:
        raise ExperimentConfigError("dataset split does not match the frozen dataset manifest")
    manifest_cases = set(dataset_manifest["case_ids"])
    requested_cases = set(config["dataset"]["case_ids"])
    if not requested_cases <= manifest_cases:
        raise ExperimentConfigError(
            "one or more requested case_ids are absent from the dataset manifest"
        )

    strict_manifests: list[tuple[str, dict[str, Any], str]] = [
        ("dataset.manifest", dataset_manifest, "dataset")
    ]
    artifact_types = {
        "frozen_inputs.candidate_universe": "candidate-universe",
        "frozen_inputs.candidate_subset": "candidate-subset",
        "frozen_inputs.narration_manifest": "narration",
        "frozen_inputs.audio_manifest": "audio",
    }
    for label, expected_artifact_type in artifact_types.items():
        if label not in direct_paths:
            continue
        document = _load_json(direct_paths[label])
        _validate_document(document, frozen_file_manifest_schema, label=label)
        if document["artifact_type"] != expected_artifact_type:
            raise ExperimentConfigError(
                f"{label} artifact_type must be {expected_artifact_type!r}"
            )
        strict_manifests.append((label, document, "frozen"))

    for parent_label, document, manifest_kind in strict_manifests:
        for index, reference in enumerate(document["files"]):
            nested_label = f"{parent_label}.files[{index}]"
            if manifest_kind == "dataset" and reference["case_id"] not in manifest_cases:
                raise ExperimentConfigError(
                    f"{nested_label}.case_id is absent from dataset manifest case_ids"
                )
            resolved, digest = _verify_file_reference(root, reference, label=nested_label)
            role_paths["generation"].add(resolved)
            role_hashes["generation"].add(digest)
            verified.append(
                {
                    "label": nested_label,
                    "path": str(resolved.relative_to(root)),
                    "sha256": digest,
                }
            )

    if role_paths["generation"] & role_paths["evaluation"]:
        raise ExperimentConfigError("gold/evaluation path is also referenced by generation inputs")
    if role_hashes["generation"] & role_hashes["evaluation"]:
        raise ExperimentConfigError(
            "gold/evaluation content hash is also used by generation inputs"
        )
    gold_reference = config["frozen_inputs"]["gold"]
    gold_path: Path | None = None
    gold_digest: str | None = None
    gold_markers: set[str] = set()
    if gold_reference is not None:
        gold_path = next(iter(role_paths["evaluation"]))
        declared_gold_digest = str(gold_reference["sha256"]).lower()
        gold_digest = direct_digests["frozen_inputs.gold"]
        gold_markers = {
            str(gold_reference["path"]).replace("\\", "/"),
            declared_gold_digest,
            gold_digest,
        }
    declared_generation_paths = role_paths["generation"]
    for generation_path in declared_generation_paths:
        text = generation_path.read_text(encoding="utf-8", errors="ignore")
        normalized = text.replace("\\", "/").lower()
        if gold_markers and any(marker.lower() in normalized for marker in gold_markers):
            raise ExperimentConfigError(
                f"generation input {generation_path.relative_to(root)} references gold"
            )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            candidate_values: set[str] = set()
        else:
            candidate_values = set()
            _extend_path_candidates(candidate_values, _path_like_strings(parsed))
            _extend_path_candidates(candidate_values, _joined_string_candidates(parsed))
        _extend_path_candidates(
            candidate_values,
            (
                match.group(0)
                for match in re.finditer(
                    r"(?:(?:\.\.?[\\/])|(?:[A-Za-z0-9_.-]+[\\/]))"
                    r"[A-Za-z0-9_./\\-]+",
                    text,
                )
            ),
        )
        _extend_path_candidates(
            candidate_values,
            (
                match.group(0)
                for match in re.finditer(
                    r"\bfile:(?://)?[^\s\"'<>]+",
                    text,
                    flags=re.IGNORECASE,
                )
            ),
        )
        for raw_value in candidate_values:
            if gold_digest is not None and gold_digest in raw_value.lower():
                raise ExperimentConfigError(
                    f"generation input {generation_path.relative_to(root)} contains gold hash"
                )
            parsed_uri = urlparse(raw_value)
            is_file_uri = parsed_uri.scheme.lower() == "file"
            is_windows_drive_path = bool(re.match(r"^[A-Za-z]:[\\/]+", raw_value))
            if not is_file_uri and not is_windows_drive_path and "://" in raw_value:
                continue
            if is_file_uri:
                uri_path = unquote(parsed_uri.path)
                if parsed_uri.netloc and parsed_uri.netloc.lower() != "localhost":
                    uri_path = f"//{parsed_uri.netloc}{uri_path}"
                if os.name == "nt" and re.match(r"^/[A-Za-z]:/", uri_path):
                    uri_path = uri_path[1:]
                normalized_candidate = os.path.normpath(
                    uri_path.replace("\\", os.sep).replace("/", os.sep)
                )
            else:
                local_path_like = (
                    is_windows_drive_path
                    or raw_value.startswith(("./", ".\\", "../", "..\\", "/", "\\"))
                    or "/" in raw_value
                    or "\\" in raw_value
                )
                if len(raw_value) > 1024 and not local_path_like:
                    continue
                normalized_candidate = os.path.normpath(
                    raw_value.replace("\\", os.sep).replace("/", os.sep)
                )
            if len(normalized_candidate) > 1024:
                raise ExperimentConfigError(
                    f"generation input {generation_path.relative_to(root)} has an "
                    "oversized local path candidate"
                )
            raw_candidate = Path(normalized_candidate)
            candidates = (
                [raw_candidate]
                if raw_candidate.is_absolute()
                else [root / raw_candidate, generation_path.parent / raw_candidate]
            )
            matched_local_file = False
            for candidate in candidates:
                try:
                    resolved_candidate = candidate.resolve()
                except OSError:
                    continue
                if not resolved_candidate.is_file():
                    continue
                matched_local_file = True
                try:
                    resolved_candidate.relative_to(root)
                except ValueError as exc:
                    raise ExperimentConfigError(
                        "generation input "
                        f"{generation_path.relative_to(root)} references a local file "
                        "outside the repository"
                    ) from exc
                if gold_path is not None and (
                    resolved_candidate == gold_path
                    or _sha256(resolved_candidate) == gold_digest
                ):
                    raise ExperimentConfigError(
                        "generation input "
                        f"{generation_path.relative_to(root)} resolves a string to gold"
                    )
                if resolved_candidate not in declared_generation_paths:
                    raise ExperimentConfigError(
                        "generation input "
                        f"{generation_path.relative_to(root)} references undeclared local file "
                        f"{resolved_candidate.relative_to(root)}"
                    )
            if is_file_uri and not matched_local_file:
                raise ExperimentConfigError(
                    f"generation input {generation_path.relative_to(root)} contains an "
                    "unresolvable local file URI"
                )

    output = Path(config["outputs"]["root"])
    if output.is_absolute():
        raise ExperimentConfigError("outputs.root must be repository-relative")
    output_resolved = (root / output).resolve()
    try:
        output_resolved.relative_to(root)
    except ValueError as exc:
        raise ExperimentConfigError("outputs.root escapes repository root") from exc
    if output_resolved.exists():
        raise ExperimentConfigError(
            "outputs.root already exists; runs must never overwrite prior output"
        )

    return {
        "config": config,
        "config_path": str(config_file),
        "config_sha256": _sha256(config_file),
        "verified_files": verified,
        "output_path": str(output_resolved),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--expected-mode")
    parser.add_argument("--allow-template", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_experiment_config(
            args.config,
            repo_root=args.repo_root,
            expected_mode=args.expected_mode,
            require_runnable=not args.allow_template,
        )
    except ExperimentConfigError as exc:
        parser.exit(1, f"AB experiment config invalid: {exc}\n")
    config = result["config"]
    print(
        json.dumps(
            {
                "status": "PASS",
                "config_status": config["config_status"],
                "mode": config["mode"],
                "branch": config["git"]["branch"],
                "provider": config["model"]["provider"],
                "run_id": config["run_id"],
                "config_path": str(
                    Path(result["config_path"]).relative_to(Path(args.repo_root).resolve())
                ),
                "config_sha256": result.get("config_sha256"),
                "verified_file_count": len(result["verified_files"]),
                "verified_paths": [item["path"] for item in result["verified_files"]],
                "output_path": result.get("output_path"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["ExperimentConfigError", "validate_experiment_config"]
