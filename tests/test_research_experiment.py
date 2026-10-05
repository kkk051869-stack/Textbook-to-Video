import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from textbook2video.research.experiment import run_pilot_dry_run

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "datasets" / "research_event_alignment" / "pilot_v1"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_one_case_dry_run_writes_complete_model_free_bundle(tmp_path: Path) -> None:
    output = tmp_path / "dry-run"
    summary = run_pilot_dry_run(
        PILOT,
        output,
        case_ids=["lesson_002"],
        repository_root=ROOT,
    )
    bundle = output / "cases" / "lesson_002" / "result_bundle"
    expected = {
        "run_manifest.json",
        "binding_predictions.json",
        "event_schedule_predictions.json",
        "runtime_comparison.json",
        "rendered_evaluation.json",
        "signaling_audit.json",
        "metrics.json",
        "failures.json",
        "README.md",
    }
    assert {path.name for path in bundle.iterdir()} == expected
    assert summary["uses_external_model"] is False
    assert summary["case_count"] == 1
    assert summary["metrics"]["proposition_count"] > 0
    assert summary["metrics"]["runtime_event_count"] > 0
    assert summary["metrics"]["render_observed_event_count"] == 0
    aggregate = _load(output / "aggregate_metrics.json")
    assert aggregate["aggregation_unit"] == "case"
    assert aggregate["case_count"] == 1

    manifest = _load(bundle / "run_manifest.json")
    assert manifest["uses_external_model"] is False
    assert manifest["model"] is None
    assert all(len(item["sha256"]) == 64 for item in manifest["inputs"])

    binding = _load(bundle / "binding_predictions.json")
    binding_schema = _load(ROOT / "contracts" / "proposition_visual_binding.schema.json")
    Draft202012Validator(binding_schema).validate(binding)

    evaluation = _load(bundle / "rendered_evaluation.json")
    event_schema = _load(ROOT / "contracts" / "event_evaluation.schema.json")
    Draft202012Validator(event_schema).validate(evaluation)
    assert evaluation["claims"]["runtime_execution_evaluated"] is True
    assert evaluation["claims"]["rendered_visibility_evaluated"] is False
    assert evaluation["claims"]["semantic_timing_evaluated"] is False


def test_dry_run_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "dry-run"
    run_pilot_dry_run(PILOT, output, case_ids=["lesson_002"], repository_root=ROOT)
    with pytest.raises(FileExistsError):
        run_pilot_dry_run(PILOT, output, case_ids=["lesson_002"], repository_root=ROOT)
