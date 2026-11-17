import pytest

from textbook2video.research.rq1_evaluation import evaluate_rq1_predictions


def test_rq1_metrics_report_classification_calibration_abstention_and_cost() -> None:
    references = {
        "p1": "none",
        "p2": "source-sufficient",
        "p3": "extra-support-needed",
        "p4": "none",
    }
    predictions = [
        {"proposition_id": "p1", "label": "none", "action": "none", "confidence": 0.9},
        {
            "proposition_id": "p2",
            "label": "source-sufficient",
            "action": "reuse",
            "confidence": 0.8,
        },
        {
            "proposition_id": "p3",
            "label": "none",
            "action": "none",
            "confidence": 0.6,
        },
        {
            "proposition_id": "p4",
            "label": "uncertain",
            "action": "retrieve",
            "confidence": 0.2,
            "abstain": True,
        },
    ]

    result = evaluate_rq1_predictions(references, predictions)

    assert result["coverage"] == 0.75
    assert result["selective_accuracy"] == pytest.approx(2 / 3, abs=1e-6)
    assert result["abstain_count"] == 1
    assert result["visual_trigger"]["fn"] == 1
    assert result["cost"]["external_retrieval_requests"] == 1
    assert result["cost"]["generation_requests"] == 0
    assert result["calibration"]["multiclass_brier"] > 0


def test_rq1_metrics_reject_duplicate_predictions() -> None:
    with pytest.raises(ValueError, match="duplicate prediction"):
        evaluate_rq1_predictions(
            {"p1": "none"},
            [
                {"proposition_id": "p1", "label": "none"},
                {"proposition_id": "p1", "label": "none"},
            ],
        )
