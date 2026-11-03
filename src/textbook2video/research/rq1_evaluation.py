"""Objective metrics for the RQ1 visual-support decision study.

The evaluator is intentionally independent from generation and judging.  It
consumes frozen references only after predictions have been produced, so gold
labels cannot leak into a method prompt or candidate selector.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

VISUAL_SUPPORT_LABELS = ("none", "source-sufficient", "extra-support-needed")


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _bounded_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def evaluate_rq1_predictions(
    references: dict[str, str],
    predictions: list[dict[str, Any]],
    *,
    labels: tuple[str, ...] = VISUAL_SUPPORT_LABELS,
    calibration_bins: int = 5,
) -> dict[str, Any]:
    """Evaluate one method with classification, calibration and cost metrics."""
    if calibration_bins < 1:
        raise ValueError("calibration_bins must be positive")
    unknown_references = sorted(set(references.values()) - set(labels))
    if unknown_references:
        raise ValueError(f"unsupported reference labels: {unknown_references}")

    by_id: dict[str, dict[str, Any]] = {}
    for item in predictions:
        proposition_id = str(item.get("proposition_id") or "").strip()
        if not proposition_id:
            raise ValueError("prediction requires proposition_id")
        if proposition_id in by_id:
            raise ValueError(f"duplicate prediction: {proposition_id}")
        by_id[proposition_id] = item

    unknown_ids = sorted(set(by_id) - set(references))
    if unknown_ids:
        raise ValueError(f"predictions reference unknown propositions: {unknown_ids}")

    confusion = {actual: {guess: 0 for guess in labels} for actual in labels}
    decided: list[dict[str, Any]] = []
    abstained: list[str] = []
    missing: list[str] = []
    action_counts: Counter[str] = Counter()
    for proposition_id, reference in references.items():
        item = by_id.get(proposition_id)
        if item is None:
            missing.append(proposition_id)
            continue
        action_counts[str(item.get("action") or "unspecified")] += 1
        prediction = str(item.get("label") or "").strip()
        is_abstain = bool(item.get("abstain")) or prediction in {"", "uncertain", "abstain"}
        if is_abstain:
            abstained.append(proposition_id)
            continue
        if prediction not in labels:
            raise ValueError(f"unsupported prediction label: {prediction!r}")
        confidence = _bounded_confidence(item.get("confidence"))
        confusion[reference][prediction] += 1
        decided.append(
            {
                "proposition_id": proposition_id,
                "reference": reference,
                "prediction": prediction,
                "confidence": confidence,
                "correct": reference == prediction,
            }
        )

    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    supported_recalls: list[float] = []
    for label in labels:
        tp = confusion[label][label]
        support = sum(confusion[label].values())
        predicted_count = sum(confusion[actual][label] for actual in labels)
        precision = _safe_div(tp, predicted_count)
        recall = _safe_div(tp, support)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        if support:
            supported_recalls.append(recall)
        f1_values.append(f1)
        per_class[label] = {
            "support": support,
            "predicted_count": predicted_count,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }

    correct_count = sum(row["correct"] for row in decided)
    brier_total = 0.0
    for row in decided:
        residual = (1.0 - row["confidence"]) / max(1, len(labels) - 1)
        for label in labels:
            probability = row["confidence"] if label == row["prediction"] else residual
            target = 1.0 if label == row["reference"] else 0.0
            brier_total += (probability - target) ** 2
    brier = _safe_div(brier_total, len(decided))

    calibration_rows: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(calibration_bins):
        lower = index / calibration_bins
        upper = (index + 1) / calibration_bins
        bucket = [
            row
            for row in decided
            if lower <= row["confidence"] <= upper
            and (index == calibration_bins - 1 or row["confidence"] < upper)
        ]
        if not bucket:
            continue
        mean_confidence = sum(row["confidence"] for row in bucket) / len(bucket)
        accuracy = sum(row["correct"] for row in bucket) / len(bucket)
        weight = len(bucket) / len(decided) if decided else 0.0
        ece += weight * abs(accuracy - mean_confidence)
        calibration_rows.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(bucket),
                "mean_confidence": round(mean_confidence, 6),
                "accuracy": round(accuracy, 6),
            }
        )

    trigger_tp = trigger_fp = trigger_fn = trigger_tn = 0
    for row in decided:
        reference_trigger = row["reference"] != "none"
        predicted_trigger = row["prediction"] != "none"
        if reference_trigger and predicted_trigger:
            trigger_tp += 1
        elif not reference_trigger and predicted_trigger:
            trigger_fp += 1
        elif reference_trigger and not predicted_trigger:
            trigger_fn += 1
        else:
            trigger_tn += 1
    trigger_precision = _safe_div(trigger_tp, trigger_tp + trigger_fp)
    trigger_recall = _safe_div(trigger_tp, trigger_tp + trigger_fn)

    total = len(references)
    return {
        "reference_count": total,
        "prediction_count": len(by_id),
        "decided_count": len(decided),
        "abstain_count": len(abstained),
        "missing_count": len(missing),
        "coverage": round(_safe_div(len(decided), total), 6),
        "selective_accuracy": round(_safe_div(correct_count, len(decided)), 6),
        "macro_f1": round(_safe_div(sum(f1_values), len(f1_values)), 6),
        "balanced_accuracy_supported_classes": round(
            _safe_div(sum(supported_recalls), len(supported_recalls)), 6
        ),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "calibration": {
            "multiclass_brier": round(brier, 6),
            "expected_calibration_error": round(ece, 6),
            "bins": calibration_rows,
        },
        "visual_trigger": {
            "tp": trigger_tp,
            "fp": trigger_fp,
            "fn": trigger_fn,
            "tn": trigger_tn,
            "precision": round(trigger_precision, 6),
            "recall": round(trigger_recall, 6),
            "f1": round(
                _safe_div(2 * trigger_precision * trigger_recall, trigger_precision + trigger_recall),
                6,
            ),
        },
        "cost": {
            "action_counts": dict(sorted(action_counts.items())),
            "external_retrieval_requests": action_counts["retrieve"],
            "generation_requests": action_counts["generate"],
            "visual_asset_requests": action_counts["retrieve"] + action_counts["generate"],
        },
        "abstained_ids": abstained,
        "missing_ids": missing,
        "scored_items": decided,
    }


__all__ = ["VISUAL_SUPPORT_LABELS", "evaluate_rq1_predictions"]
