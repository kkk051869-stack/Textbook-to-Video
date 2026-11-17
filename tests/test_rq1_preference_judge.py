import json

import pytest

from textbook2video.research.rq1_preference_judge import (
    judge_rq1_action_preferences,
    normalize_preference_judgment,
)


def test_preference_judge_requires_complete_strict_ranking() -> None:
    result = normalize_preference_judgment(
        {
            "ranking": ["reuse", "none", "generate", "retrieve"],
            "rejected_actions": ["retrieve"],
            "reason_by_action": {
                "none": "Text alone is possible but less clear.",
                "reuse": "The source diagram directly explains the structure.",
                "retrieve": "External retrieval is unnecessary.",
                "generate": "Generation duplicates the available source image.",
            },
            "confidence": 0.9,
            "abstain": False,
        },
        proposition_id="p1",
        eligible_actions=["none", "reuse", "retrieve", "generate"],
        judge_kind="VLM",
    )

    assert result["best_action"] == "reuse"
    assert result["second_action"] == "none"
    assert result["method_blind"] is True


def test_preference_judge_rejects_partial_ranking() -> None:
    with pytest.raises(ValueError, match="rank every eligible action"):
        normalize_preference_judgment(
            {
                "ranking": ["none"],
                "reason_by_action": {"none": "Enough", "retrieve": "Too broad"},
                "confidence": 0.7,
                "abstain": False,
            },
            proposition_id="p1",
            eligible_actions=["none", "retrieve"],
            judge_kind="LLM",
        )


def test_preference_judge_rejected_actions_must_be_ranking_suffix() -> None:
    with pytest.raises(ValueError, match="ranking suffix"):
        normalize_preference_judgment(
            {
                "ranking": ["none", "reuse", "retrieve"],
                "rejected_actions": ["reuse"],
                "reason_by_action": {
                    "none": "Best",
                    "reuse": "Wrong image",
                    "retrieve": "Possible",
                },
                "confidence": 0.8,
                "abstain": False,
            },
            proposition_id="p1",
            eligible_actions=["none", "reuse", "retrieve"],
            judge_kind="VLM",
        )


def test_preference_judge_uses_one_comparative_model_call() -> None:
    captured = {}

    def fake_text(prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(
            {
                "ranking": ["none", "generate", "retrieve"],
                "rejected_actions": ["retrieve"],
                "reason_by_action": {
                    "none": "Text is sufficient.",
                    "retrieve": "Likely generic.",
                    "generate": "Possible but unnecessary.",
                },
                "confidence": 0.8,
                "abstain": False,
            }
        )

    result = judge_rq1_action_preferences(
        proposition={"id": "p1", "text": "抽象定义"},
        source_evidence=[{"id": "s1", "text": "定义内容"}],
        options=[
            {"action": "retrieve", "proposal": "search"},
            {"action": "none", "proposal": "text only"},
            {"action": "generate", "proposal": "diagram"},
        ],
        text_call=fake_text,
    )

    assert result["best_action"] == "none"
    assert result["format_repair_used"] is False
    assert "current_visual_decision" not in captured["prompt"]


def test_preference_judge_repairs_incomplete_ranking_once() -> None:
    replies = iter(
        [
            json.dumps(
                {
                    "ranking": ["none"],
                    "rejected_actions": [],
                    "reason_by_action": {"none": "Enough", "retrieve": "Too broad"},
                    "confidence": 0.7,
                    "abstain": False,
                }
            ),
            json.dumps(
                {
                    "ranking": ["none", "retrieve"],
                    "rejected_actions": ["retrieve"],
                    "reason_by_action": {"none": "Enough", "retrieve": "Too broad"},
                    "confidence": 0.7,
                    "abstain": False,
                }
            ),
        ]
    )

    result = judge_rq1_action_preferences(
        proposition={"id": "p1", "text": "抽象定义"},
        source_evidence=[],
        options=[
            {"action": "none", "proposal": "text only"},
            {"action": "retrieve", "proposal": "search"},
        ],
        text_call=lambda *args, **kwargs: next(replies),
    )

    assert result["ranking"] == ["none", "retrieve"]
    assert result["format_repair_used"] is True
    assert "rank every eligible action" in result["initial_validation_error"]
