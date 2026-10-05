import json
from pathlib import Path

from jsonschema import Draft202012Validator

from textbook2video.research.semantic_binding import build_binding_report

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1" / "cases" / "mock_lesson_001"


def _load(name: str) -> dict:
    return json.loads((MOCK / name).read_text(encoding="utf-8"))


def test_mock_binding_report_is_schema_valid_and_model_free() -> None:
    report = build_binding_report(_load("script_v2.json"), _load("storyboard.json"))
    schema = json.loads(
        (ROOT / "contracts" / "proposition_visual_binding.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(report)

    assert report["method"]["uses_external_model"] is False
    assert report["metrics"] == {
        "proposition_count": 2,
        "bound_count": 2,
        "abstained_count": 0,
        "binding_coverage": 1.0,
    }
    by_proposition = {
        item["narration_proposition_id"]: item["target_element_ids"] for item in report["bindings"]
    }
    assert by_proposition["mock-lesson-001-nprop-001"] == ["mock-lesson-001-seg-001-el-001"]
    assert by_proposition["mock-lesson-001-nprop-002"] == ["mock-lesson-001-seg-001-el-002"]


def test_missing_storyboard_segment_is_reported_not_silently_dropped() -> None:
    script = _load("script_v2.json")
    report = build_binding_report(script, {"case_id": "mock_lesson_001", "segments": []})
    assert report["bindings"] == []
    assert len(report["failures"]) == 2
    assert all(item["type"] == "missing_storyboard_segment" for item in report["failures"])


def test_duplicate_narration_proposition_id_is_rejected() -> None:
    script = _load("script_v2.json")
    duplicate = dict(script["segments"][0]["narration_propositions"][0])
    script["segments"][0]["narration_propositions"].append(duplicate)
    try:
        build_binding_report(script, _load("storyboard.json"))
    except ValueError as exc:
        assert "duplicate narration proposition ID" in str(exc)
    else:
        raise AssertionError("duplicate proposition ID must fail")
