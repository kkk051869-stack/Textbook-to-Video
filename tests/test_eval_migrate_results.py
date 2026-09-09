import json
from pathlib import Path

from textbook2video.eval.migrate_results import (
    normalize_readability_frames,
    normalize_videoqa_combined,
)
from textbook2video.eval.schemas import validate_with_contract


def test_combined_videoqa_is_split_into_audience_and_reference(tmp_path):
    source = tmp_path / "videoqa.json"
    source.write_text(
        json.dumps(
            {
                "lesson": "lesson_002",
                "system": "internal_C01",
                "answers": [
                    {"question_id": "q1", "answer_from_video": "answer", "confidence": 90}
                ],
                "scores": [{"question_id": "q1", "score": 1, "reason": "missing detail"}],
                "raw_answer": "raw audience",
                "raw_score": "raw score",
            }
        ),
        encoding="utf-8",
    )

    audience, reference = normalize_videoqa_combined(
        source,
        case_id="case_lesson_002",
        model="qwen2.5-vl-32b-awq",
        audience_prompt_version="audience-v1",
        reference_prompt_version="reference-v1",
    )

    assert audience["result_type"] == "videoqa_audience"
    assert audience["items"][0]["answer_from_video"] == "answer"
    assert reference["result_type"] == "videoqa_reference"
    assert reference["metrics"]["mean_score"] == 1.0
    assert reference["issues"][0]["question_id"] == "q1"
    for result in (audience, reference):
        validate_with_contract(
            result,
            "judge_result.schema.json",
            contracts_dir=Path(__file__).resolve().parents[1] / "contracts",
        )


def test_readability_history_becomes_one_case_result(tmp_path):
    paths = []
    for index, score in enumerate((2, 1), start=1):
        path = tmp_path / f"frame-{index}.json"
        path.write_text(
            json.dumps(
                {
                    "lesson_id": "lesson_004",
                    "system": "internal_C01",
                    "frame": f"frame-{index}.jpg",
                    "readability_score": score,
                    "brief_observation": "clear" if score == 2 else "too small",
                }
            ),
            encoding="utf-8",
        )
        paths.append(path)

    result = normalize_readability_frames(
        paths,
        case_id="case_lesson_004",
        lesson_id="lesson_004",
        system="internal_C01",
        model="qwen2.5-vl-32b-awq",
        prompt_version="readability-v1",
    )

    assert result["metrics"]["frame_count"] == 2
    assert result["metrics"]["mean_readability_score"] == 1.5
    assert result["metrics"]["low_score_frame_count"] == 1
    assert result["issues"][0]["type"] == "READABILITY_LOW_SCORE"
