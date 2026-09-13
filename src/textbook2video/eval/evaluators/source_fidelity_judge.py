"""Claim-level Source Fidelity v0.2 helpers and controlled Judge adapter.

The existing deterministic Source Fidelity evaluator owns the public
``source_fidelity`` result.  This module adds the claim-level layer without
replacing the v0.1 concept/evidence coverage fields.  It only sees candidate
script/storyboard text and frozen source paragraphs; held-out answers and
other evaluator results are intentionally out of scope.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runner import EvalContext

EVALUATOR_VERSION = "source-fidelity-v0.2"
EXTRACTION_PROMPT_VERSION = "claim_extraction_v1"
CLASSIFICATION_PROMPT_VERSION = "claim_classification_v1"
CLAIM_TYPES = {
    "FACTUAL",
    "DEFINITION",
    "CAUSAL",
    "COMPARATIVE",
    "PROCESS",
    "QUANTITATIVE",
    "PEDAGOGICAL_INSTRUCTION",
    "NON_FACTUAL",
}
JUDGE_STATUSES = {
    "SUPPORTED",
    "INFERABLE",
    "EXTERNAL_CORRECT",
    "UNSUPPORTED",
    "INCORRECT",
    "CONTRADICTS_SOURCE",
    "UNCERTAIN",
}
CONFIDENCES = {"high", "medium", "low"}
_SENTENCE_END = re.compile(r"[。！？!?；;\n]+")
_SPACE = re.compile(r"\s+")
_CJK_OR_WORD = re.compile(r"[0-9A-Za-z\u3400-\u9fff]+")
_SCRIPT_MARKER = re.compile(r"^segment\s+\d+\s*:\s*$", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(value: Any) -> str:
    return _SPACE.sub("", str(value or "")).lower()


def _normalized_with_spans(value: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize whitespace while retaining offsets in the original text."""

    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(str(value or "")):
        part = _normalize(character)
        for item in part:
            normalized.append(item)
            spans.append((index, index + 1))
    return "".join(normalized), spans


def _tokens(value: Any) -> list[str]:
    return _CJK_OR_WORD.findall(str(value or "").lower())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_span(value: Any, text: str) -> tuple[int, int] | None:
    if not isinstance(value, list) or len(value) != 2:
        return None
    start = _number(value[0])
    end = _number(value[1])
    if start is None or end is None or int(start) != start or int(end) != end:
        return None
    start, end = int(start), int(end)
    if start < 0 or end <= start or end > len(text):
        return None
    return start, end


def _sentence_units(
    text: str, *, source_artifact: str, slide: int | str | None = None
) -> list[dict[str, Any]]:
    """Split one candidate artifact deterministically while retaining spans."""

    units: list[dict[str, Any]] = []
    cursor = 0
    for match in _SENTENCE_END.finditer(text):
        raw_end = match.end()
        fragment = text[cursor:raw_end]
        left = len(fragment) - len(fragment.lstrip())
        right = len(fragment.rstrip())
        if right > left:
            units.append(
                {
                    "source_artifact": source_artifact,
                    "slide": slide,
                    "text": fragment[left:right],
                    "character_span": [cursor + left, cursor + right],
                }
            )
        cursor = raw_end
    if cursor < len(text):
        fragment = text[cursor:]
        left = len(fragment) - len(fragment.lstrip())
        right = len(fragment.rstrip())
        if right > left:
            units.append(
                {
                    "source_artifact": source_artifact,
                    "slide": slide,
                    "text": fragment[left:right],
                    "character_span": [cursor + left, cursor + right],
                }
            )
    return units


def _infer_claim_type(text: str) -> str:
    normalized = _normalize(text)
    if re.search(
        r"^(接下来|下面|让我们|我们来看|请注意|思考一下|试着|现在来|请|观察|try|let's|now|consider|please)",
        text.strip(),
        re.I,
    ):
        return "PEDAGOGICAL_INSTRUCTION"
    if re.search(r"(定义|是指|指的是|称为|意味着|definition|means|refers to)", text, re.I):
        return "DEFINITION"
    if re.search(
        r"(因为|由于|因此|导致|从而|使得|原因|because|therefore|causes?|leads? to)", text, re.I
    ):
        return "CAUSAL"
    if re.search(
        r"(相比|比较|不同于|优于|低于|高于|而不是|compare|different|higher|lower|rather than)",
        text,
        re.I,
    ):
        return "COMPARATIVE"
    if re.search(
        r"(首先|然后|接着|最后|步骤|流程|first|then|next|finally|step|process)", text, re.I
    ):
        return "PROCESS"
    if re.search(
        r"\d|百分比|比例|数量|增长率|年份|每年|percent|ratio|amount|rate|year", text, re.I
    ):
        return "QUANTITATIVE"
    if not normalized or text.strip().endswith(("吗", "？", "?")):
        return "NON_FACTUAL"
    return "FACTUAL"


def _paragraphs(source: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("text") or "")
        for item in source.get("paragraphs", [])
        if isinstance(item, dict) and item.get("id") is not None
    }


def _paragraph_score(claim: str, paragraph: str) -> float:
    left = set(_tokens(claim))
    right = set(_tokens(paragraph))
    if not left or not right:
        return 0.0
    overlap = len(left & right) / max(1, len(left))
    normalized_claim = _normalize(claim)
    normalized_paragraph = _normalize(paragraph)
    substring_bonus = 0.5 if normalized_claim and normalized_claim in normalized_paragraph else 0.0
    return round(overlap + substring_bonus, 6)


def _annotation_priority(
    annotation: dict[str, Any], claim: str, segment: dict[str, Any] | None
) -> list[str]:
    priority: list[str] = []
    segment_concepts = {str(value) for value in (segment or {}).get("knowledge_point_ids", [])}
    for concept in annotation.get("core_concepts", []):
        if not isinstance(concept, dict):
            continue
        concept_id = str(concept.get("id") or "")
        terms = [str(item) for item in concept.get("must_mention_terms", [])]
        if concept_id in segment_concepts or any(
            _normalize(term) in _normalize(claim) for term in terms
        ):
            priority.extend(str(item) for item in concept.get("evidence_paragraphs", []))
    return list(dict.fromkeys(priority))


def retrieve_source_evidence(
    claim: str,
    *,
    source_paragraphs: dict[str, str],
    annotation: dict[str, Any],
    segment: dict[str, Any] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return only frozen source paragraphs, with deterministic provenance."""

    top_k = max(1, min(5, int(top_k)))
    priority = _annotation_priority(annotation, claim, segment)
    scored = [
        {
            "paragraph_id": paragraph_id,
            "text": text,
            "score": _paragraph_score(claim, text),
            "retrieval_source": "annotation_evidence" if paragraph_id in priority else "lexical",
        }
        for paragraph_id, text in source_paragraphs.items()
    ]
    scored.sort(
        key=lambda item: (
            item["paragraph_id"] not in priority,
            -item["score"],
            priority.index(item["paragraph_id"]) if item["paragraph_id"] in priority else 999999,
            item["paragraph_id"],
        )
    )
    return scored[:top_k]


def _valid_quote(quote: Any, paragraph: str) -> bool:
    if not isinstance(quote, str) or not quote.strip():
        return False
    return _normalize(quote) in _normalize(paragraph)


def validate_judge_evidence(
    evidence: Any, source_paragraphs: dict[str, str]
) -> tuple[list[dict[str, str]], str | None]:
    if not isinstance(evidence, list) or not evidence:
        return [], "judge returned no source evidence"
    validated: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            return [], "judge evidence item is not an object"
        paragraph_id = str(item.get("paragraph_id") or "")
        quote = item.get("quote")
        paragraph = source_paragraphs.get(paragraph_id)
        if paragraph is None:
            return [], f"judge cited unknown source paragraph {paragraph_id}"
        if not _valid_quote(quote, paragraph):
            return [], f"judge quote is not present in source paragraph {paragraph_id}"
        validated.append({"paragraph_id": paragraph_id, "quote": str(quote)})
    return validated, None


@dataclass(frozen=True)
class _CallResult:
    parsed: Any | None
    raw_response: str | None
    provenance: dict[str, Any]
    error: str | None = None


class SourceFidelityJudgeAdapter:
    """Controlled extraction/classification adapter using an existing client."""

    def __init__(
        self,
        client: Any,
        *,
        prompt_dir: str | Path | None = None,
        max_retries: int = 1,
        max_tokens: int = 900,
    ) -> None:
        self.client = client
        self.prompt_dir = (
            Path(prompt_dir)
            if prompt_dir
            else Path(__file__).resolve().parents[1] / "rubrics" / "source_fidelity"
        )
        self.max_retries = max(0, int(max_retries))
        self.max_tokens = max(128, int(max_tokens))

    def _call(self, prompt_version: str, filename: str, payload: dict[str, Any]) -> _CallResult:
        rubric_path = self.prompt_dir / filename
        rubric = rubric_path.read_text(encoding="utf-8")
        input_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prompt = f"{rubric.rstrip()}\n\nINPUT (JSON):\n{input_text}\n"
        prompt_sha256 = _sha256_text(prompt)
        input_sha256 = _sha256_text(input_text)
        started = time.perf_counter()
        last_error = "Judge did not return a valid result"
        raw_response: str | None = None
        attempts = 0
        for attempts in range(1, self.max_retries + 2):
            try:
                parsed, raw = self.client.chat(
                    [{"role": "user", "content": prompt}], max_tokens=self.max_tokens
                )
                raw_response = raw if isinstance(raw, str) else str(raw)
                provenance = {
                    "provider": type(self.client).__name__,
                    "model": getattr(self.client, "model", "unknown"),
                    "model_version": getattr(
                        self.client, "model_version", getattr(self.client, "model", "unknown")
                    ),
                    "temperature": 0,
                    "prompt_version": prompt_version,
                    "prompt_sha256": prompt_sha256,
                    "input_sha256": input_sha256,
                    "raw_response": raw_response,
                    "parsed_response": parsed,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "retry_count": attempts - 1,
                    "timestamp": _now(),
                    "source_evidence_ids": [
                        str(item.get("paragraph_id"))
                        for item in payload.get("source_evidence", [])
                        if isinstance(item, dict) and item.get("paragraph_id") is not None
                    ],
                }
                return _CallResult(parsed, raw_response, provenance)
            except Exception as exc:  # noqa: BLE001 - fail closed at evaluator boundary
                last_error = f"{type(exc).__name__}: {exc}"
        return _CallResult(
            None,
            raw_response,
            {
                "provider": type(self.client).__name__,
                "model": getattr(self.client, "model", "unknown"),
                "model_version": getattr(
                    self.client, "model_version", getattr(self.client, "model", "unknown")
                ),
                "temperature": 0,
                "prompt_version": prompt_version,
                "prompt_sha256": prompt_sha256,
                "input_sha256": input_sha256,
                "raw_response": raw_response,
                "parsed_response": None,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "retry_count": max(0, attempts - 1),
                "timestamp": _now(),
                "error": last_error,
                "source_evidence_ids": [
                    str(item.get("paragraph_id"))
                    for item in payload.get("source_evidence", [])
                    if isinstance(item, dict) and item.get("paragraph_id") is not None
                ],
            },
            last_error,
        )

    def extract_claims(self, unit: dict[str, Any]) -> _CallResult:
        return self._call(
            EXTRACTION_PROMPT_VERSION,
            "claim_extraction_v1.txt",
            {
                "candidate_text": unit["text"],
                "source_artifact": unit["source_artifact"],
                "slide": unit.get("slide"),
                "character_span": unit.get("character_span"),
            },
        )

    def classify_claim(
        self, claim: dict[str, Any], source_evidence: list[dict[str, Any]]
    ) -> _CallResult:
        return self._call(
            CLASSIFICATION_PROMPT_VERSION,
            "claim_classification_v1.txt",
            {
                "claim": claim["candidate_text"],
                "claim_context": claim.get("context", ""),
                "claim_type": claim["claim_type"],
                "source_evidence": [
                    {"paragraph_id": item["paragraph_id"], "text": item["text"]}
                    for item in source_evidence
                ],
            },
        )


def _claim_from_unit(
    unit: dict[str, Any], text: str, claim_type: str, span: list[int] | None = None
) -> dict[str, Any]:
    claim_span = span or list(unit["character_span"])
    return {
        "source_artifact": unit["source_artifact"],
        "slide": unit.get("slide"),
        "candidate_text": text,
        "text": text,
        "claim_type": claim_type if claim_type in CLAIM_TYPES else "FACTUAL",
        "context": unit["text"],
        "character_span": claim_span,
    }


def _deterministic_claims(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_claim_from_unit(unit, unit["text"], _infer_claim_type(unit["text"])) for unit in units]


def _is_script_marker(unit: dict[str, Any]) -> bool:
    return bool(_SCRIPT_MARKER.fullmatch(str(unit.get("text") or "").strip()))


def _claim_output(parsed: Any) -> list[dict[str, Any]] | None:
    if isinstance(parsed, dict):
        parsed = parsed.get("claims")
    if not isinstance(parsed, list):
        return None
    return (
        [item for item in parsed if isinstance(item, dict)]
        if all(isinstance(item, dict) for item in parsed)
        else None
    )


def _safe_claim_type(value: Any, fallback: str) -> str:
    value = str(value or fallback).upper()
    return value if value in CLAIM_TYPES else fallback


def _extract_with_adapter(
    units: list[dict[str, Any]], adapter: SourceFidelityJudgeAdapter
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    claims: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    extraction_issues: list[dict[str, Any]] = []
    for unit in units:
        call = adapter.extract_claims(unit)
        calls.append(call.provenance)
        parsed = _claim_output(call.parsed)
        if parsed is None:
            fallback = _claim_from_unit(unit, unit["text"], _infer_claim_type(unit["text"]))
            fallback["_extraction_error"] = call.error or "malformed claim extraction output"
            claims.append(fallback)
            extraction_issues.append(
                {
                    "type": "SOURCE_CLAIM_EXTRACTION_FAILED",
                    "severity": "warning",
                    "message": (
                        f"claim extraction failed for {unit['source_artifact']} "
                        f"slide {unit.get('slide')}"
                    ),
                    "slide": unit.get("slide"),
                    "evidence": call.provenance,
                }
            )
            continue
        if not parsed:
            # An empty model list is valid for a purely presentational unit, but
            # it must not make a deterministic candidate unit disappear from
            # calibration. Retain the unit and let the semantic Judge decide;
            # the extraction warning is exposed for human review.
            fallback = _claim_from_unit(unit, unit["text"], _infer_claim_type(unit["text"]))
            fallback["_extraction_warning"] = (
                "judge returned no claims; deterministic unit retained"
            )
            claims.append(fallback)
            extraction_issues.append(
                {
                    "type": "SOURCE_CLAIM_EXTRACTION_EMPTY",
                    "severity": "warning",
                    "message": (
                        f"claim extraction returned no claims for {unit['source_artifact']} "
                        f"slide {unit.get('slide')}; deterministic unit retained"
                    ),
                    "slide": unit.get("slide"),
                    "evidence": {"unit": unit, "judge": call.provenance},
                }
            )
            continue
        accepted = False
        for item in parsed:
            candidate_text = str(item.get("candidate_text") or item.get("text") or "").strip()
            span = _valid_span(item.get("character_span"), unit["text"])
            if not candidate_text or _normalize(candidate_text) not in _normalize(unit["text"]):
                extraction_issues.append(
                    {
                        "type": "SOURCE_CLAIM_EXTRACTION_FAILED",
                        "severity": "warning",
                        "message": "extracted claim cannot be located in candidate source text",
                        "slide": unit.get("slide"),
                        "evidence": {"unit": unit, "claim": item},
                    }
                )
                continue
            if span is None:
                # The text occurrence is valid, but the model span is not. Keep
                # an explainable deterministic span rather than trusting it.
                normalized_unit, normalized_spans = _normalized_with_spans(unit["text"])
                normalized_claim = _normalize(candidate_text)
                start = normalized_unit.find(normalized_claim)
                if start >= 0 and start + len(normalized_claim) <= len(normalized_spans):
                    first = normalized_spans[start][0]
                    last = normalized_spans[start + len(normalized_claim) - 1][1]
                    span = [first, last]
                else:
                    span = list(unit["character_span"])
            claims.append(
                _claim_from_unit(
                    unit,
                    candidate_text,
                    _safe_claim_type(item.get("claim_type"), _infer_claim_type(candidate_text)),
                    span,
                )
            )
            accepted = True
        if parsed and not accepted:
            fallback = _claim_from_unit(unit, unit["text"], _infer_claim_type(unit["text"]))
            fallback["_extraction_error"] = "all extracted claims were rejected"
            claims.append(fallback)
    return claims, calls, extraction_issues


def _heuristic_status(claim: str, evidence: list[dict[str, Any]]) -> str:
    normalized_claim = _normalize(claim)
    if any(normalized_claim and normalized_claim in _normalize(item["text"]) for item in evidence):
        return "possible_supported"
    if any(_paragraph_score(claim, item["text"]) > 0 for item in evidence):
        return "candidate_overlap"
    return "possible_unsupported_addition"


def _judge_status(
    parsed: Any, source_paragraphs: dict[str, str]
) -> tuple[str, str, list[dict[str, str]], str, str | None]:
    if not isinstance(parsed, dict):
        return "UNCERTAIN", "low", [], "judge output is not an object", "malformed judge output"
    status = str(parsed.get("status") or "").upper()
    confidence = str(parsed.get("confidence") or "low").lower()
    reason = str(parsed.get("reason") or "").strip()
    if status not in JUDGE_STATUSES or confidence not in CONFIDENCES or not reason:
        return (
            "UNCERTAIN",
            "low",
            [],
            "judge output failed the result contract",
            "invalid judge result",
        )
    evidence, error = validate_judge_evidence(parsed.get("evidence"), source_paragraphs)
    if error:
        return "UNCERTAIN", "low", [], error, "evidence mismatch"
    return status, confidence, evidence, reason, None


def _issue_for_claim(claim: dict[str, Any], status: str, reason: str) -> dict[str, Any] | None:
    if status == "UNSUPPORTED":
        return {"type": "SOURCE_CLAIM_UNSUPPORTED", "severity": "warning", "message": reason}
    if status == "INCORRECT":
        return {"type": "SOURCE_CLAIM_INCORRECT", "severity": "major", "message": reason}
    if status == "CONTRADICTS_SOURCE":
        return {"type": "SOURCE_CONTRADICTION", "severity": "major", "message": reason}
    if status == "EXTERNAL_CORRECT":
        return {"type": "SOURCE_EXTERNAL_EXTENSION", "severity": "info", "message": reason}
    if status == "UNCERTAIN":
        return {"type": "SOURCE_CLAIM_UNCERTAIN", "severity": "warning", "message": reason}
    return None


def _calibration(path: Path, claims: list[dict[str, Any]]) -> None:
    lines = [
        "# Source Fidelity v0.2 Calibration",
        "",
        "Human labels are intentionally `pending`; no reliability claim is made before review.",
        "",
        "| Claim | Candidate text | Source evidence | Auto label | Confidence | "
        "Human label | Extraction correct | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for claim in claims:
        evidence = (
            ", ".join(str(item.get("paragraph_id")) for item in claim.get("source_evidence", []))
            or "(none)"
        )
        text = str(claim.get("candidate_text") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            (
                "| {claim_id} | {text} | {evidence} | {status} | {confidence} | "
                "pending | pending |  |"
            ).format(
                claim_id=claim.get("claim_id", ""),
                text=text,
                evidence=evidence,
                status=claim.get("final_status", "UNCERTAIN"),
                confidence=claim.get("confidence", "low"),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_claim_level_source_fidelity(
    context: EvalContext,
    *,
    source: dict[str, Any],
    annotation: dict[str, Any],
    storyboard: dict[str, Any],
    script_text: str,
    script_path: Path | None,
    source_path: Path | None,
    annotation_path: Path | None,
) -> dict[str, Any]:
    paragraphs = _paragraphs(source)
    units: list[dict[str, Any]] = []
    if script_text:
        units.extend(_sentence_units(script_text, source_artifact="script"))
    segments = storyboard.get("segments", []) if isinstance(storyboard, dict) else []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        slide = segment.get("id", index)
        narration = str(segment.get("narration") or "")
        if narration:
            units.extend(
                _sentence_units(narration, source_artifact="storyboard_narration", slide=slide)
            )
        # Body text is included only for actual content fields; titles, labels,
        # badges, navigation, and animation metadata are intentionally omitted.
        for element in segment.get("elements", []):
            if not isinstance(element, dict) or str(element.get("type") or "").lower() in {
                "title",
                "heading",
                "subheading",
                "label",
                "badge",
                "icon",
                "icon_group",
            }:
                continue
            values = [element.get(key) for key in ("text", "description", "content", "quote")]
            body = " ".join(
                str(value) for value in values if isinstance(value, str) and value.strip()
            )
            if body:
                units.extend(_sentence_units(body, source_artifact="storyboard_body", slide=slide))

    # Do not duplicate identical candidate sentences when the script repeats
    # the same narration already present in the storyboard.  Same-text units
    # on different storyboard slides remain distinct claims.
    narration_texts = {
        _normalize(unit["text"])
        for unit in units
        if unit["source_artifact"] == "storyboard_narration"
    }
    unique_units: list[dict[str, Any]] = []
    seen_units: set[tuple[str, str, str]] = set()
    for unit in units:
        normalized_text = _normalize(unit["text"])
        if _is_script_marker(unit):
            continue
        if unit["source_artifact"] == "script" and normalized_text in narration_texts:
            continue
        key = (unit["source_artifact"], str(unit.get("slide")), normalized_text)
        if key in seen_units or not _normalize(unit["text"]):
            continue
        seen_units.add(key)
        unique_units.append(unit)

    adapter = context.source_fidelity_judge
    extraction_calls: list[dict[str, Any]] = []
    extraction_issues: list[dict[str, Any]] = []
    if adapter is None:
        claims = _deterministic_claims(unique_units)
        semantic_status = "unavailable"
        semantic_reason = (
            "Source Fidelity v0.2 Judge is not configured; factual claims are "
            "fail-closed as UNCERTAIN"
        )
    else:
        claims, extraction_calls, extraction_issues = _extract_with_adapter(unique_units, adapter)
        semantic_status = "ok"
        semantic_reason = None

    segment_by_id = {
        str(segment.get("id", index)): segment
        for index, segment in enumerate(segments, start=1)
        if isinstance(segment, dict)
    }
    classification_calls: list[dict[str, Any]] = []
    semantic_issues = list(extraction_issues)
    counts: Counter[str] = Counter()
    output_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(claims, start=1):
        claim = dict(claim)
        extraction_error = claim.pop("_extraction_error", None)
        extraction_warning = claim.pop("_extraction_warning", None)
        if extraction_warning:
            claim["extraction_warning"] = extraction_warning
        claim["claim_id"] = str(claim.get("claim_id") or f"claim_{index:03d}")
        source_evidence = retrieve_source_evidence(
            claim["candidate_text"],
            source_paragraphs=paragraphs,
            annotation=annotation,
            segment=segment_by_id.get(str(claim.get("slide"))),
            top_k=5,
        )
        claim["source_evidence"] = source_evidence
        claim["retrieval_status"] = "ok" if source_evidence else "unavailable"
        claim["retrieval_provenance"] = {
            "top_k": 5,
            "paragraph_ids": [item["paragraph_id"] for item in source_evidence],
            "source_sha256": _sha256(source_path),
        }
        claim["heuristic_status"] = _heuristic_status(claim["candidate_text"], source_evidence)
        claim["judge_status"] = "unavailable"
        claim["semantic_status"] = "unavailable"
        claim["confidence"] = "low"
        claim["reason"] = semantic_reason or "semantic Judge not called for non-factual claim"
        claim["uncertainty"] = ""
        claim["semantic_evidence"] = []
        if claim["claim_type"] in {"NON_FACTUAL", "PEDAGOGICAL_INSTRUCTION"}:
            final_status = "NON_FACTUAL"
            claim["semantic_status"] = "NON_FACTUAL"
        elif extraction_error:
            final_status = "UNCERTAIN"
            claim["judge_status"] = "UNCERTAIN"
            claim["semantic_status"] = "UNCERTAIN"
            claim["reason"] = f"claim extraction failed closed: {extraction_error}"
            semantic_issues.append(
                {
                    "type": "SOURCE_CLAIM_UNCERTAIN",
                    "severity": "warning",
                    "message": claim["reason"],
                    "slide": claim.get("slide"),
                    "evidence": claim,
                }
            )
        elif adapter is None:
            final_status = "UNCERTAIN"
            claim["semantic_status"] = "UNCERTAIN"
            semantic_issues.append(
                {
                    "type": "SOURCE_CLAIM_UNCERTAIN",
                    "severity": "warning",
                    "message": semantic_reason,
                    "slide": claim.get("slide"),
                    "evidence": claim,
                }
            )
        else:
            call = adapter.classify_claim(claim, source_evidence)
            classification_calls.append(call.provenance)
            final_status, confidence, semantic_evidence, reason, error = _judge_status(
                call.parsed, paragraphs
            )
            claim["judge_status"] = final_status
            claim["semantic_status"] = final_status
            claim["confidence"] = confidence
            if isinstance(call.parsed, dict):
                claim["uncertainty"] = str(call.parsed.get("uncertainty") or "")
            claim["semantic_evidence"] = semantic_evidence
            claim["reason"] = reason
            if error == "evidence mismatch":
                semantic_issues.append(
                    {
                        "type": "SOURCE_EVIDENCE_MISMATCH",
                        "severity": "warning",
                        "message": reason,
                        "slide": claim.get("slide"),
                        "evidence": {"claim": claim, "judge_error": error},
                    }
                )
            elif error:
                semantic_issues.append(
                    {
                        "type": "SOURCE_CLAIM_UNCERTAIN",
                        "severity": "warning",
                        "message": reason,
                        "slide": claim.get("slide"),
                        "evidence": {"claim": claim, "judge_error": error},
                    }
                )
            issue = _issue_for_claim(claim, final_status, reason)
            if issue:
                issue["slide"] = claim.get("slide")
                issue["element_id"] = claim.get("claim_id")
                issue["evidence"] = claim
                semantic_issues.append(issue)
        claim["final_status"] = final_status
        counts[final_status] += 1
        output_claims.append(claim)

    factual_count = sum(
        item["claim_type"] not in {"NON_FACTUAL", "PEDAGOGICAL_INSTRUCTION"}
        for item in output_claims
    )
    # UNCERTAIN claims are retained in the raw denominator evidence but are
    # excluded from the supported-rate denominator: no semantic conclusion
    # was established for them.  This makes an unconfigured Judge report
    # ``null`` rather than misrepresenting uncertainty as unsupported.
    evaluable = factual_count - counts["UNCERTAIN"]
    metrics = {
        "claim_count": len(output_claims),
        "factual_claim_count": factual_count,
        "evaluable_factual_claim_count": evaluable,
        "non_factual_count": len(output_claims) - factual_count,
        "supported_count": counts["SUPPORTED"],
        "inferable_count": counts["INFERABLE"],
        "external_extension_count": counts["EXTERNAL_CORRECT"],
        "unsupported_count": counts["UNSUPPORTED"],
        "incorrect_count": counts["INCORRECT"],
        "contradiction_count": counts["CONTRADICTS_SOURCE"],
        "uncertain_count": counts["UNCERTAIN"],
        "source_supported_rate": round((counts["SUPPORTED"] + counts["INFERABLE"]) / evaluable, 6)
        if evaluable
        else None,
        "strict_supported_rate": round(counts["SUPPORTED"] / evaluable, 6) if evaluable else None,
    }
    calibration_path = context.output_root / "source_fidelity_calibration.md"
    _calibration(calibration_path, output_claims)
    details = {
        "version": EVALUATOR_VERSION,
        "semantic_status": semantic_status,
        "semantic_reason": semantic_reason,
        "claims": output_claims,
        "claim_extraction": {
            "method": "deterministic sentence segmentation + controlled LLM extraction"
            if adapter
            else "deterministic sentence segmentation",
            "unit_count": len(unique_units),
            "extraction_call_count": len(extraction_calls),
            "source_artifacts": sorted({unit["source_artifact"] for unit in unique_units}),
        },
        "retrieval": {
            "method": "annotation-priority lexical retrieval",
            "top_k": 5,
            "source_sha256": _sha256(source_path),
            "paragraph_count": len(paragraphs),
        },
        "judge_calls": [*extraction_calls, *classification_calls],
        "calibration_path": str(calibration_path),
        "provenance": {
            "evaluator_version": EVALUATOR_VERSION,
            "source_sha256": _sha256(source_path),
            "annotation_sha256": _sha256(annotation_path),
            "script_sha256": _sha256(script_path),
            "candidate_commit": context.candidate_commit,
            "run_id": context.run_id,
            "judge_configured": adapter is not None,
            "judge_calls": [*extraction_calls, *classification_calls],
            "leakage_scope": [
                "candidate script/storyboard text",
                "frozen source paragraphs",
                "annotation evidence links",
            ],
        },
    }
    return {
        "metrics": metrics,
        "details": details,
        "issues": semantic_issues,
        "evidence_ids": [],
        "status": "unavailable" if adapter is None else "ok",
    }


__all__ = [
    "CLAIM_TYPES",
    "EVALUATOR_VERSION",
    "JUDGE_STATUSES",
    "SourceFidelityJudgeAdapter",
    "evaluate_claim_level_source_fidelity",
    "retrieve_source_evidence",
    "validate_judge_evidence",
]
