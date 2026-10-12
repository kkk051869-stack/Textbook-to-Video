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


def bind_source_conditioned(
    proposition: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    *,
    threshold: float = 0.45,
    allow_decision_bridge: bool = False,
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
        results.append(_result(
            "direct_llm_vlm", proposition, selected=None, status="NOT_RUN", rationale="direct comparator disabled; no synthetic model response was used",
            comparator_mode="NOT_RUN", candidate_count=len(_eligible_candidates(proposition, candidates)),
        ))
    results.append(bind_source_conditioned(
        proposition, candidates, allow_decision_bridge=allow_decision_bridge,
    ))
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
