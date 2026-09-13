import json

import pytest

from textbook2video.eval.fault_injection import parse_args, run_fault_injection_suite
from textbook2video.eval.perturbation import perturb_tts_durations, perturb_viewport
from textbook2video.eval.regression_promotion import promote_failure


def test_fault_injection_suite_detects_three_local_failures():
    report = run_fault_injection_suite()
    assert report["fixture_count"] >= 3
    assert report["all_detected"] is True
    assert {item["expected_evaluator"] for item in report["fixtures"]} == {"structure"}


def test_regression_promotion_requires_confirmation_and_writes_fixture(tmp_path):
    with pytest.raises(ValueError, match="confirmed"):
        promote_failure(
            case_id="case",
            issue={"issue_id": "i1", "type": "LAYOUT_ISSUE"},
            input_conditions={"viewport": "1366x768"},
            expected_invariants=[{"evaluator": "layout", "must_pass": True}],
            evaluator="layout",
            confirmed=False,
        )
    destination = tmp_path / "regression" / "layout.json"
    fixture = promote_failure(
        case_id="case",
        issue={"issue_id": "i1", "type": "LAYOUT_ISSUE", "severity": "major"},
        input_conditions={"viewport": "1366x768"},
        expected_invariants=[{"evaluator": "layout", "must_pass": True}],
        evaluator="layout",
        confirmed=True,
        output_path=destination,
    )
    assert fixture["promotion"]["confirmed"] is True
    assert json.loads(destination.read_text(encoding="utf-8"))["fixture_id"] == "case-i1"


def test_perturbations_preserve_input_and_change_only_requested_value():
    report = {"metrics": {"x": 1}, "metadata": {"viewport": {"width": 1920, "height": 1080}}}
    changed_report = perturb_viewport(report, width=1366, height=768)
    assert report["metadata"]["viewport"]["width"] == 1920
    assert changed_report["metadata"]["viewport"] == {"width": 1366, "height": 768}
    storyboard = {"segments": [{"audio_duration_sec": 2.0}, {"audio_duration_sec": 3.0}]}
    changed_storyboard = perturb_tts_durations(storyboard, factor=1.1)
    assert storyboard["segments"][0]["audio_duration_sec"] == 2.0
    assert changed_storyboard["segments"][0]["audio_duration_sec"] == 2.2


def test_fault_injection_cli_parse():
    args = parse_args(["--fixtures", "fixtures", "--out", "out/report.json"])
    assert args.fixtures.name == "fixtures"
