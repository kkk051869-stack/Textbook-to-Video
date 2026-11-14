"""Source → pages, spoken teaching actions and focus references for produce.

Engineering metadata lives on the existing Storyboard. Events are materialized
only after TTS has measured each complete action utterance.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path

from textbook2video.animation_ids import native_object_targets, sanitize_animation_id

VERSION = "joint-teaching-actions-v2"


def action_narrations(segment: dict) -> list[str]:
    actions = segment.get("teaching_actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("joint page requires nonempty teaching_actions")
    texts = [a.get("narration") for a in actions]
    if any(not isinstance(t, str) or not t.strip() for t in texts):
        raise ValueError("each teaching action requires spoken narration")
    if "".join(texts) != segment.get("narration"):
        raise ValueError("teaching actions do not exactly cover page narration")
    return texts


def resolve_reference(segment: dict, ref: dict) -> str:
    elements = {e["id"]: e for e in segment["elements"]}
    if not isinstance(ref, dict) or ref.get("element_id") not in elements:
        raise ValueError(f"unknown joint focus object: {ref}")
    element = elements[ref["element_id"]]
    index = ref.get("index")
    if index is None:
        return element["id"]
    if type(index) is not int:
        raise ValueError(f"joint object index must be an integer: {ref}")
    hits = [key for key, obj in native_object_targets(element).items() if obj["index"] == index]
    if len(hits) != 1:
        raise ValueError(f"joint object index does not resolve: {ref}")
    return hits[0]


def _source_quote_matches(source: str, quote: str) -> bool:
    """Legacy compatibility: ellipses may join exact source fragments in order."""
    markers = re.compile(r"(?:\.{3,}|…+)")
    parts = markers.split(quote)
    if len(parts) == 1:
        return quote in source
    fragments = [part.strip() for part in parts if part.strip()]
    if not fragments:
        return False
    cursor = 0
    for fragment in fragments:
        start = source.find(fragment, cursor)
        if start < 0:
            return False
        cursor = start + len(fragment)
    return True


def validate_joint_segment(
    segment: dict,
    source: str | None = None,
    *,
    source_unit_ids: set[str] | None = None,
) -> None:
    action_narrations(segment)
    elements = segment.get("elements", [])
    allowed = {
        "heading",
        "text",
        "flow_step",
        "activity_step",
        "comparison_panel",
        "table",
        "image",
    }
    if segment.get("visual_type") in {"network", "tree"} or any(
        e.get("type") not in allowed for e in elements
    ):
        raise ValueError("joint planning requires deterministic native page components")
    ids = [e.get("id") for e in elements]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not isinstance(i, str) or not i or sanitize_animation_id(i) != i for i in ids)
    ):
        raise ValueError("joint elements require unique selector-safe IDs")
    relations = segment.get("visual_relations", [])
    rel_ids = [r["id"] for r in relations]
    if len(set(rel_ids)) != len(rel_ids):
        raise ValueError("duplicate joint relation ID")
    for relation in relations:
        for ref in relation["from"] + relation["to"]:
            resolve_reference(segment, ref)
    for action in segment["teaching_actions"]:
        for key in ("teaching_goal", "focus_reason"):
            if not isinstance(action.get(key), str) or not action[key].strip():
                raise ValueError(f"teaching action requires {key}")
        focus = [resolve_reference(segment, r) for r in action.get("focus", [])]
        background = {resolve_reference(segment, r) for r in action["background"]}
        if len(focus) != len(set(focus)) or set(focus) & background:
            raise ValueError("joint focus duplicated or also marked as background")
        if not set(action["relation_refs"]) <= set(rel_ids):
            raise ValueError("joint action references an unknown relation")
    joint_meta = segment.get("joint_planning", {})
    has_source_unit_contract = source_unit_ids is not None or "source_unit_ids" in joint_meta
    valid_source_ids = source_unit_ids
    if valid_source_ids is None and has_source_unit_contract:
        raw_ids = joint_meta.get("source_unit_ids")
        if not isinstance(raw_ids, list) or any(not isinstance(item, str) for item in raw_ids):
            raise ValueError("joint planning source_unit_ids metadata is invalid")
        valid_source_ids = set(raw_ids)
    if has_source_unit_contract:
        if not valid_source_ids:
            raise ValueError("joint planning requires available source-unit IDs")
        reference_mode = joint_meta.get("source_reference_mode", "source_unit_ids")
        for item in relations + segment["teaching_actions"]:
            refs = item.get("source_refs")
            if reference_mode == "legacy_quote_compat" and refs is None:
                quote = item.get("source_quote")
                if source is not None and (
                    not isinstance(quote, str)
                    or not quote.strip()
                    or not _source_quote_matches(source, quote)
                ):
                    raise ValueError("legacy source quote cannot be located in its source chunk")
                continue
            if (
                not isinstance(refs, list)
                or not refs
                or any(not isinstance(ref, str) or ref not in valid_source_ids for ref in refs)
                or len(refs) != len(set(refs))
            ):
                raise ValueError("joint action/relation source_refs contain missing or unknown IDs")
    elif source is not None:
        # Preserve validation for saved v1 plans. New v2 plans cite stable source IDs.
        for item in relations + segment["teaching_actions"]:
            quote = item.get("source_quote")
            if not isinstance(quote, str) or not quote.strip() or not _source_quote_matches(source, quote):
                raise ValueError("joint action/relation quote is absent from its textbook chunk")


def _source_chunks(source: str, limit: int = 800) -> list[str]:
    # Bound requests at sentence/paragraph boundaries; never discard source text.
    parts = re.split(r"(?<=[。！？\n])|(?<=[.!?])(?=\s)", source)
    chunks: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) > limit:
            chunks.append(current)
            current = ""
        current += part
    if current:
        chunks.append(current)
    return chunks


def _source_unit_chunks(
    source: str, source_units: list[dict], limit: int = 800
) -> list[tuple[str, list[dict]]]:
    """Group existing source-evidence units without changing or dropping source text."""
    if not source_units:
        raise ValueError("joint planning requires existing numbered source units")
    if any(
        not isinstance(unit, dict) or not isinstance(unit.get("char_span"), dict)
        for unit in source_units
    ):
        raise ValueError("joint planning received invalid source-unit locations")
    units = sorted(source_units, key=lambda item: item["char_span"].get("start", -1))
    seen: set[str] = set()
    for unit in units:
        span = unit.get("char_span")
        ident = unit.get("id")
        if (
            not isinstance(ident, str)
            or not ident
            or ident in seen
            or not isinstance(span, dict)
            or type(span.get("start")) is not int
            or type(span.get("end")) is not int
            or span["start"] < 0
            or span["end"] < span["start"]
            or span["end"] > len(source)
            or source[span["start"] : span["end"]].strip() != str(unit.get("text") or "").strip()
        ):
            raise ValueError("joint planning received invalid source-unit locations")
        seen.add(ident)

    chunks: list[tuple[str, list[dict]]] = []
    cursor = 0
    grouped: list[dict] = []
    for index, unit in enumerate(units):
        start = unit["char_span"]["start"]
        next_start = (
            units[index + 1]["char_span"]["start"] if index + 1 < len(units) else len(source)
        )
        if grouped and next_start - cursor > limit:
            chunks.append((source[cursor:start], grouped))
            cursor = start
            grouped = []
        grouped.append(unit)
    if grouped:
        chunks.append((source[cursor:], grouped))
    if not chunks or "".join(chunk for chunk, _ in chunks) != source:
        raise ValueError("joint source-unit grouping changed textbook text")
    return chunks


def generate_joint_storyboard(
    source: str,
    *,
    lesson_title: str,
    model: str | None,
    output_dir: Path,
    stem: str,
    lesson_plan: dict,
    available_images: list[dict] | None = None,
    available_source_units: list[dict] | None = None,
    source_evidence_path: str | Path | None = None,
    agent_review: bool = False,
    agent_review_rounds: int = 2,
    agent_review_strict: bool = False,
) -> dict:
    from textbook2video.llm.client import chat
    from textbook2video.pipeline.checks import validate_storyboard
    from textbook2video.pipeline.config import LLM_DEFAULT_MODEL

    if not source.strip():
        raise ValueError("joint planning requires textbook text")
    output_dir = Path(output_dir)
    evidence = output_dir / f"{stem}_joint_planning"
    evidence.mkdir(parents=True, exist_ok=True)
    prompt_base = Path(__file__).parent.parent / "llm" / "prompts" / "joint_teaching.md"
    instructions = prompt_base.read_text(encoding="utf-8")
    image_catalog = {}
    for image in available_images or []:
        ident = str(image.get("id") or image.get("filename") or "")
        if ident and image.get("filename"):
            image_catalog[ident] = image
    legacy_reference_compat = available_source_units is None
    if available_source_units is None:
        from textbook2video.research.source_evidence import _source_units

        source_units = _source_units(source)
    else:
        source_units = available_source_units
    unit_chunks = _source_unit_chunks(source, source_units)
    pages = []
    for chunk_index, (chunk, chunk_units) in enumerate(unit_chunks, 1):
        unit_ids = [str(unit["id"]) for unit in chunk_units]
        prompt = (
            instructions
            + "\n"
            + json.dumps(
                {
                    "lesson_title": lesson_title,
                    "lesson_plan": lesson_plan,
                    "source_units": chunk_units,
                    "available_images": list(image_catalog.values()),
                },
                ensure_ascii=False,
            )
        )
        prefix = evidence / f"chunk-{chunk_index:03d}"
        if prefix.with_suffix(".prompt.txt").exists():
            raise FileExistsError(
                f"joint planning evidence already exists: {prefix}; use a new output directory"
            )
        prefix.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
        raw = chat(
            [{"role": "user", "content": prompt}],
            model=model or LLM_DEFAULT_MODEL,
            temperature=0.3,
            max_tokens=12000,
            timeout=180,
            response_format={"type": "json_object"},
        )
        prefix.with_suffix(".response.txt").write_text(raw, encoding="utf-8")
        try:
            batch = json.loads(raw)["segments"]
            if not isinstance(batch, list) or not batch:
                raise ValueError("joint planner returned no pages")
            for index, item in enumerate(batch, 1):
                segment = copy.deepcopy(item)
                segment["id"] = f"joint-{chunk_index}-{index}"
                segment["narration"] = "".join(a["narration"] for a in segment["teaching_actions"])
                for n, action in enumerate(segment["teaching_actions"], 1):
                    action["id"] = f"{segment['id']}-action-{n}"
                for element in segment["elements"]:
                    if element.get("type") == "image":
                        image = image_catalog.get(str(element.get("source_image_id") or ""))
                        if image is None:
                            raise ValueError("joint planner referenced an unknown textbook image")
                        element["src"] = image["filename"]
                segment["joint_planning"] = {
                    "producer": VERSION,
                    "source_chunk": chunk_index,
                    "source_sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                    "source_unit_ids": unit_ids,
                    "source_reference_mode": (
                        "legacy_quote_compat" if legacy_reference_compat else "source_unit_ids"
                    ),
                    "semantic_review": "MODEL_PLANNED_NOT_INDEPENDENTLY_VERIFIED",
                }
                if legacy_reference_compat:
                    validate_joint_segment(segment, chunk, source_unit_ids=set(unit_ids))
                else:
                    validate_joint_segment(segment, source_unit_ids=set(unit_ids))
                pages.append(segment)
            validation = validate_storyboard({"segments": pages})
            if validation.errors:
                raise ValueError("; ".join(validation.errors))
        except (ValueError, KeyError, TypeError) as exc:
            prefix.with_suffix(".failure.json").write_text(
                json.dumps(
                    {
                        "status": "FAILED",
                        "error": str(exc),
                        "stage": "joint_planning_validation",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            raise ValueError(f"joint planning chunk {chunk_index} rejected: {exc}") from exc
    board = {
        "lesson_title": lesson_title,
        "segments": pages,
        "metadata": {
            "joint_planning": {
                "producer": VERSION,
                "chunks": len(unit_chunks),
                "evidence_dir": str(evidence),
                "model": model or LLM_DEFAULT_MODEL,
                "prompt_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                "source_evidence_path": str(source_evidence_path) if source_evidence_path else None,
            },
            "available_images": available_images or [],
        },
    }
    if agent_review or os.environ.get("T2V_STORYBOARD_AGENT_REVIEW") == "1":
        from textbook2video.pipeline.storyboard import run_storyboard_agent_review

        board = run_storyboard_agent_review(
            board,
            lesson_plan=lesson_plan,
            model=model,
            max_rounds=agent_review_rounds,
            strict=agent_review_strict,
        )
        for page in board["segments"]:
            validate_joint_segment(page, source)
    return board


def apply_joint_action_timing(segment: dict, cues: list[dict]) -> None:
    """Rebuild only this page's event plan from measured action utterances."""
    validate_joint_segment(segment)
    if [c.get("text") for c in cues] != action_narrations(segment):
        raise ValueError("measured action cues do not match joint narration")
    duration = float(segment["audio_duration_sec"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("joint actions require a positive measured audio duration")
    # A first-action focus already ensures visibility. Do not overlap it with
    # a separate entrance on the same root; children still need their parent.
    initial_focus = {resolve_reference(segment, r) for r in segment["teaching_actions"][0]["focus"]}
    events = [
        {
            "event_id": f"{segment['id']}-show-{e['id']}",
            "target": e["id"],
            "action": "show",
            "effect": "fadeInUp",
            "at_sec": 0,
        }
        for e in segment["elements"]
        if e["id"] not in initial_focus
    ]
    cursor = 0.0
    for action, cue in zip(segment["teaching_actions"], cues):
        start, end = float(cue["start_sec"]), float(cue["end_sec"])
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or end <= start
            or abs(start - cursor) > 0.02
            or end > duration + 0.02
        ):
            raise ValueError("joint action cue boundaries invalid or noncontiguous")
        cursor = end
        at = min(start + 0.12, start + (end - start) / 2)
        for index, ref in enumerate(action["focus"], 1):
            target = resolve_reference(segment, ref)
            events.append(
                {
                    "event_id": f"{action['id']}-focus-{index}",
                    "target": target,
                    "action": "focus",
                    "effect": "highlight",
                    "at_sec": at,
                    "hold_sec": end - at,
                    "teaching_action_id": action["id"],
                    "timing_source": "measured_action_cue_approximate_start",
                }
            )
        action["timing"] = {
            "cue_id": cue["sentence_id"],
            "start_sec": start,
            "end_sec": end,
            "focus_at_sec": at,
            "approximation": "action cue + 0.12s; no word-level alignment",
        }
    if abs(cursor - duration) > 0.02:
        raise ValueError("joint action cues do not cover measured page audio")
    segment["timeline"] = events
    segment["animations"] = copy.deepcopy(events)
