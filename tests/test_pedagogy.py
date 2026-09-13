import json
from pathlib import Path

from textbook2video.eval.dataset import FileAsset
from textbook2video.eval.evaluators.pedagogy import (
    _candidate_repetition_pairs,
    evaluate_pedagogy,
    parse_pedagogy_judge,
)
from textbook2video.eval.runner import EvalContext, run_case


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


def test_objective_mapping_and_assessment_use_frozen_ids(tmp_path):
    result = evaluate_pedagogy(_context(tmp_path))

    objectives = result["details"]["learning_objective_coverage"]
    assessment = result["details"]["assessment_alignment"]
    assert objectives["summary"]["objective_source"] == "explicit"
    assert objectives["items"][0]["objective_id"] == "obj-1"
    assert objectives["items"][0]["matched_concepts"] == ["c1"]
    assert assessment["items"][0]["target_concepts"] == ["c1"]
    assert assessment["items"][0]["status"] == "aligned"


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
    }
    assert set(report["pedagogy"]["details"]) >= dimensions
    assert report["pedagogy"]["details"]["provenance"]["llm_judge_used"] is False
    assert (tmp_path / "lesson001" / "pedagogy_calibration.md").is_file()
    manifest = json.loads((tmp_path / "lesson001" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["evaluator_provenance"]["pedagogy"]["rule_version"] == "pedagogy-v0.1"
    assert report["status"] in {"pass", "pass_with_warnings", "failed"}
