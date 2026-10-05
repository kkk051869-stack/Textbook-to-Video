from textbook2video.research.metrics import aggregate_event_reports


def test_aggregate_is_case_macro_not_event_micro() -> None:
    reports = [
        {
            "case_id": "small",
            "metrics": {
                "event_count": 1,
                "runtime_coverage": 0.0,
                "missing_runtime_count": 1,
                "wrong_target_count": 0,
                "render_unobservable_count": 1,
            },
        },
        {
            "case_id": "large",
            "metrics": {
                "event_count": 99,
                "runtime_coverage": 1.0,
                "missing_runtime_count": 0,
                "wrong_target_count": 2,
                "render_unobservable_count": 99,
            },
        },
    ]
    aggregate = aggregate_event_reports(reports)
    assert aggregate["aggregation_unit"] == "case"
    assert aggregate["macro_metrics"]["runtime_coverage"] == 0.5
    assert aggregate["totals"]["event_count"] == 100
    assert aggregate["totals"]["wrong_target_count"] == 2
