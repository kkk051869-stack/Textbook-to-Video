"""Optional baseline/candidate regression adapter.

The normal one-case runner does not invent a baseline.  When a caller places a
precomputed ``regression.json`` or ``baseline_eval_report.json`` beside the
candidate artifacts, this adapter preserves it; otherwise the report clearly
records that Before/After comparison must be run with ``eval-compare``.
"""

from __future__ import annotations

import json

from ..runner import EvalContext
from .common import evidence_for


def evaluate_regression(context: EvalContext) -> dict:
    name = "regression"
    path = context.artifact("regression")
    if path is None or not path.is_file():
        baseline = context.artifact("baseline_eval_report")
        if baseline is None or not baseline.is_file():
            return {
                "status": "skipped",
                "passed": None,
                "metrics": {},
                "details": {
                    "reason": "no baseline/candidate comparison supplied; use t2v eval-compare"
                },
                "issues": [],
                "evidence_ids": [],
            }
        path = baseline
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("regression input must be a JSON object")
    issues = value.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("regression input issues must be an array")
    evidence_id = f"{context.case.case_id}-regression"
    return {
        "status": str(value.get("status", "ok")),
        "passed": value.get("passed"),
        "metrics": value.get("metrics", {}),
        "details": value,
        "issues": issues,
        "evidence_ids": [evidence_id],
        "_evidence": [evidence_for(path, evidence_id=evidence_id, kind="regression")],
    }


evaluate_regression.evaluator_name = "regression"
