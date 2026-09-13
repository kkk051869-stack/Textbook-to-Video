"""Promote a confirmed local failure into an independent regression fixture."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .schemas import validate_with_contract

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def promote_failure(
    *,
    case_id: str,
    issue: dict[str, Any],
    input_conditions: dict[str, Any],
    expected_invariants: list[dict[str, Any]],
    evaluator: str,
    confirmed: bool,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create a regression fixture only after repair/re-eval confirmation."""

    if not confirmed:
        raise ValueError("only a confirmed repaired failure may be promoted")
    issue_id = str(issue.get("issue_id") or "").strip()
    issue_type = str(issue.get("type") or issue.get("category") or "").strip()
    if not case_id.strip() or not issue_id or not issue_type:
        raise ValueError("case_id, issue.issue_id, and issue.type are required")
    if not isinstance(expected_invariants, list) or not expected_invariants:
        raise ValueError("expected_invariants must be a non-empty list")
    fixture_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"{case_id}-{issue_id}").strip("-")
    fixture = {
        "schema_version": "textbookeval-regression-fixture-v0.1",
        "fixture_id": fixture_id,
        "case_id": case_id,
        "source_issue": dict(issue),
        "input_conditions": dict(input_conditions),
        "expected_invariants": [dict(item) for item in expected_invariants],
        "evaluator": evaluator,
        "promotion": {"confirmed": True, "requires_targeted_re_eval": True},
    }
    validate_with_contract(fixture, "regression_fixture.schema.json", contracts_dir=_CONTRACTS_DIR)
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fixture


__all__ = ["promote_failure"]
