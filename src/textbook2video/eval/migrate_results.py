"""Convert recovered VLM result files into the current judge result contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .report import write_json
from .schemas import validate_with_contract


def _contracts_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "contracts"


def _validate_and_write(path: Path, result: dict[str, Any]) -> Path:
    validate_with_contract(result, "judge_result.schema.json", contracts_dir=_contracts_dir())
    return write_json(path, result)


def normalize_videoqa_combined(
    source: str | Path,
    *,
    case_id: str,
    model: str,
    audience_prompt_version: str,
    reference_prompt_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_path = Path(source).resolve()
    pack = json.loads(source_path.read_text(encoding="utf-8"))
    lesson_id = str(pack.get("lesson") or pack.get("lesson_id") or "")
    if not lesson_id:
        raise ValueError(f"historical Video-QA result has no lesson id: {source_path}")
    answers = pack.get("answers", [])
    scores = pack.get("scores", [])
    if not isinstance(answers, list) or not isinstance(scores, list):
        raise ValueError("historical Video-QA answers and scores must be arrays")
    evidence_id = f"{case_id}-historical-videoqa"
    evidence = [
        {
            "evidence_id": evidence_id,
            "kind": "historical_videoqa_combined_result",
            "path": str(source_path),
        }
    ]
    base = {
        "schema_version": "textbookeval-judge-result-v0.1",
        "case_id": case_id,
        "lesson_id": lesson_id,
        "status": "ok",
        "passed": None,
        "model": model,
        "issues": [],
        "evidence_ids": [evidence_id],
        "evidence": evidence,
        "metadata": {
            "source_format": "vlm_videoqa_full_v1_combined",
            "system": pack.get("system"),
        },
    }
    audience = {
        **base,
        "result_type": "videoqa_audience",
        "evaluator": "videoqa_audience",
        "prompt_version": audience_prompt_version,
        "items": answers,
        "metrics": {
            "question_count": len(answers),
            "insufficient_evidence_count": sum(
                "证据不足" in str(item.get("answer_from_video", ""))
                for item in answers
                if isinstance(item, dict)
            ),
        },
        "raw_output": pack.get("raw_answer"),
    }
    numeric_scores = [
        float(item["score"])
        for item in scores
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float))
    ]
    reference_issues = [
        {
            "case_id": case_id,
            "stage": "eval",
            "evaluator": "videoqa_reference",
            "type": "VIDEOQA_LOW_SCORE",
            "severity": "major" if float(item["score"]) == 0 else "minor",
            "message": str(item.get("reason") or "Video-QA reference score is below 2"),
            "question_id": str(item.get("question_id")),
            "evidence_ids": [evidence_id],
            "review_status": "unreviewed",
        }
        for item in scores
        if isinstance(item, dict)
        and isinstance(item.get("score"), (int, float))
        and float(item["score"]) < 2
    ]
    reference = {
        **base,
        "result_type": "videoqa_reference",
        "evaluator": "videoqa_reference",
        "prompt_version": reference_prompt_version,
        "items": scores,
        "metrics": {
            "question_count": len(scores),
            "mean_score": (
                round(sum(numeric_scores) / len(numeric_scores), 6) if numeric_scores else None
            ),
            "low_score_count": len(reference_issues),
        },
        "issues": reference_issues,
        "raw_output": pack.get("raw_score"),
    }
    return audience, reference


def normalize_readability_frames(
    sources: Sequence[str | Path],
    *,
    case_id: str,
    lesson_id: str,
    system: str,
    model: str,
    prompt_version: str,
) -> dict[str, Any]:
    pairs = [
        (path, row)
        for path in (Path(source).resolve() for source in sources)
        for row in [json.loads(path.read_text(encoding="utf-8"))]
        if row.get("lesson_id") == lesson_id and row.get("system") == system
    ]
    if not pairs:
        raise ValueError(f"no readability rows matched {lesson_id}/{system}")
    paths = [path for path, _row in pairs]
    rows = [row for _path, row in pairs]
    evidence = [
        {
            "evidence_id": f"{case_id}-readability-frame-{index:03d}",
            "kind": "historical_readability_frame_result",
            "path": str(path),
            "frame": str(row.get("frame")) if row.get("frame") else None,
        }
        for index, (path, row) in enumerate(zip(paths, rows, strict=True), start=1)
    ]
    scores = [
        int(row["readability_score"])
        for row in rows
        if isinstance(row.get("readability_score"), int)
    ]
    issues = []
    for index, row in enumerate(rows, start=1):
        score = row.get("readability_score")
        if not isinstance(score, int) or score >= 2:
            continue
        issues.append(
            {
                "case_id": case_id,
                "stage": "eval",
                "evaluator": "vlm_readability",
                "type": "READABILITY_LOW_SCORE",
                "severity": "major" if score == 0 else "minor",
                "message": str(row.get("brief_observation") or f"readability score is {score}"),
                "evidence_ids": [evidence[index - 1]["evidence_id"]],
                "review_status": "unreviewed",
            }
        )
    return {
        "schema_version": "textbookeval-judge-result-v0.1",
        "result_type": "vlm_readability",
        "case_id": case_id,
        "lesson_id": lesson_id,
        "evaluator": "vlm_readability",
        "status": "ok",
        "passed": None,
        "model": model,
        "prompt_version": prompt_version,
        "items": rows,
        "metrics": {
            "frame_count": len(rows),
            "mean_readability_score": round(sum(scores) / len(scores), 6) if scores else None,
            "min_readability_score": min(scores) if scores else None,
            "low_score_frame_count": len(issues),
        },
        "issues": issues,
        "evidence_ids": [item["evidence_id"] for item in evidence],
        "evidence": evidence,
        "metadata": {"source_format": "vlm_readability_full_v1", "system": system},
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize recovered VLM evaluation results")
    commands = parser.add_subparsers(dest="command", required=True)
    videoqa = commands.add_parser("videoqa-combined")
    videoqa.add_argument("--input", required=True, type=Path)
    videoqa.add_argument("--out-dir", required=True, type=Path)
    videoqa.add_argument("--case-id", required=True)
    videoqa.add_argument("--model", required=True)
    videoqa.add_argument("--audience-prompt-version", required=True)
    videoqa.add_argument("--reference-prompt-version", required=True)
    readability = commands.add_parser("readability-frames")
    readability.add_argument("--input-dir", required=True, type=Path)
    readability.add_argument("--out", required=True, type=Path)
    readability.add_argument("--case-id", required=True)
    readability.add_argument("--lesson-id", required=True)
    readability.add_argument("--system", required=True)
    readability.add_argument("--model", required=True)
    readability.add_argument("--prompt-version", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "videoqa-combined":
        audience, reference = normalize_videoqa_combined(
            args.input,
            case_id=args.case_id,
            model=args.model,
            audience_prompt_version=args.audience_prompt_version,
            reference_prompt_version=args.reference_prompt_version,
        )
        _validate_and_write(args.out_dir / "videoqa_audience_result.json", audience)
        _validate_and_write(args.out_dir / "videoqa_reference_result.json", reference)
        return 0

    sources = sorted(args.input_dir.glob(f"{args.lesson_id}__{args.system}__*.json"))
    result = normalize_readability_frames(
        sources,
        case_id=args.case_id,
        lesson_id=args.lesson_id,
        system=args.system,
        model=args.model,
        prompt_version=args.prompt_version,
    )
    _validate_and_write(args.out, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
