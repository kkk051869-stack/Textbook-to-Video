"""Run one parameterized model evaluator and emit a normalized Judge Result."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Protocol, Sequence

from .model_client import OpenAICompatibleClient
from .report import write_json
from .schemas import validate_with_contract


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, Any]], *, max_tokens: int) -> tuple[Any, str]: ...


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _questions(path: Path) -> list[dict[str, Any]]:
    value = _load_json(path)
    if isinstance(value, list):
        return value
    for key in ("questions", "heldout_questions"):
        if isinstance(value, dict) and isinstance(value.get(key), list):
            return value[key]
    raise ValueError(f"{path} must contain a questions or heldout_questions array")


def _question_id(item: dict[str, Any], index: int) -> str:
    return str(item.get("question_id") or item.get("id") or f"q{index:03d}")


def _public_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove all reference-only fields before the Audience request is built."""
    public = []
    for index, item in enumerate(items, start=1):
        public.append(
            {
                "question_id": _question_id(item, index),
                "question": item.get("question", ""),
                "type": item.get("type"),
            }
        )
    return public


def _image_part(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def _write_raw(out: Path, name: str, raw: str) -> Path:
    path = out.parent / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return path


def _base_result(
    *, case_id: str, lesson_id: str, evaluator: str, client: ChatClient, prompt_version: str
) -> dict[str, Any]:
    return {
        "schema_version": "textbookeval-judge-result-v0.1",
        "result_type": evaluator,
        "case_id": case_id,
        "lesson_id": lesson_id,
        "evaluator": evaluator,
        "status": "ok",
        "passed": None,
        "model": client.model,
        "prompt_version": prompt_version,
        "config": {},
        "items": [],
        "metrics": {},
        "issues": [],
        "evidence_ids": [],
        "evidence": [],
        "metadata": {},
    }


def _finalize(result: dict[str, Any], out: Path) -> dict[str, Any]:
    validate_with_contract(
        result,
        "judge_result.schema.json",
        contracts_dir=Path(__file__).resolve().parents[3] / "contracts",
    )
    write_json(out, result)
    return result


def run_text_judge(
    *,
    case_id: str,
    lesson_id: str,
    annotation: Path,
    generated_text: Path,
    out: Path,
    client: ChatClient,
    prompt_version: str,
) -> dict[str, Any]:
    annotation_value = _load_json(annotation)
    video_text = generated_text.read_text(encoding="utf-8", errors="replace")
    prompt = json.dumps(
        {
            "task": "Judge coverage and correctness using only GENERATED_VIDEO_TEXT.",
            "score_scale": {"0": "missing or wrong", "1": "partial", "2": "accurate"},
            "output": {"items": [{"item_id": "string", "score": "0|1|2", "reason": "string"}]},
            "annotation": annotation_value,
            "GENERATED_VIDEO_TEXT": video_text,
        },
        ensure_ascii=False,
    )
    parsed, raw = client.chat([{"role": "user", "content": prompt}], max_tokens=1800)
    items = parsed.get("items", []) if isinstance(parsed, dict) else []
    raw_path = _write_raw(out, "text_judge.txt", raw)
    result = _base_result(
        case_id=case_id,
        lesson_id=lesson_id,
        evaluator="text_judge",
        client=client,
        prompt_version=prompt_version,
    )
    result["items"] = items
    scores = [int(item["score"]) for item in items if str(item.get("score", "")).isdigit()]
    result["metrics"] = {
        "item_count": len(items),
        "mean_score": round(sum(scores) / len(scores), 6) if scores else None,
    }
    result["raw_output"] = str(raw_path.relative_to(out.parent))
    result["metadata"] = {
        "annotation_sha256": hashlib.sha256(annotation.read_bytes()).hexdigest(),
        "generated_text_sha256": hashlib.sha256(generated_text.read_bytes()).hexdigest(),
    }
    return _finalize(result, out)


def run_readability(
    *,
    case_id: str,
    lesson_id: str,
    frames: Sequence[Path],
    out: Path,
    client: ChatClient,
    prompt_version: str,
    low_score_threshold: int = 1,
) -> dict[str, Any]:
    result = _base_result(
        case_id=case_id,
        lesson_id=lesson_id,
        evaluator="vlm_readability",
        client=client,
        prompt_version=prompt_version,
    )
    scores: list[int] = []
    for index, frame in enumerate(frames, start=1):
        prompt = (
            "只根据截图判断教学视频文字可读性。返回严格 JSON："
            '{"readability_score":0或1或2,"has_garbled_text":false,'
            '"has_box_glyphs":false,"too_dense":false,"clipped_text":false,'
            '"brief_observation":"一句中文说明"}。2=清楚；1=部分可读；0=不可读。'
        )
        parsed, raw = client.chat(
            [{"role": "user", "content": [{"type": "text", "text": prompt}, _image_part(frame)]}],
            max_tokens=320,
        )
        raw_path = _write_raw(out, f"readability-{index:03d}.txt", raw)
        score = int(parsed["readability_score"])
        scores.append(score)
        evidence_id = f"{case_id}-readability-frame-{index:03d}"
        item = {"frame": frame.name, **parsed, "evidence_id": evidence_id}
        result["items"].append(item)
        result["evidence"].append(
            {
                "evidence_id": evidence_id,
                "kind": "video_frame",
                "path": str(frame),
                "frame": frame.name,
            }
        )
        result["evidence"].append(
            {
                "evidence_id": f"{evidence_id}-raw",
                "kind": "model_raw_output",
                "path": str(raw_path.relative_to(out.parent)),
                "frame": frame.name,
            }
        )
        result["evidence_ids"].append(evidence_id)
        if score <= low_score_threshold:
            result["issues"].append(
                {
                    "case_id": case_id,
                    "stage": "eval",
                    "evaluator": "vlm_readability",
                    "type": "READABILITY_LOW_SCORE",
                    "severity": "major",
                    "message": str(
                        parsed.get("brief_observation") or f"readability score is {score}"
                    ),
                    "evidence_ids": [evidence_id],
                    "review_status": "unreviewed",
                }
            )
    result["metrics"] = {
        "frame_count": len(frames),
        "mean_readability_score": round(sum(scores) / len(scores), 6) if scores else None,
        "min_readability_score": min(scores) if scores else None,
        "low_score_frame_count": sum(score <= low_score_threshold for score in scores),
    }
    return _finalize(result, out)


def run_videoqa_audience(
    *,
    case_id: str,
    lesson_id: str,
    questions: Path,
    frames: Sequence[Path],
    transcript: Path,
    out: Path,
    client: ChatClient,
    prompt_version: str,
) -> dict[str, Any]:
    public_questions = _public_questions(_questions(questions))
    prompt = json.dumps(
        {
            "task": "仅根据视频关键帧和视频文本回答问题，不使用教材或外部知识。",
            "input_mode": "keyframes_plus_transcript",
            "questions": public_questions,
            "video_text": transcript.read_text(encoding="utf-8", errors="replace"),
            "output": {
                "answers": [
                    {"question_id": "string", "answer_from_video": "string", "confidence": "0-100"}
                ]
            },
        },
        ensure_ascii=False,
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    content.extend(_image_part(frame) for frame in frames)
    parsed, raw = client.chat([{"role": "user", "content": content}], max_tokens=1400)
    items = parsed.get("answers", []) if isinstance(parsed, dict) else []
    raw_path = _write_raw(out, "videoqa_audience.txt", raw)
    result = _base_result(
        case_id=case_id,
        lesson_id=lesson_id,
        evaluator="videoqa_audience",
        client=client,
        prompt_version=prompt_version,
    )
    result["items"] = items
    result["metrics"] = {"question_count": len(public_questions), "answered_count": len(items)}
    result["raw_output"] = str(raw_path.relative_to(out.parent))
    result["config"] = {"input_mode": "keyframes_plus_transcript", "frame_count": len(frames)}
    return _finalize(result, out)


def run_videoqa_reference(
    *,
    case_id: str,
    lesson_id: str,
    questions: Path,
    audience_result: Path,
    out: Path,
    client: ChatClient,
    prompt_version: str,
    low_score_threshold: int = 1,
) -> dict[str, Any]:
    references = _questions(questions)
    audience = _load_json(audience_result)
    prompt = json.dumps(
        {
            "task": "依据标准答案严格评分视频回答。",
            "score_scale": {"0": "wrong", "1": "partial", "2": "correct"},
            "reference_questions": references,
            "audience_answers": audience.get("items", []),
            "output": {"scores": [{"question_id": "string", "score": "0|1|2", "reason": "string"}]},
        },
        ensure_ascii=False,
    )
    parsed, raw = client.chat([{"role": "user", "content": prompt}], max_tokens=1200)
    items = parsed.get("scores", []) if isinstance(parsed, dict) else []
    raw_path = _write_raw(out, "videoqa_reference.txt", raw)
    result = _base_result(
        case_id=case_id,
        lesson_id=lesson_id,
        evaluator="videoqa_reference",
        client=client,
        prompt_version=prompt_version,
    )
    result["items"] = items
    scores = [int(item["score"]) for item in items if str(item.get("score", "")).isdigit()]
    result["metrics"] = {
        "scored_count": len(scores),
        "mean_score": round(sum(scores) / len(scores), 6) if scores else None,
        "low_score_count": sum(score <= low_score_threshold for score in scores),
    }
    result["raw_output"] = str(raw_path.relative_to(out.parent))
    for item in items:
        score = int(item["score"])
        if score <= low_score_threshold:
            result["issues"].append(
                {
                    "case_id": case_id,
                    "stage": "eval",
                    "evaluator": "videoqa_reference",
                    "type": "VIDEOQA_LOW_SCORE",
                    "severity": "major",
                    "message": str(item.get("reason") or f"Video-QA score is {score}"),
                    "question_id": str(item.get("question_id")),
                    "review_status": "unreviewed",
                    "evidence_ids": [],
                }
            )
    return _finalize(result, out)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--lesson-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--timeout", type=int, default=600)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a parameterized TextbookEval model judge")
    commands = parser.add_subparsers(dest="evaluator", required=True)
    text = commands.add_parser("text-judge")
    readability = commands.add_parser("readability")
    audience = commands.add_parser("videoqa-audience")
    reference = commands.add_parser("videoqa-reference")
    for command in (text, readability, audience, reference):
        _add_common(command)
    text.add_argument("--annotation", required=True, type=Path)
    text.add_argument("--generated-text", required=True, type=Path)
    readability.add_argument("--frames", required=True, type=Path)
    audience.add_argument("--questions", required=True, type=Path)
    audience.add_argument("--frames", required=True, type=Path)
    audience.add_argument("--transcript", required=True, type=Path)
    reference.add_argument("--questions", required=True, type=Path)
    reference.add_argument("--audience-result", required=True, type=Path)
    return parser.parse_args(argv)


def _discover_frames(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    client = OpenAICompatibleClient(
        api_base=args.api_base,
        model=args.model,
        timeout=args.timeout,
        api_key=os.getenv("OPENAI_API_KEY"),
    )
    common = dict(
        case_id=args.case_id,
        lesson_id=args.lesson_id,
        out=args.out,
        client=client,
        prompt_version=args.prompt_version,
    )
    if args.evaluator == "text-judge":
        run_text_judge(annotation=args.annotation, generated_text=args.generated_text, **common)
    elif args.evaluator == "readability":
        run_readability(frames=_discover_frames(args.frames), **common)
    elif args.evaluator == "videoqa-audience":
        run_videoqa_audience(
            questions=args.questions,
            frames=_discover_frames(args.frames),
            transcript=args.transcript,
            **common,
        )
    else:
        run_videoqa_reference(
            questions=args.questions, audience_result=args.audience_result, **common
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
