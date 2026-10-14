import pytest

from textbook2video.research.visual_decision import validate_visual_decision_document
from textbook2video.research.visual_decision_baselines import predict_baseline


def _proposition(text: str = "区块结构关系") -> dict:
    return {"id": "p1", "segment_id": "1", "text": text, "source_refs": ["s1"]}


@pytest.mark.parametrize(
    ("policy", "source_ids", "external_ids", "action", "need"),
    [
        ("never_retrieve", ["fig-1"], [], "reuse", "source-sufficient"),
        ("never_retrieve", [], ["ext-1"], "none", "none"),
        ("always_retrieve", ["fig-1"], [], "retrieve", "extra-support-needed"),
        ("keyword_heuristic", [], [], "retrieve", "extra-support-needed"),
        ("pool_availability", ["fig-1"], ["ext-1"], "reuse", "source-sufficient"),
        ("pool_availability", [], ["ext-1"], "retrieve", "extra-support-needed"),
    ],
)
def test_baselines_preserve_need_and_acquisition_as_separate_fields(
    policy: str,
    source_ids: list[str],
    external_ids: list[str],
    action: str,
    need: str,
) -> None:
    decision = predict_baseline(
        policy=policy,
        proposition=_proposition(),
        source_image_ids=source_ids,
        external_candidate_ids=external_ids,
    )

    assert decision["action"] == action
    assert decision["visual_support_need"] == need
    assert decision["claim"].endswith("not human gold.")
    validate_visual_decision_document(
        {"decisions": [decision]}, proposition_ids={"p1"}, require_evidence=True
    )


def test_keyword_baseline_does_not_retrieve_without_a_frozen_keyword() -> None:
    decision = predict_baseline(
        policy="keyword_heuristic",
        proposition=_proposition("这是一个抽象价值判断"),
    )
    assert decision["action"] == "none"
    assert decision["keyword_hits"] == []


def test_baseline_rejects_missing_proposition_id() -> None:
    with pytest.raises(ValueError, match="requires an ID"):
        predict_baseline(policy="never_retrieve", proposition={"text": "结构"})
