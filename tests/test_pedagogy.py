import copy
import json
from pathlib import Path

from textbook2video.eval.dataset import FileAsset
from textbook2video.eval.evaluators.pedagogy import (
    _candidate_repetition_pairs,
    _evaluate_examples,
    _evaluate_assessment,
    _evaluate_misconceptions,
    _evaluate_ordering,
    _merge_judge,
    evaluate_pedagogy,
    parse_pedagogy_judge,
)
from textbook2video.eval.evaluators.pedagogy_judge import PedagogyJudgeAdapter
from textbook2video.eval.runner import EvalContext, run_case
from textbook2video.eval.schemas import SchemaValidationError, validate_with_contract


class _Case:
    case_id = "case_pedagogy"
    lesson_id = "lesson_pedagogy"
    dataset_version = "dataset-test"

    def __init__(self, root: Path):
        self.root = root
        self.raw = {"case_id": self.case_id, "lesson_id": self.lesson_id}

    def assets(self):
        return [
            FileAsset("source_json", "source.json", ""),
            FileAsset("annotation", "annotation.json", ""),
            FileAsset("heldout_questions", "questions.json", ""),
        ]

    def resolve_asset(self, asset):
        return self.root / asset.path


def _context(tmp_path: Path, *, inverted: bool = False) -> EvalContext:
    (tmp_path / "source.json").write_text(
        json.dumps(
            {"paragraphs": [{"id": "p1", "text": "Core concept is explained before application."}]}
        ),
        encoding="utf-8",
    )
    (tmp_path / "annotation.json").write_text(
        json.dumps(
            {
                "learning_objectives": [
                    {"id": "obj-1", "statement": "Explain the core concept.", "concept_ids": ["c1"]}
                ],
                "core_concepts": [
                    {"id": "c1", "statement": "Core concept", "must_mention_terms": ["core concept"], "evidence_paragraphs": ["p1"]},
                    {"id": "c2", "statement": "Application", "must_mention_terms": ["application"], "evidence_paragraphs": ["p1"]},
                ],
                "prerequisite_relations": [{"prerequisite": "c1", "dependent": "c2"}],
                "misconceptions": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "questions.json").write_text(
        json.dumps({"questions": [{"id": "q1", "question": "What is the core concept?", "answer": "Core concept", "targets": ["c1"]}]}),
        encoding="utf-8",
    )
    ordered = [
        {"id": 1, "narration": "Core concept is defined.", "teaching_role": "definition", "elements": []},
        {"id": 2, "narration": "Application follows.", "teaching_role": "application", "elements": []},
    ]
    if inverted:
        ordered = [
            {"id": 1, "narration": "Application follows.", "teaching_role": "application", "elements": []},
            {"id": 2, "narration": "Core concept is defined.", "teaching_role": "definition", "elements": []},
        ]
    (tmp_path / "storyboard.json").write_text(json.dumps({"segments": ordered}), encoding="utf-8")
    return EvalContext(
        case=_Case(tmp_path),
        run_id="pedagogy-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
    )


def test_prerequisite_ordering_is_deterministic_and_evidenced(tmp_path):
    result = evaluate_pedagogy(_context(tmp_path, inverted=True))
    prerequisite = result["details"]["prerequisite_satisfaction"]

    assert prerequisite["items"][0]["status"] == "violated"
    assert prerequisite["items"][0]["first_explained"]["slide"] == 2
    assert result["issues"][0]["type"] == "PEDAGOGY_PREREQUISITE_GAP"
    assert result["issues"][0]["severity"] == "error"


def test_objective_mapping_and_heldout_alignment_use_frozen_ids(tmp_path):
    result = evaluate_pedagogy(_context(tmp_path))

    objectives = result["details"]["learning_objective_coverage"]
    assessment = result["details"]["assessment_alignment"]
    heldout = result["details"]["heldout_alignment"]
    assert objectives["summary"]["objective_source"] == "explicit"
    assert objectives["items"][0]["objective_id"] == "obj-1"
    assert objectives["items"][0]["matched_concepts"] == ["c1"]
    assert assessment["status"] == "not_applicable"
    assert assessment["items"] == []
    assert heldout["items"][0]["target_concepts"] == ["c1"]
    assert heldout["items"][0]["status"] == "aligned"


def test_redundancy_retrieval_distinguishes_recap_from_reteach():
    concept = {"id": "c1", "must_mention_terms": ["core concept"]}
    repeated = [
        ("1", "Core concept is explained.", {}),
        ("2", "Core concept is explained.", {}),
    ]
    recap = [
        ("1", "Core concept is explained.", {}),
        ("2", "Recap: core concept is explained.", {}),
    ]

    assert _candidate_repetition_pairs(concept, repeated)[0]["status"] == "redundant_reteach"
    assert _candidate_repetition_pairs(concept, recap)[0]["status"] == "productive_repetition"


def test_optional_judge_parser_fails_closed():
    valid = parse_pedagogy_judge(
        {"status": "questionable", "confidence": "medium", "evidence": [{"slide": 2, "text": "evidence"}], "reason": "ordering"}
    )
    malformed = parse_pedagogy_judge("not-json")
    missing_evidence = parse_pedagogy_judge({"status": "reasonable", "confidence": "high", "evidence": []})

    assert valid["status"] == "questionable"
    assert malformed["status"] == "uncertain"
    assert missing_evidence["status"] == "uncertain"


def test_lesson001_pedagogy_report_has_all_dimensions_and_calibration(tmp_path):
    from textbook2video.eval.dataset import load_case

    root = Path(__file__).resolve().parents[1]
    case = load_case(root / "datasets/pilot3/cases/lesson_001/case_manifest.json", verify_files=False, require_frozen=True)
    report = run_case(
        case,
        run_id="pedagogy-lesson001-test",
        artifacts_root=root / "datasets/pilot3/artifacts/lesson_001",
        output_root=tmp_path / "lesson001",
        repo_root=root,
        evaluators=[evaluate_pedagogy],
    )

    dimensions = {
        "learning_objective_coverage",
        "prerequisite_satisfaction",
        "concept_ordering",
        "example_relevance",
        "misconception_handling",
        "redundancy",
        "assessment_alignment",
        "heldout_alignment",
    }
    assert set(report["pedagogy"]["details"]) >= dimensions
    assert report["pedagogy"]["details"]["provenance"]["llm_judge_used"] is False
    assert (tmp_path / "lesson001" / "pedagogy_calibration.md").is_file()
    manifest = json.loads((tmp_path / "lesson001" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["evaluator_provenance"]["pedagogy"]["rule_version"] == "pedagogy-v0.2"
    assert report["status"] in {"pass", "pass_with_warnings", "failed"}


class _StaticJudge:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def judge(self, judge_type, payload, *, allowed_slides, evidence_texts):
        self.calls.append((judge_type, payload, allowed_slides, evidence_texts))
        return {
            "judgement": self.response,
            "provenance": {"judge_type": judge_type, "model": "static-test"},
        }


class _Client:
    model = "fake-pedagogy-model"
    api_base = "in-process-test-client"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, *, max_tokens):
        self.calls += 1
        response = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        return response, json.dumps(response, ensure_ascii=False)


def _valid_judgement(status, slide=3, text="Example: core concept"):
    return {
        "status": status,
        "confidence": "high",
        "evidence": [{"slide": slide, "text": text}],
        "reason": "supplied evidence supports the judgement",
        "uncertainty": None,
    }


def test_example_judge_only_receives_real_example_candidate_and_merges_result():
    concept = {
        "id": "c1",
        "statement": "Core concept",
        "must_mention_terms": ["core concept"],
        "evidence_paragraphs": ["p1"],
    }
    segments = [
        ("2", "A definition of core concept.", {"id": 2}),
        ("3", "Example: core concept in practice.", {"id": 3, "elements": [{"type": "example"}]}),
    ]
    judge = _StaticJudge(_valid_judgement("directly_relevant", text="Example: core concept in practice."))
    result, issues = _evaluate_examples(
        [concept], segments, {"p1": "The principle is described."}, judge=judge, judge_log=[]
    )

    assert len(judge.calls) == 1
    item = result["items"][0]
    assert item["deterministic_status"] == "partially_relevant"
    assert item["judge_status"] == "directly_relevant"
    assert item["final_status"] == "directly_relevant"
    assert item["judge_used"] is True
    assert not issues


def test_misconception_judge_does_not_treat_negation_alone_as_handled():
    annotation = {
        "misconceptions": [
            {"id": "m1", "wrong_claim": "水在50度沸腾", "why_wrong": "标准气压下应为100度", "must_address": True}
        ],
    }
    segments = [("1", "不是水在50度沸腾，而是水在100度沸腾。", {"id": 1})]
    judge = _StaticJudge(_valid_judgement("introduced", text=segments[0][1]))
    result, _ = _evaluate_misconceptions(
        annotation, segments, "", {"p1": "标准气压下水在100度沸腾。"}, judge=judge, judge_log=[]
    )

    item = result["items"][0]
    assert item["deterministic_status"] == "introduced"
    assert item["judge_status"] == "introduced"
    assert item["final_status"] == "introduced"


def test_ordering_judge_is_limited_to_ambiguous_lexical_inversion():
    concepts = [{"id": "c1", "statement": "Core concept", "must_mention_terms": ["core concept"]}]
    segments = [
        ("1", "Core concept is an application in practice.", {"id": 1}),
        ("2", "Core concept definition appears here.", {"id": 2}),
    ]
    judge_log = []
    judge = _StaticJudge(_valid_judgement("reasonable", slide=1, text=segments[0][1]))
    result, _ = _evaluate_ordering(concepts, segments, {}, judge=judge, judge_log=judge_log)

    assert result["items"][0]["deterministic_status"] == "questionable"
    assert result["items"][0]["final_status"] == "reasonable"
    assert len(judge.calls) == 1
    assert judge_log[0]["judge_type"] == "concept_ordering"


def test_judge_conflict_without_high_confidence_becomes_uncertain():
    record = {}
    _merge_judge(
        record,
        deterministic_status="partially_relevant",
        outcome={
            "judgement": _valid_judgement("directly_relevant"),
            "provenance": {},
        },
    )
    record["judge_confidence"] = "medium"
    _merge_judge(
        record,
        deterministic_status="partially_relevant",
        outcome={
            "judgement": {**_valid_judgement("directly_relevant"), "confidence": "medium"},
            "provenance": {},
        },
    )
    assert record["final_status"] == "uncertain"


def test_pedagogy_judge_adapter_validates_evidence_and_retries_malformed():
    client = _Client([
        {"not": "a judgement"},
        _valid_judgement("directly_relevant"),
    ])
    adapter = PedagogyJudgeAdapter(client, max_retries=1)
    result = adapter.judge(
        "example_relevance",
        {"slide": 3, "example_text": "Example: core concept"},
        allowed_slides=[3],
        evidence_texts=["Example: core concept"],
    )

    assert result["judgement"]["status"] == "directly_relevant"
    assert result["provenance"]["retry_count"] == 1
    assert result["provenance"]["input_sha256"]
    assert result["provenance"]["prompt_sha256"]

    bad = PedagogyJudgeAdapter(_Client(["not-json"]), max_retries=0).judge(
        "example_relevance",
        {"slide": 3, "example_text": "Example: core concept"},
        allowed_slides=[3],
        evidence_texts=["Example: core concept"],
    )
    assert bad["judgement"]["status"] == "uncertain"
    assert bad["judgement"]["uncertainty"] in {"malformed_output", "api_error", "judge_failed"}

    mismatch = PedagogyJudgeAdapter(
        _Client([_valid_judgement("directly_relevant", slide=99, text="outside context")]),
        max_retries=0,
    ).judge(
        "example_relevance",
        {"slide": 3, "example_text": "Example: core concept"},
        allowed_slides=[3],
        evidence_texts=["Example: core concept"],
    )
    assert mismatch["judgement"]["status"] == "uncertain"
    assert mismatch["judgement"]["uncertainty"] == "evidence_mismatch"


def test_pedagogy_judge_adapter_persists_raw_call_evidence(tmp_path):
    adapter = PedagogyJudgeAdapter(
        _Client([{"not": "a judgement"}, _valid_judgement("directly_relevant")]),
        max_retries=1,
        output_root=tmp_path / "case" / "judge",
    )
    result = adapter.judge(
        "example_relevance",
        {"example_id": "example-1", "slide": 3, "example_text": "Example: core concept"},
        allowed_slides=[3],
        evidence_texts=["Example: core concept"],
    )

    raw_files = list((tmp_path / "case" / "judge").glob("example_relevance_*.json"))
    assert len(raw_files) == 1
    raw = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert raw["judge_type"] == "example_relevance"
    assert raw["raw_response"]
    assert raw["parsed_response"]["status"] == "directly_relevant"
    assert raw["retry_count"] == 1
    assert raw["attempt_count"] == 2
    assert raw["latency_ms"] >= 0
    assert raw["error"] is None
    assert result["provenance"]["raw_output_path"].replace("\\", "/").startswith("judge/")


def test_pedagogy_schema_rejects_illegal_item_status(tmp_path):
    result = evaluate_pedagogy(_context(tmp_path))
    result["details"]["example_relevance"]["items"] = [{"status": "not-a-valid-status"}]
    result = {key: value for key, value in result.items() if key != "_evidence"}
    try:
        validate_with_contract(
            {**result, "evaluator": "pedagogy"},
            "pedagogy_result.schema.json",
            contracts_dir=Path(__file__).resolve().parents[1] / "contracts",
        )
    except SchemaValidationError:
        return
    raise AssertionError("illegal pedagogy item status was accepted by schema")


def test_pedagogy_schema_requires_items_and_provenance(tmp_path):
    base = evaluate_pedagogy(_context(tmp_path))
    base = {key: value for key, value in base.items() if key != "_evidence"}
    base["evaluator"] = "pedagogy"
    missing_items = copy.deepcopy(base)
    del missing_items["details"]["example_relevance"]["items"]
    missing_provenance = copy.deepcopy(base)
    del missing_provenance["details"]["provenance"]

    for invalid in (missing_items, missing_provenance):
        try:
            validate_with_contract(
                invalid,
                "pedagogy_result.schema.json",
                contracts_dir=Path(__file__).resolve().parents[1] / "contracts",
            )
        except SchemaValidationError:
            continue
        raise AssertionError("pedagogy schema accepted a missing required field")


def test_candidate_assessment_is_separate_from_heldout_alignment():
    storyboard = {
        "segments": [
            {
                "id": 1,
                "knowledge_point_ids": ["c1"],
                "elements": [
                    {
                        "id": "quiz-1",
                        "type": "quiz_card",
                        "question": "What is the core concept?",
                        "answer": "The core concept.",
                    }
                ],
            }
        ]
    }
    annotation = {
        "core_concepts": [
            {
                "id": "c1",
                "statement": "Core concept",
                "must_mention_terms": ["core concept"],
                "evidence_paragraphs": ["p1"],
            }
        ]
    }
    result, issues = _evaluate_assessment(
        storyboard,
        annotation,
        {"c1": {"status": "covered"}},
        {"p1": "The core concept is explained."},
    )

    assert result["status"] == "ok"
    assert result["items"][0]["assessment_id"] == "quiz-1"
    assert result["items"][0]["status"] == "aligned"
    assert not issues
