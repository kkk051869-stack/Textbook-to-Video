"""Comparable proposition-to-visual binding methods for P0.

All methods return the same result shape and are side-effect free.  They do
not alter the production storyboard.  ``direct_llm_vlm`` is intentionally an
adapter: experiments can inject a cloud LLM/VLM callable, while unit tests
and offline runs use a persisted response or a deterministic stub.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_images, chat_with_system

from .source_evidence import lexical_score

BINDING_VERSION = "p0-binding-methods-v1.0"
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
            "embedding_model requires sentence-transformers; install it in the experiment environment"
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
) -> dict[str, Any]:
    """Direct comparator; use candidate pixels when a VLM and images are available.

    Text-only execution remains possible for old pools, but the returned
    ``comparator_mode`` makes that fallback explicit instead of calling it a
    VLM result.
    """
    eligible = _eligible_candidates(proposition, candidates)
    prompt = json.dumps(
        {
            "task": "Bind one narration proposition to at most one candidate visual.",
            "rules": [
                "Return abstain=true when no candidate is clearly explanatory.",
                "Do not reward decoration or shared vocabulary alone.",
                "selected_candidate_id must be one of the supplied IDs or null.",
            ],
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


def _bind_context_relations(
    proposition: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    model_fn: BindingModel,
    threshold: float,
) -> dict[str, Any]:
    """Use model-produced role evidence; literal validation is not entailment."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

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
    prompt = json.dumps(
        {
            "task": "Assess whether each candidate object performs the role narrated by this proposition, using source context and supplied object pixels. Do not select a winner.",
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
                "Assess every candidate exactly once. Same page, shared topic, a source ID or lexical overlap is not semantic support.",
                "SUPPORTED requires this actual object to perform the narrated action with the correct actor, action and patient. Negation cannot be affirmative support.",
                "Resolve pronouns using preceding source context and include the literal antecedent evidence. If unresolved, return UNCERTAIN.",
                "If the narration describes several modules, do not force it onto a single one; mark each supported role honestly. The program abstains on multiple supported objects.",
                "If the required operation is absent from this candidate subset, preserve NOT_SUPPORTED or UNCERTAIN. Never substitute a nearby block.",
                "Every source quote must be an exact nonempty substring of source_context; actor/action/patient phrases must themselves occur inside those quotes.",
                "SUPPORTED needs nonempty actor_quote, action_quote, candidate_label_quote and source_quotes. candidate_label_quote must occur literally in supplied candidate text. patient_quote may be null for an action with no explicit patient.",
                "Do not infer expected answers or claim human verification. Return one JSON instance conforming to output_json_schema, not the schema itself.",
            ],
            "output_json_schema": schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    raw = model_fn(prompt)
    value = _parse_model_json(raw)
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        raise ValueError(f"context binding response schema invalid: {exc.message}") from exc
    supported = []
    evidence = []
    for candidate in candidates:
        row = value["assessment_by_candidate"][str(candidate["id"])]
        quotes = row["source_quotes"]
        quote_anchors = [_quote_anchors(context, quote) for quote in quotes]
        if any(not anchors for anchors in quote_anchors):
            raise ValueError("context binding source quote is not literal supplied evidence")
        role_anchors = {}
        for field in ("actor_quote", "action_quote", "patient_quote"):
            phrase = row[field]
            if phrase is not None:
                located = []
                for quote_index, anchors in enumerate(quote_anchors):
                    for anchor in anchors:
                        for role in _quote_anchors(anchor["source_text"], phrase):
                            located.append(
                                {
                                    **role,
                                    "quote_index": quote_index,
                                    "start": anchor["start"] + role["start"],
                                    "end": anchor["start"] + role["end"],
                                }
                            )
                if not located:
                    raise ValueError(f"context binding {field} is not anchored in source quotes")
                role_anchors[field] = located
        label = row["candidate_label_quote"]
        if label is not None and (not label.strip() or label not in _candidate_text(candidate)):
            raise ValueError("context binding label is not literal candidate text")
        if row["support"] == "SUPPORTED":
            if (
                row["polarity"] != "AFFIRMED"
                or not quotes
                or not row["actor_quote"]
                or not row["action_quote"]
                or not label
            ):
                raise ValueError(
                    "SUPPORTED context binding requires affirmative anchored role evidence"
                )
            supported.append(candidate)
        evidence.append(
            {
                "kind": "model_context_role_evidence",
                "candidate_id": candidate["id"],
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
    chosen = supported[0] if len(supported) == 1 else None
    overlap = (
        lexical_score(str(proposition.get("text") or ""), _candidate_text(chosen))
        if chosen
        else 0.0
    )
    # Preserve the existing scoring weights/threshold. Only the provenance of
    # source support changes, explicitly labelled as a model judgment.
    score = 0.7 + 0.3 * overlap if chosen else 0.0
    accepted = chosen if score >= threshold else None
    status = (
        "BOUND"
        if accepted
        else (
            "ABSTAINED_AMBIGUOUS_SOURCE_RELATIONS"
            if len(supported) > 1
            else "ABSTAINED_NO_SOURCE_SUPPORTED_CANDIDATE"
        )
    )
    return _result(
        "source_conditioned",
        proposition,
        selected=accepted,
        score=score,
        threshold=threshold,
        status=status,
        evidence=evidence,
        source_support=1.0 if chosen else 0.0,
        source_support_mode="context_role_model",
        supported_candidate_count=len(supported),
        confidence_basis="MODEL_ROLE_JUDGMENT_WITH_LITERAL_ANCHORS_NOT_TRUTH_PROBABILITY",
        rationale="unique anchored model-supported object required; ambiguous or unsupported cases abstain",
        raw_response_sha256=hashlib.sha256(str(raw).encode("utf-8")).hexdigest(),
        candidate_count=len(candidates),
        decision_bridge_allowed=False,
    )


def bind_source_conditioned(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    threshold: float = 0.45,
    allow_decision_bridge: bool = False,
    context_model_fn: BindingModel | None = None,
) -> dict[str, Any]:
    """Proposed binding: source provenance is a first-class scoring signal.

    A candidate with no source relation cannot win merely through lexical
    similarity.  Exact source IDs dominate, followed by source-locator/caption
    support and only then text overlap.
    """
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
        return _bind_context_relations(
            proposition,
            eligible,
            model_fn=context_model_fn,
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
