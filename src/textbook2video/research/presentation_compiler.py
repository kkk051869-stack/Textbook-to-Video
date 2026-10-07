"""Compile an A-side visual package into an isolated renderer candidate.

This module deliberately does not mutate baseline artifacts.  It accepts a
small, frozen interchange package so the presentation track can be developed
against mock visuals while the acquisition track is still running.  All times
emitted here are *planned* times; this module never claims final-video
visibility.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_WIDE_TYPES = {"comparison_panel", "flow_step", "table", "image"}
_RENDERER_TYPE = {
    "diagram": "highlight_box",
    "illustration": "image",
    "chart": "bar",
}


@dataclass(frozen=True)
class LayoutResult:
    placements: list[dict[str, Any]]
    status: str
    passes: int
    cycle_detected: bool


def optimize_layout(elements: list[dict[str, Any]], *, max_passes: int = 3) -> LayoutResult:
    """Place elements in a bounded vertical grid without repair loops.

    Hints use normalized coordinates for a later renderer adapter.  Existing
    template rendering remains unchanged unless a caller explicitly consumes
    these hints.
    """
    if max_passes < 1:
        raise ValueError("max_passes must be positive")
    placements: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, int, int], ...]] = set()
    for attempt in range(1, max_passes + 1):
        placements = []
        row = 0
        column = 0
        for element in elements:
            element_id = str(element.get("id") or "")
            width_units = 2 if str(element.get("type")) in _WIDE_TYPES else 1
            if width_units == 2 and column:
                row += 1
                column = 0
            if column + width_units > 2:
                row += 1
                column = 0
            placements.append(
                {
                    "element_id": element_id,
                    "row": row,
                    "column": column,
                    "width_units": width_units,
                    "layout_source": "bounded_grid_v0.1",
                }
            )
            column += width_units
            if column >= 2:
                row += 1
                column = 0
        signature = tuple((item["element_id"], item["row"], item["column"]) for item in placements)
        if signature in seen:
            return LayoutResult(placements, "cycle_detected", attempt, True)
        seen.add(signature)
        return LayoutResult(placements, "converged", attempt, False)
    return LayoutResult(placements, "max_passes_reached", max_passes, False)


def _index_segments(document: dict[str, Any], key: str = "id") -> dict[str, dict[str, Any]]:
    return {
        str(segment.get(key) or segment.get("id") or ""): segment
        for segment in document.get("segments", []) or []
        if isinstance(segment, dict) and str(segment.get(key) or segment.get("id") or "")
    }


def _proposition_times(script_segment: dict[str, Any], duration: float) -> dict[str, float]:
    text = str(script_segment.get("narration_text") or "")
    total = max(len(text), 1)
    result: dict[str, float] = {}
    for proposition in script_segment.get("narration_propositions", []) or []:
        if not isinstance(proposition, dict):
            continue
        span = proposition.get("span") if isinstance(proposition.get("span"), dict) else {}
        start = span.get("start")
        if isinstance(start, int):
            result[str(proposition.get("id") or "")] = round(
                max(0.0, min(duration, start / total * duration)), 6
            )
    return result


def _as_renderer_element(element: dict[str, Any]) -> dict[str, Any]:
    payload = element.get("payload") if isinstance(element.get("payload"), dict) else {}
    element_type = str(element.get("type") or "highlight_box")
    return {
        "id": element.get("id"),
        "type": _RENDERER_TYPE.get(element_type, element_type),
        "text": payload.get("text") or payload.get("description") or element.get("label") or "",
        "items": payload.get("items") or [],
        "src": payload.get("src") or payload.get("candidate_uri"),
        "semantic_role": element.get("semantic_role"),
        "presentation_layout": element.get("presentation_layout"),
    }


def compile_presentation_candidate(
    script: dict[str, Any],
    storyboard: dict[str, Any],
    timed_storyboard: dict[str, Any],
    visual_package: dict[str, Any],
    *,
    max_layout_passes: int = 3,
) -> dict[str, Any]:
    """Create a candidate storyboard/timeline and renderer-ready segments.

    ``visual_package`` has ``visuals`` records with ``segment_id``,
    ``narration_proposition_id`` and a ``element`` payload.  Existing IDs are
    retained; incoming element/event IDs are required so an acquisition run
    can be joined without positional guessing.
    """
    case_id = str(script.get("case_id") or storyboard.get("case_id") or "")
    if not case_id or visual_package.get("case_id") != case_id:
        raise ValueError("visual_package case_id must match script/storyboard")
    candidate_storyboard = deepcopy(storyboard)
    candidate_timed = deepcopy(timed_storyboard)
    storyboard_segments = _index_segments(candidate_storyboard)
    timed_segments = _index_segments(candidate_timed, "segment_id")
    script_segments = _index_segments(script)
    failures: list[dict[str, Any]] = []

    for visual in visual_package.get("visuals", []) or []:
        if not isinstance(visual, dict):
            failures.append({"type": "invalid_visual_record"})
            continue
        segment_id = str(visual.get("segment_id") or "")
        proposition_id = str(visual.get("narration_proposition_id") or "")
        element = (
            deepcopy(visual.get("element")) if isinstance(visual.get("element"), dict) else None
        )
        event_id = str(visual.get("event_id") or "")
        if not element or not str(element.get("id") or "") or not event_id:
            failures.append(
                {
                    "type": "visual_missing_stable_id",
                    "segment_id": segment_id,
                    "narration_proposition_id": proposition_id,
                }
            )
            continue
        segment = storyboard_segments.get(segment_id)
        timed_segment = timed_segments.get(segment_id)
        script_segment = script_segments.get(segment_id)
        if not segment or not timed_segment or not script_segment:
            failures.append({"type": "missing_segment_context", "segment_id": segment_id})
            continue
        known_propositions = {
            str(value) for value in segment.get("narration_proposition_ids", []) or []
        }
        if proposition_id not in known_propositions:
            failures.append(
                {
                    "type": "unknown_narration_proposition",
                    "segment_id": segment_id,
                    "narration_proposition_id": proposition_id,
                }
            )
            continue
        element_id = str(element["id"])
        if any(
            str(item.get("id") or "") == element_id for item in segment.get("elements", []) or []
        ):
            failures.append(
                {"type": "duplicate_element_id", "segment_id": segment_id, "element_id": element_id}
            )
            continue
        element["narration_proposition_ids"] = [proposition_id]
        element.setdefault("semantic_role", "explain")
        segment.setdefault("elements", []).append(element)
        duration = float(timed_segment.get("audio_duration_sec") or 0)
        trigger = _proposition_times(script_segment, duration).get(proposition_id)
        if trigger is None:
            failures.append(
                {
                    "type": "missing_proposition_span",
                    "segment_id": segment_id,
                    "narration_proposition_id": proposition_id,
                }
            )
            segment["elements"].pop()
            continue
        event = {
            "id": event_id,
            "action": "show",
            "target_element_id": element_id,
            "narration_proposition_ids": [proposition_id],
            "semantic_role": "content_reveal",
        }
        segment.setdefault("events", []).append(event)
        timed_segment.setdefault("scheduled_events", []).append(
            {
                "event_id": event_id,
                "target_element_id": element_id,
                "action": "show",
                "trigger_at_sec": trigger,
                "planned_duration_sec": 0.6,
                "timing_source": "semantic",
            }
        )

    renderer_segments: list[dict[str, Any]] = []
    layout_reports: list[dict[str, Any]] = []
    for segment in candidate_storyboard.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        layout = optimize_layout(segment.get("elements", []) or [], max_passes=max_layout_passes)
        by_id = {item["element_id"]: item for item in layout.placements}
        for element in segment.get("elements", []) or []:
            if isinstance(element, dict):
                element["presentation_layout"] = by_id.get(str(element.get("id") or ""))
        layout_reports.append(
            {
                "segment_id": segment.get("id"),
                "status": layout.status,
                "passes": layout.passes,
                "cycle_detected": layout.cycle_detected,
                "placements": layout.placements,
            }
        )
        renderer_segments.append(
            {
                "id": segment.get("legacy_segment_id") or segment.get("id"),
                "visual_type": "text",
                "audio_duration_sec": (timed_segments.get(str(segment.get("id") or "")) or {}).get(
                    "audio_duration_sec"
                ),
                "narration": (script_segments.get(str(segment.get("id") or "")) or {}).get(
                    "narration_text", ""
                ),
                "elements": [
                    _as_renderer_element(item)
                    for item in segment.get("elements", []) or []
                    if isinstance(item, dict)
                ],
                "animations": [
                    {
                        "target": event.get("target_element_id"),
                        "effect": "fadeInUp",
                        "trigger_at_sec": next(
                            (
                                scheduled.get("trigger_at_sec")
                                for scheduled in (
                                    timed_segments.get(str(segment.get("id") or "")) or {}
                                ).get("scheduled_events", [])
                                or []
                                if scheduled.get("event_id") == event.get("id")
                            ),
                            0.0,
                        ),
                    }
                    for event in segment.get("events", []) or []
                    if isinstance(event, dict)
                ],
            }
        )

    return {
        "schema_version": "presentation-candidate-v0.1",
        "case_id": case_id,
        "baseline_mutated": False,
        "candidate_storyboard": candidate_storyboard,
        "candidate_timed_storyboard": candidate_timed,
        "renderer_segments": renderer_segments,
        "layout_reports": layout_reports,
        "failures": failures,
        "time_claim": "planned_event_times_only_not_rendered_visibility",
    }


def write_presentation_candidate(candidate: dict[str, Any], output_path: str | Path) -> Path:
    """Persist an isolated candidate artifact without overwriting baseline files."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


__all__ = [
    "LayoutResult",
    "compile_presentation_candidate",
    "optimize_layout",
    "write_presentation_candidate",
]
