import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_rq1_small_comparison.py"
SPEC = importlib.util.spec_from_file_location("run_rq1_small_comparison", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_alignment_uses_unique_text_not_reused_proposition_id() -> None:
    graph = {
        "case_id": "lesson-002",
        "knowledge_propositions": [
            {"id": "p1", "text": "新的短命题"},
            {"id": "p2", "text": "保持一致的命题。"},
        ],
    }
    gold = {
        "items": [
            {
                "case_id": "lesson_002",
                "knowledge_proposition_id": "p1",
                "proposition_text": "旧的长命题",
                "annotation": {"visual_support_need": "none"},
            },
            {
                "case_id": "lesson_002",
                "knowledge_proposition_id": "old-p2",
                "proposition_text": "保持一致的命题",
                "annotation": {"visual_support_need": "source-sufficient"},
            },
        ]
    }

    references, unmatched = MODULE._align_references(gold, graph)

    assert references == {"p2": "source-sufficient"}
    assert unmatched == [
        {
            "gold_proposition_id": "p1",
            "reason": "no_exact_text_match",
            "candidate_ids": [],
        }
    ]
