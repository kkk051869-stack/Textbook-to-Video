"""Compute Pilot v1 agreement only after two completed human annotations.

The module never adjudicates.  Empty or incomplete annotations return
``NOT_READY`` and no synthetic agreement score.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


CATEGORICAL_FIELDS = (
    "boundary_status",
    "visual_applicability",
    "visual_relation",
    "temporal_label",
    "visibility_status",
    "signal_applicability",
    "signal_label",
)
TARGET_FIELDS = (
    "visual_element_ids",
    "expected_target_element_ids",
    "observed_target_ids",
)


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"annotation must be an object: {path}")
    return value


def _rows(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"segment_id": segment.get("segment_id"), **row}
        for segment in annotation.get("segments", []) or []
        for row in segment.get("propositions", []) or []
        if isinstance(row, dict)
    ]


def _ready(annotation: dict[str, Any]) -> tuple[bool, str]:
    if annotation.get("annotation_status") != "COMPLETED":
        return False, "annotation_status is not COMPLETED"
    rows = _rows(annotation)
    if not rows:
        return False, "annotation contains no proposition rows"
    if any(not row.get("proposition_id") for row in rows):
        return False, "one or more proposition_id values are empty"
    return True, "ready"


def _kappa(pairs: list[tuple[Any, Any]]) -> float | None:
    pairs = [(left, right) for left, right in pairs if left is not None and right is not None]
    if not pairs:
        return None
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left_counts, right_counts = Counter(left for left, _ in pairs), Counter(right for _, right in pairs)
    labels = set(left_counts) | set(right_counts)
    expected = sum(
        left_counts[label] / len(pairs) * right_counts[label] / len(pairs)
        for label in labels
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return round((observed - expected) / (1.0 - expected), 6)


def _interval_iou(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    values = (
        left.get("acceptable_start_min"), left.get("acceptable_start_max"),
        right.get("acceptable_start_min"), right.get("acceptable_start_max"),
    )
    if any(value is None for value in values):
        return None
    a0, a1, b0, b1 = map(float, values)
    intersection = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return round(intersection / union, 6) if union > 0 else (1.0 if a0 == b0 else 0.0)


def _jaccard(left: Any, right: Any) -> float:
    a, b = set(left or []), set(right or [])
    if not a and not b:
        return 1.0
    return round(len(a & b) / len(a | b), 6) if a | b else 1.0


def evaluate_agreement(annotation_a: dict[str, Any], annotation_b: dict[str, Any]) -> dict[str, Any]:
    ready_a, reason_a = _ready(annotation_a)
    ready_b, reason_b = _ready(annotation_b)
    if not ready_a or not ready_b:
        return {
            "status": "NOT_READY",
            "reason": {"annotator_A": reason_a, "annotator_B": reason_b},
            "metrics": None,
            "disagreements": [],
        }
    rows_a = {(str(row["segment_id"]), str(row["proposition_id"])): row for row in _rows(annotation_a)}
    rows_b = {(str(row["segment_id"]), str(row["proposition_id"])): row for row in _rows(annotation_b)}
    shared = sorted(set(rows_a) & set(rows_b))
    disagreements = []
    categorical = {}
    for field in CATEGORICAL_FIELDS:
        pairs = [(rows_a[key].get(field), rows_b[key].get(field)) for key in shared]
        categorical[field] = {"cohen_kappa": _kappa(pairs), "comparable_count": sum(a is not None and b is not None for a, b in pairs)}
        for key, (left, right) in zip(shared, pairs):
            if left != right:
                disagreements.append({
                    "case": annotation_a.get("case_id"),
                    "segment": key[0],
                    "proposition": key[1],
                    "field": field,
                    "annotator_A": left,
                    "annotator_B": right,
                })
    interval_ious = [value for key in shared if (value := _interval_iou(rows_a[key], rows_b[key])) is not None]
    target_agreement = {
        field: round(sum(_jaccard(rows_a[key].get(field), rows_b[key].get(field)) for key in shared) / len(shared), 6)
        if shared else None
        for field in TARGET_FIELDS
    }
    return {
        "status": "READY",
        "matched_proposition_count": len(shared),
        "unmatched_A": [list(key) for key in sorted(set(rows_a) - set(rows_b))],
        "unmatched_B": [list(key) for key in sorted(set(rows_b) - set(rows_a))],
        "metrics": {
            "categorical": categorical,
            "mean_temporal_window_iou": round(sum(interval_ious) / len(interval_ious), 6) if interval_ious else None,
            "target_jaccard": target_agreement,
        },
        "disagreements": disagreements,
    }


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute human annotation agreement without adjudication")
    parser.add_argument("annotation_a")
    parser.add_argument("annotation_b")
    parser.add_argument("--output", required=True)
    parser.add_argument("--disagreements")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    result = evaluate_agreement(_read(args.annotation_a), _read(args.annotation_b))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.disagreements:
        Path(args.disagreements).write_text(
            json.dumps(result.get("disagreements", []), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
