import json

from textbook2video.eval.run_judge import run_videoqa_audience, run_videoqa_reference


class FakeClient:
    model = "fake-model"

    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    def chat(self, messages, *, max_tokens):
        self.messages = messages
        return self.reply, json.dumps(self.reply)


def test_audience_prompt_excludes_reference_answers(tmp_path):
    questions = tmp_path / "questions.json"
    questions.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "id": "q1",
                        "question": "What?",
                        "answer": "SECRET",
                        "scoring": "SECRET RUBRIC",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("visible content", encoding="utf-8")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    client = FakeClient(
        {"answers": [{"question_id": "q1", "answer_from_video": "visible", "confidence": 80}]}
    )

    result = run_videoqa_audience(
        case_id="case-1",
        lesson_id="lesson-1",
        questions=questions,
        frames=[frame],
        transcript=transcript,
        out=tmp_path / "audience.json",
        client=client,
        prompt_version="audience-v1",
    )

    prompt = client.messages[0]["content"][0]["text"]
    assert "SECRET" not in prompt
    assert result["config"]["input_mode"] == "keyframes_plus_transcript"
    assert result["items"][0]["question_id"] == "q1"
    assert len(result["metadata"]["prompt_sha256"]) == 64
    assert result["metadata"]["questions_sha256"]


def test_reference_scorer_consumes_audience_result_separately(tmp_path):
    questions = tmp_path / "questions.json"
    questions.write_text(
        json.dumps({"questions": [{"id": "q1", "question": "What?", "answer": "reference"}]}),
        encoding="utf-8",
    )
    audience = tmp_path / "audience.json"
    audience.write_text(
        json.dumps({"items": [{"question_id": "q1", "answer_from_video": "partial"}]}),
        encoding="utf-8",
    )
    client = FakeClient({"scores": [{"question_id": "q1", "score": 1, "reason": "partial"}]})

    result = run_videoqa_reference(
        case_id="case-1",
        lesson_id="lesson-1",
        questions=questions,
        audience_result=audience,
        out=tmp_path / "reference.json",
        client=client,
        prompt_version="reference-v1",
    )

    assert result["metrics"]["mean_score"] == 1.0
    assert result["issues"][0]["question_id"] == "q1"
    assert result["issues"][0]["evidence_ids"] == ["case-1-videoqa-reference-raw"]
    assert "reference" in client.messages[0]["content"]
