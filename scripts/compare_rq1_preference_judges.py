"""Compare two RQ1 preference-Judge reports on the same development sample."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def compare_reports(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rows = {str(row["proposition_id"]): row for row in left.get("rows", [])}
    right_rows = {str(row["proposition_id"]): row for row in right.get("rows", [])}
    if set(left_rows) != set(right_rows) or not left_rows:
        raise ValueError("preference reports must cover the same nonempty proposition set")
    pairs: list[dict[str, Any]] = []
    confusion: dict[str, Counter[str]] = {}
    for proposition_id in sorted(left_rows):
        left_row = left_rows[proposition_id]
        right_row = right_rows[proposition_id]
        if set(left_row["option_order"]) != set(right_row["option_order"]):
            raise ValueError(f"eligible actions differ for {proposition_id}")
        left_best = str(left_row["judgment"]["best_action"])
        right_best = str(right_row["judgment"]["best_action"])
        confusion.setdefault(left_best, Counter())[right_best] += 1
        pairs.append(
            {
                "proposition_id": proposition_id,
                "stratum": left_row.get("stratum"),
                "left_best": left_best,
                "right_best": right_best,
                "agree": left_best == right_best,
                "left_ranking": left_row["judgment"]["ranking"],
                "right_ranking": right_row["judgment"]["ranking"],
            }
        )
    agreement_count = sum(pair["agree"] for pair in pairs)
    disputed = [pair for pair in pairs if not pair["agree"]]
    return {
        "schema_version": "rq1-preference-judge-comparison-v0.1",
        "status": "DEVELOPMENT_JUDGE_RELIABILITY_DIAGNOSTIC",
        "sample_count": len(pairs),
        "agreement_count": agreement_count,
        "agreement_rate": round(agreement_count / len(pairs), 6),
        "disagreement_count": len(disputed),
        "left_model": left.get("model"),
        "right_model": right.get("model"),
        "left_winner_counts": left.get("winner_action_counts"),
        "right_winner_counts": right.get("winner_action_counts"),
        "confusion_matrix": {
            action: dict(sorted(counts.items())) for action, counts in sorted(confusion.items())
        },
        "disputed_items": disputed,
        "pairs": pairs,
        "limitations": [
            "This is model-model agreement, not human inter-rater agreement.",
            "Agreement does not establish that either Judge is correct.",
            "Disputed VLM cases require independent model review and verifiable visual evidence; "
            "unresolved cases remain abstain.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite Judge comparison: {args.output}")
    result = compare_reports(_read(args.left), _read(args.right))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
