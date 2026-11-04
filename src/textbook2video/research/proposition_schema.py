"""Versioned research_generation_v2 dual-write helpers.

This module is the only bridge from permissive production JSON to the frozen
research contract.  It never changes an artifact unless the feature flag is
enabled, and every derived relation is labelled as deterministic bootstrap
metadata rather than human or model gold.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "research-generation-v2-v0.1"
FLAG = "T2V_RESEARCH_GENERATION_V2"


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def stable_case_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "research-case"


def _id(case_id: str, kind: str, index: int) -> str:
    return f"{case_id}-{kind}-{index:03d}"


def _meta(
    *, producer: str, confidence: float | None = None, abstain_reason: str | None = None
) -> dict[str, Any]:
    return {
        "producer": producer,
        "version": SCHEMA_VERSION,
        "confidence": confidence,
        "abstain_reason": abstain_reason,
    }


def _write(path: Path, document: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sentences(text: str) -> list[tuple[str, int, int]]:
    results: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[^。！？!?]+[。！？!?]?", text):
        value = match.group().strip()
        if value:
            start = match.start() + (len(match.group()) - len(match.group().lstrip()))
            results.append((value, start, start + len(value)))
    return results or ([(text.strip(), 0, len(text.strip()))] if text.strip() else [])


def _element_target_ids(segment: dict[str, Any], *, segment_label: str) -> dict[str, str]:
    """Return an unambiguous legacy→v2 element mapping or fail closed."""
    target_ids: dict[str, str] = {}
    v2_ids: set[str] = set()
    for element in segment.get("elements", []) or []:
        if not isinstance(element, dict):
            raise ValueError(f"{segment_label}: visual element must be an object")
        legacy_id = str(element.get("id") or "").strip()
        v2_id = str((element.get("research_generation_v2") or {}).get("element_id") or "").strip()
        if not legacy_id:
            raise ValueError(f"{segment_label}: visual element is missing its legacy id")
        if not v2_id:
            raise ValueError(f"{segment_label}: element {legacy_id!r} is missing its v2 element_id")
        if legacy_id in target_ids:
            raise ValueError(f"{segment_label}: duplicate legacy element id {legacy_id!r}")
        if v2_id in v2_ids:
            raise ValueError(f"{segment_label}: duplicate v2 element id {v2_id!r}")
        target_ids[legacy_id] = v2_id
        v2_ids.add(v2_id)
    return target_ids


def _resolve_animation_target(
    animation: dict[str, Any], target_ids: dict[str, str], *, segment_label: str
) -> str:
    legacy_target = str(animation.get("target") or "").strip()
    if not legacy_target:
        raise ValueError(f"{segment_label}: animation is missing its target")
    if legacy_target not in target_ids:
        raise ValueError(
            f"{segment_label}: animation target {legacy_target!r} does not resolve to an element"
        )
    return target_ids[legacy_target]


def _validated_animation_sources(
    segment: dict[str, Any], *, segment_label: str, target_ids: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    """Index annotated animation sources by legacy target, preserving order."""
    by_target: dict[str, list[dict[str, Any]]] = {}
    seen_event_ids: set[str] = set()
    for animation_index, animation in enumerate(segment.get("animations", []) or [], 1):
        if not isinstance(animation, dict):
            raise ValueError(f"{segment_label}: animation {animation_index} must be an object")
        raw_target = str(animation.get("target") or "").strip()
        if not raw_target:
            raise ValueError(f"{segment_label}: animation is missing its target")
        data = animation.get("research_generation_v2") or {}
        event_id = str(data.get("event_id") or "").strip()
        if not event_id:
            raise ValueError(
                f"{segment_label}: animation {animation_index} is missing event_id"
            )
        if event_id in seen_event_ids:
            raise ValueError(f"{segment_label}: duplicate event_id {event_id!r}")
        seen_event_ids.add(event_id)
        for target in (part.strip() for part in raw_target.split(",")):
            if not target:
                continue
            if target not in target_ids:
                raise ValueError(
                    f"{segment_label}: animation target {target!r} does not resolve to an element"
                )
            by_target.setdefault(target, []).append(
                {"event_id": event_id, "metadata": data, "animation": animation}
            )
    return by_target


def _canonical_compiled_events(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the renderer's compiler so G0 projects the events that can run."""
    # Import locally to keep proposition/schema helpers independent at module
    # import time while reusing the renderer's single canonical compiler.
    from textbook2video.animation_gen import build_slide_timelines

    return build_slide_timelines([segment])[0]


def _project_canonical_events(
    segment: dict[str, Any],
    *,
    case_id: str,
    segment_index: int,
    segment_label: str,
    target_ids: dict[str, str],
    segment_narration_ids: list[str],
) -> list[dict[str, Any]] | None:
    """Project renderer-compiled target events with deterministic G0 IDs.

    When the renderer uses ``timeline[]``, an event can cover several targets.
    The compiler expands those targets; match each expanded target to the
    first unused annotated legacy animation for that target so existing G0
    event IDs remain traceable. Events that exist only in the canonical
    timeline receive an ID derived from their stable compiled order.
    """
    sources = _validated_animation_sources(
        segment, segment_label=segment_label, target_ids=target_ids
    )
    compiled = _canonical_compiled_events(segment)
    if not compiled:
        if segment.get("timeline"):
            raise ValueError(
                f"{segment_label}: renderer timeline has entries but compiles no events"
            )
        return None

    source_offsets: dict[str, int] = {}
    used_event_ids: set[str] = set()
    projected: list[dict[str, Any]] = []
    allowed_actions = {"show", "reveal", "highlight", "focus", "transition", "remove", "dim"}
    for event_index, event in enumerate(compiled, 1):
        legacy_target = str(event.get("target") or "").strip()
        target_element_id = target_ids.get(legacy_target)
        if not target_element_id:
            raise ValueError(
                f"{segment_label}: compiled target {legacy_target!r} does not resolve to an element"
            )
        candidates = sources.get(legacy_target, [])
        source_offset = source_offsets.get(legacy_target, 0)
        source = candidates[source_offset] if source_offset < len(candidates) else None
        if source is not None:
            source_offsets[legacy_target] = source_offset + 1
        event_id = str(source["event_id"]) if source else ""
        if not event_id or event_id in used_event_ids:
            event_id = _id(case_id, "evt", segment_index * 100 + event_index)
        if event_id in used_event_ids:
            raise ValueError(f"{segment_label}: duplicate projected event_id {event_id!r}")
        used_event_ids.add(event_id)

        action = str(event.get("action") or "show")
        if action not in allowed_actions:
            raise ValueError(
                f"{segment_label}: renderer action {action!r} cannot be represented in G0 v0.1"
            )
        if action == "highlight" or action == "focus":
            semantic_role = "signaling"
        elif action == "dim" or action == "remove":
            semantic_role = "visibility_control"
        elif action == "transition":
            semantic_role = "transition"
        else:
            semantic_role = "content_reveal"
        source_metadata = source["metadata"] if source else {}
        narration_ids = source_metadata.get("narration_proposition_ids") or segment_narration_ids
        projected.append(
            {
                "id": event_id,
                "target_element_id": target_element_id,
                "action": action,
                "semantic_role": semantic_role,
                "narration_proposition_ids": narration_ids,
                "compiled_event_id": str(event.get("event_id") or ""),
                "legacy_target": legacy_target,
                "start_ms": int(event.get("start_ms") or 0),
                "duration_ms": int(event.get("duration_ms") or 0),
                "easing": str(event.get("easing") or "ease-out"),
                "source_animation_event_id": str(source["event_id"]) if source else None,
            }
        )
    return projected


def build_lesson_plan_v2(legacy: dict[str, Any], *, case_id: str, raw_text: str) -> dict[str, Any]:
    """Derive stable proposition/source fields while preserving legacy plan."""
    cid = stable_case_id(case_id)
    source_id = _id(cid, "src", 1)
    points: list[dict[str, Any]] = []
    for kp_index, raw in enumerate(legacy.get("knowledge_points", []) or [], 1):
        if not isinstance(raw, dict):
            continue
        kp_id = _id(cid, "kp", kp_index)
        text = str(raw.get("description") or raw.get("name") or "").strip()
        if not text:
            continue
        props = []
        for prop_index, (sentence, _start, _end) in enumerate(_sentences(text), 1):
            props.append(
                {
                    "id": f"{kp_id}-kprop-{prop_index:03d}",
                    "text": sentence,
                    "source_refs": [source_id],
                    "visual_support": {
                        "label": "uncertain",
                        "acquisition": "uncertain",
                        "rationale": None,
                        "metadata": _meta(
                            producer="bootstrap.lesson_plan", abstain_reason="not_yet_decided"
                        ),
                    },
                }
            )
        points.append(
            {
                "id": kp_id,
                "name": str(raw.get("name") or text),
                "description": raw.get("description"),
                "source_refs": [source_id],
                "propositions": props,
            }
        )
    if not points:
        points = [
            {
                "id": _id(cid, "kp", 1),
                "name": "Lesson content",
                "description": None,
                "source_refs": [source_id],
                "propositions": [
                    {
                        "id": f"{_id(cid, 'kp', 1)}-kprop-001",
                        "text": raw_text.strip()[:240] or "Untitled lesson",
                        "source_refs": [source_id],
                        "visual_support": {
                            "label": "uncertain",
                            "acquisition": "uncertain",
                            "rationale": None,
                            "metadata": _meta(
                                producer="bootstrap.lesson_plan", abstain_reason="empty_legacy_plan"
                            ),
                        },
                    }
                ],
            }
        ]
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "lesson_plan_v2",
        "case_id": cid,
        "lesson_title": str(legacy.get("lesson_title") or legacy.get("title") or "Untitled lesson"),
        "knowledge_points": points,
    }


def build_source_units_v2(
    *, case_id: str, raw_text: str, document_path: str = "raw_text"
) -> dict[str, Any]:
    cid = stable_case_id(case_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "source_units_v2",
        "case_id": cid,
        "document": {"title": cid, "path": document_path, "sha256": None},
        "source_units": [
            {
                "id": _id(cid, "src", 1),
                "kind": "span",
                "text": raw_text,
                "source_locator": "raw_text",
                "page_number": None,
                "char_span": {"start": 0, "end": len(raw_text)},
                "image_refs": [],
            }
        ],
        "source_images": [],
    }


def build_script_v2(
    segments: list[str], *, case_id: str, lesson_plan_v2: dict[str, Any]
) -> dict[str, Any]:
    cid = stable_case_id(case_id)
    kp_ids = [
        p["id"]
        for kp in lesson_plan_v2.get("knowledge_points", [])
        for p in kp.get("propositions", [])
    ]
    if not kp_ids:
        raise ValueError("lesson_plan_v2 has no knowledge propositions")
    result = []
    for index, narration in enumerate(segments, 1):
        seg_id = _id(cid, "seg", index)
        props = []
        for sentence_index, (text, start, end) in enumerate(_sentences(str(narration)), 1):
            # Deterministic bootstrap only.  Later semantic binding may revise
            # this relation, but it is never silently presented as gold.
            kp_id = kp_ids[min(index - 1, len(kp_ids) - 1)]
            props.append(
                {
                    "id": f"{seg_id}-nprop-{sentence_index:03d}",
                    "knowledge_proposition_ids": [kp_id],
                    "text": text,
                    "span": {
                        "start": start,
                        "end": end,
                        "unit": "unicode_codepoint",
                        "end_exclusive": True,
                    },
                    "metadata": _meta(
                        producer="bootstrap.script_v2",
                        confidence=None,
                        abstain_reason="deterministic_bootstrap_relation",
                    ),
                }
            )
        result.append(
            {
                "id": seg_id,
                "legacy_segment_id": index,
                "narration_text": str(narration),
                "narration_propositions": props,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "script_v2",
        "case_id": cid,
        "segments": result,
    }


def annotate_storyboard_v2(
    storyboard: dict[str, Any], script_v2: dict[str, Any], lesson_plan_v2: dict[str, Any]
) -> dict[str, Any]:
    """Dual-write explicit relations into legacy storyboard under one namespaced key."""
    segments = script_v2.get("segments", [])
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            continue
        script_segment = segments[min(index - 1, len(segments) - 1)] if segments else {}
        nprops = [
            str(item.get("id"))
            for item in script_segment.get("narration_propositions", [])
            if item.get("id")
        ]
        # A segment can contain several narration propositions that refer to
        # the same knowledge proposition.  Preserve first-seen order while
        # projecting the union so the standalone contract's uniqueItems rule
        # is satisfied without implying additional semantic bindings.
        kprops = list(
            dict.fromkeys(
                kid
                for item in script_segment.get("narration_propositions", [])
                for kid in item.get("knowledge_proposition_ids", [])
            )
        )
        segment["research_generation_v2"] = {
            "segment_id": script_segment.get("id"),
            "narration_proposition_ids": nprops,
            "knowledge_proposition_ids": kprops,
            "producer": "bootstrap.storyboard_v2",
        }
        for eindex, element in enumerate(segment.get("elements", []) or [], 1):
            if not isinstance(element, dict):
                continue
            element["research_generation_v2"] = {
                "element_id": _id(script_v2["case_id"], "el", index * 100 + eindex),
                "semantic_role": "explain"
                if element.get("type") in {"image", "diagram", "flow_step", "table"}
                else "organize",
                "source_refs": [],
                "knowledge_proposition_ids": kprops,
                "narration_proposition_ids": nprops,
                "acquisition": "reuse" if element.get("source_image_id") else "system-authored",
                "binding_source": "deterministic_bootstrap",
            }
        for aindex, animation in enumerate(segment.get("animations", []) or [], 1):
            if isinstance(animation, dict):
                animation["research_generation_v2"] = {
                    "event_id": _id(script_v2["case_id"], "evt", index * 100 + aindex),
                    "narration_proposition_ids": nprops,
                    "semantic_role": "content_reveal",
                    "producer": "bootstrap.storyboard_v2",
                }
    storyboard.setdefault("metadata", {})["research_generation_v2"] = {
        "schema_version": SCHEMA_VERSION,
        "case_id": script_v2["case_id"],
        "enabled": True,
    }
    return storyboard


def build_storyboard_v2(storyboard: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    """Project namespaced legacy relations into the strict standalone schema."""
    segments = []
    event_ids: set[str] = set()
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            raise ValueError(f"segment {index}: storyboard segment must be an object")
        relation = segment.get("research_generation_v2") or {}
        segment_label = str(relation.get("segment_id") or segment.get("id") or index)
        legacy_to_v2 = _element_target_ids(segment, segment_label=segment_label)
        elements = []
        for element in segment.get("elements", []) or []:
            if not isinstance(element, dict):
                continue
            data = element.get("research_generation_v2") or {}
            elements.append(
                {
                    "id": data.get("element_id"),
                    "legacy_id": str(element.get("id") or "") or None,
                    "type": str(element.get("type") or "unknown"),
                    "semantic_role": data.get("semantic_role", "organize"),
                    "source_refs": data.get("source_refs", []),
                    "knowledge_proposition_ids": data.get("knowledge_proposition_ids", []),
                    "narration_proposition_ids": data.get("narration_proposition_ids", []),
                    "acquisition": data.get("acquisition", "system-authored"),
                    "payload": {
                        key: value
                        for key, value in element.items()
                        if key != "research_generation_v2"
                    },
                }
            )
        canonical_events = _project_canonical_events(
            segment,
            case_id=case_id,
            segment_index=index,
            segment_label=segment_label,
            target_ids=legacy_to_v2,
            segment_narration_ids=relation.get("narration_proposition_ids", []),
        )
        events = []
        if canonical_events is not None:
            for event in canonical_events:
                event_id = event["id"]
                if event_id in event_ids:
                    raise ValueError(f"{segment_label}: duplicate event_id {event_id!r}")
                event_ids.add(event_id)
                events.append(
                    {
                        "id": event_id,
                        "action": event["action"],
                        "target_element_id": event["target_element_id"],
                        "narration_proposition_ids": event["narration_proposition_ids"],
                        "semantic_role": event["semantic_role"],
                    }
                )
        else:
            for animation_index, animation in enumerate(segment.get("animations", []) or [], 1):
                if not isinstance(animation, dict):
                    raise ValueError(
                        f"{segment_label}: animation {animation_index} must be an object"
                    )
                data = animation.get("research_generation_v2") or {}
                target_element_id = _resolve_animation_target(
                    animation,
                    legacy_to_v2,
                    segment_label=segment_label,
                )
                event_id = str(data.get("event_id") or "").strip()
                if not event_id:
                    raise ValueError(
                        f"{segment_label}: animation {animation_index} is missing event_id"
                    )
                if event_id in event_ids:
                    raise ValueError(f"{segment_label}: duplicate event_id {event_id!r}")
                event_ids.add(event_id)
                events.append(
                    {
                        "id": event_id,
                        "action": str(animation.get("action") or "show"),
                        "target_element_id": target_element_id,
                        "narration_proposition_ids": data.get("narration_proposition_ids", []),
                        "semantic_role": data.get("semantic_role", "content_reveal"),
                    }
                )
        if elements and events:
            segments.append(
                {
                    "id": relation.get("segment_id"),
                    "legacy_segment_id": segment.get("id"),
                    "narration_proposition_ids": relation.get("narration_proposition_ids", []),
                    "elements": elements,
                    "events": events,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "storyboard_v2",
        "case_id": stable_case_id(case_id),
        "segments": segments,
    }


def build_timed_storyboard_v2(
    storyboard: dict[str, Any], *, case_id: str, timing_source: str
) -> dict[str, Any]:
    segments = []
    event_ids: set[str] = set()
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            raise ValueError(f"segment {index}: storyboard segment must be an object")
        relation = segment.get("research_generation_v2") or {}
        segment_label = str(relation.get("segment_id") or segment.get("id") or index)
        target_ids = _element_target_ids(segment, segment_label=segment_label)
        canonical_events = _project_canonical_events(
            segment,
            case_id=case_id,
            segment_index=index,
            segment_label=segment_label,
            target_ids=target_ids,
            segment_narration_ids=relation.get("narration_proposition_ids", []),
        )
        events = []
        if canonical_events is not None:
            event_sources = [
                {
                    "event_id": event["id"],
                    "target_element_id": event["target_element_id"],
                    "action": event["action"],
                    "trigger_at_sec": event["start_ms"] / 1000.0,
                    "planned_duration_sec": event["duration_ms"] / 1000.0 or None,
                    "timing_source": timing_source,
                }
                for event in canonical_events
            ]
        else:
            event_sources = []
            for animation_index, animation in enumerate(segment.get("animations", []) or [], 1):
                if not isinstance(animation, dict):
                    raise ValueError(
                        f"{segment_label}: animation {animation_index} must be an object"
                    )
                target_element_id = _resolve_animation_target(
                    animation,
                    target_ids,
                    segment_label=segment_label,
                )
                data = animation.get("research_generation_v2") or {}
                event_sources.append(
                    {
                        "event_id": str(data.get("event_id") or "").strip(),
                        "target_element_id": target_element_id,
                        "action": str(animation.get("action") or "show"),
                        "trigger_at_sec": float(animation.get("trigger_at_sec") or 0.0),
                        "planned_duration_sec": float(animation.get("duration") or 0.0) or None,
                        "timing_source": timing_source,
                    }
                )
        for event in event_sources:
            event_id = event["event_id"]
            if not event_id:
                raise ValueError(f"{segment_label}: animation is missing event_id")
            if event_id in event_ids:
                raise ValueError(f"{segment_label}: duplicate event_id {event_id!r}")
            event_ids.add(event_id)
            events.append(event)
        if events:
            segments.append(
                {
                    "segment_id": relation.get("segment_id"),
                    "audio_duration_sec": float(segment.get("audio_duration_sec") or 0.001),
                    "scheduled_events": events,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "timed_storyboard_v2",
        "case_id": stable_case_id(case_id),
        "segments": segments,
    }


def build_compiled_timeline_v2(storyboard: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    """Export the same canonical renderer events using the frozen G0 schema."""
    segments = []
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            raise ValueError(f"segment {index}: storyboard segment must be an object")
        relation = segment.get("research_generation_v2") or {}
        segment_label = str(relation.get("segment_id") or segment.get("id") or index)
        target_ids = _element_target_ids(segment, segment_label=segment_label)
        events = _project_canonical_events(
            segment,
            case_id=case_id,
            segment_index=index,
            segment_label=segment_label,
            target_ids=target_ids,
            segment_narration_ids=relation.get("narration_proposition_ids", []),
        )
        if not events:
            raise ValueError(f"{segment_label}: renderer produced no compiled events")
        segments.append(
            {
                "segment_id": relation.get("segment_id"),
                "events": [
                    {
                        "event_id": event["id"],
                        "target_element_id": event["target_element_id"],
                        "action": event["action"],
                        "start_ms": event["start_ms"],
                        "duration_ms": event["duration_ms"],
                        "easing": event["easing"],
                    }
                    for event in events
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "compiled_timeline_v2",
        "case_id": stable_case_id(case_id),
        "segments": segments,
    }


def migrate_legacy_bundle(
    *,
    lesson_plan: dict[str, Any],
    script_segments: list[str],
    storyboard: dict[str, Any],
    raw_text: str,
    case_id: str,
) -> dict[str, Any]:
    """Explicit, deterministic v1→v2 migration used by old frozen runs."""
    plan = build_lesson_plan_v2(lesson_plan, case_id=case_id, raw_text=raw_text)
    script = build_script_v2(script_segments, case_id=case_id, lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)
    return {"lesson_plan_v2": plan, "script_v2": script, "storyboard": annotated}


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


__all__ = [
    "FLAG",
    "SCHEMA_VERSION",
    "annotate_storyboard_v2",
    "build_compiled_timeline_v2",
    "build_lesson_plan_v2",
    "build_script_v2",
    "build_source_units_v2",
    "build_storyboard_v2",
    "build_timed_storyboard_v2",
    "enabled",
    "migrate_legacy_bundle",
    "sha256",
    "stable_case_id",
]
