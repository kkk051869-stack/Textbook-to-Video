"""Append-only repair lineage for local candidate repairs.

The writer is intentionally independent from a repair implementation. Existing
Storyboard and layout repair functions can call it without adopting a second
report format. Every attempt records artifact hashes and an explicit outcome;
missing files are represented as ``null`` plus a reason instead of being
silently omitted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from textbook2video.eval.schemas import validate_with_contract

LINEAGE_SCHEMA_VERSION = "textbookeval-repair-lineage-v0.1"
_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def sha256_file(path: str | Path | None) -> str | None:
    """Return a file SHA-256, or ``None`` when the path is not a file."""

    if path is None:
        return None
    source = Path(path)
    if not source.is_file():
        return None
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactRef:
    """A path/hash pair suitable for a repair lineage record."""

    path: str | None
    sha256: str | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.reason is None:
            value.pop("reason")
        return value


def artifact_reference(path: str | Path | None, *, root: Path) -> ArtifactRef:
    """Build a safe relative artifact reference with an observed hash."""

    if path is None:
        return ArtifactRef(path=None, sha256=None, reason="artifact path was not supplied")
    source = Path(path)
    try:
        resolved = source.resolve()
    except OSError:
        resolved = source.absolute()
    if not resolved.is_file():
        return ArtifactRef(
            path=None,
            sha256=None,
            reason=f"artifact does not exist: {source}",
        )
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        # External paths are allowed for callers that are joining a pre-existing
        # report, but are explicit and never mistaken for a relative candidate.
        relative = str(resolved)
    return ArtifactRef(path=relative, sha256=sha256_file(resolved))


def _relative_or_absolute(value: Path, root: Path) -> str:
    resolved = value.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _report_reference(value: Any, *, root: Path) -> Any:
    if value is None or isinstance(value, dict):
        return value
    if isinstance(value, (str, Path)):
        return _relative_or_absolute(Path(value), root)
    raise TypeError(f"evaluation report reference must be a path, object, or null: {value!r}")


@dataclass
class RepairAttempt:
    """One immutable logical repair attempt."""

    repair_id: str
    case_id: str
    run_id: str
    source_issue_id: str | None
    issue_type: str
    stage: str
    severity: str
    repair_strategy: str
    round: int
    before_artifact: ArtifactRef | dict[str, Any]
    after_artifact: ArtifactRef | dict[str, Any]
    before_eval_report: str | dict[str, Any] | None = None
    after_eval_report: str | dict[str, Any] | None = None
    model: str = "N/A"
    token: int | float | None = None
    latency_sec: float | None = None
    result: str = "attempted"
    provenance: dict[str, Any] = field(default_factory=dict)
    candidate_dir: str | None = None
    accepted_artifact: str | None = None
    targeted_evaluators: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("before_artifact", "after_artifact"):
            ref = value[key]
            if isinstance(ref, dict) and ref.get("reason") is None:
                ref.pop("reason", None)
        if self.notes is None:
            value.pop("notes", None)
        return value


class RepairLineageWriter:
    """Atomically append repair attempts to a single lineage JSON file."""

    def __init__(
        self,
        path: str | Path,
        *,
        case_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self.case_id = case_id
        self.run_id = run_id
        self._data = self._load_existing()

    def _load_existing(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": LINEAGE_SCHEMA_VERSION,
                **({"case_id": self.case_id} if self.case_id else {}),
                **({"run_id": self.run_id} if self.run_id else {}),
                "repairs": [],
            }
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            value = {
                "schema_version": LINEAGE_SCHEMA_VERSION,
                "repairs": value,
            }
        if not isinstance(value, dict) or not isinstance(value.get("repairs"), list):
            raise ValueError("repair lineage must be an object with a repairs array")
        value.setdefault("schema_version", LINEAGE_SCHEMA_VERSION)
        if self.case_id and value.get("case_id") not in {None, self.case_id}:
            raise ValueError("repair lineage case_id does not match writer")
        if self.run_id and value.get("run_id") not in {None, self.run_id}:
            raise ValueError("repair lineage run_id does not match writer")
        return value

    @property
    def records(self) -> list[dict[str, Any]]:
        return list(self._data["repairs"])

    def new_id(self, prefix: str = "repair") -> str:
        """Return a unique ID for this lineage file."""

        existing = {str(item.get("repair_id")) for item in self._data["repairs"] if isinstance(item, dict)}
        while True:
            value = f"{prefix}-{uuid.uuid4().hex[:12]}"
            if value not in existing:
                return value

    def append(self, attempt: RepairAttempt) -> dict[str, Any]:
        """Append one attempt and reject duplicate IDs before writing."""

        if not isinstance(attempt, RepairAttempt):
            raise TypeError("append expects a RepairAttempt")
        repair_id = str(attempt.repair_id).strip()
        if not repair_id:
            raise ValueError("repair_id must be non-empty")
        existing = {str(item.get("repair_id")) for item in self._data["repairs"] if isinstance(item, dict)}
        if repair_id in existing:
            raise ValueError(f"duplicate repair_id: {repair_id}")
        if self.case_id and attempt.case_id != self.case_id:
            raise ValueError("attempt case_id does not match writer")
        if self.run_id and attempt.run_id != self.run_id:
            raise ValueError("attempt run_id does not match writer")

        record = attempt.to_dict()
        for key in ("before_artifact", "after_artifact"):
            raw = record[key]
            if not isinstance(raw, dict):
                raise ValueError(f"{key} must be an artifact reference object")
        record["before_eval_report"] = _report_reference(record.get("before_eval_report"), root=self.path.parent)
        record["after_eval_report"] = _report_reference(record.get("after_eval_report"), root=self.path.parent)
        self._data["repairs"].append(record)
        self._write()
        return record

    def append_record(
        self,
        *,
        repair_id: str,
        case_id: str,
        run_id: str,
        source_issue_id: str | None,
        issue_type: str,
        stage: str,
        severity: str,
        repair_strategy: str,
        round: int,
        before_artifact: str | Path | None,
        after_artifact: str | Path | None,
        before_eval_report: str | Path | dict[str, Any] | None = None,
        after_eval_report: str | Path | dict[str, Any] | None = None,
        model: str = "N/A",
        token: int | float | None = None,
        latency_sec: float | None = None,
        result: str = "attempted",
        provenance: dict[str, Any] | None = None,
        candidate_dir: str | Path | None = None,
        accepted_artifact: str | Path | None = None,
        targeted_evaluators: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        attempt = RepairAttempt(
            repair_id=repair_id,
            case_id=case_id,
            run_id=run_id,
            source_issue_id=source_issue_id,
            issue_type=issue_type,
            stage=stage,
            severity=severity,
            repair_strategy=repair_strategy,
            round=round,
            before_artifact=artifact_reference(before_artifact, root=self.path.parent),
            after_artifact=artifact_reference(after_artifact, root=self.path.parent),
            before_eval_report=before_eval_report,
            after_eval_report=after_eval_report,
            model=model,
            token=token,
            latency_sec=latency_sec,
            result=result,
            provenance=provenance or {},
            candidate_dir=(
                _relative_or_absolute(Path(candidate_dir), self.path.parent)
                if candidate_dir is not None
                else None
            ),
            accepted_artifact=(
                _relative_or_absolute(Path(accepted_artifact), self.path.parent)
                if accepted_artifact is not None
                else None
            ),
            targeted_evaluators=list(targeted_evaluators or []),
            notes=notes,
        )
        return self.append(attempt)

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        validate_with_contract(
            self._data,
            "repair_lineage.schema.json",
            contracts_dir=_CONTRACTS_DIR,
        )
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


__all__ = [
    "ArtifactRef",
    "LINEAGE_SCHEMA_VERSION",
    "RepairAttempt",
    "RepairLineageWriter",
    "artifact_reference",
    "sha256_file",
]
