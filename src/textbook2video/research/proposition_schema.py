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


def _meta(*, producer: str, confidence: float | None = None, abstain_reason: str | None = None) -> dict[str, Any]:
    return {"producer": producer, "version": SCHEMA_VERSION, "confidence": confidence, "abstain_reason": abstain_reason}


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
            props.append({
                "id": f"{kp_id}-kprop-{prop_index:03d}", "text": sentence,
                "source_refs": [source_id],
                "visual_support": {
                    "label": "uncertain", "acquisition": "uncertain", "rationale": None,
                    "metadata": _meta(producer="bootstrap.lesson_plan", abstain_reason="not_yet_decided"),
                },
            })
        points.append({
            "id": kp_id, "name": str(raw.get("name") or text),
            "description": raw.get("description"), "source_refs": [source_id], "propositions": props,
        })
    if not points:
        points = [{
            "id": _id(cid, "kp", 1), "name": "Lesson content", "description": None,
            "source_refs": [source_id], "propositions": [{
                "id": f"{_id(cid, 'kp', 1)}-kprop-001", "text": raw_text.strip()[:240] or "Untitled lesson",
                "source_refs": [source_id], "visual_support": {
                    "label": "uncertain", "acquisition": "uncertain", "rationale": None,
                    "metadata": _meta(producer="bootstrap.lesson_plan", abstain_reason="empty_legacy_plan"),
                },
            }],
        }]
    return {"schema_version": SCHEMA_VERSION, "artifact_type": "lesson_plan_v2", "case_id": cid,
            "lesson_title": str(legacy.get("lesson_title") or legacy.get("title") or "Untitled lesson"),
            "knowledge_points": points}


def build_source_units_v2(*, case_id: str, raw_text: str, document_path: str = "raw_text") -> dict[str, Any]:
    cid = stable_case_id(case_id)
    return {"schema_version": SCHEMA_VERSION, "artifact_type": "source_units_v2", "case_id": cid,
            "document": {"title": cid, "path": document_path, "sha256": None},
            "source_units": [{"id": _id(cid, "src", 1), "kind": "span", "text": raw_text,
                              "source_locator": "raw_text", "page_number": None,
                              "char_span": {"start": 0, "end": len(raw_text)}, "image_refs": []}],
            "source_images": []}


def build_script_v2(segments: list[str], *, case_id: str, lesson_plan_v2: dict[str, Any]) -> dict[str, Any]:
    cid = stable_case_id(case_id)
    kp_ids = [p["id"] for kp in lesson_plan_v2.get("knowledge_points", []) for p in kp.get("propositions", [])]
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
            props.append({"id": f"{seg_id}-nprop-{sentence_index:03d}", "knowledge_proposition_ids": [kp_id],
                          "text": text, "span": {"start": start, "end": end, "unit": "unicode_codepoint", "end_exclusive": True},
                          "metadata": _meta(producer="bootstrap.script_v2", confidence=None, abstain_reason="deterministic_bootstrap_relation")})
        result.append({"id": seg_id, "legacy_segment_id": index, "narration_text": str(narration), "narration_propositions": props})
    return {"schema_version": SCHEMA_VERSION, "artifact_type": "script_v2", "case_id": cid, "segments": result}


def annotate_storyboard_v2(storyboard: dict[str, Any], script_v2: dict[str, Any], lesson_plan_v2: dict[str, Any]) -> dict[str, Any]:
    """Dual-write explicit relations into legacy storyboard under one namespaced key."""
    segments = script_v2.get("segments", [])
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            continue
        script_segment = segments[min(index - 1, len(segments) - 1)] if segments else {}
        nprops = [str(item.get("id")) for item in script_segment.get("narration_propositions", []) if item.get("id")]
        kprops = [kid for item in script_segment.get("narration_propositions", []) for kid in item.get("knowledge_proposition_ids", [])]
        segment["research_generation_v2"] = {"segment_id": script_segment.get("id"), "narration_proposition_ids": nprops,
                                             "knowledge_proposition_ids": kprops, "producer": "bootstrap.storyboard_v2"}
        for eindex, element in enumerate(segment.get("elements", []) or [], 1):
            if not isinstance(element, dict):
                continue
            element["research_generation_v2"] = {"element_id": _id(script_v2["case_id"], "el", index * 100 + eindex),
                "semantic_role": "explain" if element.get("type") in {"image", "diagram", "flow_step", "table"} else "organize",
                "source_refs": [], "knowledge_proposition_ids": kprops, "narration_proposition_ids": nprops,
                "acquisition": "reuse" if element.get("source_image_id") else "system-authored",
                "binding_source": "deterministic_bootstrap"}
        for aindex, animation in enumerate(segment.get("animations", []) or [], 1):
            if isinstance(animation, dict):
                animation["research_generation_v2"] = {"event_id": _id(script_v2["case_id"], "evt", index * 100 + aindex),
                    "narration_proposition_ids": nprops, "semantic_role": "content_reveal", "producer": "bootstrap.storyboard_v2"}
    storyboard.setdefault("metadata", {})["research_generation_v2"] = {"schema_version": SCHEMA_VERSION, "case_id": script_v2["case_id"], "enabled": True}
    return storyboard


def build_storyboard_v2(storyboard: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    """Project namespaced legacy relations into the strict standalone schema."""
    segments = []
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            continue
        relation = segment.get("research_generation_v2") or {}
        target_ids = {
            str(element.get("id") or ""): str((element.get("research_generation_v2") or {}).get("element_id") or "")
            for element in segment.get("elements", []) or [] if isinstance(element, dict)
        }
        elements = []
        legacy_to_v2: dict[str, str] = {}
        for element in segment.get("elements", []) or []:
            if not isinstance(element, dict):
                continue
            data = element.get("research_generation_v2") or {}
            legacy_to_v2[str(element.get("id") or "")] = str(data.get("element_id") or "")
            elements.append({"id": data.get("element_id"), "legacy_id": str(element.get("id") or "") or None,
                             "type": str(element.get("type") or "unknown"), "semantic_role": data.get("semantic_role", "organize"),
                             "source_refs": data.get("source_refs", []), "knowledge_proposition_ids": data.get("knowledge_proposition_ids", []),
                             "narration_proposition_ids": data.get("narration_proposition_ids", []), "acquisition": data.get("acquisition", "system-authored"),
                             "payload": {key: value for key, value in element.items() if key != "research_generation_v2"}})
        events = []
        for animation in segment.get("animations", []) or []:
            if not isinstance(animation, dict):
                continue
            data = animation.get("research_generation_v2") or {}
            events.append({"id": data.get("event_id"), "action": str(animation.get("action") or "show"),
                           "target_element_id": legacy_to_v2.get(str(animation.get("target") or ""), str(animation.get("target") or "")),
                           "narration_proposition_ids": data.get("narration_proposition_ids", []),
                           "semantic_role": data.get("semantic_role", "content_reveal")})
        if elements and events:
            segments.append({"id": relation.get("segment_id"), "legacy_segment_id": segment.get("id"),
                             "narration_proposition_ids": relation.get("narration_proposition_ids", []), "elements": elements, "events": events})
    return {"schema_version": SCHEMA_VERSION, "artifact_type": "storyboard_v2", "case_id": stable_case_id(case_id), "segments": segments}


def build_timed_storyboard_v2(storyboard: dict[str, Any], *, case_id: str, timing_source: str) -> dict[str, Any]:
    segments = []
    for index, segment in enumerate(storyboard.get("segments", []) or [], 1):
        if not isinstance(segment, dict):
            continue
        relation = segment.get("research_generation_v2") or {}
        events = []
        for animation in segment.get("animations", []) or []:
            if not isinstance(animation, dict):
                continue
            data = animation.get("research_generation_v2") or {}
            event_id = data.get("event_id")
            if not event_id:
                continue
            events.append({"event_id": event_id, "target_element_id": target_ids.get(str(animation.get("target") or ""), str(animation.get("target") or "")),
                           "action": str(animation.get("action") or "show"),
                           "trigger_at_sec": float(animation.get("trigger_at_sec") or 0.0),
                           "planned_duration_sec": float(animation.get("duration") or 0.0) or None,
                           "timing_source": timing_source})
        if events:
            segments.append({"segment_id": relation.get("segment_id"),
                             "audio_duration_sec": float(segment.get("audio_duration_sec") or 0.001),
                             "scheduled_events": events})
    return {"schema_version": SCHEMA_VERSION, "artifact_type": "timed_storyboard_v2", "case_id": stable_case_id(case_id), "segments": segments}


def migrate_legacy_bundle(*, lesson_plan: dict[str, Any], script_segments: list[str], storyboard: dict[str, Any], raw_text: str, case_id: str) -> dict[str, Any]:
    """Explicit, deterministic v1→v2 migration used by old frozen runs."""
    plan = build_lesson_plan_v2(lesson_plan, case_id=case_id, raw_text=raw_text)
    script = build_script_v2(script_segments, case_id=case_id, lesson_plan_v2=plan)
    annotated = annotate_storyboard_v2(storyboard, script, plan)
    return {"lesson_plan_v2": plan, "script_v2": script, "storyboard": annotated}


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


__all__ = ["FLAG", "SCHEMA_VERSION", "annotate_storyboard_v2", "build_lesson_plan_v2", "build_script_v2", "build_source_units_v2", "build_storyboard_v2", "build_timed_storyboard_v2", "enabled", "migrate_legacy_bundle", "sha256", "stable_case_id"]
