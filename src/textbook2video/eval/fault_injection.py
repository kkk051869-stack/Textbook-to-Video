"""Execute local fault fixtures through the repository's real evaluators.

Fault fixtures are intentionally synthetic and disposable.  They exercise the
same evaluator entry points used by a case run, while keeping all model
behaviour local and deterministic.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

from textbook2video.pipeline.checks import validate_storyboard

from .dataset import load_case, sha256_file
from .evaluators.animation_runtime import evaluate_animation_runtime
from .evaluators.audio_integrity import evaluate_audio_integrity
from .evaluators.content import evaluate_source_fidelity
from .evaluators.layout import evaluate_layout
from .evaluators.pedagogy import parse_pedagogy_judge
from .runner import run_case
from .schemas import validate_with_contract


DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "fault_injection"
_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-") or "fault"


def _local_case(
    root: Path,
    *,
    fixture_id: str,
    storyboard: dict[str, Any],
    source: dict[str, Any] | None,
    annotation: dict[str, Any] | None,
    artifact_payloads: dict[str, tuple[str, Any]],
) -> tuple[Any, Path]:
    """Build a disposable candidate case without changing the fixture tree."""
    case_root = root / "case"
    artifacts_root = case_root / "artifacts"
    case_root.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    source_value = source or {"paragraphs": [{"id": "p1", "text": "local fault fixture"}]}
    annotation_value = annotation or {"required_images": [], "core_concepts": []}
    source_path = case_root / "source.json"
    annotation_path = case_root / "annotation.json"
    _write_json(source_path, source_value)
    _write_json(annotation_path, annotation_value)

    candidate_artifacts: dict[str, str] = {}
    storyboard_filename = "storyboard.json"
    _write_json(artifacts_root / storyboard_filename, storyboard)
    candidate_artifacts["storyboard"] = storyboard_filename
    for role, (filename, payload) in artifact_payloads.items():
        destination = artifacts_root / filename
        if role == "audio_dir":
            destination.mkdir(parents=True, exist_ok=True)
        else:
            _write_json(destination, payload)
        candidate_artifacts[role] = filename

    manifest = {
        "schema_version": "textbookeval-case-v0.1",
        "case_id": f"fault-{_safe_id(fixture_id)}",
        "lesson_id": f"fault-{_safe_id(fixture_id)}-lesson",
        "status": "candidate",
        "dataset_version": "local-fault-fixture-v1",
        "source": {
            "files": [
                {
                    "role": "source_json",
                    "path": source_path.name,
                    "sha256": sha256_file(source_path),
                }
            ]
        },
        "annotation": {
            "role": "annotation",
            "path": annotation_path.name,
            "sha256": sha256_file(annotation_path),
            "review_status": "candidate",
        },
        "candidate_artifacts": candidate_artifacts,
    }
    manifest_path = case_root / "case_manifest.json"
    _write_json(manifest_path, manifest)
    return load_case(manifest_path), artifacts_root


def _run_real_evaluator(
    fixture_path: Path,
    value: dict[str, Any],
    *,
    evaluator: Any,
    artifact_payloads: dict[str, tuple[str, Any]] | None = None,
) -> dict[str, Any]:
    fixture_id = str(value.get("fixture_id") or fixture_path.stem)
    storyboard = value.get("storyboard")
    if not isinstance(storyboard, dict):
        raise ValueError(f"fault fixture has no storyboard object: {fixture_path}")
    with TemporaryDirectory(prefix="t2v-fault-") as temporary:
        root = Path(temporary)
        case, artifacts_root = _local_case(
            root,
            fixture_id=fixture_id,
            storyboard=storyboard,
            source=value.get("source") if isinstance(value.get("source"), dict) else None,
            annotation=value.get("annotation") if isinstance(value.get("annotation"), dict) else None,
            artifact_payloads=artifact_payloads or {},
        )
        report = run_case(
            case,
            run_id=f"fault-{_safe_id(fixture_id)}",
            artifacts_root=artifacts_root,
            output_root=root / "eval",
            evaluators=[evaluator],
            repo_root=_REPO_ROOT,
        )
        evaluator_name = str(getattr(evaluator, "evaluator_name", evaluator.__name__))
        result = report["evaluators"][evaluator_name]
        issues = list(result.get("issues", []))
        return {
            "actual_evaluator": evaluator_name,
            "actual_issue_types": sorted({str(item.get("type")) for item in issues}),
            "errors": [str(item.get("message") or item.get("type")) for item in issues],
            "detected": bool(issues),
            "details": {
                "status": result.get("status"),
                "passed": result.get("passed"),
                "metrics": result.get("metrics", {}),
            },
        }


def _evaluate_storyboard_fault(fixture_path: Path, value: dict[str, Any]) -> dict[str, Any]:
    storyboard = value.get("storyboard")
    if not isinstance(storyboard, dict):
        raise ValueError(f"fault fixture has no storyboard object: {fixture_path}")
    validation = validate_storyboard(storyboard, base_dir=fixture_path.parent)
    errors = list(validation.errors)
    expected = str(value.get("expected_message") or "")
    detected = bool(errors) and (not expected or any(expected in error for error in errors))
    return {
        "actual_evaluator": "structure",
        "actual_issue_types": ["STORYBOARD_INVALID"] if errors else [],
        "errors": errors,
        "detected": detected,
        "details": {"status": "failed" if errors else "pass", "passed": not errors},
    }


def _evaluate_judge_fault(value: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_pedagogy_judge(value.get("judge_response"))
    uncertainty = str(parsed.get("uncertainty") or "")
    detected = parsed.get("status") == "uncertain" and uncertainty in {
        "malformed_output", "missing_required_fields", "missing_evidence"
    }
    return {
        "actual_evaluator": "pedagogy.parse_pedagogy_judge",
        "actual_issue_types": ["PEDAGOGY_JUDGE_UNCERTAIN"] if detected else [],
        "errors": [str(parsed.get("reason") or "judge output was accepted")] if detected else [],
        "detected": detected,
        "details": {"parsed": parsed, "status": parsed.get("status")},
    }


def evaluate_fault_fixture(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path).resolve()
    value = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"fault fixture must be a JSON object: {fixture_path}")
    kind = str(value.get("kind") or "structure")
    if kind == "structure":
        evaluated = _evaluate_storyboard_fault(fixture_path, value)
    elif kind == "source_fidelity":
        evaluated = _run_real_evaluator(
            fixture_path, value, evaluator=evaluate_source_fidelity
        )
    elif kind == "animation_runtime":
        trace = value.get("animation_trace")
        if not isinstance(trace, dict):
            raise ValueError("animation_runtime fault requires animation_trace object")
        evaluated = _run_real_evaluator(
            fixture_path,
            value,
            evaluator=evaluate_animation_runtime,
            artifact_payloads={"animation_trace": ("animation_trace.json", trace)},
        )
    elif kind == "audio_integrity":
        timed = value.get("timed_storyboard") or value.get("storyboard")
        if not isinstance(timed, dict):
            raise ValueError("audio_integrity fault requires timed_storyboard object")
        evaluated = _run_real_evaluator(
            fixture_path,
            value,
            evaluator=evaluate_audio_integrity,
            artifact_payloads={
                "timed_storyboard": ("storyboard_timed.json", timed),
                "audio_dir": ("audio", None),
            },
        )
    elif kind == "layout":
        layout_report = value.get("layout_report")
        if not isinstance(layout_report, dict):
            raise ValueError("layout fault requires layout_report object")
        evaluated = _run_real_evaluator(
            fixture_path,
            value,
            evaluator=evaluate_layout,
            artifact_payloads={"layout_report": ("layout_report.json", layout_report)},
        )
    elif kind == "pedagogy_judge":
        evaluated = _evaluate_judge_fault(value)
    else:
        raise ValueError(f"unsupported fault fixture kind: {kind}")

    expected = str(value.get("expected_message") or "")
    if expected and evaluated["errors"]:
        evaluated["detected"] = evaluated["detected"] and any(
            expected in message for message in evaluated["errors"]
        )
    evaluated.update(
        {
            "fixture_id": str(value.get("fixture_id") or fixture_path.stem),
            "fault": str(value.get("fault") or "unknown"),
            "kind": kind,
            "expected_evaluator": str(value.get("expected_evaluator") or "structure"),
            "expected_message": expected,
            "repair_available": bool(value.get("repair_available", False)),
            "repair_attempted": False,
            "final_status": "detected" if evaluated["detected"] else "not_detected",
            "path": str(fixture_path),
        }
    )
    return evaluated


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
