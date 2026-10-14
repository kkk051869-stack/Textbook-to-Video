import hashlib
import json
from collections import Counter
from pathlib import Path

GOLD = (
    Path(__file__).parents[1]
    / "datasets"
    / "research_generation_v2"
    / "reference"
    / "a_visual_support_gold_v0.1"
    / "human_reviewed_gold.json"
)


def test_committed_human_reviewed_gold_is_complete_and_canonical() -> None:
    document = json.loads(GOLD.read_text(encoding="utf-8"))
    items = document["items"]

    assert document["gold_status"] == "HUMAN_REVIEWED_GOLD"
    assert document["review_status"] == "CONFIRMED_BY_USER"
    assert len(items) == 30
    assert Counter(item["annotation"]["visual_support_need"] for item in items) == {
        "none": 28,
        "source-sufficient": 1,
        "extra-support-needed": 1,
    }
    assert Counter(item["annotation"]["retrieval_need"] for item in items) == {
        "no": 29,
        "generation-candidate": 1,
    }

    canonical = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == (
        "d5ec065f116f5ab9fb668b81becfa0185a788e2cfeb989c8f15325d483342139"
    )
