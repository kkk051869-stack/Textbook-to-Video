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


def _text_judge_required(context: EvalContext) -> bool:
    """Read an explicit requirement without changing the frozen manifest."""
    raw = context.case.raw if isinstance(context.case.raw, dict) else {}
    for section_name in ("evaluation", "eval_config", "evaluators"):
        section = raw.get(section_name)
        if not isinstance(section, dict):
            continue
        config = section.get("text_judge")
        if isinstance(config, dict) and isinstance(config.get("required"), bool):
            return config["required"]
    return False


def _evaluate_result(
    context: EvalContext,
    *,
    evaluator: str,
    result_type: str,
    artifact_role: str,
) -> dict:
    path = context.artifact(artifact_role)
    if path is None or not path.is_file():
        result = unavailable(context, evaluator, f"baseline_artifacts.{artifact_role} is missing")
        required = _text_judge_required(context) if evaluator == "text_judge" else True
        result["details"] = {
            "required": required,
            "artifact_role": artifact_role,
            "reason": "required evaluator input is unavailable" if required else "optional evaluator input is unavailable",
        }
        if evaluator == "text_judge" and not required:
            for issue in result["issues"]:
                issue.update(
                    {
                        "type": "OPTIONAL_EVALUATOR_UNAVAILABLE",
                        "severity": "minor",
                        "message": "optional text judge result is unavailable",
                        "metadata": {"required": False, "artifact_role": artifact_role},
                    }
                )
        return result

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
    heldout_ids: list[str] = []
    if result_type.startswith("videoqa_"):
        assets = context.case.assets() if hasattr(context.case, "assets") else []
        for asset in assets:
            if asset.role == "heldout_questions":
                heldout = load_json_object(context.case.resolve_asset(asset))
                heldout_ids = [
                    str(item.get("id") or item.get("question_id"))
                    for item in heldout.get("questions", [])
                    if isinstance(item, dict) and (item.get("id") or item.get("question_id"))
                ]
                break
    items = []
    for item in result["items"]:
        normalized = dict(item)
        if result_type == "videoqa_audience":
            normalized.setdefault("model_answer", normalized.get("answer_from_video"))
            normalized.setdefault(
                "evidence_from_video_or_transcript",
                normalized.get("evidence_text") or normalized.get("evidence_frames", []),
            )
            normalized.setdefault("failure_reason", normalized.get("failure_reason"))
        elif result_type == "videoqa_reference":
            score = normalized.get("score")
            normalized.setdefault(
                "correctness",
                "correct" if score == 2 else "partial" if score == 1 else "incorrect" if score == 0 else None,
            )
        items.append(normalized)
    item_ids = {str(item.get("question_id")) for item in items if item.get("question_id")}
    issues = []
    for raw_issue in result["issues"]:
        issue = dict(raw_issue)
        issue["evidence_ids"] = list(
            dict.fromkeys([*issue.get("evidence_ids", []), result_evidence_id])
        )
        issues.append(issue)
    missing_ids = [question_id for question_id in heldout_ids if question_id not in item_ids]
    for question_id in missing_ids:
        issues.append(
            {
                "case_id": context.case.case_id,
                "stage": "eval",
                "evaluator": evaluator,
                "type": "VIDEOQA_UNANSWERED",
                "severity": "major",
                "message": f"held-out question {question_id} has no model result",
                "question_id": question_id,
                "evidence_ids": [result_evidence_id],
                "review_status": "unreviewed",
            }
        )
    metrics = dict(result["metrics"])
    if result_type == "videoqa_audience":
        answered_count = sum(bool(item.get("model_answer") or item.get("answer_from_video")) for item in items)
        metrics.update(
            {
                "question_count": len(heldout_ids) or metrics.get("question_count", len(items)),
                "answered_count": answered_count,
                "unanswered_count": len(missing_ids),
            }
        )
    if result_type == "videoqa_reference":
        scores = [item.get("score") for item in items if item.get("score") in {0, 1, 2}]
        metrics.update(
            {
                "question_count": len(heldout_ids) or metrics.get("question_count", len(items)),
                "correct_count": sum(score == 2 for score in scores),
                "partial_count": sum(score == 1 for score in scores),
                "incorrect_count": sum(score == 0 for score in scores),
                "unanswered_count": len(missing_ids),
            }
        )
    return {
        "status": result["status"],
        "passed": result.get("passed"),
        "metrics": metrics,
        "details": {
            "result_type": result_type,
            "model": result["model"],
            "prompt_version": result["prompt_version"],
            "config": result.get("config", {}),
            "items": items,
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
