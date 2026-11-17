"""Opt-in experiment bookkeeping, independent of generation and model selection.

These tools pin existing file bytes and check references; they do not run an
experiment, copy media, adjudicate methods, or turn execution into visibility.
Use snapshot.freeze_case when an independent copy of an entire case is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .snapshot import sha256_file

INPUT_MANIFEST_VERSION = "research-experiment-inputs-v1.0"


def frozen_file_records(paths: dict[str, str | Path]) -> dict[str, dict[str, str]]:
    """Pin files at their supplied locations; missing inputs are never omitted."""
    return {name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in paths.items()}


def verify_frozen_files(records: dict[str, dict[str, Any]]) -> None:
    """Shared byte-integrity check, retaining candidate-pool error messages."""
    for label, record in records.items():
        path = Path(str(record.get("path") or ""))
        if not path.is_file() or sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"frozen input changed or missing: {label}: {path}")


def freeze_experiment_inputs(
    output_path: str | Path, *, inputs: dict[str, str | Path],
    methods: dict[str, Any], version: dict[str, Any],
) -> Path:
    """Create a new manifest for source/propositions/candidates/config/version.

    Callers explicitly enumerate their inputs. Configs, prompts and dirty-source
    snapshots should be listed as files, rather than identified only by Git HEAD.
    The manifest pins references, not immutable copies of the referenced files.
    """
    document = {
        "schema_version": INPUT_MANIFEST_VERSION,
        "inputs": frozen_file_records({
            name: Path(path).resolve() for name, path in inputs.items()
        }),
        "methods": methods, "version": version,
    }
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(text)
    return destination


def verify_experiment_inputs(
    manifest_path: str | Path, *, expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Check pinned inputs; supply the frozen manifest hash to detect edits to it."""
    path = Path(manifest_path)
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise ValueError("experiment input manifest hash changed")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != INPUT_MANIFEST_VERSION:
        raise ValueError("unsupported experiment input manifest schema")
    verify_frozen_files(document["inputs"])
    return document


def validate_binding_references(
    *, source_units: list[dict], propositions: list[dict],
    candidates: list[dict], results: list[dict],
) -> None:
    """Check IDs and source links without applying a method's semantic policy.

    A valid reference is not proof that a source entails a claim or an object
    supports a relation. Selection, abstention and failure statuses stay intact.
    """
    source_ids = {str(item["id"]) for item in source_units}
    proposition_ids = {str(item["id"]) for item in propositions}
    candidate_ids = {str(item["id"]) for item in candidates}
    for proposition in propositions:
        for ref in proposition.get("source_refs", []):
            source_id = (
                (ref.get("source_unit_id") or ref.get("id")) if isinstance(ref, dict) else ref
            )
            if str(source_id) not in source_ids:
                raise ValueError(f"unknown source reference: {source_id}")
    for result in results:
        if str(result.get("proposition_id") or "") not in proposition_ids:
            raise ValueError("method result references unknown proposition")
        selected = result.get("selected_candidate_ids") or [result.get("selected_candidate_id")]
        for target in selected:
            if target is not None and str(target) not in candidate_ids:
                raise ValueError(f"method result references unknown candidate: {target}")


def index_event_records(
    records: list[dict], *, id_fields: tuple[str, ...] = ("event_id", "id"),
) -> dict[str, dict]:
    """Index persisted events with the historical last-record-wins semantics."""
    return {str(next((item[key] for key in id_fields if item.get(key)), "")): item
            for item in records if isinstance(item, dict)}


def collect_event_evidence(
    *, method_decisions: list[dict], bindings: list[dict], planned: list[dict],
    compiled: list[dict], runtime: list[dict], rendered: list[dict],
) -> dict[str, Any]:
    """Associate evidence layers without collapsing their original verdicts.

    Unmatched events are retained, including extra legacy runtime records.
    Missing evidence remains None; executed and extracted never mean visible.
    """
    supplied = {"planned": planned, "compiled": compiled, "runtime": runtime, "rendered": rendered}
    layers = {name: index_event_records(records) for name, records in supplied.items()}
    unkeyed = {}
    for name, records in supplied.items():
        keys = set()
        unkeyed[name] = []
        for item in records:
            if not isinstance(item, dict):
                raise ValueError(f"invalid event record in {name} evidence")
            key = next(iter(index_event_records([item])))
            if key and key in keys:
                raise ValueError(f"duplicate event ID in {name} evidence")
            keys.add(key)
            if not key:
                unkeyed[name].append(item)
    event_ids = dict.fromkeys(key for layer in layers.values() for key in layer if key)
    events = []
    for event_id in event_ids:
        row = {name: layer.get(event_id) for name, layer in layers.items()}
        proposition_id = next((
            str(item.get("proposition_id") or
                (item.get("research_p0") or {}).get("proposition_id") or "")
            for item in row.values() if item and (item.get("proposition_id") or
                (item.get("research_p0") or {}).get("proposition_id"))
        ), "")
        row.update(event_id=event_id, proposition_id=proposition_id,
                   method_decisions=[item for item in method_decisions
                                     if proposition_id and str(item.get("proposition_id") or
                                         item.get("narration_proposition_id") or "")
                                     == proposition_id],
                   bindings=[item for item in bindings if proposition_id and
                             str(item.get("proposition_id") or "") == proposition_id])
        events.append(row)
    return {"events": events,
            "unkeyed_records": unkeyed,
            "claim": "Evidence linkage only; runtime execution is not final-video visibility."}
