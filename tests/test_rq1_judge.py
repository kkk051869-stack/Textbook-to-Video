import json

from textbook2video.research.rq1_judge import judge_rq1_decision


def _response() -> str:
    return json.dumps(
        {
            "verdict": "ACCEPT",
            "scores": {
                "necessity_correctness": 4,
                "source_grounding": 4,
                "coherence": 3,
                "candidate_appropriateness": None,
            },
            "reason": "The no-visual decision is supported by the supplied explanation.",
            "issues": [],
        }
    )


def test_text_judge_is_gold_blind_and_uses_llm_path() -> None:
    captured = {}

    def fake_text(prompt, **kwargs):
        captured["prompt"] = prompt
        return _response()

    result = judge_rq1_decision(
        proposition={"id": "p1", "text": "抽象定义"},
        source_evidence=[{"id": "s1", "text": "定义证据"}],
        decision={"action": "none", "rationale": "文字说明已经足够"},
        text_call=fake_text,
    )

    assert result["judge_kind"] == "LLM"
    assert result["gold_blind"] is True
    assert "gold" not in captured["prompt"].lower()


def test_image_judge_uses_vlm_path() -> None:
    calls = []

    def fake_image(prompt, paths, **kwargs):
        calls.append(paths)
        return _response().replace('"candidate_appropriateness": null', '"candidate_appropriateness": 4')

    result = judge_rq1_decision(
        proposition={"id": "p1", "text": "结构关系"},
        source_evidence=[{"id": "s1", "text": "结构由三部分组成"}],
        decision={"action": "reuse", "rationale": "图示对应结构"},
        candidate_image="candidate.png",
        image_call=fake_image,
    )

    assert result["judge_kind"] == "VLM"
    assert calls == [["candidate.png"]]
