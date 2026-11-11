"""Comparable proposition-to-visual binding methods for P0.

All methods return the same result shape and are side-effect free.  They do
not alter the production storyboard.  ``direct_llm_vlm`` is intentionally an
adapter: experiments can inject a cloud LLM/VLM callable, while unit tests
and offline runs use a persisted response or a deterministic stub.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_images, chat_with_system, redact_response_text

from .source_evidence import lexical_score

BINDING_VERSION = "p0-binding-methods-v1.0"
CONTEXT_FOCUS_VERSION = "source-context-teaching-focus-v1.1"
CONTEXT_EVIDENCE_VERSION = "context-evidence-v1.1.1"
CONTEXT_REVISABLE_VERSION = "source-context-teaching-focus-v1.2"
CONTEXT_SEMANTIC_VERSION = "source-context-teaching-focus-v1.3"


class BindingValidationError(ValueError):
    """Located feedback for bounded correction; never supplies a target answer."""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("; ".join(f"{v['path']}: {v['message']}" for v in issues))


TEACHING_FOCUS_RULES = (
    "Select a source-supported instructional focus, which may be an actor, patient, input, "
    "output, or relation. Do not confuse grammatical actor identification with teaching attention.",
    "Explain the candidate's role in this proposition using source evidence; label overlap, "
    "page proximity and a literal citation alone do not establish semantic support.",
    "A reasonable object selection does not establish sufficient visual explanation: "
    "input/output relations, readability and final presentation are evaluated separately.",
)
ACTOR_BINDING_RULES = (
    "This experiment requires the semantic actor: the candidate must denote the entity "
    "performing the proposition's action, not merely a relevant visual attention target.",
    "A patient, input, output or result alone is not an actor match. Literal source and label "
    "quotes establish provenance, not identity between the candidate and actor_quote.",
    "Resolve passive voice and pronouns from source evidence, not grammatical position or "
    "label overlap alone. Do not rename a patient as actor to satisfy the contract.",
    "If the actor is absent, negated, ambiguous or not distinguishable at candidate granularity, "
    "preserve non-support or uncertainty; do not substitute its data or a neighboring module.",
)
BindingModel = Callable[[str], str]
EmbeddingFn = Callable[[str], Sequence[float]]


def _quote_anchors(source: str, quote: str) -> list[dict[str, Any]]:
    """Locate typographic quotes, retaining every original source span.

    Spaces are collapsed, never deleted: ``re calculate`` cannot match
    ``recalculate``. Only Latin presentation ligatures are expanded; punctuation,
    case, mathematical notation and lexical content stay exact.
    """

    def mapped(value: str) -> tuple[str, list[tuple[int, int]]]:
        ligatures = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
        chars, offsets = [], []
        for match in re.finditer(r"\s+|\S", value):
            replacement = (
                " " if match.group().isspace() else ligatures.get(match.group(), match.group())
            )
            chars.append(replacement)
            offsets.extend([(match.start(), match.end())] * len(replacement))
        return "".join(chars), offsets

    if not quote.strip():
        return []
    normalized, offsets = mapped(source)
    needle, _ = mapped(quote.strip())
    anchors = []
    cursor = 0
    while (start := normalized.find(needle, cursor)) >= 0:
        begin, end = offsets[start][0], offsets[start + len(needle) - 1][1]
        original = source[begin:end]
        if mapped(original)[0] != needle:
            # Never accept a match ending inside an expanded ligature.
            cursor = start + 1
            continue
        anchors.append(
            {
                "start": begin,
                "end": end,
                "source_text": original,
                "submitted_quote": quote,
                "match_mode": (
                    "exact"
                    if original == quote
                    else (
                        "whitespace_equivalent"
                        if re.sub(r"\s+", " ", original) == re.sub(r"\s+", " ", quote.strip())
                        else "latin_ligature_equivalent"
                    )
                ),
            }
        )
        cursor = start + 1
    return anchors


def _pdf_text_map(
    text: str, *, dehyphenate: bool, join_words: set[str] | None = None
) -> tuple[str, list[tuple[int, int]]]:
    """Narrow PDF typography normalization with original codepoint offsets.

    Unlike general NFKC, never rewrite mathematical symbols or delete ordinary
    word spaces. Joining requires a real line break and two Latin letters on
    each side; single-letter algebra and suspended 'input- and' stay unchanged.
    """
    skipped: set[int] = set()
    if dehyphenate:
        for match in re.finditer(r"(?<=[A-Za-z]{2})-[ \t]*\r?\n[ \t]*(?=[A-Za-z]{2})", text):
            left = re.search(r"[A-Za-z]+$", text[: match.start()]).group()
            right = re.match(r"[A-Za-z]+", text[match.end() :]).group()
            if left + right in (join_words or set()) and not re.match(
                r"(?:and|or)\b", text[match.end() :], re.I
            ):
                skipped.update(range(match.start(), match.end()))
        for match in re.finditer(r"(?<=[A-Za-z]{2})\u00ad(?=[A-Za-z]{2})", text):
            skipped.add(match.start())
    ligatures = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
    chars, offsets = [], []
    for match in re.finditer(r"\s+|\S", text):
        remaining = [i for i in range(match.start(), match.end()) if i not in skipped]
        if not remaining:
            continue
        value = " " if match.group().isspace() else ligatures.get(match.group(), match.group())
        chars.extend(value)
        offsets.extend([(remaining[0], remaining[-1] + 1)] * len(value))
    if chars and chars[0] == " ":
        chars, offsets = chars[1:], offsets[1:]
    if chars and chars[-1] == " ":
        chars, offsets = chars[:-1], offsets[:-1]
    return "".join(chars), offsets


def _pdf_span_anchors(
    context: str, quote: str, raw: str, *, raw_start: int, provenance: dict[str, Any]
) -> list[dict[str, Any]]:
    plain, plain_offsets = _pdf_text_map(raw, dehyphenate=False)
    visible, context_offsets = _pdf_text_map(context, dehyphenate=False)
    if plain != visible:
        raise ValueError("raw source region does not reproduce the supplied context")
    anchors, seen = [], set()
    join_words = set(provenance["verified_linebreak_join_words"])
    # Keep both the originally supplied spelling and verified line-break joins.
    # Normalizing the source must never reject a previously valid literal quote.
    for dehyphenate in (False, True):
        normalized, offsets = _pdf_text_map(raw, dehyphenate=dehyphenate, join_words=join_words)
        needle, _ = _pdf_text_map(quote, dehyphenate=dehyphenate, join_words=join_words)
        if not needle:
            continue
        cursor = 0
        while (start := normalized.find(needle, cursor)) >= 0:
            cursor = start + 1
            begin, end = offsets[start][0], offsets[start + len(needle) - 1][1]
            if (
                _pdf_text_map(raw[begin:end], dehyphenate=dehyphenate, join_words=join_words)[0]
                != needle
            ):
                continue
            indices = [i for i, (a, b) in enumerate(plain_offsets) if b > begin and a < end]
            a, b = context_offsets[indices[0]][0], context_offsets[indices[-1]][1]
            if (a, b, begin, end) in seen:
                continue
            seen.add((a, b, begin, end))
            exact = next(
                (v for v in _quote_anchors(context, quote) if v["start"] == a and v["end"] == b),
                None,
            )
            anchors.append(
                {
                    **provenance,
                    "start": a,
                    "end": b,
                    "source_text": context[a:b],
                    "submitted_quote": quote,
                    "raw_start": raw_start + begin,
                    "raw_end": raw_start + end,
                    "raw_source_text": raw[begin:end],
                    "match_mode": exact["match_mode"]
                    if exact
                    else "verified_pdf_linebreak_equivalent",
                }
            )
    return anchors


def _context_source_regions(
    context: str, source_refs: Any, evidence: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Resolve existing source-evidence sidecars, never model-supplied provenance."""
    if evidence is None:
        return []
    doc = evidence["document"]
    raw = Path(doc["raw_path"]).read_text(encoding="utf-8")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != doc["sha256"]:
        raise ValueError("raw source hash mismatch")
    # A bare ASCII minus at a newline is ambiguous. Require the joined word to
    # occur independently, unbroken, in the same verified raw document.
    plain_words = set(re.findall(r"[A-Za-z]+", raw))
    join_words = sorted(
        {
            a + b
            for a, b in re.findall(r"([A-Za-z]{2,})-[ \t]*\r?\n[ \t]*([A-Za-z]{2,})", raw)
            if a + b in plain_words and b.lower() not in {"and", "or"}
        }
    )
    regions = []
    for unit in evidence["source_units"]:
        if unit["id"] not in _source_ids(source_refs):
            continue
        span = unit["char_span"]
        a, b = span["start"], span["end"]
        if not (isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(raw)):
            raise ValueError("raw source span invalid")
        region = raw[a:b]
        if region.strip() != unit["text"]:
            raise ValueError("raw source unit text/span mismatch")
        locations = _quote_anchors(context, region)
        if not locations:
            raise ValueError("source reference region is absent from context")
        for location in locations:
            regions.append(
                {
                    "context_start": location["start"],
                    "context_end": location["end"],
                    "raw": region,
                    "raw_start": a,
                    "provenance": {
                        "source_ref": unit["id"],
                        "source_locator": unit["source_locator"],
                        "raw_path": doc["raw_path"],
                        "raw_document_sha256": doc["sha256"],
                        "verified_linebreak_join_words": join_words,
                    },
                }
            )
    if not regions:
        raise ValueError("source_refs do not resolve to raw evidence regions")
    return regions


def _evidence_anchors(
    context: str, quote: str, regions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not regions:
        return _quote_anchors(context, quote)
    anchors = []
    for region in regions:
        a, b = region["context_start"], region["context_end"]
        for anchor in _pdf_span_anchors(
            context[a:b],
            quote,
            region["raw"],
            raw_start=region["raw_start"],
            provenance=region["provenance"],
        ):
            anchors.append({**anchor, "start": a + anchor["start"], "end": a + anchor["end"]})
    return anchors


def _role_evidence_anchors(anchor: dict[str, Any], phrase: str) -> list[dict[str, Any]]:
    if "raw_source_text" not in anchor:
        return _quote_anchors(anchor["source_text"], phrase)
    return _pdf_span_anchors(
        anchor["source_text"],
        phrase,
        anchor["raw_source_text"],
        raw_start=anchor["raw_start"],
        provenance={
            k: anchor[k]
            for k in (
                "source_ref",
                "source_locator",
                "raw_path",
                "raw_document_sha256",
                "verified_linebreak_join_words",
            )
        },
    )


def _candidate_text(candidate: dict[str, Any]) -> str:
    fields = ("text", "description", "caption", "title", "label", "alt", "name")
    values: list[str] = []
    for field in fields:
        value = candidate.get(field)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(value.strip() for value in values if value and value.strip())


def _candidate_image_path(candidate: dict[str, Any]) -> str | None:
    """Return an existing local image candidate for a real VLM comparison."""
    for key in ("local_path", "image_path", "path"):
        value = candidate.get(key)
        if value and Path(str(value)).is_file():
            return str(Path(str(value)))
    return None


def _prop_id(proposition: dict[str, Any]) -> str:
    return str(proposition.get("id") or proposition.get("proposition_id") or "")


def _source_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        value = [value] if value else []
    result: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            for key in ("source_unit_id", "source_image_id", "id", "source_locator"):
                if item.get(key):
                    result.add(str(item[key]))
        elif str(item).strip():
            result.add(str(item).strip())
    return result


def _eligible_candidates(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    segment_id = str(proposition.get("segment_id") or "")
    eligible = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not str(candidate.get("id") or "").strip():
            continue
        candidate_segment = str(candidate.get("segment_id") or "")
        if candidate_segment and segment_id and candidate_segment != segment_id:
            continue
        if str(candidate.get("teaching_asset_status") or "").startswith("INELIGIBLE_"):
            continue
        eligible.append(candidate)
    return eligible


def _result(
    method: str,
    proposition: dict[str, Any],
    *,
    selected: dict[str, Any] | None,
    score: float = 0.0,
    threshold: float | None = None,
    evidence: list[dict[str, Any]] | None = None,
    status: str | None = None,
    rationale: str = "",
    **extra: Any,
) -> dict[str, Any]:
    selected_id = str(selected.get("id") or "") if selected else None
    if status is None:
        status = "BOUND" if selected else "ABSTAINED_NO_ACCEPTABLE_RESULT"
    confidence = round(max(0.0, min(1.0, float(score))), 4)
    return {
        "schema_version": BINDING_VERSION,
        "method": method,
        "proposition_id": _prop_id(proposition),
        "segment_id": str(proposition.get("segment_id") or ""),
        "selected_candidate_id": selected_id,
        "score": round(float(score), 4),
        "confidence": confidence,
        "threshold": threshold,
        "status": status,
        "evidence": evidence or [],
        "rationale": rationale,
        **extra,
    }


def bind_lexical(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    threshold: float = 0.25,
) -> dict[str, Any]:
    """Transparent lexical overlap baseline."""
    eligible = _eligible_candidates(proposition, candidates)
    scored = [
        (lexical_score(str(proposition.get("text") or ""), _candidate_text(candidate)), candidate)
        for candidate in eligible
    ]
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or "")))
    score, selected = scored[0] if scored else (0.0, None)
    return _result(
        "lexical",
        proposition,
        selected=selected if score >= threshold else None,
        score=score,
        threshold=threshold,
        evidence=[{"kind": "token_overlap", "overlap_score": score}],
        rationale="character/word n-gram overlap; not semantic entailment",
        candidate_count=len(eligible),
    )


def _hash_embedding(text: str, dimensions: int = 256) -> list[float]:
    """Dependency-free hashed n-gram embedding used only as an offline fallback."""
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
    tokens += [f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1)]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) ** 2 for a in left))
    right_norm = math.sqrt(sum(float(b) ** 2 for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def make_sentence_transformer_embedding(model_name: str) -> EmbeddingFn:
    """Create a real, named embedding backend for a reproducible experiment.

    Importing the optional dependency is deliberately deferred: normal
    production/P0 rendering stays dependency-free, while an experiment fails
    loudly instead of silently substituting the hashing fallback.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - installation dependent
        raise RuntimeError(
            "embedding_model requires sentence-transformers; install it in the "
            "experiment environment"
        ) from exc
    encoder = SentenceTransformer(model_name)

    def embed(text: str) -> Sequence[float]:
        return encoder.encode(str(text), normalize_embeddings=True).tolist()

    return embed


def bind_embedding(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    embed_fn: EmbeddingFn | None = None,
    threshold: float = 0.20,
) -> dict[str, Any]:
    """Embedding cosine baseline with an explicit offline backend label."""
    backend = "injected_embedding_function" if embed_fn else "deterministic_hashing_fallback"
    embed = embed_fn or _hash_embedding
    eligible = _eligible_candidates(proposition, candidates)
    query = str(proposition.get("text") or "")
    query_vector = list(embed(query))
    scored = [
        (_cosine(query_vector, list(embed(_candidate_text(candidate)))), candidate)
        for candidate in eligible
    ]
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or "")))
    score, selected = scored[0] if scored else (0.0, None)
    return _result(
        "embedding",
        proposition,
        selected=selected if score >= threshold else None,
        score=score,
        threshold=threshold,
        evidence=[{"kind": "embedding_cosine", "backend": backend, "cosine": round(score, 4)}],
        rationale="cosine similarity over proposition and candidate text",
        candidate_count=len(eligible),
        embedding_backend=backend,
    )


def _parse_model_json(raw: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("direct LLM/VLM binding did not return JSON")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("direct LLM/VLM binding must return an object")
    return value


def bind_direct_llm_vlm(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    model_fn: BindingModel | None = None,
    model: str | None = None,
    use_vision: bool = True,
    required_target_role: str | None = None,
) -> dict[str, Any]:
    """Direct comparator; use candidate pixels when a VLM and images are available.

    Text-only execution remains possible for old pools, but the returned
    ``comparator_mode`` makes that fallback explicit instead of calling it a
    VLM result.
    """
    if required_target_role not in {None, "actor"}:
        raise ValueError("unsupported binding target role")
    eligible = _eligible_candidates(proposition, candidates)
    prompt = json.dumps(
        {
            "task": "Bind one narration proposition to at most one candidate visual.",
            "rules": [
                "Return abstain=true when no candidate is clearly explanatory.",
                "Do not reward decoration or shared vocabulary alone.",
                "selected_candidate_id must be one of the supplied IDs or null.",
            ]
            + (
                list(ACTOR_BINDING_RULES)
                if required_target_role == "actor"
                else list(TEACHING_FOCUS_RULES)
            ),
            "proposition": proposition,
            "candidates": [
                {
                    "id": candidate.get("id"),
                    "text": _candidate_text(candidate),
                    "caption": candidate.get("caption"),
                    "source_refs": candidate.get("source_refs"),
                }
                for candidate in eligible
            ],
            "output_schema": {
                "selected_candidate_id": "id or null",
                "confidence": "0..1",
                "abstain": "boolean",
                "rationale": "short",
                "rationale_evidence": [],
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    image_paths = [path for candidate in eligible if (path := _candidate_image_path(candidate))]
    if model_fn:
        raw = model_fn(prompt)
        comparator_mode = "CALLER_MODEL_FN"
    elif use_vision and image_paths:
        raw = chat_with_images(
            prompt,
            image_paths,
            system_prompt="You are a strict visual binding judge. Output only valid JSON.",
            model=model,
            temperature=0.0,
            max_tokens=2048,
            timeout=600,
        )
        comparator_mode = "VLM_PIXELS"
    else:
        raw = chat_with_system(
            prompt,
            system_prompt="You are a strict visual binding judge. Output only valid JSON.",
            model=model,
            temperature=0.0,
            max_tokens=2048,
            timeout=600,
        )
        comparator_mode = "LLM_TEXT_FALLBACK"
    parsed = _parse_model_json(raw)
    selected_id = str(parsed.get("selected_candidate_id") or "")
    selected = next((item for item in eligible if str(item.get("id")) == selected_id), None)
    if selected_id and selected is None:
        raise ValueError(f"direct LLM/VLM selected an unknown candidate: {selected_id}")
    abstain = bool(parsed.get("abstain")) or selected is None
    score = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
    return _result(
        "direct_llm_vlm",
        proposition,
        selected=None if abstain else selected,
        score=score,
        evidence=parsed.get("rationale_evidence") or [],
        status="ABSTAINED_NO_ACCEPTABLE_RESULT" if abstain else "BOUND",
        rationale=str(parsed.get("rationale") or "").strip(),
        candidate_count=len(eligible),
        model=model or "configured_default",
        comparator_mode=comparator_mode,
        image_candidate_ids=[
            str(candidate.get("id")) for candidate in eligible if _candidate_image_path(candidate)
        ],
    )


def _binding_issue(path: list[Any], code: str, message: str, candidates: list[dict]) -> dict:
    candidate_id = path[1] if len(path) > 1 and path[0] == "assessment_by_candidate" else None
    candidate = next((c for c in candidates if c["id"] == candidate_id), {})
    return {
        "path": "/" + "/".join(str(p) for p in path),
        "code": code,
        "message": message,
        "candidate_id": candidate_id,
        "source_locator": candidate.get("source_locator"),
    }


def _revisable_evidence_issues(
    value: dict, context: str, regions: list[dict], candidates: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Reuse locators for feedback; do not infer semantic truth or choose IDs."""
    errors, warnings = [], []
    selected = value.get("selected_candidate_ids", [])
    selected = (
        set(selected)
        if isinstance(selected, list) and all(isinstance(x, str) for x in selected)
        else set()
    )
    assessments = value.get("assessment_by_candidate", {})
    if not isinstance(assessments, dict):
        return errors, warnings
    for candidate in candidates:
        ident = candidate["id"]
        row = assessments.get(ident)
        if not isinstance(row, dict):
            continue
        destination = errors if ident in selected else warnings
        base = ["assessment_by_candidate", ident]
        quotes = row.get("source_quotes")
        if not isinstance(quotes, list) or any(not isinstance(q, str) for q in quotes):
            continue  # Schema feedback covers structural failures.
        anchors = [_evidence_anchors(context, q, regions) for q in quotes]
        for i, found in enumerate(anchors):
            if not found:
                destination.append(
                    _binding_issue(
                        base + ["source_quotes", i],
                        "SOURCE_QUOTE_NOT_FOUND",
                        "Quote is not locatable in the supplied source region; preserve exact "
                        "content or uncertainty.",
                        candidates,
                    )
                )
        for field in ("actor_quote", "action_quote", "patient_quote", "focus_quote"):
            phrase = row.get(field)
            if isinstance(phrase, str) and not any(
                _role_evidence_anchors(a, phrase) for group in anchors for a in group
            ):
                destination.append(
                    _binding_issue(
                        base + [field],
                        "ROLE_QUOTE_UNANCHORED",
                        "Phrase is not inside this candidate's submitted source quotes.",
                        candidates,
                    )
                )
        if ident in selected and (
            row.get("support") != "SUPPORTED" or row.get("polarity") != "AFFIRMED"
        ):
            errors.append(
                _binding_issue(
                    base + ["support"],
                    "SELECTED_WITHOUT_SUPPORT",
                    "Selected candidates require affirmative source support, not merely "
                    "topic relevance.",
                    candidates,
                )
            )
        if ident in selected and (
            not quotes or not row.get("focus_quote") or not row.get("attention_role")
        ):
            errors.append(
                _binding_issue(
                    base,
                    "FOCUS_EVIDENCE_REQUIRED",
                    "Selected focus needs source quotes, a focus phrase and a defined role.",
                    candidates,
                )
            )
    return errors, warnings


def _bind_context_relations(
    proposition: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    model_fn: BindingModel,
    threshold: float,
    required_target_role: str | None = None,
    evidence_validation_version: str = "context-evidence-v1.1",
    source_evidence: dict[str, Any] | None = None,
    context_method_version: str = CONTEXT_FOCUS_VERSION,
) -> dict[str, Any]:
    """Use model-produced role evidence; literal validation is not entailment."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

    revisable = context_method_version == CONTEXT_REVISABLE_VERSION

    context = proposition.get("source_context")
    if not isinstance(context, str) or not context.strip():
        return _result(
            "source_conditioned",
            proposition,
            selected=None,
            threshold=threshold,
            status="ABSTAINED_SOURCE_CONTEXT_MISSING",
            source_support=0.0,
            source_support_mode="context_role_model",
            rationale="no source context supplied",
        )
    ids = [str(c["id"]) for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("context binding requires unique candidate IDs")
    if not ids:
        return _result(
            "source_conditioned",
            proposition,
            selected=None,
            threshold=threshold,
            source_support_mode="context_role_model",
            rationale="no eligible candidates",
        )
    reliable = evidence_validation_version == CONTEXT_EVIDENCE_VERSION
    regions = (
        _context_source_regions(context, proposition.get("source_refs"), source_evidence)
        if reliable
        else []
    )
    assessment = {
        "type": "object",
        "properties": {
            "support": {"enum": ["SUPPORTED", "NOT_SUPPORTED", "UNCERTAIN"]},
            "polarity": {"enum": ["AFFIRMED", "NEGATED", "UNRESOLVED"]},
            "source_quotes": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
            "actor_quote": {"type": ["string", "null"]},
            "action_quote": {"type": ["string", "null"]},
            "patient_quote": {"type": ["string", "null"]},
            "candidate_label_quote": {"type": ["string", "null"]},
            "explanation": {"type": "string", "minLength": 1},
        },
        "required": [
            "support",
            "polarity",
            "source_quotes",
            "actor_quote",
            "action_quote",
            "patient_quote",
            "candidate_label_quote",
            "explanation",
        ],
        "additionalProperties": False,
    }
    if required_target_role is None:
        assessment["properties"].update(
            {
                "attention_role": {
                    "enum": ["actor", "patient", "input", "output", "relation", None]
                },
                "focus_quote": {"type": ["string", "null"]},
            }
        )
        assessment["required"].extend(["attention_role", "focus_quote"])
        if revisable:
            assessment["properties"]["attention_role"]["enum"].append("action")
    schema = {
        "type": "object",
        "properties": {
            "assessment_by_candidate": {
                "type": "object",
                "properties": {key: assessment for key in sorted(ids)},
                "required": sorted(ids),
                "additionalProperties": False,
            }
        },
        "required": ["assessment_by_candidate"],
        "additionalProperties": False,
    }
    if required_target_role is None:
        schema["properties"]["joint_focus"] = {
            "type": "object",
            "properties": {
                "candidate_ids": {
                    "type": "array",
                    "items": {"enum": ids},
                    "uniqueItems": True,
                    "minItems": 2,
                },
                "source_quotes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                },
                "explanation": {"type": "string", "minLength": 1},
            },
            "required": ["candidate_ids", "source_quotes", "explanation"],
            "additionalProperties": False,
        }
    if revisable:
        schema["properties"]["selected_candidate_ids"] = {
            "type": "array",
            "items": {"enum": ids},
            "uniqueItems": True,
        }
        schema["properties"]["selection_review"] = {
            "type": "object",
            "properties": {
                "coverage": {"enum": ["SUFFICIENT", "INSUFFICIENT", "UNCERTAIN"]},
                "minimal": {"type": "boolean"},
                "source_quotes": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "member_contributions": {
                    "type": "object",
                    "properties": {k: {"type": "string", "minLength": 1} for k in ids},
                    "additionalProperties": False,
                },
                "explanation": {"type": "string", "minLength": 1},
            },
            "required": [
                "coverage",
                "minimal",
                "source_quotes",
                "member_contributions",
                "explanation",
            ],
            "additionalProperties": False,
        }
        schema["required"].extend(["selected_candidate_ids", "selection_review"])
    prompt = json.dumps(
        {
            "task": (
                "Assess each candidate as a source-supported instructional focus for this "
                "proposition using context and supplied object pixels."
            ),
            "proposition": {
                "id": _prop_id(proposition),
                "text": proposition.get("text"),
                "source_refs": proposition.get("source_refs"),
            },
            "source_context": context,
            "candidates": [
                {
                    "id": c["id"],
                    "text": _candidate_text(c),
                    "source_locator": c.get("source_locator"),
                }
                for c in candidates
            ],
            "rules": [
                "Assess every candidate exactly once. Same page, shared topic, a "
                "source ID or lexical overlap is not semantic support.",
                "SUPPORTED requires this actual object to perform the narrated action "
                "with the correct actor, action and patient. Negation cannot be "
                "affirmative support.",
                "Resolve pronouns using preceding source context and include the "
                "literal antecedent evidence. If unresolved, return UNCERTAIN.",
                "If the narration describes several modules, do not force it onto a "
                "single one; mark each supported role honestly. The program abstains "
                "on multiple supported objects.",
                "If the required operation is absent from this candidate subset, "
                "preserve NOT_SUPPORTED or UNCERTAIN. Never substitute a nearby block.",
                "Every source quote must be an exact nonempty substring of "
                "source_context; actor/action/patient phrases must themselves occur "
                "inside those quotes.",
                "Each actor_quote, action_quote and patient_quote must copy ONE "
                "contiguous source fragment. Never join separated words with invented "
                "ellipses (... or …), brackets, or paraphrases. Copy punctuation "
                "exactly; put interpretation only in explanation.",
                "For a discontinuous or passive predicate, copy a shorter contiguous "
                "action phrase that is actually present; do not assemble the full "
                "grammatical predicate from separate spans. If you cannot provide "
                "valid role evidence, preserve UNCERTAIN rather than inventing a quote.",
                "SUPPORTED needs nonempty actor_quote, action_quote, "
                "candidate_label_quote and source_quotes. candidate_label_quote must "
                "occur literally in supplied candidate text. patient_quote may be null "
                "for an action with no explicit patient.",
                "Do not infer expected answers or claim human verification. Return one "
                "JSON instance conforming to output_json_schema, not the schema itself.",
            ]
            + list(ACTOR_BINDING_RULES),
            "output_json_schema": schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    if required_target_role is None:
        payload = json.loads(prompt)
        payload["rules"] = (
            [
                rule
                for rule in payload["rules"]
                if rule not in ACTOR_BINDING_RULES
                and not rule.startswith(
                    (
                        "SUPPORTED requires",
                        "If the narration describes",
                        "If the required operation",
                        "SUPPORTED needs",
                    )
                )
            ]
            + list(TEACHING_FOCUS_RULES)
            + [
                "SUPPORTED requires AFFIRMED polarity, source_quotes, a literal "
                "candidate_label_quote, "
                "attention_role and focus_quote anchored inside source_quotes. "
                "Actor/action/patient "
                "quotes describe source semantics and may be null; never rename a "
                "patient as actor.",
                "focus_quote identifies the focused entity or relation in the source, "
                "not necessarily "
                "the candidate's literal label. Resolve identity from context in "
                "explanation; abstain "
                "when that relationship is uncertain or negated.",
                "Multiple SUPPORTED objects are not automatically a joint focus. Only "
                "supply joint_focus "
                "when its exact candidate set jointly explains one source-supported "
                "relation; quote "
                "that relation and explain each member's contribution. Otherwise omit joint_focus.",
            ]
        )
        prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    if revisable:
        payload = json.loads(prompt)
        payload["method_version"] = CONTEXT_REVISABLE_VERSION
        payload["rules"] = [
            r for r in payload["rules"] if not r.startswith("Multiple SUPPORTED objects")
        ]
        payload["rules"] = [
            (
                "SUPPORTED requires AFFIRMED polarity, source_quotes, a defined attention_role "
                "and focus_quote anchored inside those quotes. Candidate identity is its supplied "
                "stable ID, not a copied label; candidate_label_quote may be null. "
                "Actor/action/patient quotes may be null, but supplied phrases must be anchored."
                if r.startswith("SUPPORTED requires AFFIRMED")
                else r
            )
            for r in payload["rules"]
        ]
        payload["rules"].extend(
            [
                "SUPPORTED means a usable alternative, not mandatory selection. "
                "Explicitly choose a "
                "minimal sufficient selected_candidate_ids set. An entire relation diagram and its "
                "components may all be supported without all being selected.",
                "For multiple selected foci, joint_focus.candidate_ids must match that "
                "selected set, "
                "not all SUPPORTED candidates. Explain each selected member's distinct "
                "contribution "
                "in selection_review.member_contributions and quote their shared relation.",
                "Review the actual narrated relation, direction, entity types and quantities. "
                "Producing a quantity does not automatically express a different relation defined "
                "over that quantity. Shared terminology is insufficient.",
                "Report SUFFICIENT coverage only when the selected set explains the proposition's "
                "relation using the supplied source and candidates. Otherwise select [] and report "
                "INSUFFICIENT or UNCERTAIN with a reason; never invent missing objects "
                "or citations.",
                "Selection review is your source-grounded self-check, not independent "
                "proof. Do not "
                "claim full visual explanation or learning effectiveness.",
            ]
        )
        prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    raw = model_fn(prompt)
    value = _parse_model_json(raw)
    # Preserve the frozen v1.1 request. Only the independently versioned
    # replay validator admits 'action' as an instructional operation focus.
    validation_schema = copy.deepcopy(schema)
    if reliable and required_target_role is None:
        for item in validation_schema["properties"]["assessment_by_candidate"][
            "properties"
        ].values():
            roles = item["properties"]["attention_role"]["enum"]
            if "action" not in roles:
                roles.append("action")
    validation_warnings = []
    if revisable:
        issues = []
        for error in Draft202012Validator(validation_schema).iter_errors(value):
            path = list(error.absolute_path)
            missing = re.match(r"'([^']+)' is a required property", error.message)
            if missing:
                path.append(missing.group(1))
            issues.append(_binding_issue(path, "SCHEMA", error.message, candidates))
        evidence_issues, validation_warnings = _revisable_evidence_issues(
            value, context, regions, candidates
        )
        issues.extend(evidence_issues)
        if issues:
            raise BindingValidationError(
                issues
                + [{**w, "severity": "UNSELECTED_CANDIDATE_WARNING"} for w in validation_warnings]
            )
    try:
        Draft202012Validator(validation_schema).validate(value)
    except ValidationError as exc:
        raise ValueError(f"context binding response schema invalid: {exc.message}") from exc
    supported = []
    evidence = []
    rejected = []
    for candidate in candidates:
        row = value["assessment_by_candidate"][str(candidate["id"])]
        try:
            quotes = row["source_quotes"]
            quote_anchors = [
                _evidence_anchors(context, quote, regions)
                if reliable
                else _quote_anchors(context, quote)
                for quote in quotes
            ]
            if any(not anchors for anchors in quote_anchors):
                raise ValueError("context binding source quote is not literal supplied evidence")
            role_anchors = {}
            for field in ("actor_quote", "action_quote", "patient_quote") + (
                ("focus_quote",) if required_target_role is None else ()
            ):
                phrase = row[field]
                if phrase is not None:
                    located = []
                    for quote_index, anchors in enumerate(quote_anchors):
                        for anchor in anchors:
                            role_locations = (
                                _role_evidence_anchors(anchor, phrase)
                                if reliable
                                else _quote_anchors(anchor["source_text"], phrase)
                            )
                            for role in role_locations:
                                located.append(
                                    {
                                        **role,
                                        "quote_index": quote_index,
                                        "start": anchor["start"] + role["start"],
                                        "end": anchor["start"] + role["end"],
                                    }
                                )
                    if not located:
                        raise ValueError(
                            f"context binding {field} is not anchored in source quotes"
                        )
                    role_anchors[field] = located
            label = row["candidate_label_quote"]
            if reliable and label and label not in _candidate_text(candidate):
                if any(
                    label == _candidate_text(c) for c in candidates if c["id"] != candidate["id"]
                ):
                    raise ValueError("candidate label conflicts with another stable candidate ID")
            elif (
                not reliable
                and label is not None
                and (not label.strip() or label not in _candidate_text(candidate))
            ):
                raise ValueError("context binding label is not literal candidate text")
            if row["support"] == "SUPPORTED":
                if (
                    row["polarity"] != "AFFIRMED"
                    or not quotes
                    or (
                        required_target_role == "actor"
                        and (not row["actor_quote"] or not row["action_quote"])
                    )
                    or (
                        required_target_role is None
                        and (not row["focus_quote"] or not row["attention_role"])
                    )
                    or (not reliable and not label)
                ):
                    raise ValueError(
                        "SUPPORTED context binding requires affirmative anchored role evidence"
                    )
                supported.append(candidate)
        except ValueError as exc:
            isolatable = row["support"] == "NOT_SUPPORTED" or (
                revisable and candidate["id"] not in value["selected_candidate_ids"]
            )
            if required_target_role == "actor" or not isolatable:
                if revisable:
                    raise BindingValidationError(
                        [
                            _binding_issue(
                                ["assessment_by_candidate", candidate["id"]],
                                "INVALID_EVIDENCE",
                                str(exc),
                                candidates,
                            )
                        ]
                    ) from exc
                raise
            rejected.append(str(candidate["id"]))
            evidence.append(
                {
                    "kind": "invalid_candidate_evidence",
                    "candidate_id": candidate["id"],
                    "validation": (
                        "REJECTED_UNSELECTED_ROW_NOT_SEMANTICALLY_VALIDATED"
                        if revisable
                        else "REJECTED_NOT_SUPPORTED_ROW_NOT_SEMANTICALLY_VALIDATED"
                    ),
                    "error": str(exc),
                    "raw_assessment": row,
                }
            )
            continue
        evidence.append(
            {
                "kind": "model_context_role_evidence",
                "candidate_id": candidate["id"],
                **(
                    {
                        "identity_basis": "stable_candidate_id",
                        "label_copy_matches": bool(label and label in _candidate_text(candidate)),
                    }
                    if reliable
                    else {}
                ),
                "validation": (
                    "LATIN_TYPOGRAPHIC_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
                    if any(
                        a["match_mode"] == "latin_ligature_equivalent"
                        for group in quote_anchors
                        for a in group
                    )
                    or any(
                        a["match_mode"] == "latin_ligature_equivalent"
                        for group in role_anchors.values()
                        for a in group
                    )
                    else (
                        "WHITESPACE_EQUIVALENT_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
                        if any(a["match_mode"] != "exact" for group in quote_anchors for a in group)
                        or any(
                            a["match_mode"] != "exact"
                            for group in role_anchors.values()
                            for a in group
                        )
                        else "LITERAL_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
                    )
                ),
                "source_quote_anchors": quote_anchors,
                "role_anchors": role_anchors,
                **row,
            }
        )
    if reliable:
        for entry in evidence:
            if "source_quote_anchors" in entry:
                entry["validation"] = "TRACEABLE_SOURCE_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
    joint = value.get("joint_focus")
    if joint is not None:
        expected_joint = (
            set(value["selected_candidate_ids"]) if revisable else {str(c["id"]) for c in supported}
        )
        if set(joint["candidate_ids"]) != expected_joint:
            if revisable:
                raise BindingValidationError(
                    [
                        _binding_issue(
                            ["joint_focus", "candidate_ids"],
                            "JOINT_SELECTION_MISMATCH",
                            "Joint members must match selected foci, not all supported "
                            "alternatives.",
                            candidates,
                        )
                    ]
                )
            raise ValueError("joint focus must exactly match validated supported candidates")
        joint_anchors = [
            _evidence_anchors(context, q, regions) if reliable else _quote_anchors(context, q)
            for q in joint["source_quotes"]
        ]
        if any(not a for a in joint_anchors):
            if revisable:
                raise BindingValidationError(
                    [
                        _binding_issue(
                            ["joint_focus", "source_quotes"],
                            "JOINT_QUOTE_NOT_FOUND",
                            "Joint relation quote is not locatable in source.",
                            candidates,
                        )
                    ]
                )
            raise ValueError("joint focus relation quote is not anchored in source")
        evidence.append(
            {
                "kind": "model_joint_focus_evidence",
                **joint,
                "source_quote_anchors": joint_anchors,
                "validation": (
                    "TRACEABLE_SOURCE_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
                    if reliable
                    else "LITERAL_ANCHORS_CHECKED_NOT_ENTAILMENT_GOLD"
                ),
            }
        )
    unresolved = required_target_role is None and any(
        r["support"] == "UNCERTAIN" for r in value["assessment_by_candidate"].values()
    )
    chosen = supported[0] if len(supported) == 1 else None
    overlap = (
        lexical_score(str(proposition.get("text") or ""), _candidate_text(chosen))
        if chosen
        else 0.0
    )
    # Preserve the existing scoring weights/threshold. Only the provenance of
    # source support changes, explicitly labelled as a model judgment.
    score = 0.7 + 0.3 * overlap if chosen else 0.0
    accepted = chosen if score >= threshold and not unresolved else None
    status = (
        "BOUND"
        if accepted
        else (
            "ABSTAINED_AMBIGUOUS_SOURCE_RELATIONS"
            if len(supported) > 1
            else "ABSTAINED_NO_SOURCE_SUPPORTED_CANDIDATE"
        )
    )
    selected_ids = [str(accepted["id"])] if accepted else []
    if required_target_role is None:
        if unresolved:
            status = "ABSTAINED_UNCERTAIN_SOURCE_RELATIONS"
        elif joint is not None:
            # Every member has independently validated support; no lexical winner.
            score = 0.7
            if score >= threshold:
                selected_ids = [str(c["id"]) for c in supported]
                status = "BOUND_MULTIPLE"
            else:
                status = "ABSTAINED_BELOW_THRESHOLD"
        elif accepted and rejected:
            status = "BOUND_PARTIAL_EVIDENCE"
        elif not accepted and rejected:
            status = "INVALID_CANDIDATE_EVIDENCE"
    if revisable:
        proposed_ids = value["selected_candidate_ids"]
        review = value["selection_review"]
        issues = []

        def selection_error(field, code, message):
            issues.append(_binding_issue(field, code, message, candidates))

        if set(review["member_contributions"]) != set(proposed_ids):
            selection_error(
                ["selection_review", "member_contributions"],
                "MEMBER_CONTRIBUTIONS",
                "Explain exactly each selected member, without adding unselected members.",
            )
        if not set(proposed_ids) <= {str(c["id"]) for c in supported}:
            selection_error(
                ["selected_candidate_ids"],
                "SELECTED_WITHOUT_VALIDATED_SUPPORT",
                "Every selected ID must have validated source support.",
            )
        if proposed_ids and (review["coverage"] != "SUFFICIENT" or not review["minimal"]):
            selection_error(
                ["selection_review"],
                "INSUFFICIENT_SELECTION",
                "A nonempty selection requires asserted sufficient, minimal relation "
                "coverage; otherwise abstain.",
            )
        if not proposed_ids and review["coverage"] == "SUFFICIENT":
            selection_error(
                ["selection_review", "coverage"],
                "EMPTY_SUFFICIENT_SELECTION",
                "An empty selection cannot claim sufficient visual relation coverage.",
            )
        review_anchors = [_evidence_anchors(context, q, regions) for q in review["source_quotes"]]
        if (proposed_ids and not review_anchors) or any(not a for a in review_anchors):
            selection_error(
                ["selection_review", "source_quotes"],
                "SELECTION_QUOTE_NOT_FOUND",
                "Selection's relation review needs locatable source evidence.",
            )
        if len(proposed_ids) > 1 and joint is None:
            selection_error(
                ["joint_focus"],
                "JOINT_EVIDENCE_REQUIRED",
                "Multiple selected members require their shared relation evidence.",
            )
        if issues:
            raise BindingValidationError(issues)
        chosen = next((c for c in candidates if proposed_ids == [c["id"]]), None)
        score = (
            0.7 + 0.3 * lexical_score(str(proposition.get("text") or ""), _candidate_text(chosen))
            if chosen
            else 0.7
            if proposed_ids
            else 0.0
        )
        selected_ids = proposed_ids if score >= threshold else []
        accepted = chosen if selected_ids else None
        status = (
            "BOUND_MULTIPLE"
            if len(selected_ids) > 1
            else "BOUND_PARTIAL_EVIDENCE"
            if selected_ids and rejected
            else "BOUND"
            if selected_ids
            else "ABSTAINED_BELOW_THRESHOLD"
            if proposed_ids
            else "ABSTAINED_INSUFFICIENT_RELATION_COVERAGE"
            if review["coverage"] == "INSUFFICIENT"
            else "ABSTAINED_UNCERTAIN_RELATION_COVERAGE"
        )
    return _result(
        "source_conditioned",
        proposition,
        selected=accepted,
        score=score,
        threshold=threshold,
        status=status,
        evidence=evidence,
        source_support=1.0 if selected_ids else 0.0,
        source_support_mode="context_role_model",
        supported_candidate_count=len(supported),
        confidence_basis="MODEL_ROLE_JUDGMENT_WITH_LITERAL_ANCHORS_NOT_TRUTH_PROBABILITY",
        rationale=(
            "model-selected sufficient focus set with checked source anchors; semantic entailment "
            "is not independently proven"
            if revisable
            else "source-supported focus; ungrouped alternatives or unresolved evidence abstain"
        ),
        context_method_version=(
            context_method_version if required_target_role is None else "source-context-actor-v1"
        ),
        **(
            {
                "selection_review": value["selection_review"],
                "semantic_verification_status": "MODEL_SELF_REVIEWED_NOT_INDEPENDENTLY_PROVEN",
                "joint_required_candidate_ids": joint["candidate_ids"]
                if joint and selected_ids
                else [],
                "downstream_compatibility": "MULTI_TARGET_ADAPTER_REQUIRED"
                if len(selected_ids) > 1
                else "SINGLE_TARGET_COMPATIBLE",
                "validation_warnings": validation_warnings,
            }
            if revisable
            else {}
        ),
        evidence_validation_version=evidence_validation_version,
        selected_candidate_ids=selected_ids,
        supported_candidate_ids=[str(c["id"]) for c in supported],
        rejected_candidate_ids=rejected,
        evidence_complete=not rejected,
        visual_explanation_status="NOT_EVALUATED",
        raw_response_sha256=hashlib.sha256(str(raw).encode("utf-8")).hexdigest(),
        candidate_count=len(candidates),
        decision_bridge_allowed=False,
    )


def _bind_context_with_repair(
    proposition: dict,
    candidates: list[dict],
    *,
    model_fn: BindingModel,
    threshold: float,
    source_evidence: dict | None,
    max_repair_rounds: int,
    deadline_sec: float,
    initial_response: str | None,
    semantic_model_fn: Callable[[str, list[str]], str] | None = None,
    semantic_full_figure: dict | None = None,
) -> dict[str, Any]:
    semantic_calls, semantic_last = 0, None
    images = None
    if semantic_model_fn is not None:
        from .binding_semantics import semantic_images

        images = semantic_images(candidates, semantic_full_figure)
    if (
        isinstance(max_repair_rounds, bool)
        or not isinstance(max_repair_rounds, int)
        or max_repair_rounds < 0
    ):
        raise ValueError("max_repair_rounds must be a nonnegative integer")
    if not math.isfinite(deadline_sec) or deadline_sec <= 0:
        raise ValueError("repair deadline must be positive and finite")
    prop, pool = copy.deepcopy(proposition), copy.deepcopy(candidates)
    evidence = copy.deepcopy(source_evidence)
    attempts, previous_issues, seen_raw = [], [], set()
    previous_raw, previous_signature = None, None
    started, model_calls, last_valid = time.monotonic(), 0, None
    selected_from_round = None
    reason = "MAX_REPAIR_ROUNDS"
    for round_index in range(max_repair_rounds + 1):
        if time.monotonic() - started >= deadline_sec:
            reason = "DEADLINE_EXCEEDED"
            break
        attempt = {
            "round": round_index,
            "seeded_response": round_index == 0 and initial_response is not None,
        }
        raw, model_called, call_failed = None, False, False

        def invoke(prompt):
            nonlocal raw, model_called, model_calls, call_failed
            request = json.loads(prompt)
            if round_index:
                request["repair_context"] = {
                    "previous_response": previous_raw,
                    "validation_issues": previous_issues,
                    "source_regions": (evidence or {}).get("source_units", []),
                    "instruction": (
                        "Recheck the original proposition, all original candidates and source. "
                        "Correct evidence, roles, relation coverage or selection yourself, or "
                        "abstain. "
                        "Return a complete replacement JSON response, assessing every candidate; "
                        "do not remove candidates, invent quotes or treat a located quote as "
                        "entailment. "
                        "Feedback identifies errors, never an expected target answer."
                    ),
                }
            attempt["prompt"] = json.dumps(request, ensure_ascii=False, indent=2)
            if attempt["seeded_response"]:
                raw = initial_response
            else:
                model_called = True
                model_calls += 1
                try:
                    raw = model_fn(attempt["prompt"])
                except Exception:
                    call_failed = True
                    raise
            attempt["raw_response"] = raw
            return raw

        try:
            result = _bind_context_relations(
                prop,
                pool,
                model_fn=invoke,
                threshold=threshold,
                evidence_validation_version=CONTEXT_EVIDENCE_VERSION,
                source_evidence=evidence,
                context_method_version=CONTEXT_REVISABLE_VERSION,
            )
            issues = result.get("validation_warnings", [])
            if semantic_model_fn is not None and result.get("selected_candidate_ids"):
                from .binding_semantics import check_semantic_sufficiency

                # Do not expose selection_review, rationales or binder evidence to the checker.
                attempt["validated_binding"] = copy.deepcopy(result)
                attempt["semantic_check"] = {}
                # A newer unchecked/failed semantic selection must never fall back to an older one.
                last_valid = None
                semantic_last = {"verdict": "UNCERTAIN", "error": "Check has not completed"}
                if time.monotonic() - started >= deadline_sec:
                    reason = "DEADLINE_EXCEEDED"
                    attempts.append(attempt)
                    break

                def check_model(prompt, paths):
                    nonlocal semantic_calls, call_failed
                    semantic_calls += 1
                    try:
                        return semantic_model_fn(prompt, paths)
                    except Exception:
                        call_failed = True
                        raise

                try:
                    semantic_last = check_semantic_sufficiency(
                        prop,
                        pool,
                        result["selected_candidate_ids"],
                        images,
                        evidence,
                        check_model,
                        attempt["semantic_check"],
                    )
                except ValueError as exc:
                    if call_failed:
                        raise
                    semantic_last = {"verdict": "UNCERTAIN", "error": str(exc)}
                    raise BindingValidationError(
                        [
                            {
                                "path": "/semantic_check",
                                "code": "SEMANTIC_CHECK_INVALID",
                                "message": "Semantic check was inconclusive: " + str(exc),
                            }
                        ]
                    ) from exc
                result["semantic_check"] = semantic_last
                if semantic_last["verdict"] != "SUFFICIENT":
                    raise BindingValidationError(
                        [
                            {
                                "path": "/semantic_check",
                                "code": "SEMANTIC_" + semantic_last["verdict"],
                                "message": "Reconsider relation coverage or abstain using "
                                "original evidence.",
                                "required_relations": semantic_last["required_relations"],
                                "missing_relations": semantic_last["missing_relations"],
                                "uncertainties": semantic_last["uncertainties"],
                                "source_and_visual_evidence": semantic_last["satisfied_relations"],
                                "explanation": semantic_last["explanation"],
                            }
                        ]
                    )
            last_valid = result
            selected_from_round = round_index
            attempt["binding_status"] = result["status"]
            attempt["selected_candidate_ids"] = result.get("selected_candidate_ids", [])
            attempt["issues"] = issues
            if time.monotonic() - started >= deadline_sec:
                reason, last_valid = "DEADLINE_EXCEEDED", None
                attempts.append(attempt)
                break
            if not issues or result["status"].startswith("ABSTAINED"):
                reason = "COMPLETED_WITH_WARNINGS" if issues else "COMPLETED"
                attempts.append(attempt)
                break
        except Exception as exc:
            if call_failed:
                reason = (
                    "MODEL_CALL_TIMEOUT"
                    if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
                    else "MODEL_CALL_FAILED"
                )
                attempt["issues"] = [
                    {"path": "/", "code": reason, "message": redact_response_text(str(exc))}
                ]
                attempts.append(attempt)
                break
            if "prompt" not in attempt:
                reason = "INVALID_INPUT"
                attempt["issues"] = [
                    {
                        "path": "/source_evidence",
                        "code": reason,
                        "message": redact_response_text(str(exc)),
                    }
                ]
                attempts.append(attempt)
                break
            issues = (
                exc.issues
                if isinstance(exc, BindingValidationError)
                else [
                    {
                        "path": "/",
                        "code": "INVALID_JSON"
                        if isinstance(exc, json.JSONDecodeError)
                        else "INVALID_RESPONSE",
                        "message": redact_response_text(str(exc)),
                    }
                ]
            )
            attempt["issues"] = issues
            attempt["binding_status"] = "INVALID_RESPONSE"
        attempts.append(attempt)
        signature = tuple(sorted((i["path"], i["code"]) for i in issues))
        if semantic_model_fn is not None and any(i["code"].startswith("SEMANTIC_") for i in issues):
            signature += (
                (
                    "semantic_selection",
                    json.dumps(
                        {
                            "ids": result.get("selected_candidate_ids", []),
                            "missing": (semantic_last or {}).get("missing_relations"),
                            "uncertainties": (semantic_last or {}).get("uncertainties"),
                        },
                        sort_keys=True,
                    ),
                ),
            )
        raw_hash = hashlib.sha256(str(raw).encode()).hexdigest()
        if signature == previous_signature or raw_hash in seen_raw:
            reason = "REPEATED_ERRORS"
            break
        seen_raw.add(raw_hash)
        previous_signature, previous_raw, previous_issues = signature, raw, issues
    final = (
        last_valid
        if last_valid is not None
        else _result(
            "source_conditioned",
            prop,
            selected=None,
            status="REPAIR_FAILED",
            rationale="No validated selection; see structured repair trace.",
        )
    )
    final.update(
        context_method_version=(
            CONTEXT_SEMANTIC_VERSION if semantic_model_fn is not None else CONTEXT_REVISABLE_VERSION
        ),
        evidence_validation_version=CONTEXT_EVIDENCE_VERSION,
        repair_status=reason,
        model_calls=model_calls,
        selected_from_round=selected_from_round if last_valid is not None else None,
        repair_rounds=max(0, len(attempts) - 1),
        repair_trace=attempts,
        original_input={
            "proposition": prop,
            "candidates": pool,
            "source_document": (evidence or {}).get("document"),
        },
        semantic_verification_status="MODEL_SELF_REVIEWED_NOT_INDEPENDENTLY_PROVEN",
    )
    if semantic_model_fn is not None:
        final["semantic_model_calls"] = semantic_calls
        final["semantic_check"] = semantic_last
        final["semantic_verification_status"] = (
            "MODEL_ASSISTED_SUFFICIENT_NOT_GOLD"
            if last_valid is not None and final.get("selected_candidate_ids")
            else "NOT_CHECKED_ABSTENTION"
            if final["status"].startswith("ABSTAINED")
            else "MODEL_ASSISTED_UNRESOLVED_NOT_GOLD"
        )
        if last_valid is None and semantic_last is not None:
            final["status"] = (
                "SEMANTIC_UNCERTAIN"
                if semantic_last["verdict"] == "UNCERTAIN"
                else "SEMANTIC_CHECK_FAILED"
            )
        final.setdefault("selected_candidate_ids", [])
    return final


def bind_source_conditioned(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    threshold: float = 0.45,
    allow_decision_bridge: bool = False,
    context_model_fn: BindingModel | None = None,
    required_target_role: str | None = None,
    evidence_validation_version: str = "context-evidence-v1.1",
    source_evidence: dict[str, Any] | None = None,
    context_method_version: str = CONTEXT_FOCUS_VERSION,
    max_repair_rounds: int = 3,
    initial_context_response: str | None = None,
    repair_deadline_sec: float = 480,
    semantic_model_fn: Callable[[str, list[str]], str] | None = None,
    semantic_full_figure: dict | None = None,
) -> dict[str, Any]:
    """Proposed binding: source provenance is a first-class scoring signal.

    A candidate with no source relation cannot win merely through lexical
    similarity.  Exact source IDs dominate, followed by source-locator/caption
    support and only then text overlap.
    """
    if required_target_role not in {None, "actor"}:
        raise ValueError("unsupported binding target role")
    if evidence_validation_version not in {"context-evidence-v1.1", CONTEXT_EVIDENCE_VERSION}:
        raise ValueError("unsupported context evidence validation version")
    revisable = context_method_version in {CONTEXT_REVISABLE_VERSION, CONTEXT_SEMANTIC_VERSION}
    if context_method_version not in {
        CONTEXT_FOCUS_VERSION,
        CONTEXT_REVISABLE_VERSION,
        CONTEXT_SEMANTIC_VERSION,
    }:
        raise ValueError("unsupported context method version")
    if revisable and required_target_role is not None:
        raise ValueError("revisable teaching-focus method cannot use actor-only task")
    if revisable and context_model_fn is None:
        raise ValueError("revisable teaching-focus method requires explicit context_model_fn")
    if initial_context_response is not None and not revisable:
        raise ValueError("initial context response requires the revisable method")
    if context_method_version == CONTEXT_SEMANTIC_VERSION:
        if semantic_model_fn is None or semantic_full_figure is None or source_evidence is None:
            raise ValueError(
                "semantic version requires checker, full figure and raw source evidence"
            )
    elif semantic_model_fn is not None or semantic_full_figure is not None:
        raise ValueError("semantic check requires the independently versioned semantic method")
    eligible = _eligible_candidates(proposition, candidates)
    prop_sources = _source_ids(proposition.get("source_refs"))
    if not prop_sources:
        return _result(
            "source_conditioned",
            proposition,
            selected=None,
            threshold=threshold,
            status="ABSTAINED_SOURCE_EVIDENCE_INSUFFICIENT",
            rationale="proposition has no source_refs; proposed method abstains",
            source_support=0.0,
            candidate_count=len(eligible),
        )
    if context_model_fn is not None:
        if allow_decision_bridge:
            raise ValueError("context binding comparison cannot use decision-stage bridges")
        if revisable:
            return _bind_context_with_repair(
                proposition,
                eligible,
                model_fn=context_model_fn,
                threshold=threshold,
                source_evidence=source_evidence,
                max_repair_rounds=max_repair_rounds,
                deadline_sec=repair_deadline_sec,
                initial_response=initial_context_response,
                semantic_model_fn=semantic_model_fn,
                semantic_full_figure=semantic_full_figure,
            )
        return _bind_context_relations(
            proposition,
            eligible,
            model_fn=context_model_fn,
            required_target_role=required_target_role,
            evidence_validation_version=evidence_validation_version,
            source_evidence=source_evidence,
            threshold=threshold,
        )
    scored: list[tuple[float, float, float, dict[str, Any], list[dict[str, Any]]]] = []
    for candidate in eligible:
        candidate_sources = _source_ids(
            candidate.get("source_refs") or candidate.get("source_unit_ids")
        )
        for key in ("source_image_id", "figure_id", "source_locator"):
            if candidate.get(key):
                candidate_sources.add(str(candidate[key]))
        exact = prop_sources & candidate_sources
        decision_bridge = next(
            (
                link
                for link in candidate.get("source_evidence_links", []) or []
                if isinstance(link, dict)
                and str(link.get("proposition_id") or "") == _prop_id(proposition)
                and str(link.get("status") or "") == "DECISION_STAGE_SOURCE_BRIDGE"
            ),
            None,
        )
        # A visual-decision bridge is useful to execute the treatment pipeline,
        # but it is itself a model output.  It must never silently leak into an
        # independent binding comparison.
        usable_bridge = decision_bridge if allow_decision_bridge else None
        source_support = 1.0 if exact or usable_bridge else 0.0
        if not exact and not usable_bridge:
            caption_score = lexical_score(
                str(proposition.get("text") or ""),
                " ".join(
                    str(candidate.get(key) or "")
                    for key in ("caption", "source_locator", "nearby_text")
                ),
            )
            source_support = min(0.8, caption_score)
        lexical = lexical_score(str(proposition.get("text") or ""), _candidate_text(candidate))
        score = 0.7 * source_support + 0.3 * lexical
        evidence = [
            {
                "kind": "source_relation",
                "matched_ids": sorted(exact),
                "support": round(source_support, 4),
            },
            {"kind": "semantic_overlap", "score": lexical},
        ]
        if usable_bridge:
            evidence.append(
                {
                    "kind": "decision_stage_source_bridge",
                    "source_image_id": decision_bridge.get("source_image_id"),
                    "rationale_evidence": decision_bridge.get("rationale_evidence") or [],
                }
            )
        scored.append((score, source_support, lexical, candidate, evidence))
    scored.sort(key=lambda item: (-item[0], -item[1], str(item[3].get("id") or "")))
    score, source_support, lexical, selected, evidence = (
        scored[0] if scored else (0.0, 0.0, 0.0, None, [])
    )
    accepted = (
        selected if selected is not None and score >= threshold and source_support > 0 else None
    )
    return _result(
        "source_conditioned",
        proposition,
        selected=accepted,
        score=score,
        threshold=threshold,
        evidence=evidence,
        status="BOUND" if accepted else "ABSTAINED_NO_SOURCE_SUPPORTED_CANDIDATE",
        rationale="source support dominates semantic overlap; unsupported visuals abstain",
        source_support=round(source_support, 4),
        lexical_support=round(lexical, 4),
        candidate_count=len(eligible),
        decision_bridge_allowed=allow_decision_bridge,
    )


def compare_binding_methods(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    model_fn: BindingModel | None = None,
    model: str | None = None,
    embed_fn: EmbeddingFn | None = None,
    run_direct: bool = True,
    allow_decision_bridge: bool = False,
) -> dict[str, Any]:
    """Run all four comparators on exactly the same frozen candidate list."""
    results = [
        bind_lexical(proposition, candidates),
        bind_embedding(proposition, candidates, embed_fn=embed_fn),
    ]
    if run_direct:
        results.append(bind_direct_llm_vlm(proposition, candidates, model_fn=model_fn, model=model))
    else:
        results.append(
            _result(
                "direct_llm_vlm",
                proposition,
                selected=None,
                status="NOT_RUN",
                rationale="direct comparator disabled; no synthetic model response was used",
                comparator_mode="NOT_RUN",
                candidate_count=len(_eligible_candidates(proposition, candidates)),
            )
        )
    results.append(
        bind_source_conditioned(
            proposition,
            candidates,
            allow_decision_bridge=allow_decision_bridge,
        )
    )
    return {
        "schema_version": BINDING_VERSION,
        "proposition_id": _prop_id(proposition),
        "candidate_ids": [
            str(item.get("id")) for item in _eligible_candidates(proposition, candidates)
        ],
        "results": results,
    }


__all__ = [
    "BINDING_VERSION",
    "bind_direct_llm_vlm",
    "bind_embedding",
    "bind_lexical",
    "make_sentence_transformer_embedding",
    "bind_source_conditioned",
    "compare_binding_methods",
]
