"""Promote a confirmed local failure into an independent regression fixture."""

from __future__ import annotations

import json
import re
import argparse
from pathlib import Path
from typing import Any, Sequence

from textbook2video.pipeline.checks import validate_storyboard
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
    replay: dict[str, Any] | None = None,
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
    if replay is not None:
        if (
            not isinstance(replay, dict)
            or replay.get("kind") != "storyboard"
            or not isinstance(replay.get("fault_storyboard"), dict)
            or not isinstance(replay.get("repaired_storyboard"), dict)
        ):
            raise ValueError(
                "storyboard replay requires fault_storyboard and repaired_storyboard objects"
            )
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
    if replay is not None:
        fixture["replay"] = {
            "kind": "storyboard",
            "fault_storyboard": dict(replay["fault_storyboard"]),
            "repaired_storyboard": dict(replay["repaired_storyboard"]),
        }
    validate_with_contract(fixture, "regression_fixture.schema.json", contracts_dir=_CONTRACTS_DIR)
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fixture


def replay_regression_fixture(
    fixture_path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Re-run a promoted local fixture through the real storyboard validator.

    The replay intentionally evaluates both the repaired artifact and the
    original injected fault.  A promoted fixture passes only when the repaired
    version passes and re-injecting the fault is detected again.
    """

    path = Path(fixture_path).resolve()
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise ValueError("regression fixture must be a JSON object")
    replay = fixture.get("replay")
    if not isinstance(replay, dict) or replay.get("kind") != "storyboard":
        raise ValueError("fixture does not contain an executable storyboard replay")
    root = Path(base_dir).resolve() if base_dir is not None else path.parent
    fault = replay.get("fault_storyboard")
    repaired = replay.get("repaired_storyboard")
    if not isinstance(fault, dict) or not isinstance(repaired, dict):
        raise ValueError("storyboard replay payload is incomplete")

    fault_report = validate_storyboard(fault, base_dir=root)
    repaired_report = validate_storyboard(repaired, base_dir=root)
    reinjected_report = validate_storyboard(fault, base_dir=root)
    result = {
        "fixture_id": str(fixture.get("fixture_id") or path.stem),
        "evaluator": str(fixture.get("evaluator") or "structure"),
        "fault_detected": bool(fault_report.errors),
        "fault_issue_count": len(fault_report.errors),
        "repaired_passed": repaired_report.ok,
        "repaired_issue_count": len(repaired_report.errors),
        "reinjected_fault_detected": bool(reinjected_report.errors),
        "reinjected_issue_count": len(reinjected_report.errors),
        "passed": bool(fault_report.errors and repaired_report.ok and reinjected_report.errors),
        "fixture_path": str(path),
        "details": {
            "fault_errors": list(fault_report.errors),
            "repaired_errors": list(repaired_report.errors),
            "reinjected_errors": list(reinjected_report.errors),
        },
    }
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a promoted local regression fixture")
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--base-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = replay_regression_fixture(args.fixture, base_dir=args.base_dir)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


__all__ = ["promote_failure", "replay_regression_fixture", "parse_args"]


if __name__ == "__main__":
    raise SystemExit(main())
