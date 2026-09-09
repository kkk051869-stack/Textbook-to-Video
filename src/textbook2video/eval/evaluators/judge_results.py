"""Adapters for normalized text/VLM judge result artifacts.

Model execution stays outside this module.  A cloud script writes one validated
result file; the runner can then preserve and aggregate it without importing a
model runtime or depending on a live service.
"""

from __future__ import annotations

from pathlib import Path

from ..runner import EvalContext
from ..schemas import load_json_object, validate_with_contract
from .common import evidence_for, unavailable


def _contracts_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "contracts"


def _evaluate_result(
    context: EvalContext,
    *,
    evaluator: str,
    result_type: str,
    artifact_role: str,
) -> dict:
    path = context.artifact(artifact_role)
    if path is None or not path.is_file():
        return unavailable(context, evaluator, f"baseline_artifacts.{artifact_role} is missing")

    result = load_json_object(path)
    validate_with_contract(result, "judge_result.schema.json", contracts_dir=_contracts_dir())
    if result["case_id"] != context.case.case_id:
        raise ValueError(
            f"judge result case_id {result['case_id']!r} does not match {context.case.case_id!r}"
        )
    if result["result_type"] != result_type or result["evaluator"] != evaluator:
        raise ValueError(
            f"expected {result_type}/{evaluator}, got "
            f"{result['result_type']}/{result['evaluator']}"
        )

    result_evidence_id = f"{context.case.case_id}-{evaluator}-result"
    evidence = list(result.get("evidence", []))
    evidence.append(evidence_for(path, evidence_id=result_evidence_id, kind="judge_result"))
    evidence_ids = list(dict.fromkeys([*result["evidence_ids"], result_evidence_id]))
    issues = []
    for raw_issue in result["issues"]:
        issue = dict(raw_issue)
        if not issue.get("evidence_ids"):
            issue["evidence_ids"] = [result_evidence_id]
        issues.append(issue)
    return {
        "status": result["status"],
        "passed": result.get("passed"),
        "metrics": result["metrics"],
        "details": {
            "result_type": result_type,
            "model": result["model"],
            "prompt_version": result["prompt_version"],
            "config": result.get("config", {}),
            "items": result["items"],
            "metadata": result.get("metadata", {}),
        },
        "issues": issues,
        "evidence_ids": evidence_ids,
        "_evidence": evidence,
    }


def evaluate_text_judge(context: EvalContext) -> dict:
    return _evaluate_result(
        context,
        evaluator="text_judge",
        result_type="text_judge",
        artifact_role="text_judge_result",
    )


def evaluate_vlm_readability(context: EvalContext) -> dict:
    return _evaluate_result(
        context,
        evaluator="vlm_readability",
        result_type="vlm_readability",
        artifact_role="vlm_readability_result",
    )


def evaluate_videoqa_audience(context: EvalContext) -> dict:
    return _evaluate_result(
        context,
        evaluator="videoqa_audience",
        result_type="videoqa_audience",
        artifact_role="videoqa_audience_result",
    )


def evaluate_videoqa_reference(context: EvalContext) -> dict:
    return _evaluate_result(
        context,
        evaluator="videoqa_reference",
        result_type="videoqa_reference",
        artifact_role="videoqa_reference_result",
    )


evaluate_text_judge.evaluator_name = "text_judge"
evaluate_vlm_readability.evaluator_name = "vlm_readability"
evaluate_videoqa_audience.evaluator_name = "videoqa_audience"
evaluate_videoqa_reference.evaluator_name = "videoqa_reference"
