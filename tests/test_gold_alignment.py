import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.research.gold_alignment import evaluate_reviewed_gold


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _gold(*, retrieval_need: str = "no") -> dict:
    return {
        "gold_status": "HUMAN_REVIEWED_GOLD",
        "review_status": "CONFIRMED_BY_USER",
        "items": [
            {
                "case_id": "lesson_1",
                "knowledge_proposition_id": "old-k1",
                "proposition_text": "区块结构关系。",
                "annotation": {
                    "visual_support_need": "source-sufficient",
                    "retrieval_need": retrieval_need,
                },
            }
        ],
    }


def _graph(*, duplicate_text: bool = False, two_narration: bool = False) -> dict:
    knowledge = [{"id": "k1", "text": "区块结构关系"}]
    if duplicate_text:
        knowledge.append({"id": "k2", "text": "区块结构关系！"})
    narration = [{"id": "n1", "knowledge_proposition_ids": ["k1"], "text": "旁白一"}]
    if two_narration:
        narration.append({"id": "n2", "knowledge_proposition_ids": ["k1"], "text": "旁白二"})
    return {
        "case_id": "lesson-1",
        "knowledge_propositions": knowledge,
        "narration_propositions": narration,
    }


def _decision(prop_id: str, action: str) -> dict:
    return {
        "narration_proposition_id": prop_id,
        "action": action,
        "decision_state": "DECIDED",
        "source_sufficiency": "SUFFICIENT" if action == "reuse" else "INSUFFICIENT",
    }


def test_alignment_records_hashes_and_separate_retrieval_metrics(tmp_path: Path) -> None:
    gold = _write(tmp_path / "gold.json", _gold())
    graph = _write(tmp_path / "graph.json", _graph())
    decisions = _write(tmp_path / "decisions.json", {"decisions": [_decision("n1", "reuse")]})
    output = tmp_path / "evaluation.json"

    evaluate_reviewed_gold(
        gold_path=gold,
        proposition_graph_path=graph,
        visual_decisions_path=decisions,
        output_path=output,
    )
    result = json.loads(output.read_text(encoding="utf-8"))

    assert result["coverage"] == 1.0
    assert result["metrics"]["accuracy"] == 1.0
    assert result["retrieval_metrics"]["accuracy"] == 1.0
    assert result["aligned_items"][0]["prediction_retrieval"] == "no"
    assert result["input_sha256"]["gold"] == hashlib.sha256(gold.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        evaluate_reviewed_gold(
            gold_path=gold,
            proposition_graph_path=graph,
            visual_decisions_path=decisions,
            output_path=output,
        )


def test_alignment_reports_ambiguous_exact_text_without_guessing(tmp_path: Path) -> None:
    gold = _write(tmp_path / "gold.json", _gold())
    graph = _write(tmp_path / "graph.json", _graph(duplicate_text=True))
    decisions = _write(tmp_path / "decisions.json", {"decisions": [_decision("n1", "reuse")]})
    output = tmp_path / "evaluation.json"

    evaluate_reviewed_gold(
        gold_path=gold,
        proposition_graph_path=graph,
        visual_decisions_path=decisions,
        output_path=output,
    )
    result = json.loads(output.read_text(encoding="utf-8"))

    assert result["coverage"] == 0.0
    assert result["unmatched_items"][0]["reason"] == "ambiguous_exact_text_match"


def test_alignment_excludes_conflicting_linked_decisions_from_scores(tmp_path: Path) -> None:
    gold = _write(tmp_path / "gold.json", _gold())
    graph = _write(tmp_path / "graph.json", _graph(two_narration=True))
    decisions = _write(
        tmp_path / "decisions.json",
        {"decisions": [_decision("n1", "reuse"), _decision("n2", "retrieve")]},
    )
    output = tmp_path / "evaluation.json"

    evaluate_reviewed_gold(
        gold_path=gold,
        proposition_graph_path=graph,
        visual_decisions_path=decisions,
        output_path=output,
    )
    result = json.loads(output.read_text(encoding="utf-8"))

    assert result["scored_count"] == 0
    assert result["retrieval_scored_count"] == 0
    assert result["aligned_items"][0]["prediction"] == "uncertain"
    assert result["aligned_items"][0]["prediction_retrieval"] == "uncertain"
