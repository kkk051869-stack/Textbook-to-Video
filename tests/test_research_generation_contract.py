import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "research_generation_v2.schema.json"
TRACE_CONTRACT = ROOT / "contracts" / "animation_trace.schema.json"
MOCK_ROOT = ROOT / "datasets" / "research_generation_v2" / "mock_v0.1"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_g0_mock_files_exist_and_validate() -> None:
    manifest = _load(MOCK_ROOT / "package_manifest.json")
    research_validator = Draft202012Validator(_load(CONTRACT))
    trace_validator = Draft202012Validator(_load(TRACE_CONTRACT))

    research_validator.validate(manifest)
    for role, relative_path in manifest["files"].items():
        path = MOCK_ROOT / relative_path
        assert path.is_file(), f"missing {role}: {path}"
        value = _load(path)
        if role == "runtime_trace":
            trace_validator.validate(value)
        else:
            research_validator.validate(value)


def test_g0_mock_cross_file_ids_and_spans_are_consistent() -> None:
    case_root = MOCK_ROOT / "cases" / "mock_lesson_001"
    source = _load(case_root / "source_units.json")
    plan = _load(case_root / "lesson_plan.json")
    script = _load(case_root / "script_v2.json")
    storyboard = _load(case_root / "storyboard.json")
    timed = _load(case_root / "storyboard_timed.json")
    compiled = _load(case_root / "compiled_timeline.json")
    trace = _load(case_root / "animation_trace.json")
    rendered = _load(case_root / "render_evidence.json")

    case_ids = {
        source["case_id"],
        plan["case_id"],
        script["case_id"],
        storyboard["case_id"],
        timed["case_id"],
        compiled["case_id"],
        trace["case_id"],
        rendered["case_id"],
    }
    assert case_ids == {"mock_lesson_001"}

    source_ids = {item["id"] for item in source["source_units"]}
    image_ids = {item["id"] for item in source["source_images"]}
    source_reference_ids = source_ids | image_ids

    knowledge_point_ids = {kp["id"] for kp in plan["knowledge_points"]}
    knowledge_propositions = {
        proposition["id"]: proposition
        for kp in plan["knowledge_points"]
        for proposition in kp["propositions"]
    }
    assert knowledge_point_ids
    for kp in plan["knowledge_points"]:
        assert set(kp["source_refs"]) <= source_ids
    for proposition in knowledge_propositions.values():
        assert set(proposition["source_refs"]) <= source_ids

    segment_ids = {segment["id"] for segment in script["segments"]}
    narration_propositions = {}
    for segment in script["segments"]:
        narration = segment["narration_text"]
        for proposition in segment["narration_propositions"]:
            narration_propositions[proposition["id"]] = proposition
            assert set(proposition["knowledge_proposition_ids"]) <= set(knowledge_propositions)
            span = proposition["span"]
            assert narration[span["start"] : span["end"]] == proposition["text"]

    elements = {}
    events = {}
    for segment in storyboard["segments"]:
        assert segment["id"] in segment_ids
        assert set(segment["narration_proposition_ids"]) <= set(narration_propositions)
        for element in segment["elements"]:
            assert element["id"] not in elements
            elements[element["id"]] = element
            assert set(element["source_refs"]) <= source_reference_ids
            assert set(element["knowledge_proposition_ids"]) <= set(knowledge_propositions)
            assert set(element["narration_proposition_ids"]) <= set(narration_propositions)
        for event in segment["events"]:
            assert event["id"] not in events
            events[event["id"]] = event
            assert event["target_element_id"] in elements
            assert set(event["narration_proposition_ids"]) <= set(narration_propositions)

    planned_by_event = {}
    for segment in timed["segments"]:
        assert segment["segment_id"] in segment_ids
        for event in segment["scheduled_events"]:
            planned_by_event[event["event_id"]] = event
            assert event["event_id"] in events
            assert event["target_element_id"] in elements
            assert event["trigger_at_sec"] <= segment["audio_duration_sec"]

    compiled_by_event = {}
    for segment in compiled["segments"]:
        assert segment["segment_id"] in segment_ids
        for event in segment["events"]:
            compiled_by_event[event["event_id"]] = event
            assert event["event_id"] in events
            assert event["target_element_id"] in elements

    assert set(planned_by_event) == set(compiled_by_event) == set(events)
    for event_id, event in compiled_by_event.items():
        assert event["start_ms"] == round(planned_by_event[event_id]["trigger_at_sec"] * 1000)

    trace_by_event = {event["event_id"]: event for event in trace["events"]}
    assert set(trace_by_event) == set(events)
    for event in trace_by_event.values():
        assert event["target"] in elements

    observations = {item["event_id"]: item for item in rendered["observations"]}
    assert set(observations) == set(events)
    for observation in observations.values():
        assert observation["target_element_id"] in elements
        assert observation["observed_visible_start_sec"] <= observation["observed_visible_end_sec"]


def test_g0_contract_has_no_duplicate_runtime_trace() -> None:
    manifest = _load(MOCK_ROOT / "package_manifest.json")
    files = manifest["files"]
    assert list(files).count("runtime_trace") == 1
    assert files["runtime_trace"].endswith("animation_trace.json")
    assert files["render_evidence"].endswith("render_evidence.json")
    assert files["runtime_trace"] != files["render_evidence"]

