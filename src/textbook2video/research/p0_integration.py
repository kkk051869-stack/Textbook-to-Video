"""P0 research adapter for the production Textbook-to-Video pipeline.

The adapter deliberately does *not* render HTML, synthesize audio, or create
an alternative storyboard schema.  It copies an ordinary production storyboard,
attaches research-only provenance, and optionally adjusts animations that
target elements already present in that storyboard.  The caller then continues
through the normal TTS, animation, recording, and composition pipeline.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textbook2video.pipeline.subtitles import SentenceSplitter, build_subtitle_cues
from textbook2video.pipeline.timing import timed_storyboard_path

from .source_evidence import link_propositions

P0_PLAN_VERSION = "p0-event-plan-v0.1"
P0_SIDECAR_VERSION = "p0-production-sidecar-v0.1"


@dataclass(frozen=True)
class P0IntegrationPaths:
    """Paths emitted by one non-destructive P0 integration run."""

    baseline_storyboard_path: Path
    candidate_storyboard_path: Path
    sidecar_path: Path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _candidate_stem(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]
    return f"{stem}_p0"


def _segment_id(segment: dict[str, Any], index: int) -> str:
    return str(segment.get("id") or index)


def _sentence_propositions(segment: dict[str, Any], segment_id: str) -> list[dict[str, Any]]:
    narration = str(segment.get("narration") or "")
    cursor = 0
    propositions: list[dict[str, Any]] = []
    for index, sentence in enumerate(SentenceSplitter().split(narration), start=1):
        start = narration.find(sentence, cursor)
        if start < 0:
            start = cursor
        end = start + len(sentence)
        cursor = end
        propositions.append(
            {
                "id": f"{segment_id}-nprop-{index:02d}",
                "segment_id": segment_id,
                "sentence_index": index,
                "text": sentence,
                "span": {"start": start, "end": end},
                "source_refs": [],
                "knowledge_point_ids": [],
                "status": "DERIVED_FROM_PRODUCTION_NARRATION_NOT_GOLD",
            }
        )
    return propositions


def _element_ids(segment: dict[str, Any]) -> set[str]:
    return {
        str(element.get("id") or "").strip()
        for element in segment.get("elements", []) or []
        if isinstance(element, dict) and str(element.get("id") or "").strip()
    }


def _load_plan(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"schema_version": P0_PLAN_VERSION, "events": []}
    plan_path = Path(path)
    plan = _read_json(plan_path)
    if plan.get("schema_version") != P0_PLAN_VERSION:
        raise ValueError(f"unsupported P0 plan schema: {plan.get('schema_version')!r}")
    events = plan.get("events")
    if not isinstance(events, list):
        raise ValueError("P0 plan events must be a list")
    return plan


def _materialize_retrieved_visuals(
    candidate: dict[str, Any],
    retrieved_visuals: list[Any],
) -> None:
    """Add only whitelisted local textbook images to the P0 copy.

    ``src`` remains a plain filename because ``animation_gen.load_textbook_images``
    deliberately resolves it inside the production ``images/`` directory.
    """
    available = candidate.get("metadata", {}).get("available_images", [])
    allowed = {
        (str(item.get("id") or ""), str(item.get("filename") or "")): item
        for item in available
        if isinstance(item, dict)
    }
    segments = candidate.get("segments", [])
    by_id = {
        _segment_id(segment, index): segment
        for index, segment in enumerate(segments, start=1)
        if isinstance(segment, dict)
    }
    for visual in retrieved_visuals:
        if not isinstance(visual, dict):
            raise ValueError("P0 retrieved_visuals entries must be objects")
        segment = by_id.get(str(visual.get("segment_id") or ""))
        image_id = str(visual.get("source_image_id") or "")
        filename = str(visual.get("filename") or "")
        element_id = str(visual.get("element_id") or "")
        if segment is None or not element_id or (image_id, filename) not in allowed:
            raise ValueError("P0 retrieved visual is not a whitelisted available textbook image")
        if Path(filename).name != filename:
            raise ValueError("P0 retrieved visual filename must not contain a path")
        elements = segment.setdefault("elements", [])
        existing_ids = {
            str(item.get("id") or "") for item in elements if isinstance(item, dict)
        }
        if element_id in existing_ids:
            continue
        source = allowed[(image_id, filename)]
        elements.append(
            {
                "id": element_id,
                "type": "image",
                "src": filename,
                "description": str(
                    visual.get("description") or source.get("description") or "教材原图"
                ),
                "research_p0": {
                    "acquisition": "RETRIEVE_LOCAL_TEXTBOOK_IMAGE",
                    "source_image_id": image_id,
                    "proposition_id": str(visual.get("proposition_id") or ""),
                },
            }
        )


def prepare_p0_candidate(
    storyboard_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    plan_path: str | Path | None = None,
) -> P0IntegrationPaths:
    """Copy a production storyboard and attach a validated P0 sidecar.

    The baseline file is never changed.  A plan may only reference existing
    segment/element IDs; it cannot silently invent a visual or reroute a
    target.  Timing is intentionally deferred until production TTS has written
    measured segment durations.
    """
    baseline = Path(storyboard_path)
    storyboard = _read_json(baseline)
    segments = storyboard.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("production storyboard must contain non-empty segments")

    plan = _load_plan(plan_path)
    out_dir = Path(output_dir) if output_dir is not None else baseline.parent
    stem = _candidate_stem(baseline)
    candidate_path = out_dir / f"{stem}_storyboard.json"
    sidecar_path = out_dir / f"{stem}_research_p0.json"

    propositions: list[dict[str, Any]] = []
    segments_by_id: dict[str, dict[str, Any]] = {}
    proposition_ids: set[str] = set()
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError(f"storyboard segments[{index}] must be an object")
        segment_id = _segment_id(segment, index)
        if segment_id in segments_by_id:
            raise ValueError(f"duplicate production segment id: {segment_id}")
        segments_by_id[segment_id] = segment
        segment_props = _sentence_propositions(segment, segment_id)
        propositions.extend(segment_props)
        proposition_ids.update(item["id"] for item in segment_props)

    candidate = copy.deepcopy(storyboard)
    _materialize_retrieved_visuals(candidate, plan.get("retrieved_visuals", []))
    candidate_segments_by_id = {
        _segment_id(segment, index): segment
        for index, segment in enumerate(candidate.get("segments", []), start=1)
        if isinstance(segment, dict)
    }
    validated_events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for index, event in enumerate(plan.get("events", []), start=1):
        if not isinstance(event, dict):
            raise ValueError(f"P0 plan events[{index}] must be an object")
        event_id = str(event.get("id") or f"p0-event-{index:03d}")
        if event_id in seen_event_ids:
            raise ValueError(f"duplicate P0 event id: {event_id}")
        seen_event_ids.add(event_id)
        segment_id = str(event.get("segment_id") or "")
        proposition_id = str(event.get("proposition_id") or "")
        target_element_id = str(event.get("target_element_id") or "")
        segment = candidate_segments_by_id.get(segment_id)
        if segment is None:
            raise ValueError(f"P0 event {event_id} references unknown segment: {segment_id}")
        if proposition_id not in proposition_ids or not proposition_id.startswith(f"{segment_id}-"):
            raise ValueError(
                f"P0 event {event_id} references unknown proposition: {proposition_id}"
            )
        if target_element_id not in _element_ids(segment):
            raise ValueError(
                f"P0 event {event_id} references missing production element: {target_element_id}"
            )
        try:
            lead_sec = float(event.get("lead_sec", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"P0 event {event_id} lead_sec must be numeric") from exc
        validated_events.append(
            {
                "id": event_id,
                "segment_id": segment_id,
                "proposition_id": proposition_id,
                "target_element_id": target_element_id,
                "lead_sec": lead_sec,
                "effect": str(event.get("effect") or "fadeInUp"),
                "signal": event.get("signal"),
                "status": "VALIDATED_PENDING_MEASURED_TTS",
            }
        )

    candidate.setdefault("metadata", {})["research_p0"] = {
        "enabled": True,
        "baseline_storyboard": str(baseline),
        "sidecar": str(sidecar_path),
        "plan_schema_version": P0_PLAN_VERSION,
        "event_count": len(validated_events),
        "materialized_retrieved_visual_count": len(plan.get("retrieved_visuals", [])),
    }
    source_evidence_path = plan.get("source_evidence_path")
    source_evidence: dict[str, Any] | None = None
    if source_evidence_path:
        candidate_evidence_path = Path(str(source_evidence_path))
        if candidate_evidence_path.is_file():
            source_evidence = _read_json(candidate_evidence_path)
            propositions = link_propositions(propositions, source_evidence)
    sidecar = {
        "schema_version": P0_SIDECAR_VERSION,
        "baseline_storyboard_path": str(baseline),
        "candidate_storyboard_path": str(candidate_path),
        "plan_path": str(plan_path) if plan_path else None,
        "propositions": propositions,
        "visual_candidates": [
            {
                "segment_id": segment_id,
                "element_ids": sorted(_element_ids(segment)),
                "status": "OBSERVED_FROM_PRODUCTION_STORYBOARD_NOT_GOLD",
            }
            for segment_id, segment in segments_by_id.items()
        ],
        "events": validated_events,
        "planning": {
            "planner": plan.get("planner"),
            "decisions": plan.get("decisions", []),
            "bindings": plan.get("bindings", []),
        },
        "source_evidence": {
            "path": str(source_evidence_path) if source_evidence_path else None,
            "status": "LINKED_MACHINE_CANDIDATES" if source_evidence else "NOT_AVAILABLE",
        },
        "render": {
            "renderer": "production_animation_gen",
            "rendered_visibility_claim": "NOT_MEASURED_BY_P0_INTEGRATION",
        },
    }
    _write_json(candidate_path, candidate)
    _write_json(sidecar_path, sidecar)
    return P0IntegrationPaths(baseline, candidate_path, sidecar_path)


def apply_p0_event_schedule(paths: P0IntegrationPaths) -> dict[str, Any]:
    """Apply validated P0 events after production TTS has measured duration.

    Existing production elements and the production renderer remain canonical.
    An event changes only an existing target's animation trigger (or adds a
    normal production animation for that existing target).  The final video is
    still rendered by ``animation_gen.generate``.
    """
    candidate = _read_json(paths.candidate_storyboard_path)
    sidecar = _read_json(paths.sidecar_path)
    propositions = {
        item["id"]
        : item
        for item in sidecar.get("propositions", [])
        if isinstance(item, dict)
    }
    events = sidecar.get("events", [])
    segments = candidate.get("segments", [])
    if not isinstance(segments, list):
        raise ValueError("candidate storyboard must contain segments")
    segment_map = {
        _segment_id(segment, index): segment
        for index, segment in enumerate(segments, start=1)
        if isinstance(segment, dict)
    }

    for event in events:
        if not isinstance(event, dict):
            continue
        segment = segment_map.get(str(event.get("segment_id") or ""))
        proposition = propositions.get(str(event.get("proposition_id") or ""))
        if segment is None or proposition is None:
            event["status"] = "SKIPPED_MISSING_CANDIDATE_CONTEXT"
            continue
        sentence_index = int(proposition["sentence_index"])
        cues = build_subtitle_cues({"segments": [segment]})
        if sentence_index < 1 or sentence_index > len(cues):
            event["status"] = "SKIPPED_MISSING_SENTENCE_CUE"
            continue
        cue = cues[sentence_index - 1]
        duration = float(segment.get("audio_duration_sec") or 0.0)
        target = str(event["target_element_id"])
        trigger = max(0.0, cue.start_sec + float(event.get("lead_sec") or 0.0))
        if duration > 0:
            trigger = min(trigger, max(0.0, duration - 0.2))
        trigger = round(trigger, 3)
        animations = segment.setdefault("animations", [])
        animation = next(
            (
                item
                for item in animations
                if isinstance(item, dict) and str(item.get("target") or "") == target
            ),
            None,
        )
        if animation is None:
            animation = {"target": target, "effect": event["effect"]}
            animations.append(animation)
        animation["trigger_at_sec"] = trigger
        animation["research_p0"] = {
            "event_id": event["id"],
            "proposition_id": event["proposition_id"],
            "timing_source": "p0_proposition_to_production_subtitle_cue",
        }
        event.update(
            {
                "status": "SCHEDULED_ON_PRODUCTION_ANIMATION",
                "planned_trigger_at_sec": trigger,
                "cue_text": cue.text,
                "cue_timing_kind": (
                    "measured_sentence_cue" if cue.sentence_id else "duration_estimate"
                ),
            }
        )

    timed_path = timed_storyboard_path(paths.candidate_storyboard_path)
    _write_json(paths.candidate_storyboard_path, candidate)
    _write_json(timed_path, candidate)
    sidecar["timed_storyboard_path"] = str(timed_path)
    _write_json(paths.sidecar_path, sidecar)
    return sidecar


def finalize_p0_render_evidence(
    paths: P0IntegrationPaths,
    *,
    html_path: str | Path,
    video_path: str | Path,
) -> None:
    """Record production-render artifact paths without claiming visibility."""
    sidecar = _read_json(paths.sidecar_path)
    sidecar.setdefault("render", {}).update(
        {
            "html_path": str(html_path),
            "video_path": str(video_path),
            "rendered_visibility_claim": "NOT_MEASURED_BY_P0_INTEGRATION",
        }
    )
    _write_json(paths.sidecar_path, sidecar)


__all__ = [
    "P0IntegrationPaths",
    "P0_PLAN_VERSION",
    "P0_SIDECAR_VERSION",
    "apply_p0_event_schedule",
    "finalize_p0_render_evidence",
    "prepare_p0_candidate",
]
