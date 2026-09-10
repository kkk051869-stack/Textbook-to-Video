"""Shared helpers for evaluator adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..runner import EvalContext


def unavailable(context: EvalContext, evaluator: str, message: str) -> dict[str, Any]:
    evidence_id = f"{context.case.case_id}-{evaluator}-missing-input"
    manifest_path = getattr(context.case, "manifest_path", None)
    evidence = []
    if manifest_path is not None:
        evidence.append(
            evidence_for(Path(manifest_path), evidence_id=evidence_id, kind="case_manifest")
        )
    return {
        "status": "unavailable",
        "passed": None,
        "issues": [
            {
                "case_id": context.case.case_id,
                "stage": "eval",
                "evaluator": evaluator,
                "type": "EVALUATOR_INPUT_MISSING",
                "severity": "major",
                "message": message,
                "evidence_ids": [evidence_id] if evidence else [],
                "review_status": "unreviewed",
            }
        ],
        "evidence_ids": [evidence_id] if evidence else [],
        "_evidence": evidence,
    }


def evidence_for(path: Path, *, evidence_id: str, kind: str) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "kind": kind, "path": str(path)}
