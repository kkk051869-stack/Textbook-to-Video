import json
from pathlib import Path

import pytest

from textbook2video.eval.dataset import FileAsset
from textbook2video.eval.evaluators.content import evaluate_source_fidelity
from textbook2video.eval.evaluators.source_fidelity_judge import (
    SourceFidelityJudgeAdapter,
    evaluate_claim_level_source_fidelity,
    retrieve_source_evidence,
    validate_judge_evidence,
)
from textbook2video.eval.runner import EvalContext, run_case
from textbook2video.eval.schemas import validate_with_contract


class _Case:
    case_id = "case_sf_v2"
    lesson_id = "lesson_sf_v2"
    dataset_version = "dataset-test"

    def __init__(self, root: Path):
        self.root = root
        self.manifest_path = root / "case_manifest.json"
        self.raw = {"case_id": self.case_id, "lesson_id": self.lesson_id}

    def assets(self):
        return [
            FileAsset("source_json", "source.json", ""),
            FileAsset("annotation", "annotation.json", ""),
        ]

    def resolve_asset(self, asset):
        return self.root / asset.path


class _Client:
    model = "fake-source-judge"
    model_version = "fake-source-judge-v1"

    def __init__(self, extraction, classification=None):
        self.extraction = extraction
        self.classification = classification or {
            "status": "SUPPORTED",
            "confidence": "high",
            "evidence": [{"paragraph_id": "p1", "quote": "The sun is a star."}],
            "reason": "The source states the same fact.",
            "uncertainty": "",
        }

    def chat(self, messages, *, max_tokens):
        payload = json.loads(messages[0]["content"].split("INPUT (JSON):", 1)[1])
        response = self.classification if "source_evidence" in payload else self.extraction
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(payload)
        return response, json.dumps(response, ensure_ascii=False)


def _context(tmp_path: Path, candidate_text: str = "The sun is a star."):
    source = {"paragraphs": [{"id": "p1", "text": "The sun is a star."}]}
    annotation = {
        "core_concepts": [
            {"id": "c1", "evidence_paragraphs": ["p1"], "must_mention_terms": ["sun"]}
        ],
        "required_images": [],
    }
    storyboard = {"segments": [{"id": 1, "narration": candidate_text, "elements": []}]}
    source_path = tmp_path / "source.json"
    annotation_path = tmp_path / "annotation.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    return (
        EvalContext(
            case=_Case(tmp_path),
            run_id="source-fidelity-v2-test",
            artifacts_root=tmp_path,
            output_root=tmp_path / "out",
        ),
        source,
        annotation,
        storyboard,
        source_path,
        annotation_path,
    )


def _evaluate(tmp_path, candidate_text, client=None):
    context, source, annotation, storyboard, source_path, annotation_path = _context(
        tmp_path, candidate_text
    )
    if client is not None:
        context = EvalContext(
            **{**context.__dict__, "source_fidelity_judge": SourceFidelityJudgeAdapter(client)}
        )
    return evaluate_claim_level_source_fidelity(
        context,
        source=source,
        annotation=annotation,
        storyboard=storyboard,
        script_text=candidate_text,
        script_path=None,
        source_path=source_path,
        annotation_path=annotation_path,
    )


def test_one_sentence_one_claim_is_deterministically_segmented(tmp_path):
    result = _evaluate(tmp_path, "The sun is a star.")

    assert result["details"]["claim_extraction"]["unit_count"] == 1
    assert result["metrics"]["claim_count"] == 1
    assert result["metrics"]["factual_claim_count"] == 1
    assert result["metrics"]["evaluable_factual_claim_count"] == 0
    assert result["metrics"]["source_supported_rate"] is None
    assert result["details"]["claims"][0]["candidate_text"] == "The sun is a star."


def test_script_segment_markers_are_not_claims(tmp_path):
    result = _evaluate(tmp_path, "Segment 1:\nThe sun is a star.")

    assert result["metrics"]["claim_count"] == 1
    assert all("Segment 1:" not in item["candidate_text"] for item in result["details"]["claims"])


def test_one_sentence_two_atomic_claims_are_kept_separate(tmp_path):
    sentence = "The sun is a star, and the sun is bright."
    client = _Client(
        {
            "claims": [
                {
                    "candidate_text": "The sun is a star",
                    "claim_type": "FACTUAL",
                    "character_span": [0, 18],
                },
                {
                    "candidate_text": "the sun is bright",
                    "claim_type": "FACTUAL",
                    "character_span": [24, 41],
                },
            ]
        }
    )
    result = _evaluate(tmp_path, sentence, client)

    assert result["metrics"]["claim_count"] == 2
    assert [item["final_status"] for item in result["details"]["claims"]] == [
        "SUPPORTED",
        "SUPPORTED",
    ]


def test_instruction_is_non_factual_and_out_of_denominator(tmp_path):
    result = _evaluate(tmp_path, "Please observe the chart.")

    claim = result["details"]["claims"][0]
    assert claim["claim_type"] == "PEDAGOGICAL_INSTRUCTION"
    assert claim["final_status"] == "NON_FACTUAL"
    assert result["metrics"]["factual_claim_count"] == 0


def test_malformed_extraction_fails_closed(tmp_path):
    result = _evaluate(tmp_path, "The sun is a star.", _Client("not-json"))

    claim = result["details"]["claims"][0]
    assert claim["final_status"] == "UNCERTAIN"
    assert any(issue["type"] == "SOURCE_CLAIM_EXTRACTION_FAILED" for issue in result["issues"])


def test_empty_extraction_retains_unit_for_semantic_judge(tmp_path):
    result = _evaluate(tmp_path, "The sun is a star.", _Client({"claims": []}))

    claim = result["details"]["claims"][0]
    assert claim["candidate_text"] == "The sun is a star."
    assert claim["final_status"] == "SUPPORTED"
    assert claim["extraction_warning"] == "judge returned no claims; deterministic unit retained"
    assert any(issue["type"] == "SOURCE_CLAIM_EXTRACTION_EMPTY" for issue in result["issues"])


def test_extracted_claim_absent_from_candidate_is_rejected(tmp_path):
    client = _Client({"claims": [{"candidate_text": "Mars is red", "claim_type": "FACTUAL"}]})
    result = _evaluate(tmp_path, "The sun is a star.", client)

    assert all(item["candidate_text"] != "Mars is red" for item in result["details"]["claims"])
    assert any(issue["type"] == "SOURCE_CLAIM_EXTRACTION_FAILED" for issue in result["issues"])


@pytest.mark.parametrize(
    "status",
    sorted(
        {
            "SUPPORTED",
            "INFERABLE",
            "EXTERNAL_CORRECT",
            "UNSUPPORTED",
            "INCORRECT",
            "CONTRADICTS_SOURCE",
            "UNCERTAIN",
        }
    ),
)
def test_classification_statuses_are_preserved(tmp_path, status):
    client = _Client(
        {"claims": [{"candidate_text": "The sun is a star", "claim_type": "FACTUAL"}]},
        {
            "status": status,
            "confidence": "medium",
            "evidence": [{"paragraph_id": "p1", "quote": "The sun is a star."}],
            "reason": f"fixture status {status}",
            "uncertainty": "" if status != "UNCERTAIN" else "not enough context",
        },
    )
    result = _evaluate(tmp_path, "The sun is a star.", client)

    assert result["details"]["claims"][0]["final_status"] == status
    assert result["details"]["claims"][0]["judge_status"] == status


@pytest.mark.parametrize(
    "evidence",
    [
        [{"paragraph_id": "missing", "quote": "The sun is a star."}],
        [{"paragraph_id": "p1", "quote": "The moon is a star."}],
        [{"paragraph_id": "p2", "quote": "The sun is a star."}],
    ],
)
def test_missing_or_fabricated_evidence_becomes_uncertain(tmp_path, evidence):
    client = _Client(
        {"claims": [{"candidate_text": "The sun is a star", "claim_type": "FACTUAL"}]},
        {
            "status": "SUPPORTED",
            "confidence": "high",
            "evidence": evidence,
            "reason": "fixture evidence",
            "uncertainty": "",
        },
    )
    result = _evaluate(tmp_path, "The sun is a star.", client)

    assert result["details"]["claims"][0]["final_status"] == "UNCERTAIN"
    assert any(issue["type"] == "SOURCE_EVIDENCE_MISMATCH" for issue in result["issues"])


def test_heuristic_is_not_used_as_semantic_judgement(tmp_path):
    client = _Client(
        {"claims": [{"candidate_text": "The sun is a star", "claim_type": "FACTUAL"}]},
        {
            "status": "UNSUPPORTED",
            "confidence": "high",
            "evidence": [{"paragraph_id": "p1", "quote": "The sun is a star."}],
            "reason": "fixture semantic result",
            "uncertainty": "",
        },
    )
    result = _evaluate(tmp_path, "The sun is a star.", client)
    claim = result["details"]["claims"][0]

    assert claim["heuristic_status"] == "possible_supported"
    assert claim["final_status"] == "UNSUPPORTED"


def test_model_error_is_uncertain_and_provenance_is_retained(tmp_path):
    result = _evaluate(tmp_path, "The sun is a star.", _Client(RuntimeError("offline")))
    claim = result["details"]["claims"][0]
    calls = result["details"]["judge_calls"]

    assert claim["final_status"] == "UNCERTAIN"
    assert calls[0]["provider"] == "_Client"
    assert calls[0]["raw_response"] is None
    assert calls[0]["input_sha256"]


def test_evidence_retrieval_and_validation_are_fail_closed():
    source = {"p1": "The sun is a star."}
    retrieved = retrieve_source_evidence(
        "The sun is a star", source_paragraphs=source, annotation={}
    )
    assert retrieved[0]["paragraph_id"] == "p1"
    assert (
        validate_judge_evidence([{"paragraph_id": "p1", "quote": "The sun is a star."}], source)[1]
        is None
    )
    assert validate_judge_evidence(
        [{"paragraph_id": "p1", "quote": "The moon is a star."}], source
    )[1]


def test_runner_without_judge_keeps_v01_and_adds_v02_details(tmp_path):
    context, source, annotation, storyboard, source_path, annotation_path = _context(tmp_path)
    (tmp_path / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
    report = run_case(
        context.case,
        run_id="source-fidelity-v2-runner-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "runner-out",
        evaluators=[evaluate_source_fidelity],
        repo_root=Path(__file__).resolve().parents[1],
    )

    source_result = report["source_fidelity"]
    assert "evidence_coverage" in source_result["metrics"]
    assert source_result["details"]["claim_level_v2"]["semantic_status"] == "unavailable"
    assert (tmp_path / "runner-out" / "source_fidelity_calibration.md").is_file()
    for claim in source_result["details"]["claim_level_v2"]["claims"]:
        validate_with_contract(
            claim,
            "source_fidelity_claim.schema.json",
            contracts_dir=Path(__file__).resolve().parents[1] / "contracts",
        )


def test_runner_with_judge_records_v02_provenance(tmp_path):
    context, source, annotation, storyboard, source_path, annotation_path = _context(tmp_path)
    (tmp_path / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
    client = _Client({"claims": [{"candidate_text": "The sun is a star", "claim_type": "FACTUAL"}]})
    report = run_case(
        context.case,
        run_id="source-fidelity-v2-judge-runner-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "runner-out",
        evaluators=[evaluate_source_fidelity],
        repo_root=Path(__file__).resolve().parents[1],
        source_fidelity_judge=SourceFidelityJudgeAdapter(client),
    )

    details = report["source_fidelity"]["details"]["claim_level_v2"]
    provenance = json.loads(
        (tmp_path / "runner-out" / "run_manifest.json").read_text(encoding="utf-8")
    )["metadata"]["evaluator_provenance"]["source_fidelity"]
    assert details["semantic_status"] == "ok"
    assert details["claims"][0]["final_status"] == "SUPPORTED"
    assert provenance["judge_calls"]
    assert provenance["judge_calls"][0]["prompt_version"] == "claim_extraction_v1"
