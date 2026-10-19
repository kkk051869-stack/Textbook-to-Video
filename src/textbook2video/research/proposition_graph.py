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


def _prompt(
    source_units: list[dict[str, Any]],
    knowledge_points: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "task": "Build a source-grounded proposition graph for an instructional video.",
            "rules": [
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
                    "Cite the most direct source passage. Every material detail in the "
                    "proposition must be supported by the cited passage; do not strengthen "
                    "claims with words such as unique, impossible, immediate, or causal "
                    "unless the passage states them."
                ),
                (
                    "A narration proposition is one atomic claim expressed by the narration. "
                    "Its text must be an exact contiguous substring of the given segment "
                    "narration."
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
            ],
            "output_schema": {
                "knowledge_propositions": [
                    {
                        "local_id": "kp1-p1",
                        "knowledge_point_id": "existing knowledge point id",
                        "text": "atomic factual/causal claim",
                        "source_unit_ids": ["raw-unit-0001"],
                    }
                ],
                "narration_propositions": [
                    {
                        "segment_id": "existing segment id",
                        "text": "exact substring from narration",
                        "knowledge_proposition_local_ids": ["kp1-p1"],
                    }
                ],
            },
            "source_units": source_units,
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
    return scored[:limit]


def build_proposition_graph(
    *,
    raw_path: str | Path,
    source_evidence_path: str | Path,
    storyboard_path: str | Path,
    lesson_plan_path: str | Path | None,
    output_path: str | Path,
    model: str | None = None,
) -> Path:
    """Generate and validate a real proposition graph with an LLM.

    No sentence-splitting fallback exists.  A failed/invalid response stops
    the research treatment because proceeding would make provenance claims
    that the data do not support.
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
    graph_kprops: list[dict[str, Any]] = []
    local_to_stable: dict[str, str] = {}
    graph_nprops: list[dict[str, Any]] = []
    cursors: dict[str, int] = {}
    for segment in segments:
        relevant_kps = [
            item
            for item in knowledge_points
            if item["id"] in set(segment.get("knowledge_point_ids", []))
        ] or knowledge_points
        evidence_context = _evidence_for_segment(source_units, segment["narration"])
        generated = _json_object(
            chat_with_system(
                _prompt(
                    evidence_context,
                    relevant_kps,
                    [{"id": segment["id"], "narration": segment["narration"]}],
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
        provided_source_ids = {str(item["id"]) for item in evidence_context}
        requires_propositions = any(
            lexical_score(segment["narration"], str(unit["text"])) >= 0.08
            for unit in evidence_context
        )
        if requires_propositions and (
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
                    + "\nYour previous response omitted propositions. Return at least one knowledge_proposition and one narration_proposition for this source-overlapping segment; cite only the supplied source unit IDs.",
                    system_prompt="You are a careful instructional-content analyst. Output only valid JSON.",
                    model=model,
                    temperature=0.0,
                    max_tokens=GRAPH_MAX_TOKENS,
                    timeout=GRAPH_REQUEST_TIMEOUT_SEC,
                )
            )
            if not generated.get("knowledge_propositions") or not generated.get("narration_propositions"):
                raise ValueError(
                    "model omitted all propositions after retry for a source-overlapping narration "
                    f"segment: {segment['id']}"
                )
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
            if not any(lexical_score(text, str(unit["text"])) > 0 for unit in cited_units):
                raise ValueError(
                    "knowledge proposition has no lexical grounding in its cited "
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
                    "status": "LLM_PROPOSED_SOURCE_GROUNDED_PENDING_HUMAN_REVIEW",
                }
            )
        missing_links = [
            item
            for item in generated.get("narration_propositions", [])
            if isinstance(item, dict) and not item.get("knowledge_proposition_local_ids")
        ]
        if missing_links:
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
        invalid_spans = []
        for item in generated.get("narration_propositions", []):
            if not isinstance(item, dict):
                continue
            candidate_text = str(item.get("text") or "").strip()
            try:
                _locate_span(segment["narration"], candidate_text)
            except ValueError:
                invalid_spans.append(item)
        if invalid_spans:
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
            if segment_id != segment["id"] or not text or not links:
                raise ValueError(
                    "invalid narration proposition for segment "
                    f"{segment['id']}: returned_segment={segment_id!r}, "
                    f"has_text={bool(text)}, returned_links="
                    f"{item.get('knowledge_proposition_local_ids')!r}, "
                    f"available_links={sorted(segment_local_to_stable)}"
                )
            start, end = _locate_span(segment_text[segment_id], text, cursors.get(segment_id, 0))
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
    if not graph_kprops:
        raise ValueError("model returned no valid knowledge propositions")
    if not graph_nprops:
        raise ValueError("model returned no valid narration propositions")
    payload = {
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
