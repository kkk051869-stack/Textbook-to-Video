"""Unified local fault-injection entry point using existing deterministic checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from textbook2video.pipeline.checks import validate_storyboard
from .schemas import validate_with_contract


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fault_injection"
_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


def evaluate_fault_fixture(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path).resolve()
    value = json.loads(fixture_path.read_text(encoding="utf-8"))
    storyboard = value.get("storyboard")
    if not isinstance(storyboard, dict):
        raise ValueError(f"fault fixture has no storyboard object: {fixture_path}")
    validation = validate_storyboard(storyboard, base_dir=fixture_path.parent)
    errors = list(validation.errors)
    expected = str(value.get("expected_message") or "")
    detected = bool(errors) and (not expected or any(expected in error for error in errors))
    return {
        "fixture_id": str(value.get("fixture_id") or fixture_path.stem),
        "fault": str(value.get("fault") or "unknown"),
        "expected_evaluator": str(value.get("expected_evaluator") or "structure"),
        "detected": detected,
        "errors": errors,
        "expected_message": expected,
        "path": str(fixture_path),
    }


def run_fault_injection_suite(fixture_dir: str | Path = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    directory = Path(fixture_dir)
    fixtures = sorted(directory.glob("*.json"))
    if not fixtures:
        raise FileNotFoundError(f"no fault fixtures found under {directory}")
    results = [evaluate_fault_fixture(path) for path in fixtures]
    report = {
        "schema_version": "textbookeval-fault-injection-v0.1",
        "fixture_count": len(results),
        "detected_count": sum(item["detected"] for item in results),
        "all_detected": all(item["detected"] for item in results),
        "fixtures": results,
    }
    validate_with_contract(report, "fault_injection_report.schema.json", contracts_dir=_CONTRACTS_DIR)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Textbook-to-Video fault injection fixtures")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_fault_injection_suite(args.fixtures)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_detected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
