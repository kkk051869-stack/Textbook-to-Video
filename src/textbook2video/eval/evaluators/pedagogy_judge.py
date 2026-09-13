"""Controlled semantic judging for the three open Pedagogy v0.2 questions.

The adapter deliberately accepts only finite, deterministic candidate context.
It never discovers concepts, slide order, prerequisite edges, or evidence
paragraphs.  A malformed response, API failure, or evidence mismatch is
returned as ``uncertain`` and never replaces the deterministic baseline.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..model_client import extract_json


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[dict[str, Any]], *, max_tokens: int) -> tuple[Any, str]: ...


PROMPT_VERSION = {
    "example_relevance": "example_relevance_v1",
    "misconception_handling": "misconception_v1",
    "concept_ordering": "ordering_v1",
}

ALLOWED_STATUSES = {
    "example_relevance": {
        "directly_relevant",
        "partially_relevant",
        "weakly_relevant",
        "irrelevant",
        "uncertain",
    },
    "misconception_handling": {
        "handled",
        "avoided",
        "not_addressed",
        "introduced",
        "uncertain",
    },
    "concept_ordering": {"reasonable", "questionable", "problematic", "uncertain"},
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_evidence_text(value: str) -> str:
    return "".join(str(value).split()).lower()


class PedagogyJudgeAdapter:
    """Invoke one semantic judge call with bounded retries and provenance."""

    def __init__(
        self,
        client: ChatClient,
        *,
        prompt_dir: str | Path | None = None,
        max_retries: int = 1,
        max_tokens: int = 700,
        output_root: str | Path | None = None,
    ) -> None:
        self.client = client
        self.prompt_dir = Path(prompt_dir) if prompt_dir else Path(__file__).resolve().parents[1] / "rubrics" / "pedagogy"
        self.max_retries = max(0, int(max_retries))
        self.max_tokens = max(128, int(max_tokens))
        self.output_root = Path(output_root).resolve() if output_root else None

    def set_output_root(self, output_root: str | Path | None) -> None:
        """Set the per-case directory used for raw call evidence."""
        self.output_root = Path(output_root).resolve() if output_root else None

    @staticmethod
    def _call_identity(judge_type: str, payload: dict[str, Any], input_sha256: str) -> str:
        identity = next(
            (
                payload.get(key)
                for key in (
                    "example_id", "concept_id", "misconception_id", "objective_id", "slide"
                )
                if payload.get(key) is not None
            ),
            "item",
        )
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(identity)).strip("-") or "item"
        return f"{judge_type}_{safe}_{input_sha256[:12]}.json"

    def _prompt(self, judge_type: str) -> tuple[str, str, str]:
        if judge_type not in PROMPT_VERSION:
            raise ValueError(f"unsupported pedagogy judge type: {judge_type}")
        version = PROMPT_VERSION[judge_type]
        path = self.prompt_dir / f"{version}.txt"
        template = path.read_text(encoding="utf-8")
        return version, template, str(path)

    @staticmethod
    def _evidence_matches_input(
        parsed: dict[str, Any], *, allowed_slides: list[Any], evidence_texts: list[str]
    ) -> bool:
        slides = {str(slide) for slide in allowed_slides}
        texts = [_normalize_evidence_text(text) for text in evidence_texts if str(text).strip()]
        for item in parsed.get("evidence", []):
            if str(item.get("slide")) not in slides:
                return False
            candidate = _normalize_evidence_text(str(item.get("text") or ""))
            if not candidate or not any(candidate in source or source in candidate for source in texts):
                return False
        return True

    def judge(
        self,
        judge_type: str,
        payload: dict[str, Any],
        *,
        allowed_slides: list[Any],
        evidence_texts: list[str],
    ) -> dict[str, Any]:
        """Return a normalized judgement and a per-call provenance record."""
        prompt_version, rubric, rubric_path = self._prompt(judge_type)
        input_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prompt = f"{rubric.rstrip()}\n\nINPUT (JSON):\n{input_text}\n"
        started_at = _now()
        started_monotonic = time.perf_counter()
        input_sha256 = _sha256_text(input_text)
        prompt_sha256 = _sha256_text(prompt)
        last_reason = "judge did not return a valid result"
        retry_count = 0
        failure_code = "judge_failed"
        normalized: dict[str, Any] | None = None
        parsed_response: Any = None
        raw_response: str | None = None
        errors: list[dict[str, Any]] = []
        accepted = False

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            try:
                # Import lazily so the evaluator can expose its parser without
                # creating a pedagogy <-> adapter import cycle.
                from .pedagogy import parse_pedagogy_judge

                parsed, raw = self.client.chat(
                    [{"role": "user", "content": prompt}], max_tokens=self.max_tokens
                )
                raw_response = raw if isinstance(raw, str) else str(raw)
                parsed_response = parsed
                if not isinstance(parsed, dict):
                    parsed = extract_json(raw)
                    parsed_response = parsed
                normalized = parse_pedagogy_judge(parsed)
                if normalized["status"] not in ALLOWED_STATUSES[judge_type]:
                    last_reason = "judge returned a status for another dimension"
                    failure_code = "invalid_status"
                    errors.append({"attempt": attempt, "code": failure_code, "message": last_reason})
                    continue
                if normalized["status"] == "uncertain" and normalized.get("uncertainty") in {
                    "malformed_output",
                    "missing_required_fields",
                    "missing_evidence",
                }:
                    last_reason = normalized.get("reason") or "judge output was incomplete"
                    failure_code = str(normalized.get("uncertainty") or "malformed_output")
                    errors.append({"attempt": attempt, "code": failure_code, "message": last_reason})
                    continue
                if not self._evidence_matches_input(
                    normalized, allowed_slides=allowed_slides, evidence_texts=evidence_texts
                ):
                    last_reason = "judge evidence does not correspond to supplied slide context"
                    failure_code = "evidence_mismatch"
                    errors.append({"attempt": attempt, "code": failure_code, "message": last_reason})
                    continue
                accepted = True
                break
            except Exception as exc:  # noqa: BLE001 - fail closed is intentional
                normalized = None
                last_reason = f"judge call failed: {type(exc).__name__}: {exc}"
                failure_code = "api_error"
                errors.append({"attempt": attempt, "code": failure_code, "message": last_reason})
        else:
            normalized = None

        if not accepted:
            normalized = {
                "status": "uncertain",
                "confidence": "low",
                "evidence": [],
                "reason": last_reason,
                "uncertainty": failure_code,
            }

        finished_at = _now()
        latency_ms = round((time.perf_counter() - started_monotonic) * 1000, 3)
        error = last_reason if errors and not accepted else None
        provenance = {
            "model": getattr(self.client, "model", "unknown"),
            "provider": getattr(self.client, "provider", "openai-compatible"),
            "runtime": getattr(self.client, "runtime", getattr(self.client, "api_base", type(self.client).__name__)),
            "provider_runtime": getattr(self.client, "api_base", type(self.client).__name__),
            "model_version": getattr(self.client, "model_version", getattr(self.client, "model", "unknown")),
            "prompt_version": prompt_version,
            "prompt_sha256": prompt_sha256,
            "rubric_sha256": _sha256_text(rubric),
            "rubric_path": rubric_path,
            "temperature": getattr(self.client, "temperature", 0),
            "input_sha256": input_sha256,
            "judge_type": judge_type,
            "started_at": started_at,
            "finished_at": finished_at,
            "latency_ms": latency_ms,
            "retry_count": retry_count,
            "attempt_count": retry_count + 1,
            "error": error,
        }
        if self.output_root is not None:
            raw_dir = self.output_root
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / self._call_identity(judge_type, payload, input_sha256)
            raw_record = {
                "judge_type": judge_type,
                "model": provenance["model"],
                "provider": provenance["provider"],
                "runtime": provenance["runtime"],
                "prompt_version": prompt_version,
                "prompt_sha256": prompt_sha256,
                "rubric_sha256": provenance["rubric_sha256"],
                "input_sha256": input_sha256,
                "temperature": provenance["temperature"],
                "started_at": started_at,
                "finished_at": finished_at,
                "latency_ms": latency_ms,
                "retry_count": retry_count,
                "attempt_count": retry_count + 1,
                "error": error,
                "errors": errors,
                "raw_response": raw_response,
                "parsed_response": parsed_response,
                "judgement": normalized,
            }
            raw_path.write_text(
                json.dumps(raw_record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            provenance["raw_output_path"] = str(raw_path.relative_to(self.output_root.parent))
        return {"judgement": normalized, "provenance": provenance}


__all__ = ["PedagogyJudgeAdapter", "PROMPT_VERSION", "ALLOWED_STATUSES"]
