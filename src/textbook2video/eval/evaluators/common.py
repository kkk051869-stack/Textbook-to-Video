"""Shared helpers for evaluator adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..runner import EvalContext


def unavailable(context: EvalContext, evaluator: str, message: str) -> dict[str, Any]:
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
                "evidence_ids": [],
                "review_status": "unreviewed",
            }
        ],
    }


def evidence_for(path: Path, *, evidence_id: str, kind: str) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "kind": kind, "path": str(path)}
