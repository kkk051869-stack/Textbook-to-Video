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
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runner import EvalContext

EVALUATOR_VERSION = "source-fidelity-v0.2.1"
EXTRACTION_PROMPT_VERSION = "claim_extraction_v1"
EXTRACTION_RETRY_PROMPT_VERSION = "claim_extraction_retry_v1"
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
_QUESTION_PREFIX = re.compile(
    r"^(?:\u4e3a\u4ec0\u4e48|\u4ec0\u4e48\u662f|\u5982\u4f55|"
    r"\u6211\u4eec\u5e94\u8be5\u5982\u4f55|\u4f60\u80fd\u53d1\u73b0|"
    r"\u90a3\u4e48[\uFF0C,].*[\u5982\u4f55\u600e\u6837])"
)
_TRANSITION_PREFIX = re.compile(
    r"^(?:\u63a5\u4e0b\u6765|\u4e0b\u9762|\u6211\u4eec\u518d\u6765\u770b|"
    r"\u73b0\u5728\u6765\u770b|\u90a3\u4e48)[\uFF0C,]"
)
_DISPLAY_PREFIX = re.compile(r"^(?:\u5c55\u793a|\u56fe\s*\d*\s*)")
_LABEL_SUFFIX = re.compile(
    r"(?:\u56fe|\u7ed3\u6784|\u6d41\u7a0b|\u751f\u4ea7\u7ebf|\u5de5\u5382|"
    r"\u6210\u679c|\u7279\u70b9|\u5347\u7ea7|\u5e03\u5c40)$"
)
UNCERTAINTY_REASONS = {
    "EXTRACTION_INVALID",
    "EXTRACTION_EMPTY",
    "RETRIEVAL_MISS",
    "EVIDENCE_MISMATCH",
    "JUDGE_MALFORMED",
    "JUDGE_ERROR",
    "LOW_CONFIDENCE_CONFLICT",
    "INSUFFICIENT_SOURCE",
    "PARSER_MISMATCH",
    "EVIDENCE_QUOTE_PARAPHRASED",
    "EVIDENCE_QUOTE_NOT_EXACT",
    "EVIDENCE_PARAGRAPH_NOT_FOUND",
    "JUDGE_REFERENCED_UNRETRIEVED_EVIDENCE",
}


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


_EVIDENCE_PUNCTUATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "、": ",",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def _strip_outer_quotes(value: str) -> str:
    text = value.strip()
    quote_pairs = (("\"", "\""), ("'", "'"), ("「", "」"), ("『", "』"))
    for left, right in quote_pairs:
        if text.startswith(left) and text.endswith(right) and len(text) > len(left) + len(right):
            return text[len(left) : -len(right)].strip()
    return text


def _evidence_normalized_with_spans(value: str) -> tuple[str, list[tuple[int, int]]]:
    normalized: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(str(value or "")):
        part = unicodedata.normalize("NFKC", character).translate(_EVIDENCE_PUNCTUATION)
        if part.isspace():
            continue
        for item in part.lower():
            normalized.append(item)
            spans.append((index, index + 1))
    return "".join(normalized), spans


def _find_evidence_span(needle: Any, paragraph: str) -> tuple[int, int] | None:
    if not isinstance(needle, str) or not needle.strip():
        return None
    needle = _strip_outer_quotes(needle)
    normalized_needle, _ = _evidence_normalized_with_spans(needle)
    normalized_paragraph, paragraph_spans = _evidence_normalized_with_spans(paragraph)
    if not normalized_needle:
        return None
    start = normalized_paragraph.find(normalized_needle)
    if start < 0 or start + len(normalized_needle) > len(paragraph_spans):
        return None
    return paragraph_spans[start][0], paragraph_spans[start + len(normalized_needle) - 1][1]


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


def _deterministic_prefilter(text: str) -> str | None:
    """Classify obvious presentation units before asking the extractor."""

    value = str(text or "").strip()
    if not value:
        return "NON_FACTUAL"
    if value.endswith(("?", "？")) or _QUESTION_PREFIX.search(value):
        return "NON_FACTUAL"
    if _TRANSITION_PREFIX.match(value):
        return "NON_FACTUAL"
    if value.startswith(("\u5927\u5bb6\u597d", "\u5e0c\u671b\u4eca\u5929")):
        return "NON_FACTUAL"
    if _DISPLAY_PREFIX.match(value):
        return "NON_FACTUAL"
    if _LABEL_SUFFIX.search(value) and not re.search(
        r"(?:\u662f|\u4e3a|\u5305\u62ec|\u6539\u53d8|\u63a8\u52a8|\u4fc3\u8fdb|\u5bfc\u81f4|"
        r"\u80fd\u591f|\u53ef\u4ee5|\u6b63\u5728|\u9700\u8981|\u5305\u542b|is|are|means|causes?)",
        value,
        re.I,
    ):
        return "NON_FACTUAL"
    return None


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

    top_k = max(1, min(8, int(top_k)))
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
    return _find_evidence_span(quote, paragraph) is not None


def _evidence_token_overlap(left: Any, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _validate_judge_evidence_detailed(
    evidence: Any,
    source_paragraphs: dict[str, str],
    retrieved_paragraphs: dict[str, str],
) -> tuple[list[dict[str, str]], str | None, dict[str, Any] | None]:
    if not isinstance(evidence, list) or not evidence:
        return [], "judge returned no source evidence", {
            "reason": "PARSER_MISMATCH",
            "paragraph_id": None,
            "returned_quote": None,
        }
    validated: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            return [], "judge evidence item is not an object", {
                "reason": "PARSER_MISMATCH",
                "paragraph_id": None,
                "returned_quote": item,
            }
        paragraph_id = str(item.get("paragraph_id") or "")
        evidence_value = item.get("evidence_span")
        if evidence_value is None:
            evidence_value = item.get("quote")
        paragraph = source_paragraphs.get(paragraph_id)
        if paragraph is None:
            return [], f"judge cited unknown source paragraph {paragraph_id}", {
                "reason": "EVIDENCE_PARAGRAPH_NOT_FOUND",
                "paragraph_id": paragraph_id,
                "returned_quote": evidence_value,
                "source_text": None,
            }
        if paragraph_id not in retrieved_paragraphs:
            return [], f"judge cited unretrieved source paragraph {paragraph_id}", {
                "reason": "JUDGE_REFERENCED_UNRETRIEVED_EVIDENCE",
                "paragraph_id": paragraph_id,
                "returned_quote": evidence_value,
                "source_text": paragraph,
            }
        span = _find_evidence_span(evidence_value, paragraph)
        if span is None:
            reason = "EVIDENCE_QUOTE_NOT_EXACT"
            normalized_returned = _normalize(evidence_value)
            if normalized_returned and normalized_returned in _normalize(paragraph):
                reason = "EVIDENCE_SPAN_NORMALIZATION"
            elif any(
                _find_evidence_span(evidence_value, other_text) is not None
                for other_id, other_text in source_paragraphs.items()
                if other_id != paragraph_id
            ):
                reason = "EVIDENCE_WRONG_PARAGRAPH"
            elif _evidence_token_overlap(evidence_value, paragraph) >= 0.5:
                reason = "EVIDENCE_QUOTE_PARAPHRASED"
            return [], f"judge evidence is not an exact span in paragraph {paragraph_id}", {
                "reason": reason,
                "paragraph_id": paragraph_id,
                "returned_quote": evidence_value,
                "source_text": paragraph,
            }
        start, end = span
        canonical_span = paragraph[start:end]
        validated.append(
            {
                "paragraph_id": paragraph_id,
                "evidence_span": canonical_span,
                "quote": canonical_span,
            }
        )
    return validated, None, None


def validate_judge_evidence(
    evidence: Any,
    source_paragraphs: dict[str, str],
    *,
    retrieved_paragraphs: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    retrieved = retrieved_paragraphs or source_paragraphs
    validated, error, _ = _validate_judge_evidence_detailed(
        evidence, source_paragraphs, retrieved
    )
    return validated, error


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

    def extract_claims_retry(self, unit: dict[str, Any]) -> _CallResult:
        return self._call(
            EXTRACTION_RETRY_PROMPT_VERSION,
            "claim_extraction_retry_v1.txt",
            {
                "candidate_text": unit["text"],
                "source_artifact": unit["source_artifact"],
                "slide": unit.get("slide"),
                "character_span": unit.get("character_span"),
                "factual_candidate": True,
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
    unit: dict[str, Any],
    text: str,
    claim_type: str,
    span: list[int] | None = None,
    *,
    extraction_status: str = "deterministic",
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
        "source_span": unit["text"],
        "source_span_range": list(unit["character_span"]),
        "extraction_status": extraction_status,
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


def _item_local_span(item: dict[str, Any], text: str) -> tuple[int, int] | None:
    if item.get("start") is not None or item.get("end") is not None:
        return _valid_span([item.get("start"), item.get("end")], text)
    return _valid_span(item.get("character_span"), text)


def _model_claim_from_item(
    unit: dict[str, Any], item: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    claim_text = str(
        item.get("claim_text")
        or item.get("normalized_claim")
        or item.get("candidate_text")
        or item.get("text")
        or ""
    ).strip()
    source_span = item.get("source_span")
    local_span = _item_local_span(item, unit["text"])
    if source_span is not None and not isinstance(source_span, str):
        return None, "source_span is not a string"
    if isinstance(source_span, str) and source_span:
        exact_start = unit["text"].find(source_span)
        if exact_start < 0:
            return None, "source_span is not an exact substring of candidate text"
        exact_span = (exact_start, exact_start + len(source_span))
        if local_span is not None and local_span != exact_span:
            return None, "start/end do not identify the supplied source_span"
        local_span = exact_span
    elif local_span is not None:
        source_span = unit["text"][local_span[0] : local_span[1]]
    elif claim_text:
        exact_start = unit["text"].find(claim_text)
        if exact_start >= 0:
            local_span = (exact_start, exact_start + len(claim_text))
            source_span = claim_text
    if not claim_text or not source_span or local_span is None:
        return None, "claim_text/source_span cannot be mapped to candidate text"
    global_start = unit["character_span"][0] + local_span[0]
    global_end = unit["character_span"][0] + local_span[1]
    claim = _claim_from_unit(
        unit,
        claim_text,
        _safe_claim_type(item.get("claim_type"), _infer_claim_type(claim_text)),
        [global_start, global_end],
        extraction_status="model",
    )
    claim["source_span"] = source_span
    claim["source_span_range"] = [global_start, global_end]
    return claim, None


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
            retry = adapter.extract_claims_retry(unit)
            calls.append(retry.provenance)
            retry_parsed = _claim_output(retry.parsed)
            if retry_parsed:
                parsed = retry_parsed
            else:
                extraction_code = (
                    "EXTRACTION_EMPTY" if retry_parsed == [] else "EXTRACTION_INVALID"
                )
                fallback = _claim_from_unit(
                    unit,
                    unit["text"],
                    _infer_claim_type(unit["text"]),
                    extraction_status=(
                        "empty" if extraction_code == "EXTRACTION_EMPTY" else "invalid"
                    ),
                )
                fallback["_extraction_error"] = extraction_code
                claims.append(fallback)
                extraction_issues.append(
                    {
                        "type": "SOURCE_CLAIM_EXTRACTION_EMPTY",
                        "severity": "warning",
                        "message": (
                            f"claim extraction remained empty after retry for "
                            f"{unit['source_artifact']} slide {unit.get('slide')}"
                        ),
                        "slide": unit.get("slide"),
                        "evidence": {
                            "unit": unit,
                            "judge": call.provenance,
                            "retry": retry.provenance,
                        },
                    }
                )
                continue
        accepted = False
        invalid_item_errors: list[str] = []
        for item in parsed:
            claim, error = _model_claim_from_item(unit, item)
            if error:
                invalid_item_errors.append(error)
                extraction_issues.append(
                    {
                        "type": "SOURCE_CLAIM_EXTRACTION_FAILED",
                        "severity": "warning",
                        "message": (
                            "extracted claim cannot be mapped to exact candidate source_span"
                        ),
                        "slide": unit.get("slide"),
                        "evidence": {"unit": unit, "claim": item, "reason": error},
                    }
                )
                continue
            claims.append(claim)
            accepted = True
        if parsed and not accepted:
            fallback = _claim_from_unit(
                unit, unit["text"], _infer_claim_type(unit["text"]), extraction_status="invalid"
            )
            fallback["_extraction_error"] = "EXTRACTION_INVALID"
            claims.append(fallback)
            extraction_issues.append(
                {
                    "type": "SOURCE_CLAIM_EXTRACTION_FAILED",
                    "severity": "warning",
                    "message": "all extracted claims were rejected",
                    "slide": unit.get("slide"),
                    "evidence": {"unit": unit, "errors": invalid_item_errors},
                }
            )
    return claims, calls, extraction_issues


def _heuristic_status(claim: str, evidence: list[dict[str, Any]]) -> str:
    normalized_claim = _normalize(claim)
    if any(normalized_claim and normalized_claim in _normalize(item["text"]) for item in evidence):
        return "possible_supported"
    if any(_paragraph_score(claim, item["text"]) > 0 for item in evidence):
        return "candidate_overlap"
    return "possible_unsupported_addition"


def _judge_status(
    parsed: Any,
    source_paragraphs: dict[str, str],
    all_source_paragraphs: dict[str, str] | None = None,
) -> dict[str, Any]:
    all_source_paragraphs = all_source_paragraphs or source_paragraphs
    if not isinstance(parsed, dict):
        return {
            "judge_status": "UNCERTAIN",
            "final_status": "UNCERTAIN",
            "confidence": "low",
            "evidence": [],
            "reason": "judge output is not an object",
            "error": "malformed judge output",
            "evidence_status": "invalid",
            "uncertainty_reason": "JUDGE_MALFORMED",
            "diagnostic": {"reason": "PARSER_MISMATCH", "paragraph_id": None},
        }
    status = str(parsed.get("status") or "").upper()
    confidence = str(parsed.get("confidence") or "low").lower()
    reason = str(parsed.get("reason") or "").strip()
    if status not in JUDGE_STATUSES or confidence not in CONFIDENCES or not reason:
        return {
            "judge_status": "UNCERTAIN",
            "final_status": "UNCERTAIN",
            "confidence": "low",
            "evidence": [],
            "reason": "judge output failed the result contract",
            "error": "invalid judge result",
            "evidence_status": "invalid",
            "uncertainty_reason": "JUDGE_MALFORMED",
            "diagnostic": {"reason": "PARSER_MISMATCH", "paragraph_id": None},
        }
    evidence, error, diagnostic = _validate_judge_evidence_detailed(
        parsed.get("evidence"), all_source_paragraphs, source_paragraphs
    )
    if error:
        return {
            "judge_status": status,
            "final_status": "UNCERTAIN",
            "confidence": confidence,
            "evidence": [],
            "reason": reason or error,
            "error": "evidence mismatch",
            "evidence_status": "invalid",
            "uncertainty_reason": (
                diagnostic.get("reason") if diagnostic else "EVIDENCE_MISMATCH"
            ),
            "diagnostic": diagnostic,
        }
    return {
        "judge_status": status,
        "final_status": status,
        "confidence": confidence,
        "evidence": evidence,
        "reason": reason,
        "error": None,
        "evidence_status": "valid",
        "uncertainty_reason": None,
        "diagnostic": None,
    }


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


def _evidence_diagnostics_report(path: Path, diagnostics: list[dict[str, Any]]) -> None:
    lines = [
        "# Source Fidelity v0.2.1 Evidence Diagnostics",
        "",
        (
            "Only evidence validation failures are listed. Model labels are retained; "
            "no validation rule is relaxed."
        ),
        "",
        (
            "| Claim | Judge label | Paragraph ID | Returned evidence span | Source text | "
            "Mismatch reason |"
        ),
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in diagnostics:
        def cell(value: Any) -> str:
            return str(value or "(none)").replace("|", "\\|").replace("\n", " ")

        lines.append(
            "| {claim} | {label} | {paragraph} | {returned} | {source} | {reason} |".format(
                claim=cell(item.get("claim_id")),
                label=cell(item.get("judge_label")),
                paragraph=cell(item.get("paragraph_id")),
                returned=cell(item.get("returned_quote")),
                source=cell(item.get("source_text")),
                reason=cell(item.get("mismatch_reason")),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _retrieval_diagnostic(
    claim: dict[str, Any],
    source_paragraphs: dict[str, str],
    retrieved_top5: list[dict[str, Any]],
    retrieved_top8: list[dict[str, Any]],
) -> dict[str, Any] | None:
    top5_ids = {str(item["paragraph_id"]) for item in retrieved_top5}
    exact_matches = [
        paragraph_id
        for paragraph_id, paragraph in source_paragraphs.items()
        if _find_evidence_span(claim.get("candidate_text"), paragraph) is not None
    ]
    if not exact_matches or exact_matches[0] in top5_ids:
        return None
    return {
        "reason": "RETRIEVAL_MISS",
        "claim_id": claim.get("claim_id"),
        "paragraph_id": exact_matches[0],
        "top5_paragraph_ids": sorted(top5_ids),
        "top8_paragraph_ids": [str(item["paragraph_id"]) for item in retrieved_top8],
        "resolved_by_top8": exact_matches[0] in {
            str(item["paragraph_id"]) for item in retrieved_top8
        },
    }


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
    factual_candidate_units: list[dict[str, Any]] = []
    prefiltered_claims: list[dict[str, Any]] = []
    for unit in unique_units:
        prefiltered_type = _deterministic_prefilter(unit["text"])
        if prefiltered_type is None:
            factual_candidate_units.append(unit)
            continue
        prefiltered_claims.append(
            _claim_from_unit(
                unit,
                unit["text"],
                prefiltered_type,
                extraction_status="prefiltered_non_factual",
            )
        )
    if adapter is None:
        claims = prefiltered_claims + _deterministic_claims(factual_candidate_units)
        semantic_status = "unavailable"
        semantic_reason = (
            "Source Fidelity v0.2.1 Judge is not configured; factual claims are "
            "fail-closed as UNCERTAIN"
        )
    else:
        extracted_claims, extraction_calls, extraction_issues = _extract_with_adapter(
            factual_candidate_units, adapter
        )
        claims = prefiltered_claims + extracted_claims
        claims.sort(
            key=lambda item: (
                str(item.get("source_artifact")),
                str(item.get("slide")),
                list(item.get("source_span_range") or item.get("character_span") or [0])[0],
            )
        )
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
    evidence_diagnostics: list[dict[str, Any]] = []
    for index, claim in enumerate(claims, start=1):
        claim = dict(claim)
        extraction_error = claim.pop("_extraction_error", None)
        claim["claim_id"] = str(claim.get("claim_id") or f"claim_{index:03d}")
        source_evidence = retrieve_source_evidence(
            claim["candidate_text"],
            source_paragraphs=paragraphs,
            annotation=annotation,
            segment=segment_by_id.get(str(claim.get("slide"))),
            top_k=5,
        )
        source_evidence_top8 = retrieve_source_evidence(
            claim["candidate_text"],
            source_paragraphs=paragraphs,
            annotation=annotation,
            segment=segment_by_id.get(str(claim.get("slide"))),
            top_k=8,
        )
        claim["source_evidence"] = source_evidence
        claim["retrieval_status"] = "ok" if source_evidence else "unavailable"
        claim["retrieval_provenance"] = {
            "top_k": 5,
            "paragraph_ids": [item["paragraph_id"] for item in source_evidence],
            "top5_paragraph_ids": [item["paragraph_id"] for item in source_evidence],
            "top8_paragraph_ids": [item["paragraph_id"] for item in source_evidence_top8],
            "source_sha256": _sha256(source_path),
        }
        claim["heuristic_status"] = _heuristic_status(claim["candidate_text"], source_evidence)
        claim["judge_status"] = "unavailable"
        claim["semantic_status"] = "unavailable"
        claim["evidence_status"] = "not_checked"
        claim["judge_evidence"] = []
        claim["confidence"] = "low"
        claim["reason"] = semantic_reason or "semantic Judge not called for non-factual claim"
        claim["uncertainty"] = ""
        claim["uncertainty_reason"] = None
        claim["semantic_evidence"] = []
        retrieval_diagnostic = _retrieval_diagnostic(
            claim, paragraphs, source_evidence, source_evidence_top8
        )
        if retrieval_diagnostic:
            claim["retrieval_diagnostic"] = retrieval_diagnostic
            semantic_issues.append(
                {
                    "type": "SOURCE_RETRIEVAL_MISS",
                    "severity": "warning",
                    "message": "exact source evidence was outside the top-5 retrieved paragraphs",
                    "slide": claim.get("slide"),
                    "element_id": claim.get("claim_id"),
                    "evidence": retrieval_diagnostic,
                }
            )
        if claim["claim_type"] in {"NON_FACTUAL", "PEDAGOGICAL_INSTRUCTION"}:
            final_status = "NON_FACTUAL"
            claim["semantic_status"] = "NON_FACTUAL"
        elif extraction_error:
            final_status = "UNCERTAIN"
            claim["judge_status"] = "UNCERTAIN"
            claim["semantic_status"] = "UNCERTAIN"
            claim["evidence_status"] = "not_checked"
            claim["uncertainty_reason"] = (
                extraction_error
                if extraction_error in UNCERTAINTY_REASONS
                else "EXTRACTION_INVALID"
            )
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
            claim["uncertainty_reason"] = "JUDGE_ERROR"
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
            judge_result = _judge_status(
                call.parsed,
                {
                    str(item["paragraph_id"]): str(item["text"])
                    for item in source_evidence
                },
                paragraphs,
            )
            final_status = judge_result["final_status"]
            claim["judge_status"] = judge_result["judge_status"]
            claim["semantic_status"] = judge_result["judge_status"]
            claim["evidence_status"] = judge_result["evidence_status"]
            claim["confidence"] = judge_result["confidence"]
            if isinstance(call.parsed, dict):
                claim["uncertainty"] = str(call.parsed.get("uncertainty") or "")
                claim["judge_evidence"] = call.parsed.get("evidence") or []
            claim["semantic_evidence"] = judge_result["evidence"]
            claim["reason"] = judge_result["reason"]
            claim["uncertainty_reason"] = judge_result["uncertainty_reason"]
            if judge_result["diagnostic"]:
                diagnostic = {
                    "claim_id": claim["claim_id"],
                    "judge_label": claim["judge_status"],
                    "returned_quote": judge_result["diagnostic"].get("returned_quote"),
                    "paragraph_id": judge_result["diagnostic"].get("paragraph_id"),
                    "source_text": judge_result["diagnostic"].get("source_text"),
                    "mismatch_reason": judge_result["diagnostic"].get("reason"),
                }
                evidence_diagnostics.append(diagnostic)
                semantic_issues.append(
                    {
                        "type": "SOURCE_EVIDENCE_MISMATCH",
                        "severity": "warning",
                        "message": judge_result["reason"],
                        "slide": claim.get("slide"),
                        "evidence": {"claim": claim, "diagnostic": diagnostic},
                    }
                )
            elif judge_result["error"]:
                semantic_issues.append(
                    {
                        "type": "SOURCE_CLAIM_UNCERTAIN",
                        "severity": "warning",
                        "message": judge_result["reason"],
                        "slide": claim.get("slide"),
                        "evidence": {"claim": claim, "judge_error": judge_result["error"]},
                    }
                )
            issue = _issue_for_claim(claim, final_status, judge_result["reason"])
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
    extraction_retry_count = sum(
        call.get("prompt_version") == EXTRACTION_RETRY_PROMPT_VERSION
        for call in extraction_calls
    )
    retrieved_claim_count = sum(bool(item.get("source_evidence")) for item in output_claims)
    evidence_valid_count = sum(item.get("evidence_status") == "valid" for item in output_claims)
    evidence_mismatch_count = len(evidence_diagnostics)
    retrieval_miss_count = sum(
        bool(item.get("retrieval_diagnostic")) for item in output_claims
    )
    quote_mismatch_count = sum(
        item.get("mismatch_reason")
        in {"EVIDENCE_QUOTE_NOT_EXACT", "EVIDENCE_QUOTE_PARAPHRASED", "EVIDENCE_SPAN_NORMALIZATION"}
        for item in evidence_diagnostics
    )
    paragraph_mismatch_count = sum(
        item.get("mismatch_reason")
        in {
            "EVIDENCE_PARAGRAPH_NOT_FOUND",
            "EVIDENCE_WRONG_PARAGRAPH",
            "JUDGE_REFERENCED_UNRETRIEVED_EVIDENCE",
        }
        for item in evidence_diagnostics
    )
    uncertainty_reason_counts = Counter(
        item.get("uncertainty_reason") or "UNKNOWN"
        for item in output_claims
        if item.get("final_status") == "UNCERTAIN"
    )
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
        "candidate_unit_count": len(unique_units),
        "factual_candidate_unit_count": len(factual_candidate_units),
        "non_factual_candidate_unit_count": len(unique_units) - len(factual_candidate_units),
        "extracted_claim_count": sum(
            item.get("extraction_status") == "model" for item in output_claims
        ),
        "atomic_claim_count": sum(
            item.get("extraction_status") == "model" for item in output_claims
        ),
        "empty_factual_candidate_count": sum(
            item.get("extraction_status") == "empty" for item in output_claims
        ),
        "invalid_span_count": sum(
            item.get("extraction_status") == "invalid" for item in output_claims
        ),
        "extraction_retry_count": extraction_retry_count,
        "retrieved_claim_count": retrieved_claim_count,
        "evidence_valid_count": evidence_valid_count,
        "evidence_mismatch_count": evidence_mismatch_count,
        "retrieval_miss_count": retrieval_miss_count,
        "quote_mismatch_count": quote_mismatch_count,
        "paragraph_mismatch_count": paragraph_mismatch_count,
        "evidence_valid_rate": round(evidence_valid_count / len(classification_calls), 6)
        if classification_calls
        else None,
    }
    calibration_path = context.output_root / "source_fidelity_calibration.md"
    _calibration(calibration_path, output_claims)
    diagnostics_path = context.output_root / "source_fidelity_evidence_diagnostics.md"
    _evidence_diagnostics_report(diagnostics_path, evidence_diagnostics)
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
            "factual_candidate_unit_count": len(factual_candidate_units),
            "non_factual_candidate_unit_count": len(unique_units) - len(factual_candidate_units),
            "extracted_claim_count": metrics["extracted_claim_count"],
            "atomic_claim_count": metrics["atomic_claim_count"],
            "empty_factual_candidate_count": metrics["empty_factual_candidate_count"],
            "invalid_span_count": metrics["invalid_span_count"],
            "retry_count": extraction_retry_count,
            "source_artifacts": sorted({unit["source_artifact"] for unit in unique_units}),
        },
        "retrieval": {
            "method": "annotation-priority lexical retrieval",
            "top_k": 5,
            "comparison_top_k": 8,
            "source_sha256": _sha256(source_path),
            "paragraph_count": len(paragraphs),
            "retrieved_claim_count": retrieved_claim_count,
            "retrieval_miss_count": retrieval_miss_count,
        },
        "evidence": {
            "valid_count": evidence_valid_count,
            "mismatch_count": evidence_mismatch_count,
            "quote_mismatch_count": quote_mismatch_count,
            "paragraph_mismatch_count": paragraph_mismatch_count,
            "valid_rate": metrics["evidence_valid_rate"],
            "diagnostics_path": str(diagnostics_path),
            "diagnostics": evidence_diagnostics,
        },
        "uncertainty_reason_counts": dict(uncertainty_reason_counts),
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
