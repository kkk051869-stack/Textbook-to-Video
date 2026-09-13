"""Final-video-only information recoverability evaluation.

The legacy Video-QA adapters consume pre-computed judge result files.  This
module is the deliberately separate v0.1 path for evaluating what a viewer can
recover from the delivered MP4.  Audience prompts are built from MP4-derived
frames and embedded subtitles only; reference judging receives the frozen
answer/rubric and the Audience response in a separate request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from ..runner import EvalContext
from ..report import write_json


FINAL_VIDEOQA_EVALUATOR = "videoqa_final"
FINAL_VIDEOQA_PROMPT_VERSION = "final-video-qa-v0.1"
INPUT_MANIFEST_VERSION = "textbookeval-audience-input-v0.1"
MEDIA_MANIFEST_VERSION = "textbookeval-final-media-v0.1"

_FORBIDDEN_AUDIENCE_KINDS = {
    "source",
    "source_pdf",
    "source_json",
    "annotation",
    "gold_answer",
    "scoring_rubric",
    "evidence",
    "script",
    "storyboard",
    "timed_storyboard",
    "knowledge_grounding",
    "source_fidelity",
}
_REFERENCE_ONLY_KEYS = {
    "answer",
    "gold_answer",
    "scoring",
    "scoring_rubric",
    "evidence_paragraphs",
    "source_evidence",
}
_REFERENCE_STATUSES = {"correct", "partial", "incorrect", "uncertain"}
_EXPLANATION_STATUSES = {"supported", "partial", "incorrect", "unverified"}


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, Any]], *, max_tokens: int) -> tuple[Any, str]: ...


class FinalVideoError(RuntimeError):
    """A final-media input could not be validated or derived."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ResponseContractError(ValueError):
    """A model response cannot be safely interpreted under the v0.1 contract."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _image_part(path: Path) -> dict[str, Any]:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_questions(path: Path) -> list[dict[str, Any]]:
    value = _load_json(path)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("questions", "heldout_questions"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    raise ValueError(f"{path} must contain a questions or heldout_questions array")


def _question_id(item: dict[str, Any], index: int) -> str:
    return str(item.get("question_id") or item.get("id") or f"q{index:03d}")


def _question_public(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "question_id": _question_id(item, index),
        "question_type": str(item.get("type") or "unknown"),
        "question_text": str(item.get("question") or ""),
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _run_command(
    command: Sequence[str], *, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), capture_output=True, text=True, check=False, timeout=timeout
    )


@dataclass(frozen=True)
class PreparedFinalMedia:
    video_path: Path
    probe: dict[str, Any]
    frames: list[Path]
    subtitle: Path
    manifest_path: Path
    manifest: dict[str, Any]


class FfmpegFinalMediaAdapter:
    """Validate an MP4 and derive only deterministic representations from it."""

    def __init__(
        self,
        *,
        ffprobe: str = "ffprobe",
        ffmpeg: str = "ffmpeg",
        frame_count: int = 4,
        timeout: int = 180,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = _run_command,
    ) -> None:
        self.ffprobe = ffprobe
        self.ffmpeg = ffmpeg
        self.frame_count = max(1, int(frame_count))
        self.timeout = timeout
        self.command_runner = command_runner

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self.command_runner(command, timeout=self.timeout)
        except FileNotFoundError as exc:
            raise FinalVideoError(
                "FINAL_VIDEO_UNAVAILABLE", f"required media tool is unavailable: {command[0]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise FinalVideoError(
                "FINAL_VIDEO_DECODE_FAILED", f"media command timed out: {command[0]}"
            ) from exc

    def _probe(self, video_path: Path) -> dict[str, Any]:
        result = self._run(
            [self.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video_path)]
        )
        if result.returncode != 0:
            raise FinalVideoError(
                "FINAL_VIDEO_UNAVAILABLE",
                f"ffprobe could not inspect final video: {result.stderr.strip()[:500]}",
            )
        try:
            probe = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise FinalVideoError("FINAL_VIDEO_UNAVAILABLE", "ffprobe returned invalid JSON") from exc
        streams = probe.get("streams", []) if isinstance(probe, dict) else []
        counts = {
            stream_type: sum(
                isinstance(stream, dict) and stream.get("codec_type") == stream_type
                for stream in streams
            )
            for stream_type in ("video", "audio", "subtitle")
        }
        if any(counts[name] < 1 for name in counts):
            missing = ", ".join(name for name, count in counts.items() if count < 1)
            raise FinalVideoError(
                "FINAL_VIDEO_UNAVAILABLE", f"final MP4 is missing required stream(s): {missing}"
            )
        format_info = probe.get("format", {}) if isinstance(probe, dict) else {}
        return {
            "video_stream_count": counts["video"],
            "audio_stream_count": counts["audio"],
            "subtitle_stream_count": counts["subtitle"],
            "duration_sec": float(format_info.get("duration", 0) or 0),
            "streams": streams,
        }

    def _decode_check(self, video_path: Path) -> None:
        result = self._run([self.ffmpeg, "-v", "error", "-i", str(video_path), "-f", "null", "-"])
        if result.returncode != 0:
            raise FinalVideoError(
                "FINAL_VIDEO_DECODE_FAILED",
                f"ffmpeg could not decode final video: {result.stderr.strip()[:500]}",
            )

    def prepare(self, video_path: Path, output_root: Path) -> PreparedFinalMedia:
        video_path = video_path.resolve()
        if not video_path.is_file():
            raise FinalVideoError("FINAL_VIDEO_UNAVAILABLE", f"final video is missing: {video_path}")
        probe = self._probe(video_path)
        self._decode_check(video_path)
        media_root = output_root / "video_qa" / "media"
        frames_root = media_root / "frames"
        frames_root.mkdir(parents=True, exist_ok=True)
        duration = max(0.001, float(probe.get("duration_sec", 0) or 0))
        frames: list[Path] = []
        timestamps: list[float] = []
        for index in range(self.frame_count):
            timestamp = duration * (index + 0.5) / self.frame_count
            frame = frames_root / f"frame_{index + 1:04d}.png"
            result = self._run(
                [
                    self.ffmpeg,
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1280:-2",
                    str(frame),
                ]
            )
            if result.returncode != 0 or not frame.is_file():
                raise FinalVideoError(
                    "FINAL_VIDEO_DECODE_FAILED",
                    f"could not derive frame at {timestamp:.3f}s: {result.stderr.strip()[:500]}",
                )
            frames.append(frame)
            timestamps.append(round(timestamp, 6))

        subtitle = media_root / "embedded_subtitle.srt"
        subtitle_result = self._run(
            [
                self.ffmpeg,
                "-v",
                "error",
                "-y",
                "-i",
                str(video_path),
                "-map",
                "0:s:0",
                "-c:s",
                "srt",
                str(subtitle),
            ]
        )
        if subtitle_result.returncode != 0 or not subtitle.is_file():
            raise FinalVideoError(
                "FINAL_VIDEO_DECODE_FAILED",
                f"could not extract embedded subtitle: {subtitle_result.stderr.strip()[:500]}",
            )

        manifest = {
            "schema_version": MEDIA_MANIFEST_VERSION,
            "input_mode": "final_media_extracted",
            "final_video": {
                "path": str(video_path),
                "sha256": _sha256_file(video_path),
            },
            "probe": {key: value for key, value in probe.items() if key != "streams"},
            "derived_frames": [
                {
                    "path": _relative(frame, output_root),
                    "sha256": _sha256_file(frame),
                    "timestamp_sec": timestamp,
                }
                for frame, timestamp in zip(frames, timestamps)
            ],
            "derived_subtitle": {
                "path": _relative(subtitle, output_root),
                "sha256": _sha256_file(subtitle),
                "source": "embedded_mp4",
            },
            "sampling": {
                "strategy": "uniform_temporal",
                "frame_count": len(frames),
                "question_independent": True,
            },
            "audio": {
                "available_in_mp4": True,
                "consumed_by_model": False,
                "handling": "vision-model input uses MP4-derived frames and embedded subtitle",
            },
        }
        manifest_path = media_root / "manifest.json"
        write_json(manifest_path, manifest)
        return PreparedFinalMedia(video_path, probe, frames, subtitle, manifest_path, manifest)


def audit_audience_input_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if the recorded Audience payload contains reference inputs."""
    found: list[str] = []
    actual = manifest.get("actual_audience_inputs", [])
    if isinstance(actual, list):
        for item in actual:
            if isinstance(item, dict) and item.get("kind") in _FORBIDDEN_AUDIENCE_KINDS:
                found.append(str(item["kind"]))
    payload = manifest.get("audience_payload", {})
    if isinstance(payload, dict):
        for key in _REFERENCE_ONLY_KEYS:
            if key in payload:
                found.append(key)
        for key in payload:
            if str(key).lower() in _FORBIDDEN_AUDIENCE_KINDS:
                found.append(str(key))
    found = sorted(set(found))
    return {
        "status": "fail" if found else "pass",
        "passed": not found,
        "forbidden_inputs_found": found,
        "checked": True,
    }


def _write_audience_input_manifest(
    output_root: Path,
    media: PreparedFinalMedia,
    public_questions: list[dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    manifest = {
        "schema_version": INPUT_MANIFEST_VERSION,
        "input_mode": "final_media_extracted",
        "actual_audience_inputs": [
            {
                "kind": "final_video",
                "path": str(media.video_path),
                "sha256": media.manifest["final_video"]["sha256"],
            },
            *[
                {
                    "kind": "derived_frames",
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "timestamp_sec": item["timestamp_sec"],
                }
                for item in media.manifest["derived_frames"]
            ],
            {
                "kind": "derived_subtitle",
                "path": media.manifest["derived_subtitle"]["path"],
                "sha256": media.manifest["derived_subtitle"]["sha256"],
                "source": "embedded_mp4",
            },
        ],
        "question_fields": ["question_id", "question_type", "question_text"],
        "questions": public_questions,
        "forbidden_inputs": [
            {"kind": kind, "included": False}
            for kind in sorted(_FORBIDDEN_AUDIENCE_KINDS)
        ],
        "audience_payload": {
            "input_kinds": ["final_video", "derived_frames", "derived_subtitle", "question_text"],
            "reference_only_data_included": False,
        },
    }
    manifest["audit"] = audit_audience_input_manifest(manifest)
    path = output_root / "video_qa" / "audience_input_manifest.json"
    write_json(path, manifest)
    return path, manifest


def _audience_prompt(question: dict[str, Any], subtitle: str, frame_names: list[str]) -> str:
    return (
        "You are the audience evaluator for a finished educational video. "
        "Answer only from what is visibly or textually recoverable from the attached final-video "
        "frames and the embedded subtitle extracted from that same MP4. Do not use outside knowledge. "
        "If the final media does not support an answer, use answer=\"cannot_determine\" and do not guess. "
        "Return one JSON object only. Every answer other than cannot_determine must include concrete "
        "evidence_from_video observations.\n\n"
        f"QUESTION:\n{json.dumps(question, ensure_ascii=False)}\n\n"
        f"EMBEDDED_SUBTITLE_FROM_FINAL_MP4:\n{subtitle}\n\n"
        f"FRAME_NAMES_AND_ORDER:\n{json.dumps(frame_names, ensure_ascii=False)}\n\n"
        "OUTPUT:\n"
        '{"question_id":"string","answer":"string or cannot_determine",'
        '"explanation":"string","confidence":"high|medium|low",'
        '"evidence_from_video":[{"timestamp_or_frame":"string","observation":"string"}]}'
    )


def _reference_prompt(
    question: dict[str, Any], audience: dict[str, Any], source_evidence: list[str]
) -> str:
    reference = {
        "question_id": _question_id(question, 0),
        "question_type": question.get("type"),
        "question_text": question.get("question"),
        "gold_answer": question.get("answer"),
        "scoring_rubric": question.get("scoring"),
        "source_evidence": source_evidence,
        "audience_answer": audience.get("answer"),
        "audience_explanation": audience.get("explanation"),
        "audience_evidence_from_video": audience.get("evidence_from_video", []),
    }
    return (
        "You are a separate Reference Judge. Judge the Audience answer against the supplied gold "
        "answer, rubric, and source evidence. Do not answer the question yourself and do not add "
        "missing content to the Audience answer. Return only a JSON judgement object. "
        "Use uncertain when the Audience response or rubric is insufficient. Also classify the "
        "Audience explanation as supported, partial, incorrect, or unverified.\n\n"
        f"REFERENCE_CASE:\n{json.dumps(reference, ensure_ascii=False)}\n\n"
        "OUTPUT:\n"
        '{"question_id":"string","status":"correct|partial|incorrect|uncertain",'
        '"reason":"string","matched_gold_points":[],"missing_gold_points":[],'
        '"contradictions":[],"explanation_status":"supported|partial|incorrect|unverified"}'
    )


def _call_with_retries(
    client: ChatClient,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    retries: int,
) -> tuple[Any | None, str | None, dict[str, Any]]:
    started = time.monotonic()
    errors: list[str] = []
    parsed: Any | None = None
    raw: str | None = None
    attempts = 0
    for attempts in range(1, max(0, retries) + 2):
        try:
            parsed, raw = client.chat(messages, max_tokens=max_tokens)
            break
        except Exception as exc:  # noqa: BLE001 - fail closed and preserve provenance
            errors.append(f"{type(exc).__name__}: {exc}")
    return parsed, raw, {
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "attempts": attempts,
        "retry_count": max(0, attempts - 1),
        "errors": errors,
    }


def _confidence(value: Any) -> str:
    if isinstance(value, (int, float)):
        return "high" if value >= 80 else "medium" if value >= 50 else "low"
    value = str(value or "low").lower()
    return value if value in {"high", "medium", "low"} else "low"


def normalize_audience_response(
    parsed: Any, *, question_id: str
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    candidate = parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("answers"), list):
        candidate = next(
            (
                item
                for item in parsed["answers"]
                if isinstance(item, dict) and str(item.get("question_id")) == question_id
            ),
            parsed["answers"][0] if parsed["answers"] else {},
        )
    if isinstance(candidate, str) and candidate.strip().lower() == "cannot_determine":
        return {
            "question_id": question_id,
            "answer": "cannot_determine",
            "explanation": "The final media does not provide enough evidence.",
            "confidence": "low",
            "evidence_from_video": [],
        }, errors
    if not isinstance(candidate, dict):
        return {
            "question_id": question_id,
            "answer": "cannot_determine",
            "explanation": "Audience response was not a JSON object.",
            "confidence": "low",
            "evidence_from_video": [],
        }, ["response_not_object"]
    answer = candidate.get("answer", candidate.get("answer_from_video"))
    explanation = str(candidate.get("explanation") or "").strip()
    if isinstance(answer, str) and answer.strip().lower() == "cannot_determine":
        return {
            "question_id": question_id,
            "answer": "cannot_determine",
            "explanation": explanation or "The final media does not provide enough evidence.",
            "confidence": _confidence(candidate.get("confidence")),
            "evidence_from_video": [],
        }, errors
    evidence_value = candidate.get("evidence_from_video")
    evidence: list[dict[str, str]] = []
    if isinstance(evidence_value, list):
        for item in evidence_value:
            if isinstance(item, dict) and str(item.get("observation") or "").strip():
                evidence.append(
                    {
                        "timestamp_or_frame": str(item.get("timestamp_or_frame") or "unknown")[:200],
                        "observation": str(item["observation"])[:800],
                    }
                )
    if answer in (None, ""):
        errors.append("missing_answer")
    if not explanation:
        errors.append("missing_explanation")
    if not evidence:
        errors.append("missing_evidence")
    if errors:
        return {
            "question_id": question_id,
            "answer": "cannot_determine",
            "explanation": "Audience response failed the evidence contract: " + ", ".join(errors),
            "confidence": "low",
            "evidence_from_video": [],
        }, errors
    return {
        "question_id": question_id,
        "answer": answer,
        "explanation": explanation[:1200],
        "confidence": _confidence(candidate.get("confidence")),
        "evidence_from_video": evidence,
    }, errors


def normalize_reference_response(
    parsed: Any, *, question_id: str
) -> tuple[dict[str, Any], list[str]]:
    candidate = parsed
    if isinstance(parsed, dict):
        for key in ("judgements", "judgments", "results", "scores"):
            if isinstance(parsed.get(key), list):
                candidate = next(
                    (
                        item
                        for item in parsed[key]
                        if isinstance(item, dict) and str(item.get("question_id")) == question_id
                    ),
                    parsed[key][0] if parsed[key] else {},
                )
                break
    if not isinstance(candidate, dict):
        return {
            "question_id": question_id,
            "status": "uncertain",
            "reason": "Reference Judge response was not a JSON object.",
            "matched_gold_points": [],
            "missing_gold_points": [],
            "contradictions": [],
            "explanation_status": "unverified",
        }, ["response_not_object"]
    status = str(candidate.get("status") or "").lower()
    status_was_valid = status in _REFERENCE_STATUSES
    if not status_was_valid:
        score = candidate.get("score")
        status = "correct" if score == 2 else "partial" if score == 1 else "incorrect" if score == 0 else "uncertain"
    errors = [] if status_was_valid or "score" in candidate else ["invalid_status"]
    explanation_status = str(
        candidate.get("explanation_status") or candidate.get("explanation_correctness") or "unverified"
    ).lower()
    if explanation_status not in _EXPLANATION_STATUSES:
        explanation_status = "unverified"
        errors.append("invalid_explanation_status")
    def _strings(key: str) -> list[str]:
        value = candidate.get(key, [])
        if not isinstance(value, list):
            return [str(value)[:800]] if value else []
        return [str(item)[:800] for item in value]
    return {
        "question_id": question_id,
        "status": status,
        "reason": str(candidate.get("reason") or "")[:1200],
        "matched_gold_points": _strings("matched_gold_points"),
        "missing_gold_points": _strings("missing_gold_points"),
        "contradictions": _strings("contradictions"),
        "explanation_status": explanation_status,
    }, errors


def _canonical_answer(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(_canonical_answer(item) for item in value)
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def deterministic_reference(question: dict[str, Any], audience: dict[str, Any]) -> dict[str, Any] | None:
    """Use only explicitly structured accepted answers; free text stays semantic."""
    accepted = None
    for key in ("accepted_answers", "accepted", "answer_key"):
        if key in question:
            accepted = question[key]
            break
    if accepted is None:
        return None
    answer = audience.get("answer")
    if answer == "cannot_determine":
        status = "incorrect"
    elif _canonical_answer(answer) == _canonical_answer(accepted):
        status = "correct"
    else:
        status = "incorrect"
    return {
        "question_id": _question_id(question, 0),
        "status": status,
        "reason": "Exact comparison against the frozen structured answer key.",
        "matched_gold_points": ["structured answer key"] if status == "correct" else [],
        "missing_gold_points": [] if status == "correct" else ["structured answer key"],
        "contradictions": [],
        "explanation_status": "unverified",
    }


def _source_evidence(context: EvalContext, question: dict[str, Any]) -> list[str]:
    source_path = None
    for asset in context.case.assets():
        if asset.role == "source_json":
            source_path = context.case.resolve_asset(asset)
            break
    paragraphs: dict[str, str] = {}
    if source_path is not None and source_path.is_file():
        value = _load_json(source_path)
        for item in value.get("paragraphs", []) if isinstance(value, dict) else []:
            if isinstance(item, dict) and item.get("id") is not None:
                paragraphs[str(item["id"])] = str(item.get("text") or "")[:1200]
    return [paragraphs[item] for item in question.get("evidence_paragraphs", []) if str(item) in paragraphs]


def _questions_path(context: EvalContext) -> Path | None:
    for asset in context.case.assets():
        if asset.role == "heldout_questions":
            path = context.case.resolve_asset(asset)
            return path if path.is_file() else None
    return None


def _candidate_video(context: EvalContext) -> Path | None:
    """Resolve candidate-only conventional/declared artifacts, never baseline files."""
    candidate = context.case.raw.get("candidate_artifacts")
    if isinstance(candidate, dict):
        value = candidate.get("final_video")
        if isinstance(value, dict):
            value = value.get("path")
        if isinstance(value, str) and value.strip():
            path = (context.artifacts_root / value).resolve()
            if context.artifacts_root in path.parents and path.is_file():
                return path
    for name in ("final.mp4", "video.mp4", "lesson.mp4", "animation.mp4"):
        path = (context.artifacts_root / name).resolve()
        if context.artifacts_root in path.parents and path.is_file():
            return path
    return None


def _issue(context: EvalContext, issue_type: str, message: str, *, severity: str = "warning", question_id: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "case_id": context.case.case_id,
        "stage": "eval",
        "evaluator": FINAL_VIDEOQA_EVALUATOR,
        "type": issue_type,
        "severity": severity,
        "message": message,
        "review_status": "unreviewed",
    }
    if question_id:
        value["question_id"] = question_id
    return value


def _calibration(path: Path, questions: list[dict[str, Any]], audience: dict[str, dict[str, Any]], reference: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# Video-QA Calibration",
        "",
        "Human labels are intentionally left as `pending`; this worksheet is not an automatic human review.",
        "",
        "| Question | Type | Audience Answer | Judge | Gold Summary | Human label | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, question in enumerate(questions, start=1):
        qid = _question_id(question, index)
        public = _question_public(question, index)
        answer = str(audience.get(qid, {}).get("answer", "cannot_determine")).replace("|", "\\|")
        status = str(reference.get(qid, {}).get("status", "uncertain"))
        gold = str(question.get("answer", ""))[:240].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {qid} | {public['question_type']} | {answer} | {status} | {gold} | pending | |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _unavailable(context: EvalContext, issue_type: str, message: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "passed": None,
        "metrics": {},
        "details": {"required": True, "reason": message, "video_qa": {"status": "unavailable", "passed": None}},
        "issues": [_issue(context, issue_type, message, severity="error")],
        "evidence_ids": [],
    }


class FinalVideoQAAdapter:
    """Run isolated Audience and Reference Judge calls for one final MP4."""

    def __init__(
        self,
        audience_client: ChatClient,
        reference_client: ChatClient | None = None,
        *,
        media_adapter: Any | None = None,
        max_retries: int = 1,
    ) -> None:
        self.audience_client = audience_client
        self.reference_client = reference_client or audience_client
        self.media_adapter = media_adapter or FfmpegFinalMediaAdapter()
        self.max_retries = max(0, int(max_retries))

    def evaluate_case(self, context: EvalContext) -> dict[str, Any]:
        video_path = _candidate_video(context)
        if video_path is None:
            return _unavailable(context, "FINAL_VIDEO_UNAVAILABLE", "candidate final MP4 is unavailable")
        questions_path = _questions_path(context)
        if questions_path is None:
            return _unavailable(context, "VIDEO_QA_PROVIDER_ERROR", "frozen held-out questions are unavailable")
        try:
            questions = _load_questions(questions_path)
            media = self.media_adapter.prepare(video_path, context.output_root)
        except FinalVideoError as exc:
            return _unavailable(context, exc.code, str(exc))
        except Exception as exc:  # noqa: BLE001 - media preparation is an evaluator boundary
            return _unavailable(context, "FINAL_VIDEO_DECODE_FAILED", f"media preparation failed: {exc}")
        if not questions:
            return _unavailable(context, "VIDEO_QA_PROVIDER_ERROR", "held-out question set is empty")

        public_questions = [_question_public(item, index) for index, item in enumerate(questions, start=1)]
        input_manifest_path, input_manifest = _write_audience_input_manifest(
            context.output_root, media, public_questions
        )
        leakage = audit_audience_input_manifest(input_manifest)
        evidence: list[dict[str, Any]] = [
            {
                "evidence_id": f"{context.case.case_id}-videoqa-media-manifest",
                "kind": "final_media_manifest",
                "path": _relative(media.manifest_path, context.output_root),
            },
            {
                "evidence_id": f"{context.case.case_id}-videoqa-audience-input-manifest",
                "kind": "audience_input_manifest",
                "path": _relative(input_manifest_path, context.output_root),
            },
        ]
        if not leakage["passed"]:
            return {
                "status": "failed",
                "passed": False,
                "metrics": {"question_count": len(questions)},
                "details": {
                    "required": True,
                    "model": getattr(self.audience_client, "model", "unknown"),
                    "video_qa": {
                        "status": "failed",
                        "passed": False,
                        "input_mode": "final_media_extracted",
                        "leakage_audit": leakage,
                    },
                    "leakage_audit": leakage,
                },
                "issues": [_issue(context, "AUDIENCE_INFORMATION_LEAKAGE", "Audience input manifest contains forbidden reference data", severity="error")],
                "evidence_ids": [item["evidence_id"] for item in evidence],
                "_evidence": evidence,
            }

        subtitle = media.subtitle.read_text(encoding="utf-8", errors="replace")
        frame_names = [frame.name for frame in media.frames]
        audience_items: dict[str, dict[str, Any]] = {}
        reference_items: dict[str, dict[str, Any]] = {}
        audience_issues: list[dict[str, Any]] = []
        reference_issues: list[dict[str, Any]] = []
        prompt_hashes: dict[str, str] = {}
        input_hashes: dict[str, str] = {}
        raw_evidence: list[dict[str, Any]] = []
        provider_errors = 0
        reference_provider_names: set[str] = set()

        audience_root = context.output_root / "video_qa" / "audience"
        reference_root = context.output_root / "video_qa" / "reference_judge"
        audience_root.mkdir(parents=True, exist_ok=True)
        reference_root.mkdir(parents=True, exist_ok=True)
        for index, question in enumerate(questions, start=1):
            public = _question_public(question, index)
            qid = public["question_id"]
            prompt = _audience_prompt(public, subtitle, frame_names)
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, *[_image_part(frame) for frame in media.frames]]}]
            prompt_hash = _sha256_bytes(prompt.encode("utf-8"))
            input_hash = _sha256_json({"media_manifest": media.manifest, "question": public})
            parsed, raw, call = _call_with_retries(
                self.audience_client, messages, max_tokens=900, retries=self.max_retries
            )
            normalized, parse_errors = normalize_audience_response(parsed, question_id=qid)
            errors = [*call["errors"], *parse_errors]
            if errors:
                provider_errors += 1
            if parse_errors:
                audience_issues.append(
                    _issue(context, "VIDEO_QA_PROVIDER_ERROR", f"Audience response for {qid} failed contract: {', '.join(parse_errors)}", question_id=qid)
                )
            if normalized["answer"] == "cannot_determine":
                audience_issues.append(
                    _issue(context, "VIDEO_QA_UNANSWERED", f"Audience could not recover an answer for {qid}", question_id=qid)
                )
            audience_items[qid] = normalized
            prompt_hashes[f"audience:{qid}"] = prompt_hash
            input_hashes[f"audience:{qid}"] = input_hash
            raw_path = audience_root / f"{qid}.json"
            raw_record = {
                "schema_version": FINAL_VIDEOQA_PROMPT_VERSION,
                "question_id": qid,
                "provider": "openai-compatible",
                "model": getattr(self.audience_client, "model", "unknown"),
                "prompt_sha256": prompt_hash,
                "input_sha256": input_hash,
                "latency_ms": call["latency_ms"],
                "attempts": call["attempts"],
                "retry_count": call["retry_count"],
                "errors": errors,
                "raw_response": raw,
                "parsed_response": parsed,
                "normalized_response": normalized,
            }
            write_json(raw_path, raw_record)
            raw_id = f"{context.case.case_id}-videoqa-audience-{qid}"
            raw_evidence.append({"evidence_id": raw_id, "kind": "model_raw_output", "path": _relative(raw_path, context.output_root)})

        for index, question in enumerate(questions, start=1):
            qid = _question_id(question, index)
            audience = audience_items[qid]
            deterministic = deterministic_reference(question, audience)
            reference_prompt = _reference_prompt(question, audience, _source_evidence(context, question))
            reference_input = {
                "question": question,
                "audience": audience,
                "source_evidence": _source_evidence(context, question),
            }
            reference_hash = _sha256_json(reference_input)
            reference_prompt_hash = _sha256_bytes(reference_prompt.encode("utf-8"))
            if deterministic is not None:
                judged = deterministic
                raw = json.dumps(judged, ensure_ascii=False)
                call = {"latency_ms": 0, "attempts": 0, "retry_count": 0, "errors": []}
                provider = "deterministic"
            else:
                parsed, raw, call = _call_with_retries(
                    self.reference_client,
                    [{"role": "user", "content": reference_prompt}],
                    max_tokens=900,
                    retries=self.max_retries,
                )
                judged, parse_errors = normalize_reference_response(parsed, question_id=qid)
                call = {**call, "errors": [*call["errors"], *parse_errors]}
                provider = "openai-compatible"
                if call["errors"]:
                    provider_errors += 1
                    reference_issues.append(
                        _issue(context, "VIDEO_QA_PROVIDER_ERROR", f"Reference Judge response for {qid} failed contract: {', '.join(call['errors'])}", question_id=qid)
                    )
            reference_provider_names.add(provider)
            reference_items[qid] = judged
            status = judged["status"]
            if status == "incorrect":
                reference_issues.append(_issue(context, "VIDEO_QA_INCORRECT", f"Reference Judge marked {qid} incorrect", question_id=qid))
            elif status == "partial":
                reference_issues.append(_issue(context, "VIDEO_QA_PARTIAL", f"Reference Judge marked {qid} partial", question_id=qid))
            elif status == "uncertain":
                reference_issues.append(_issue(context, "VIDEO_QA_JUDGE_UNCERTAIN", f"Reference Judge was uncertain for {qid}", question_id=qid))
            prompt_hashes[f"reference:{qid}"] = reference_prompt_hash
            input_hashes[f"reference:{qid}"] = reference_hash
            raw_path = reference_root / f"{qid}.json"
            raw_record = {
                "schema_version": FINAL_VIDEOQA_PROMPT_VERSION,
                "question_id": qid,
                "provider": provider,
                "model": getattr(self.reference_client, "model", "unknown") if provider != "deterministic" else "deterministic",
                "prompt_sha256": reference_prompt_hash,
                "input_sha256": reference_hash,
                "latency_ms": call["latency_ms"],
                "attempts": call["attempts"],
                "retry_count": call["retry_count"],
                "errors": call["errors"],
                "raw_response": raw,
                "parsed_response": judged,
                "normalized_response": judged,
            }
            write_json(raw_path, raw_record)
            raw_id = f"{context.case.case_id}-videoqa-reference-{qid}"
            raw_evidence.append({"evidence_id": raw_id, "kind": "model_raw_output", "path": _relative(raw_path, context.output_root)})

        total = len(questions)
        answered = sum(item["answer"] != "cannot_determine" for item in audience_items.values())
        cannot = total - answered
        correct = sum(item["status"] == "correct" for item in reference_items.values())
        partial = sum(item["status"] == "partial" for item in reference_items.values())
        incorrect = sum(item["status"] == "incorrect" for item in reference_items.values())
        uncertain = sum(item["status"] == "uncertain" for item in reference_items.values())
        by_type: dict[str, dict[str, Any]] = {}
        for index, question in enumerate(questions, start=1):
            qid = _question_id(question, index)
            qtype = str(question.get("type") or "unknown")
            entry = by_type.setdefault(qtype, {"question_count": 0, "answered_count": 0, "correct_count": 0, "partial_count": 0, "incorrect_count": 0, "uncertain_count": 0})
            entry["question_count"] += 1
            entry["answered_count"] += audience_items[qid]["answer"] != "cannot_determine"
            entry[f"{reference_items[qid]['status']}_count"] += 1
        for entry in by_type.values():
            count = entry["question_count"]
            entry["strict_accuracy"] = round(entry["correct_count"] / count, 6) if count else 0.0
            entry["partial_credit_accuracy"] = round((entry["correct_count"] + 0.5 * entry["partial_count"]) / count, 6) if count else 0.0
        explanation_counts = {status: 0 for status in _EXPLANATION_STATUSES}
        for item in reference_items.values():
            explanation_counts[item.get("explanation_status", "unverified")] += 1
        metrics = {
            "question_count": total,
            "answered_count": answered,
            "cannot_determine_count": cannot,
            "correct_count": correct,
            "partial_count": partial,
            "incorrect_count": incorrect,
            "uncertain_count": uncertain,
            "strict_accuracy": round(correct / total, 6) if total else 0.0,
            "partial_credit_accuracy": round((correct + 0.5 * partial) / total, 6) if total else 0.0,
            "by_question_type": by_type,
            "explanation_supported": explanation_counts["supported"],
            "explanation_partial": explanation_counts["partial"],
            "explanation_incorrect": explanation_counts["incorrect"],
            "explanation_unverified": explanation_counts["unverified"],
        }
        metrics["information_recoverability"] = {
            "question_count": total,
            "answered_count": answered,
            "cannot_determine_count": cannot,
            "answer_rate": round(answered / total, 6) if total else 0.0,
        }
        metrics["quiz_accuracy"] = {
            "strict_accuracy": metrics["strict_accuracy"],
            "partial_credit_accuracy": metrics["partial_credit_accuracy"],
            "by_question_type": by_type,
        }
        calibration_path = context.output_root / "video_qa" / "video_qa_calibration.md"
        _calibration(calibration_path, questions, audience_items, reference_items)
        calibration_id = f"{context.case.case_id}-videoqa-calibration"
        raw_evidence.append({"evidence_id": calibration_id, "kind": "calibration_worksheet", "path": _relative(calibration_path, context.output_root)})
        all_issues = [*audience_issues, *reference_issues]
        details_video = {
            "status": "error" if provider_errors else "ok",
            "passed": None if provider_errors else True,
            "input_mode": "final_media_extracted",
            "metrics": metrics,
            "questions": [
                {
                    "question_id": _question_id(question, index),
                    "question_type": str(question.get("type") or "unknown"),
                    "question_text": str(question.get("question") or ""),
                    "audience": audience_items[_question_id(question, index)],
                    "reference_judge": reference_items[_question_id(question, index)],
                }
                for index, question in enumerate(questions, start=1)
            ],
            "leakage_audit": leakage,
            "media_manifest": _relative(media.manifest_path, context.output_root),
            "audience_input_manifest": _relative(input_manifest_path, context.output_root),
            "calibration_path": _relative(calibration_path, context.output_root),
            "provenance": {
                "audience_provider": "openai-compatible",
                "audience_model": getattr(self.audience_client, "model", "unknown"),
                "reference_provider": "deterministic" if reference_provider_names == {"deterministic"} else "openai-compatible",
                "reference_model": getattr(self.reference_client, "model", "unknown") if "openai-compatible" in reference_provider_names else "deterministic",
                "prompt_version": FINAL_VIDEOQA_PROMPT_VERSION,
                "input_mode": "final_media_extracted",
                "media_manifest_sha256": _sha256_file(media.manifest_path),
                "audience_input_manifest_sha256": _sha256_file(input_manifest_path),
                "prompt_sha256": prompt_hashes,
                "input_sha256": input_hashes,
                "audio_available_in_mp4": True,
                "audio_consumed_by_model": False,
            },
        }
        evidence.extend(raw_evidence)
        return {
            "status": details_video["status"],
            "passed": details_video["passed"],
            "metrics": metrics,
            "details": {
                "required": True,
                "model": getattr(self.audience_client, "model", "unknown"),
                "prompt_version": FINAL_VIDEOQA_PROMPT_VERSION,
                "metadata": {
                    "prompt_sha256": prompt_hashes,
                    "input_sha256": input_hashes,
                    "media_manifest_sha256": _sha256_file(media.manifest_path),
                },
                "video_qa": details_video,
                "provenance": details_video["provenance"],
            },
            "issues": all_issues,
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "_evidence": evidence,
        }


def evaluate_final_video_qa(context: EvalContext) -> dict[str, Any]:
    adapter = context.final_video_qa
    if adapter is None:
        return _unavailable(context, "FINAL_VIDEO_UNAVAILABLE", "final-video Video-QA is not configured")
    return adapter.evaluate_case(context)


evaluate_final_video_qa.evaluator_name = FINAL_VIDEOQA_EVALUATOR
