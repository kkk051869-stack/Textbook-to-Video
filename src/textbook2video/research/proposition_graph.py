"""Source-grounded knowledge and narration proposition graph for P0.

This is deliberately a research sidecar.  The legacy lesson plan and
storyboard stay untouched, while every graph edge is explicit and validated.
Unlike the former sentence splitter, narration propositions are generated as
semantic claims and must point to both a source-backed knowledge proposition
and an exact text span in the frozen narration.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_system
from textbook2video.research.source_evidence import lexical_score

GRAPH_VERSION = "p0-proposition-graph-v1.0"
GRAPH_MAX_TOKENS = 1536
REPAIR_MAX_TOKENS = 512
SMALL_SOURCE_BATCH_MAX_CHARS = 24_000
SMALL_SOURCE_BATCH_MAX_TOKENS = 6_144
GRAPH_REQUEST_TIMEOUT_SEC = 90


def _is_structural_source_unit(text: str) -> bool:
    """Return whether a raw unit is document structure rather than evidence."""
    value = text.strip()
    return bool(
        not value
        or value.startswith("#")
        or re.match(r"^-\s+[a-z_][a-z0-9_-]*\s*:", value, flags=re.I)
        or re.match(r"^-\s+`[^`]+`\s*:", value)
        or re.match(r"^[（(][一二三四五六七八九十0-9]+[）)]", value)
        or re.match(r"^[一二三四五六七八九十0-9]+、", value)
        or re.match(r"^图\s*\d", value)
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _case_id(raw_path: Path) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", raw_path.stem.lower()).strip("-")
    return value or "lesson"


def _json_object(raw: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("proposition model output does not contain a JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("proposition model output must be an object")
    return value


def _has_valid_source_anchor(item: dict[str, Any], cited_units: list[dict[str, Any]], raw_text: str | None = None) -> bool:
    """Return whether a model-supplied source quote occurs in cited evidence."""
    anchor = re.sub(r"\s+", " ", str(item.get("source_anchor") or "").strip()).lower()
    if len(anchor) < 3:
        return False
    if raw_text is not None:
        spans = []
        for unit in cited_units:
            span = unit.get('char_span') or {}
            start, end = span.get('start'), span.get('end')
            if type(start) is int and type(end) is int and 0 <= start < end <= len(raw_text):
                if re.sub(r"\s+", " ", raw_text[start:end]).lower() == re.sub(r"\s+", " ", str(unit['text'])).lower():
                    spans.append((start, end))
        groups = []
        for start, end in sorted(spans):
            if groups and start >= groups[-1][1] and not raw_text[groups[-1][1]:start].strip():
                groups[-1] = (groups[-1][0], end)
            else:
                groups.append((start, end))
        if any(anchor in re.sub(r"\s+", " ", raw_text[start:end]).lower() for start, end in groups):
            return True
    return any(
        anchor in re.sub(r"\s+", " ", str(unit["text"])).lower()
        for unit in cited_units
    )


def _locate_span(narration: str, text: str, hint: int = 0) -> tuple[int, int]:
    start = narration.find(text, max(0, hint))
    if start < 0:
        start = narration.find(text)
    if start >= 0:
        return start, start + len(text)

    # Models occasionally preserve all words but normalize whitespace or a
    # Chinese/full-width sentence mark while echoing a required source span.
    # Resolve only those formatting-equivalent cases, then persist the exact
    # substring from ``narration`` (never the model's rewritten text).
    def normalized_with_offsets(value: str) -> tuple[str, list[int]]:
        chars: list[str] = []
        offsets: list[int] = []
        equivalents = {"。": ".", "？": "?", "！": "!", "，": ",", "：": ":", "；": ";"}
        for index, char in enumerate(value):
            if char.isspace():
                continue
            chars.append(equivalents.get(char, char))
            offsets.append(index)
        return "".join(chars), offsets

    normalized_narration, offsets = normalized_with_offsets(narration)
    normalized_text, _ = normalized_with_offsets(text)
    # A proposition may end immediately before the source sentence mark.  The
    # mark itself carries no claim content, so do not reject an otherwise
    # exact span solely because the model emitted a different terminal mark.
    normalized_text = normalized_text.rstrip(".?!")
    if not normalized_text:
        raise ValueError(f"narration proposition has no lexical content: {text!r}")
    normalized_hint, _ = normalized_with_offsets(narration[:hint])
    normalized_start = normalized_narration.find(normalized_text, len(normalized_hint))
    if normalized_start < 0:
        normalized_start = normalized_narration.find(normalized_text)
    if normalized_start < 0:
        raise ValueError(f"narration proposition is not an exact narration span: {text!r}")
    normalized_end = normalized_start + len(normalized_text) - 1
    return offsets[normalized_start], offsets[normalized_end] + 1


def _narration_clauses(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep exact source offsets, including distinct occurrences of repeated text."""
    narration = segment["narration"]
    boundaries = [match.end() for match in re.finditer(r"[。！？；，!?;\n]+|\.(?=\s|$)", narration)]
    clauses = []
    start = 0
    for end in [*boundaries, len(narration)]:
        piece = narration[start:end]
        if piece.strip():
            clauses.append({
                "id": f"{segment['id']}-c{len(clauses) + 1}",
                "text": piece.strip(),
                "start": start + len(piece) - len(piece.lstrip()),
                "end": start + len(piece.rstrip()),
            })
        start = end
    return clauses


def _prompt(
    source_units: list[dict[str, Any]],
    knowledge_points: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    *,
    include_segment_id_on_knowledge: bool = False,
    use_narration_clause_ids: bool = False,
) -> str:
    rules = [
        (
            "A knowledge proposition is one atomic, source-supported teaching "
            "claim; do not use a whole sentence merely because it is a sentence."
        ),
        (
            "Write every knowledge proposition and narration proposition in "
            "Simplified Chinese, retaining the factual terminology used by the "
            "Chinese source passage."
        ),
        (
            "Every knowledge proposition must cite one or more source_unit_ids "
            "from source_units."
        ),
        (
            "Every knowledge proposition must include source_anchor: an exact "
            "contiguous quote from one of its cited source passages."
        ),
        (
            "Cite the most direct source passage. Every material detail in the "
            "proposition must be supported by the cited passage; do not strengthen "
            "claims with words such as unique, impossible, immediate, or causal "
            "unless the passage states them."
        ),
        (
            "A narration proposition is one atomic claim expressed by the narration. "
            "Its text must be an exact contiguous substring of the given segment narration."
        ),
        (
            "Every narration proposition must link to one or more "
            "knowledge_proposition_local_ids."
        ),
        (
            "Return every factual, definitional, causal, or substantive summary "
            "claim supported by the supplied source context; omit only greetings, "
            "transitions, and decoration."
        ),
        (
            "Do not invent facts, source ids, or narration text. Return no decorative "
            "or transition-only proposition."
        ),
    ]
    knowledge_schema: dict[str, Any] = {
        "local_id": "kp1-p1",
        "knowledge_point_id": "existing knowledge point id",
        "text": "atomic source-supported claim",
        "source_unit_ids": ["raw-unit-0001"],
        "source_anchor": "exact quote from cited source text",
    }
    if include_segment_id_on_knowledge:
        rules[1] = (
            "Write knowledge propositions and narration propositions in Simplified Chinese. "
            "Source passages may be in another language; preserve their meaning and quote "
            "source terminology exactly in source_anchor."
        )
        rules.extend(
            [
                "Each knowledge proposition must include its segment_id.",
                (
                    "For every segment with knowledge_point_ids, cover its source-supported "
                    "teaching claims with at least one linked knowledge and narration proposition."
                ),
                (
                    "If a segment claim cannot be supported by the supplied source units, do not "
                    "invent a citation; leave it uncovered so the caller can keep it pending."
                ),
            ]
        )
        knowledge_schema["segment_id"] = "existing segment id"
    narration_schema = {
        "segment_id": "existing segment id",
        "text": "exact substring from narration",
        "knowledge_proposition_local_ids": ["kp1-p1"],
    }
    if use_narration_clause_ids:
        rules = [rule for rule in rules if "must include source_anchor" not in rule]
        rules[1] = (
            "Write propositions in Simplified Chinese. Preserve source meaning and cite "
            "the supplied source_unit_ids only. The executor retrieves the exact source text."
        )
        knowledge_schema.pop("source_anchor")
        narration_rule = next(i for i, rule in enumerate(rules)
                              if rule.startswith("A narration proposition"))
        rules[narration_rule] = (
            "A narration proposition is one atomic claim expressed in the supplied narration "
            "clauses. Return its narration_clause_ids in order, using the shortest contiguous "
            "range that expresses the claim. Copy IDs only; do not return narration text."
        )
        narration_schema.pop("text")
        narration_schema["narration_clause_ids"] = ["one or more supplied clause ids"]
        segments = [
            {
                **{key: value for key, value in segment.items() if key != "narration"},
                "narration_clauses": [
                    {"id": clause["id"], "text": clause["text"]}
                    for clause in _narration_clauses(segment)
                ],
            }
            for segment in segments
        ]
    return json.dumps(
        {
            "task": "Build a source-grounded proposition graph for an instructional video.",
            "rules": rules,
            "output_schema": {
                "knowledge_propositions": [knowledge_schema],
                "narration_propositions": [narration_schema],
            },
            "source_units": [{k: v for k, v in unit.items() if k != "char_span"} for unit in source_units],
            "knowledge_points": knowledge_points,
            "segments": segments,
        },
        ensure_ascii=False,
        indent=2,
    )


def _evidence_for_segment(
    source_units: list[dict[str, Any]], narration: str, *, limit: int = 6
) -> list[dict[str, Any]]:
    """Select a bounded, deterministic evidence context for one narration segment.

    This is evidence *retrieval*, not a replacement for proposition grounding:
    the LLM must still cite the IDs in the returned context and the caller
    validates every citation.  Segment-scoped contexts keep a long textbook
    usable with local models whose context windows are smaller than the full
    document plus the storyboard prompt.
    """
    content_units = [
        unit for unit in source_units if not _is_structural_source_unit(str(unit.get("text") or ""))
    ]
    scored = sorted(
        content_units or source_units,
        key=lambda unit: (
            -lexical_score(narration, str(unit["text"])),
            str(unit["id"]),
        ),
    )
    matched = [unit for unit in scored if lexical_score(narration, str(unit['text'])) >= 0.08]
    if matched:
        return matched[:limit]
    # No lexical evidence is not evidence for the first lines of a document.
    # A bounded source can be supplied intact for cross-language grounding.
    if sum(len(str(unit['text'])) for unit in scored) <= SMALL_SOURCE_BATCH_MAX_CHARS:
        return content_units or source_units
    raise ValueError('no reliable lexical/source-position evidence; source is too large for full-context grounding')


def build_proposition_graph(
    *,
    raw_path: str | Path,
    source_evidence_path: str | Path,
    storyboard_path: str | Path,
    lesson_plan_path: str | Path | None,
    output_path: str | Path,
    model: str | None = None,
    batch_small_source: bool = False,
    allow_partial: bool = False,
    max_segments_per_batch: int | None = None,
    request_timeout_sec: float = GRAPH_REQUEST_TIMEOUT_SEC,
    use_narration_clause_ids: bool = False,
) -> Path:
    """Generate and validate a real proposition graph with an LLM.

    Development callers can keep validated claims alongside explicit rejections.
    Strict callers require the existing source and narration checks to pass.
    """
    raw = Path(raw_path)
    evidence = _read_json(Path(source_evidence_path))
    storyboard = _read_json(Path(storyboard_path))
    lesson_plan = (
        _read_json(Path(lesson_plan_path))
        if lesson_plan_path and Path(lesson_plan_path).is_file()
        else {}
    )
    source_units = [
        {
            "id": str(unit.get("id")),
            "text": str(unit.get("text")),
            "source_locator": unit.get("source_locator"),
            "char_span": unit.get("char_span"),
        }
        for unit in evidence.get("source_units", [])
        if isinstance(unit, dict) and unit.get("id") and unit.get("text")
    ]
    if not source_units:
        raise ValueError("cannot build proposition graph without source text units")
    knowledge_points = [
        {
            "id": str(kp.get("id")),
            "name": str(kp.get("name") or ""),
            "description": str(kp.get("description") or ""),
        }
        for kp in lesson_plan.get("knowledge_points", [])
        if isinstance(kp, dict) and kp.get("id")
    ]
    if not knowledge_points:
        raise ValueError("cannot build proposition graph without lesson-plan knowledge points")
    segments = [
        {
            "id": str(segment.get("id") or index),
            "narration": str(segment.get("narration") or ""),
            "knowledge_point_ids": [str(value) for value in segment.get("knowledge_point_ids", [])],
        }
        for index, segment in enumerate(storyboard.get("segments", []), start=1)
        if isinstance(segment, dict) and str(segment.get("narration") or "").strip()
    ]
    if not segments:
        raise ValueError("cannot build proposition graph without storyboard narration")
    source_ids = {item["id"] for item in source_units}
    kp_ids = {item["id"] for item in knowledge_points}
    segment_text = {item["id"]: item["narration"] for item in segments}
    case = _case_id(raw)
    rejected_claims = []
    graph_kprops: list[dict[str, Any]] = []
    local_to_stable: dict[str, str] = {}
    graph_nprops: list[dict[str, Any]] = []
    cursors: dict[str, int] = {}
    source_char_count = sum(len(str(unit["text"])) for unit in source_units)
    use_small_source_batch = (
        batch_small_source
        and len(segments) > 1
        and source_char_count <= SMALL_SOURCE_BATCH_MAX_CHARS
    )
    batch_generated_by_segment: dict[str, dict[str, list[dict[str, Any]]]] = {}
    def request_batch(batch_segments: list[dict], trace_suffix: str = "") -> None:
        # Batch only the model request for short inputs. The persisted graph
        # schema and all source/span validation below remain unchanged.
        batch_prompt = _prompt(
            source_units,
            knowledge_points,
            batch_segments,
            include_segment_id_on_knowledge=True,
            use_narration_clause_ids=use_narration_clause_ids,
        )
        response_trace = Path(output_path).with_name(
            f"{Path(output_path).stem}_model_response{trace_suffix}.json"
        )
        prompt_hash = hashlib.sha256(batch_prompt.encode('utf-8')).hexdigest()
        cached = _read_json(response_trace) if response_trace.is_file() else None
        if cached and (cached.get('prompt_sha256') != prompt_hash or cached.get('model') != model):
            raise ValueError('cached proposition response input/model mismatch')
        batch_response_text = json.dumps(cached['response'], ensure_ascii=False) if cached else chat_with_system(
            batch_prompt,
            system_prompt=(
                "You are a careful instructional-content analyst. Output only valid JSON."
            ),
            model=model,
            temperature=0.0,
            max_tokens=SMALL_SOURCE_BATCH_MAX_TOKENS,
            timeout=request_timeout_sec,
        )
        batch_generated = _json_object(batch_response_text)
        _write_json(
            response_trace,
            {
                "schema_version": "p0-proposition-graph-model-response-v1.0",
                "model": model,
                "prompt_sha256": hashlib.sha256(batch_prompt.encode("utf-8")).hexdigest(),
                "response_sha256": hashlib.sha256(
                    batch_response_text.encode("utf-8")
                ).hexdigest(),
                "response": batch_generated,
            },
        )
        batch_kprops = batch_generated.get("knowledge_propositions")
        batch_nprops = batch_generated.get("narration_propositions")
        if not isinstance(batch_kprops, list) or not isinstance(batch_nprops, list):
            raise ValueError("batched proposition graph response requires both proposition lists")
        known_segment_ids = {segment["id"] for segment in batch_segments}
        if any(
            not isinstance(item, dict)
            or str(item.get("segment_id") or "") not in known_segment_ids
            for item in [*batch_kprops, *batch_nprops]
        ):
            raise ValueError("batched proposition graph response has a missing or unknown segment_id")
        for segment in batch_segments:
            segment_id = segment["id"]
            segment_kprops = [
                item for item in batch_kprops
                if str(item.get("segment_id")) == segment_id
            ]
            segment_nprops = [
                item for item in batch_nprops
                if str(item.get("segment_id")) == segment_id
            ]
            batch_generated_by_segment[segment_id] = {
                "knowledge_propositions": segment_kprops,
                "narration_propositions": segment_nprops,
            }
    if use_small_source_batch:
        batch_size = max_segments_per_batch or len(segments)
        if batch_size < 1:
            raise ValueError("max_segments_per_batch must be positive")
        for start in range(0, len(segments), batch_size):
            request_batch(segments[start:start + batch_size],
                          f"_{start + 1:03d}" if batch_size < len(segments) else "")
    for segment in segments:
        relevant_kps = [
            item
            for item in knowledge_points
            if item["id"] in set(segment.get("knowledge_point_ids", []))
        ] or knowledge_points
        evidence_context = (
            source_units if use_small_source_batch
            else _evidence_for_segment(source_units, segment["narration"])
        )
        if not evidence_context:
            raise ValueError(
                "source evidence has no lexical match and is too large for safe "
                "cross-language proposition grounding"
            )
        generated = (
            batch_generated_by_segment[segment["id"]]
            if use_small_source_batch
            else _json_object(
                chat_with_system(
                    _prompt(
                        evidence_context,
                        relevant_kps,
                        [{"id": segment["id"], "narration": segment["narration"]}],
                        use_narration_clause_ids=use_narration_clause_ids,
                    ),
                    system_prompt=(
                        "You are a careful instructional-content analyst. Output only valid JSON."
                    ),
                    model=model,
                    temperature=0.0,
                    max_tokens=GRAPH_MAX_TOKENS,
                    timeout=request_timeout_sec,
                )
            )
        )
        if use_small_source_batch and segment.get("knowledge_point_ids") and (not generated.get("knowledge_propositions") or not generated.get("narration_propositions")):
            segment_id = segment['id']
            repair_path = Path(output_path).with_name(f"{Path(output_path).stem}_segment_{segment_id}_response.json")
            repair_prompt = _prompt(
                source_units, knowledge_points, [segment], include_segment_id_on_knowledge=True,
                use_narration_clause_ids=use_narration_clause_ids,
            )
            repair_hash = hashlib.sha256(repair_prompt.encode('utf-8')).hexdigest()
            if repair_path.is_file():
                repair_record = _read_json(repair_path)
                if repair_record.get('prompt_sha256') != repair_hash or repair_record.get('model') != model:
                    raise ValueError('cached segment response input/model mismatch')
                repair = repair_record['response']
            else:
                repair = _json_object(chat_with_system(repair_prompt, system_prompt='Output only source-grounded JSON.', model=model, temperature=0.0, max_tokens=GRAPH_MAX_TOKENS, timeout=request_timeout_sec))
                _write_json(repair_path, {'prompt_sha256': repair_hash, 'model': model, 'response': repair})
            segment_kprops = repair.get('knowledge_propositions', [])
            segment_nprops = repair.get('narration_propositions', [])
            if not segment_kprops or not segment_nprops:
                raise ValueError(f'missing source-supported propositions after single-segment recovery: {segment_id}')
            generated = {'knowledge_propositions': segment_kprops, 'narration_propositions': segment_nprops}
        provided_source_ids = {str(item["id"]) for item in evidence_context}
        requires_propositions = any(
            lexical_score(segment["narration"], str(unit["text"])) >= 0.08
            for unit in evidence_context
        )
        if requires_propositions and not use_narration_clause_ids and (
            not generated.get("knowledge_propositions")
            or not generated.get("narration_propositions")
        ):
            generated = _json_object(
                chat_with_system(
                    _prompt(
                        evidence_context,
                        relevant_kps,
                        [{"id": segment["id"], "narration": segment["narration"]}],
                    )
                    + (
                        "\nYour previous response omitted propositions. Return at least one "
                        "knowledge_proposition and one narration_proposition for this "
                        "source-overlapping segment; cite only the supplied source unit IDs."
                    ),
                    system_prompt=(
                        "You are a careful instructional-content analyst. Output only valid JSON."
                    ),
                    model=model,
                    temperature=0.0,
                    max_tokens=GRAPH_MAX_TOKENS,
                    timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                )
            )
            if (
                not generated.get("knowledge_propositions")
                or not generated.get("narration_propositions")
            ):
                minimal_evidence_context = [
                    unit
                    for unit in evidence_context
                    if lexical_score(segment["narration"], str(unit["text"])) >= 0.08
                ][:2] or evidence_context[:1]
                minimal_repair_prompt = json.dumps(
                    {
                        "task": (
                            "Return exactly one source-grounded knowledge proposition and "
                            "one linked narration proposition for this single segment."
                        ),
                        "rules": [
                            "Do not explain the task or return an empty array.",
                            (
                                "knowledge_proposition.text must reuse factual terminology "
                                "from its cited source_unit_ids."
                            ),
                            (
                                "narration_proposition.text must be an exact contiguous "
                                "substring of narration."
                            ),
                            "Use only the supplied source unit IDs and knowledge point IDs.",
                            "Return JSON only.",
                        ],
                        "source_units": minimal_evidence_context,
                        "knowledge_points": relevant_kps,
                        "segment": {
                            "id": segment["id"],
                            "narration": segment["narration"],
                        },
                        "output_schema": {
                            "knowledge_propositions": [
                                {
                                    "local_id": "kp1",
                                    "knowledge_point_id": "supplied id",
                                    "text": "source-grounded claim",
                                    "source_unit_ids": ["supplied source id"],
                                }
                            ],
                            "narration_propositions": [
                                {
                                    "segment_id": "segment id",
                                    "text": "exact narration substring",
                                    "knowledge_proposition_local_ids": ["kp1"],
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                generated = _json_object(
                    chat_with_system(
                        minimal_repair_prompt,
                        system_prompt=(
                            "You produce one minimal source-grounded graph record. "
                            "Output only valid JSON."
                        ),
                        model=model,
                        temperature=0.0,
                        max_tokens=REPAIR_MAX_TOKENS,
                        timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                    )
                )
                if (
                    not generated.get("knowledge_propositions")
                    or not generated.get("narration_propositions")
                ):
                    raise ValueError(
                        "model omitted all propositions after minimal repair for a "
                        f"source-overlapping narration segment: {segment['id']}"
                    )
        if use_narration_clause_ids:
            units_by_id = {str(unit["id"]): unit["text"] for unit in evidence_context}
            for item in generated.get("knowledge_propositions", []):
                if not isinstance(item, dict):
                    continue
                refs = item.get("source_unit_ids")
                if isinstance(refs, list) and refs and all(
                    isinstance(ref, str) and ref in units_by_id for ref in refs
                ):
                    item["source_anchor"] = units_by_id[refs[0]]
                else:
                    item.pop("source_anchor", None)
        ungrounded_knowledge_propositions = []
        for item in generated.get("knowledge_propositions", []):
            if not isinstance(item, dict):
                continue
            if use_narration_clause_ids and not item.get("source_anchor"):
                ungrounded_knowledge_propositions.append({
                    "local_id": item.get("local_id"),
                    "text": item.get("text"),
                    "source_unit_ids": item.get("source_unit_ids"),
                    "cited_source_passages": [],
                    "reason": "INVALID_SOURCE_UNIT_IDS",
                })
                continue
            refs = [
                str(value)
                for value in item.get("source_unit_ids", [])
                if str(value) in provided_source_ids
            ]
            text = str(item.get("text") or "").strip()
            cited_units = [unit for unit in evidence_context if str(unit["id"]) in refs]
            if (
                refs
                and text
                and not any(lexical_score(text, str(unit["text"])) > 0 for unit in cited_units)
                and not _has_valid_source_anchor(item, cited_units, raw.read_text(encoding="utf-8"))
            ):
                ungrounded_knowledge_propositions.append(
                    {
                        "local_id": item.get("local_id"),
                        "text": text,
                        "source_unit_ids": refs,
                        "cited_source_passages": cited_units,
                    }
                )
        if ungrounded_knowledge_propositions and allow_partial:
            invalid_ids = {str(item['local_id']) for item in ungrounded_knowledge_propositions}
            rejected_claims.append({'segment_id': segment['id'], 'reason': 'SOURCE_ANCHOR_NOT_VERIFIED', 'claims': ungrounded_knowledge_propositions})
            generated['knowledge_propositions'] = [item for item in generated['knowledge_propositions'] if str(item.get('local_id')) not in invalid_ids]
            for item in generated.get('narration_propositions', []):
                item['knowledge_proposition_local_ids'] = [value for value in item.get('knowledge_proposition_local_ids', []) if str(value) not in invalid_ids]
            generated['narration_propositions'] = [item for item in generated.get('narration_propositions', []) if item.get('knowledge_proposition_local_ids')]
            ungrounded_knowledge_propositions = []
        if ungrounded_knowledge_propositions:
            if use_small_source_batch:
                raise ValueError(
                    "batched proposition graph contains an ungrounded knowledge proposition "
                    f"for segment {segment['id']}"
                )
            grounding_repair_prompt = json.dumps(
                {
                    "task": (
                        "Repair only the listed ungrounded knowledge propositions."
                    ),
                    "rules": [
                        "Do not add, delete, reorder, or alter any unlisted proposition.",
                        (
                            "Keep every citation within the supplied source_units and cite only "
                            "listed ids."
                        ),
                        (
                            "Every repair must include source_anchor copied exactly from a "
                            "cited source passage; it may support a Simplified Chinese translation."
                        ),
                        "Do not invent facts, source ids, or narration text.",
                    ],
                    "source_units": evidence_context,
                    "knowledge_points": relevant_kps,
                    "invalid_knowledge_propositions": ungrounded_knowledge_propositions,
                    "output_schema": {
                        "repairs": [
                            {
                                "local_id": "an invalid local_id",
                                "text": "repaired atomic claim",
                                "source_unit_ids": ["cited source id"],
                                "source_anchor": "exact quote from cited source text",
                            }
                        ]
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            repaired = _json_object(
                chat_with_system(
                    grounding_repair_prompt,
                    system_prompt=(
                        "You repair source grounding only. Output only valid JSON."
                    ),
                    model=model,
                    temperature=0.0,
                    max_tokens=GRAPH_MAX_TOKENS,
                    timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                )
            )
            repairs_by_local_id = {
                str(item.get("local_id") or ""): item
                for item in repaired.get("repairs", [])
                if isinstance(item, dict)
            }
            for item in generated.get("knowledge_propositions", []):
                if not isinstance(item, dict):
                    continue
                repair = repairs_by_local_id.get(str(item.get("local_id") or ""))
                if repair:
                    item["text"] = repair.get("text")
                    item["source_unit_ids"] = repair.get("source_unit_ids")
                    item["source_anchor"] = repair.get("source_anchor")
        segment_local_to_stable: dict[str, str] = {}
        for item in generated.get("knowledge_propositions", []):
            if not isinstance(item, dict):
                raise ValueError("knowledge_propositions must contain objects")
            local_id = str(item.get("local_id") or "").strip()
            refs = [
                str(value) for value in item.get("source_unit_ids", []) if str(value) in source_ids
            ]
            knowledge_point_id = str(item.get("knowledge_point_id") or "")
            text = str(item.get("text") or "").strip()
            if not local_id or not text or not refs or knowledge_point_id not in kp_ids:
                raise ValueError(
                    f"invalid source-grounded knowledge proposition for segment {segment['id']}"
                )
            if any(ref not in provided_source_ids for ref in refs):
                raise ValueError(
                    f"knowledge proposition cites evidence outside its segment context: {refs}"
                )
            cited_units = [unit for unit in evidence_context if str(unit["id"]) in refs]
            source_anchor = str(item.get("source_anchor") or "").strip()
            if not any(
                lexical_score(text, str(unit["text"])) > 0 for unit in cited_units
            ) and not _has_valid_source_anchor(item, cited_units, raw.read_text(encoding="utf-8")):
                raise ValueError(
                    "knowledge proposition has no lexical grounding or valid source anchor "
                    "in its cited "
                    f"source passage for segment {segment['id']}: {local_id}"
                )
            scoped_local_id = f"seg-{segment['id']}::{local_id}"
            if scoped_local_id in local_to_stable:
                raise ValueError(f"duplicate knowledge proposition local_id: {scoped_local_id}")
            stable_id = f"{case}-kprop-{len(graph_kprops) + 1:03d}"
            local_to_stable[scoped_local_id] = stable_id
            segment_local_to_stable[local_id] = stable_id
            graph_kprops.append(
                {
                    "id": stable_id,
                    "knowledge_point_id": knowledge_point_id,
                    "text": text,
                    "source_refs": refs,
                    "source_anchor": source_anchor or None,
                    "status": "LLM_PROPOSED_SOURCE_GROUNDED_PENDING_HUMAN_REVIEW",
                }
            )
        def valid_local_links(item: dict) -> bool:
            links = item.get("knowledge_proposition_local_ids")
            return isinstance(links, list) and bool(links) and all(
                isinstance(link, str) and link in segment_local_to_stable for link in links
            )

        clause_spans = {}
        if use_narration_clause_ids:
            clauses = _narration_clauses(segment)
            positions = {clause["id"]: index for index, clause in enumerate(clauses)}
            resolved = []
            for item in generated.get("narration_propositions", []):
                ids = item.get("narration_clause_ids") if isinstance(item, dict) else None
                indexes = (
                    [positions.get(value, -1) for value in ids]
                    if isinstance(ids, list) and all(isinstance(value, str) for value in ids)
                    else []
                )
                if (
                    not isinstance(item, dict)
                    or str(item.get("segment_id")) != segment["id"]
                    or not indexes
                    or indexes[0] < 0
                    or indexes != list(range(indexes[0], indexes[0] + len(indexes)))
                ):
                    if not allow_partial:
                        raise ValueError(f"invalid narration clause IDs for segment {segment['id']}")
                    rejected_claims.append({
                        "segment_id": segment["id"],
                        "reason": "invalid_narration_clause_ids",
                        "returned_clause_ids": ids,
                    })
                    continue
                start = clauses[indexes[0]]["start"]
                end = clauses[indexes[-1]]["end"]
                item["text"] = segment["narration"][start:end]
                clause_spans[id(item)] = (start, end)
                resolved.append(item)
            generated["narration_propositions"] = resolved
        missing_links = [
            item
            for item in generated.get("narration_propositions", [])
            if isinstance(item, dict) and not valid_local_links(item)
        ]
        if missing_links and not use_narration_clause_ids:
            if use_small_source_batch and not allow_partial:
                raise ValueError(
                    "batched proposition graph contains an unlinked narration proposition "
                    f"for segment {segment['id']}"
                )
            repair_prompt = json.dumps(
                {
                    "task": (
                        "Repair only missing knowledge-proposition links in a proposition graph."
                    ),
                    "rules": [
                        "Do not create, delete, paraphrase, or reorder any proposition.",
                        (
                            "For every item below, return its exact narration_text and one or "
                            "more IDs from allowed_knowledge_proposition_local_ids."
                        ),
                        "Return JSON only.",
                    ],
                    "allowed_knowledge_proposition_local_ids": sorted(segment_local_to_stable),
                    "knowledge_propositions": generated.get("knowledge_propositions", []),
                    "unlinked_narration_propositions": missing_links,
                    "output_schema": {
                        "links": [
                            {
                                "narration_text": "exact input text",
                                "knowledge_proposition_local_ids": ["allowed id"],
                            }
                        ]
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            repaired = _json_object(
                chat_with_system(
                    repair_prompt,
                    system_prompt="You repair graph links only. Output only valid JSON.",
                    model=model,
                    temperature=0.0,
                    max_tokens=REPAIR_MAX_TOKENS,
                    timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                )
            )
            repaired_links = {
                str(item.get("narration_text") or ""): item.get(
                    "knowledge_proposition_local_ids", []
                )
                for item in repaired.get("links", [])
                if isinstance(item, dict)
            }
            for item in missing_links:
                item["knowledge_proposition_local_ids"] = repaired_links.get(
                    str(item.get("text") or ""), []
                )
            unresolved_links = [
                item
                for item in missing_links
                if not valid_local_links(item)
            ]
            for repair_index, item in enumerate(unresolved_links, start=1):
                minimal_link_prompt = json.dumps(
                    {
                        "task": (
                            "Return exactly one allowed knowledge-proposition local ID for "
                            "this narration proposition."
                        ),
                        "rules": [
                            "Return one non-empty ID from allowed_knowledge_proposition_local_ids.",
                            "Do not create or modify any proposition or narration text.",
                            "Return JSON only.",
                        ],
                        "repair_id": str(repair_index),
                        "narration_proposition": {
                            "text": item.get("text"),
                            "segment_id": item.get("segment_id"),
                        },
                        "allowed_knowledge_proposition_local_ids": sorted(
                            segment_local_to_stable
                        ),
                        "knowledge_propositions": generated.get("knowledge_propositions", []),
                        "output_schema": {
                            "repair_id": str(repair_index),
                            "knowledge_proposition_local_ids": ["one allowed id"],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                minimally_repaired = _json_object(
                    chat_with_system(
                        minimal_link_prompt,
                        system_prompt="You repair one graph link only. Output only valid JSON.",
                        model=model,
                        temperature=0.0,
                        max_tokens=REPAIR_MAX_TOKENS,
                        timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                    )
                )
                if str(minimally_repaired.get("repair_id") or "") == str(repair_index):
                    item["knowledge_proposition_local_ids"] = minimally_repaired.get(
                        "knowledge_proposition_local_ids", []
                    )
        invalid_spans = []
        for item in ([] if use_narration_clause_ids else generated.get("narration_propositions", [])):
            if not isinstance(item, dict):
                continue
            candidate_text = str(item.get("text") or "").strip()
            try:
                _locate_span(segment["narration"], candidate_text)
            except ValueError:
                invalid_spans.append(item)
        if invalid_spans and not allow_partial:
            if use_small_source_batch:
                raise ValueError(
                    "batched proposition graph contains a narration span outside segment "
                    f"{segment['id']}"
                )
            span_repair_prompt = json.dumps(
                {
                    "task": (
                        "Replace each paraphrased narration proposition with an exact "
                        "contiguous substring from the supplied narration."
                    ),
                    "rules": [
                        "Do not change the proposition meaning.",
                        (
                            "exact_narration_text must be copied character-for-character from "
                            "narration."
                        ),
                        "Do not add or remove propositions; repair every listed original_text.",
                    ],
                    "narration": segment["narration"],
                    "invalid_propositions": [
                        {
                            "original_text": item.get("text"),
                            "knowledge_proposition_local_ids": item.get(
                                "knowledge_proposition_local_ids", []
                            ),
                        }
                        for item in invalid_spans
                    ],
                    "output_schema": {
                        "repairs": [
                            {
                                "original_text": "exact invalid input",
                                "exact_narration_text": "exact source substring",
                            }
                        ]
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            repaired = _json_object(
                chat_with_system(
                    span_repair_prompt,
                    system_prompt="You repair source spans only. Output only valid JSON.",
                    model=model,
                    temperature=0.0,
                    max_tokens=REPAIR_MAX_TOKENS,
                    timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                )
            )
            exact_text_by_original = {
                str(item.get("original_text") or ""): str(item.get("exact_narration_text") or "")
                for item in repaired.get("repairs", [])
                if isinstance(item, dict)
            }
            for item in invalid_spans:
                item["text"] = exact_text_by_original.get(str(item.get("text") or ""), "")
        for item in generated.get("narration_propositions", []):
            if not isinstance(item, dict):
                raise ValueError("narration_propositions must contain objects")
            segment_id = str(item.get("segment_id") or "")
            text = str(item.get("text") or "").strip()
            links = [
                segment_local_to_stable[str(value)]
                for value in item.get("knowledge_proposition_local_ids", [])
                if str(value) in segment_local_to_stable
            ]
            if segment_id == segment["id"] and text and not valid_local_links(item) and allow_partial:
                rejected_claims.append({
                    "segment_id": segment_id, "text": text,
                    "reason": "unresolved_knowledge_proposition_links",
                    "returned_links": item.get("knowledge_proposition_local_ids"),
                })
                continue
            if segment_id != segment["id"] or not text or not valid_local_links(item):
                raise ValueError(
                    "invalid narration proposition for segment "
                    f"{segment['id']}: returned_segment={segment_id!r}, "
                    f"has_text={bool(text)}, returned_links="
                    f"{item.get('knowledge_proposition_local_ids')!r}, "
                    f"available_links={sorted(segment_local_to_stable)}"
                )
            try:
                if use_narration_clause_ids:
                    start, end = clause_spans[id(item)]
                else:
                    start, end = _locate_span(segment_text[segment_id], text, cursors.get(segment_id, 0))
            except ValueError:
                if not allow_partial:
                    raise
                rejected_claims.append({
                    "segment_id": segment_id,
                    "text": text,
                    "reason": "narration_span_not_found",
                    "returned_links": item.get("knowledge_proposition_local_ids"),
                })
                continue
            cursors[segment_id] = end
            graph_nprops.append(
                {
                    "id": f"{case}-seg-{segment_id}-nprop-{len(graph_nprops) + 1:03d}",
                    "segment_id": segment_id,
                    "text": segment_text[segment_id][start:end],
                    "span": {
                        "start": start,
                        "end": end,
                        "unit": "unicode_codepoint",
                        "end_exclusive": True,
                    },
                    "knowledge_proposition_ids": links,
                    "source_refs": sorted(
                        {
                            ref
                            for link in links
                            for ref in next(
                                k["source_refs"] for k in graph_kprops if k["id"] == link
                            )
                        }
                    ),
                    "status": "LLM_PROPOSED_NARRATION_GROUNDING_PENDING_HUMAN_REVIEW",
                }
            )
        _write_json(Path(output_path).with_name(f"{Path(output_path).stem}_validated_partial.json"), {
            'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
            'storyboard_sha256': hashlib.sha256(Path(storyboard_path).read_bytes()).hexdigest(),
            'validated_through_segment': segment['id'],
            'knowledge_propositions': graph_kprops, 'narration_propositions': graph_nprops,
            'rejected_claims': rejected_claims,
            'status': 'PARTIAL_NOT_A_COMPLETE_GRAPH',
        })
    if not graph_kprops:
        raise ValueError("model returned no valid knowledge propositions")
    if not graph_nprops:
        raise ValueError("model returned no valid narration propositions")
    payload = {
        "rejected_claims": rejected_claims,
        "coverage_status": "PARTIAL_SOURCE_REJECTIONS" if rejected_claims else "VALIDATED_MODEL_OUTPUT",
        "schema_version": GRAPH_VERSION,
        "case_id": case,
        "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest() if raw.is_file() else None,
        "source_evidence_path": str(Path(source_evidence_path)),
        "storyboard_path": str(Path(storyboard_path)),
        "lesson_plan_path": str(lesson_plan_path) if lesson_plan_path else None,
        "knowledge_propositions": graph_kprops,
        "narration_propositions": graph_nprops,
        "claim": (
            "LLM-generated, schema-validated source grounding; not an automatic factual gold label."
        ),
    }
    return _write_json(Path(output_path), payload)


__all__ = [
    "GRAPH_MAX_TOKENS",
    "GRAPH_REQUEST_TIMEOUT_SEC",
    "GRAPH_VERSION",
    "REPAIR_MAX_TOKENS",
    "build_proposition_graph",
]
