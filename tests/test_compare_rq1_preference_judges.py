import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "compare_rq1_preference_judges.py"
SPEC = importlib.util.spec_from_file_location("compare_rq1_preference_judges", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _report(model: str, winners: list[str]) -> dict:
    return {
        "model": model,
        "winner_action_counts": {},
        "rows": [
            {
                "proposition_id": f"p{index}",
                "stratum": "none",
                "option_order": ["none", "retrieve", "generate"],
                "judgment": {
                    "best_action": winner,
                    "ranking": [
                        winner,
                        *[
                            action
                            for action in ("none", "retrieve", "generate")
                            if action != winner
                        ],
                    ],
                },
            }
            for index, winner in enumerate(winners, start=1)
        ],
    }


def test_compare_reports_exposes_disputed_items() -> None:
    result = MODULE.compare_reports(
        _report("plus", ["none", "retrieve"]),
        _report("max", ["none", "generate"]),
    )

    assert result["agreement_count"] == 1
    assert result["agreement_rate"] == 0.5
    assert result["disputed_items"][0]["proposition_id"] == "p2"


def test_compare_reports_requires_same_sample() -> None:
    with pytest.raises(ValueError, match="same nonempty proposition set"):
        MODULE.compare_reports(_report("a", ["none"]), {"model": "b", "rows": []})
