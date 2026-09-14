import math

from textbook2video.eval.stability import aggregate_stability, parse_args, run_repeated


def _report(gate=True, value=1.0, issues=None, status=None):
    return {
        "status": status or ("pass" if gate else "failed"),
        "gates": {"layout": gate, "structure": True},
        "metrics": {"score": value},
        "issues": issues or [],
    }


def test_all_pass_repeated_run_has_stable_pass_mean_and_population_std(tmp_path):
    report = run_repeated(
        5,
        lambda index, run_id: {**_report(True, float(index)), "run_id": run_id},
        run_id_prefix="fixture",
        output_dir=tmp_path,
    )
    assert report["stable_pass_at_n"] is True
    assert report["gate_flip_rate"] == 0.0
    assert report["metrics"]["score"]["mean"] == 3.0
    assert math.isclose(report["metrics"]["score"]["std"], math.sqrt(2), rel_tol=1e-6)
    assert report["run_success_rate"] == 1.0
    assert report["worst_run"]["run_id"] == "fixture-005"
    assert (tmp_path / "stability_report.json").exists()
    assert (tmp_path / "stability_report.md").exists()


def test_gate_flip_and_issue_frequency_are_aggregated_per_repetition():
    report = aggregate_stability([
        {"run_id": "r1", "status": "pass", "run_completed": True, "system_error": False, "candidate_failure": False, "gates": {"layout": True}, "metrics": {}, "issues": [{"type": "A"}, {"type": "A"}]},
        {"run_id": "r2", "status": "failed", "run_completed": True, "system_error": False, "candidate_failure": True, "gates": {"layout": False}, "metrics": {}, "issues": [{"type": "A"}, {"type": "B"}]},
        {"run_id": "r3", "status": "pass", "run_completed": True, "system_error": False, "candidate_failure": False, "gates": {"layout": True}, "metrics": {}, "issues": []},
    ], run_id_prefix="flip")
    assert report["stable_pass_at_n"] is False
    assert report["gate_flip_rate"] == 1.0
    assert report["gates"]["layout"]["flip_count"] == 2
    assert report["issue_frequency"]["A"] == {"count": 2, "frequency": 0.666667}
    assert report["issue_frequency"]["B"] == {"count": 1, "frequency": 0.333333}
    assert report["worst_run"]["run_id"] == "r2"


def test_exception_is_system_error_and_does_not_erase_other_repetitions():
    def factory(index, _run_id):
        if index == 2:
            raise RuntimeError("local fixture failure")
        return _report(True, float(index))

    report = run_repeated(3, factory, run_id_prefix="errors")
    assert report["system_error_count"] == 1
    assert report["system_error_rate"] == 0.333333
    assert report["run_success_rate"] == 0.666667
    assert report["runs"][0]["status"] == "pass"
    assert report["runs"][1]["status"] == "system_error"
    assert report["runs"][2]["status"] == "pass"


def test_stability_cli_requires_one_source_and_supports_help_parse():
    args = parse_args(["--reports", "reports", "--repeats", "5", "--out", "out"])
    assert args.repeats == 5
    assert args.reports.name == "reports"
