from __future__ import annotations

import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


EXP_ROOT = Path("/ai/data/textbook-to-video/experiments/presentagent-comparison-v1")
INPUT_ROOT = EXP_ROOT / "metrics/vlm/judge_inputs/lesson_001"
OUTPUT_ROOT = EXP_ROOT / "metrics/vlm/judge_outputs/trial_lesson_001"
API_BASE = "http://127.0.0.1:8000/v1"
MODEL = "qwen3-32b-awq"
PROMPT_VERSION = "judge_text_evidence_v2"
JUDGE_RUN_ID = "trial_lesson_001_text_qwen32b_v2"
GENERATED_TEXT_LIMIT = 5200
TASK_MAX_TOKENS = {"core": 1500, "qa": 1400, "visual_quality": 1400}


class ParseError(RuntimeError):
    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_text(path: Path, limit: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit and len(text) > limit:
        return text[:limit] + "\n\n[TRUNCATED]"
    return text


def compact_annotation(annotation: dict) -> dict:
    return {
        "lesson_id": annotation.get("lesson_id"),
        "core_concepts": [
            {
                "id": item.get("id"),
                "statement": item.get("statement"),
                "importance": item.get("importance"),
                "evidence_paragraphs": item.get("evidence_paragraphs", []),
                "must_mention_terms": item.get("must_mention_terms", []),
            }
            for item in annotation.get("core_concepts", [])
        ],
        "heldout_questions": [
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "question": item.get("question"),
                "expected_answer": item.get("answer"),
                "evidence_paragraphs": item.get("evidence_paragraphs", []),
                "targets": item.get("targets", []),
                "scoring": item.get("scoring"),
            }
            for item in annotation.get("heldout_questions", [])
        ],
        "required_images": [
            {
                "image_id": item.get("image_id"),
                "necessity": item.get("necessity"),
                "filename": item.get("filename"),
                "caption": item.get("caption"),
                "expected_use": item.get("expected_use"),
            }
            for item in annotation.get("required_images", [])
        ],
        "misconceptions": annotation.get("misconceptions", []),
        "video_scoring_focus": annotation.get("video_scoring_focus", []),
    }


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
        return json.loads(candidate)
    raise ValueError("No JSON object found in model output")


def call_llm(prompt: str, timeout: int = 600, max_tokens: int = 1800) -> tuple[dict, str]:
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an automatic evaluator for textbook-to-video outputs. "
                    "Only score from GENERATED_VIDEO_TEXT, annotation, and metadata supplied by the user. "
                    "Do not use outside knowledge to fill missing video content. "
                    "Return strict compact JSON only, with no markdown and no explanation."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:1000]}") from exc

    raw = body["choices"][0]["message"]["content"]
    try:
        return extract_json(raw), raw
    except (ValueError, json.JSONDecodeError) as exc:
        raise ParseError(repr(exc), raw) from exc


def make_prompt(bundle: dict, annotation: dict, generated_text: str, task: str) -> str:
    if task == "core":
        required_output_schema = {
            "core_concepts": [
                {
                    "concept_id": "string",
                    "score": "0|1|2",
                    "confidence": "0.0-1.0",
                    "evidence_in_video": "short quote",
                    "problem_type": "none|missing|partial|wrong|hallucinated",
                    "reasoning_summary": "short Chinese summary",
                }
            ]
        }
        ann = {"core_concepts": annotation["core_concepts"]}
        limits = [
            "Score only core_concepts.",
            "Score by whether GENERATED_VIDEO_TEXT accurately covers the concept statement and must_mention_terms.",
            "Do not output heldout_questions, image_scores, video_quality, or errors.",
        ]
    elif task == "qa":
        required_output_schema = {
            "heldout_questions": [
                {
                    "question_id": "string",
                    "answer_from_video": "answer derivable from generated text",
                    "score": "0|1|2",
                    "reasoning_summary": "short Chinese summary",
                }
            ]
        }
        ann = {"heldout_questions": annotation["heldout_questions"]}
        limits = [
            "Score only heldout_questions.",
            "Score by whether expected_answer can be derived from GENERATED_VIDEO_TEXT.",
            "Do not output core_concepts, image_scores, video_quality, or errors.",
        ]
    elif task == "visual_quality":
        required_output_schema = {
            "image_scores": [
                {
                    "image_requirement_id": "string",
                    "score": "0|1|2",
                    "confidence": "0.0-1.0",
                    "visual_issue": "none|missing|cropped|unreadable|mismatched|hallucinated",
                    "evidence_in_video": "text evidence or no visual evidence",
                    "reasoning_summary": "short Chinese summary",
                }
            ],
            "video_quality": {
                "readability": "0|1|2",
                "layout": "0|1|2",
                "audio_visual_sync": "0|1|2",
                "pacing": "0|1|2",
                "teaching_structure": "0|1|2",
                "overall_quality": "number 0-2",
                "reasoning_summary": "short Chinese summary",
            },
            "errors": [
                {
                    "severity": "minor|major|critical",
                    "error_type": "factual_error|hallucination|missing_key_content|unreadable_text|wrong_image|audio_issue|crash|other",
                    "source_evidence": "annotation id or source evidence",
                    "video_evidence": "generated text evidence",
                    "reasoning_summary": "short Chinese summary",
                    "timestamp": "",
                }
            ],
        }
        ann = {
            "required_images": annotation["required_images"],
            "misconceptions": annotation.get("misconceptions", []),
            "video_scoring_focus": annotation.get("video_scoring_focus", []),
        }
        limits = [
            "This is a text-evidence trial, not a true VLM visual review.",
            "For image_scores, judge only from GENERATED_VIDEO_TEXT/storyboard mentions of images or image-bearing content. If there is no visual evidence, confidence must be low.",
            "For video_quality, judge only from subtitles/narration/runtime metadata. Do not give high confidence for readability or layout without visual evidence.",
        ]
    else:
        raise ValueError(task)

    payload = {
        "mode": "/no_think",
        "task": f"score_one_textbook_video_from_text_evidence::{task}",
        "important_limits": limits,
        "score_scale": {"0": "missing or wrong", "1": "partially covered", "2": "accurately covered"},
        "required_output_schema": required_output_schema,
        "output_rules": [
            "Return exactly one JSON object.",
            "Use only keys in required_output_schema.",
            "Keep every reasoning_summary concise, preferably under 25 Chinese characters.",
            "Do not include markdown fences.",
        ],
        "video_metadata": {
            "video_id": bundle["video_id"],
            "lesson_id": bundle["lesson_id"],
            "system": bundle["system"],
            "duration_sec": bundle["video"].get("duration_sec"),
            "frame_count_available": len(bundle["frames"].get("extracted_keyframes", []))
            + len(bundle["frames"].get("selected_existing_frames", [])),
            "video_notes": bundle["video"].get("notes", ""),
        },
        "annotation": ann,
        "GENERATED_VIDEO_TEXT": generated_text,
        "structured_outputs_hint": {
            "render_manifest": bundle.get("structured_outputs", {}).get("render_manifest"),
            "quality_report": bundle.get("structured_outputs", {}).get("quality_report"),
            "presentagent_slide_plan": bundle.get("structured_outputs", {}).get("slide_plan"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalize_score(value) -> str:
    try:
        n = int(round(float(value)))
    except Exception:
        return ""
    return str(max(0, min(2, n)))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    core_rows: list[dict] = []
    qa_rows: list[dict] = []
    image_rows: list[dict] = []
    quality_rows: list[dict] = []
    error_rows: list[dict] = []
    summary_rows: list[dict] = []

    bundle_paths = sorted(INPUT_ROOT.glob("*/input_bundle.json"))
    if not bundle_paths:
        bundle_paths = sorted(INPUT_ROOT.glob("*/*/input_bundle.json"))

    for bundle_path in bundle_paths:
        bundle = read_json(bundle_path)
        annotation = compact_annotation(read_json(Path(bundle["annotation"]["path"])))
        generated_text = read_text(Path(bundle["generated_text"]["path"]), limit=GENERATED_TEXT_LIMIT)
        video_id = bundle["video_id"]
        out_dir = OUTPUT_ROOT / video_id
        out_dir.mkdir(parents=True, exist_ok=True)

        started = time.time()
        parsed = {"core_concepts": [], "heldout_questions": [], "image_scores": [], "video_quality": {}, "errors": []}
        task_statuses: dict[str, str] = {}
        for task in ["core", "qa", "visual_quality"]:
            prompt = make_prompt(bundle, annotation, generated_text, task)
            (out_dir / f"prompt_{task}.json").write_text(prompt, encoding="utf-8")
            max_tokens = TASK_MAX_TOKENS[task]
            try:
                task_parsed, raw = call_llm(prompt, max_tokens=max_tokens)
                task_statuses[task] = "parsed"
            except ParseError as exc:
                task_parsed, raw = {}, exc.raw
                task_statuses[task] = "failed"
                (out_dir / f"parse_error_{task}.txt").write_text(str(exc), encoding="utf-8")
            except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                task_parsed, raw = {}, repr(exc)
                task_statuses[task] = "failed"
            (out_dir / f"raw_response_{task}.txt").write_text(raw, encoding="utf-8")
            (out_dir / f"parsed_response_{task}.json").write_text(
                json.dumps(task_parsed, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if task == "core":
                parsed["core_concepts"] = task_parsed.get("core_concepts", task_parsed.get("items", []))
            elif task == "qa":
                parsed["heldout_questions"] = task_parsed.get("heldout_questions", task_parsed.get("items", []))
            else:
                parsed["image_scores"] = task_parsed.get("image_scores", [])
                parsed["video_quality"] = task_parsed.get("video_quality", {})
                parsed["errors"] = task_parsed.get("errors", [])

        parse_status = "parsed" if all(v == "parsed" for v in task_statuses.values()) else "needs_review"
        (out_dir / "parsed_response.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")

        common = {
            "video_id": video_id,
            "lesson_id": bundle["lesson_id"],
            "system": bundle["system"],
            "judge_run_id": JUDGE_RUN_ID,
            "judge_model": MODEL,
            "prompt_version": PROMPT_VERSION,
        }
        for item in parsed.get("core_concepts", []):
            core_rows.append(
                {
                    **common,
                    "concept_id": item.get("concept_id", ""),
                    "score": normalize_score(item.get("score", "")),
                    "confidence": item.get("confidence", ""),
                    "evidence_in_video": item.get("evidence_in_video", ""),
                    "problem_type": item.get("problem_type", ""),
                    "reasoning_summary": item.get("reasoning_summary", ""),
                    "parse_status": task_statuses.get("core", parse_status),
                }
            )
        for item in parsed.get("heldout_questions", []):
            qa_rows.append(
                {
                    **common,
                    "question_id": item.get("question_id", ""),
                    "answer_from_video": item.get("answer_from_video", ""),
                    "score": normalize_score(item.get("score", "")),
                    "reasoning_summary": item.get("reasoning_summary", ""),
                    "parse_status": task_statuses.get("qa", parse_status),
                }
            )
        for item in parsed.get("image_scores", []):
            image_rows.append(
                {
                    **common,
                    "image_requirement_id": item.get("image_requirement_id", ""),
                    "score": normalize_score(item.get("score", "")),
                    "confidence": item.get("confidence", ""),
                    "visual_issue": item.get("visual_issue", ""),
                    "evidence_in_video": item.get("evidence_in_video", ""),
                    "reasoning_summary": item.get("reasoning_summary", ""),
                    "parse_status": task_statuses.get("visual_quality", parse_status),
                }
            )
        quality = parsed.get("video_quality", {}) or {}
        quality_rows.append(
            {
                **common,
                "review_status": "trial_text_evidence",
                "readability": normalize_score(quality.get("readability", "")),
                "layout": normalize_score(quality.get("layout", "")),
                "audio_visual_sync": normalize_score(quality.get("audio_visual_sync", "")),
                "pacing": normalize_score(quality.get("pacing", "")),
                "teaching_structure": normalize_score(quality.get("teaching_structure", "")),
                "overall_quality": quality.get("overall_quality", ""),
                "reasoning_summary": quality.get("reasoning_summary", ""),
                "parse_status": task_statuses.get("visual_quality", parse_status),
            }
        )
        for item in parsed.get("errors", []) or []:
            error_rows.append(
                {
                    **common,
                    "timestamp": item.get("timestamp", ""),
                    "severity": item.get("severity", ""),
                    "error_type": item.get("error_type", ""),
                    "source_evidence": item.get("source_evidence", ""),
                    "video_evidence": item.get("video_evidence", ""),
                    "reasoning_summary": item.get("reasoning_summary", ""),
                    "parse_status": task_statuses.get("visual_quality", parse_status),
                }
            )
        summary_rows.append(
            {
                **common,
                "parse_status": parse_status,
                "wall_time_sec": f"{time.time() - started:.1f}",
                "task_statuses": json.dumps(task_statuses, ensure_ascii=False, separators=(",", ":")),
                "raw_response": str(out_dir),
                "parsed_response": str(out_dir / "parsed_response.json"),
            }
        )

    write_csv(
        OUTPUT_ROOT / "core_concept_scores.csv",
        core_rows,
        ["video_id", "lesson_id", "system", "judge_run_id", "judge_model", "prompt_version", "concept_id", "score", "confidence", "evidence_in_video", "problem_type", "reasoning_summary", "parse_status"],
    )
    write_csv(
        OUTPUT_ROOT / "heldout_question_scores.csv",
        qa_rows,
        ["video_id", "lesson_id", "system", "judge_run_id", "judge_model", "prompt_version", "question_id", "answer_from_video", "score", "reasoning_summary", "parse_status"],
    )
    write_csv(
        OUTPUT_ROOT / "image_scores.csv",
        image_rows,
        ["video_id", "lesson_id", "system", "judge_run_id", "judge_model", "prompt_version", "image_requirement_id", "score", "confidence", "visual_issue", "evidence_in_video", "reasoning_summary", "parse_status"],
    )
    write_csv(
        OUTPUT_ROOT / "video_quality_scores.csv",
        quality_rows,
        ["video_id", "lesson_id", "system", "judge_run_id", "judge_model", "prompt_version", "review_status", "readability", "layout", "audio_visual_sync", "pacing", "teaching_structure", "overall_quality", "reasoning_summary", "parse_status"],
    )
    write_csv(
        OUTPUT_ROOT / "error_log.csv",
        error_rows,
        ["video_id", "lesson_id", "system", "judge_run_id", "judge_model", "prompt_version", "timestamp", "severity", "error_type", "source_evidence", "video_evidence", "reasoning_summary", "parse_status"],
    )
    write_csv(
        OUTPUT_ROOT / "trial_summary.csv",
        summary_rows,
        ["video_id", "lesson_id", "system", "judge_run_id", "judge_model", "prompt_version", "parse_status", "wall_time_sec", "task_statuses", "raw_response", "parsed_response"],
    )

    print(json.dumps({
        "output_root": str(OUTPUT_ROOT),
        "videos": len(summary_rows),
        "core_rows": len(core_rows),
        "qa_rows": len(qa_rows),
        "image_rows": len(image_rows),
        "quality_rows": len(quality_rows),
        "error_rows": len(error_rows),
        "failed": [r["video_id"] for r in summary_rows if r["parse_status"] != "parsed"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
