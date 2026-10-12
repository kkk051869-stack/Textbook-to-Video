"""Export objective evidence and empty human-label templates for Pilot v1.

The exporter may derive candidate boundaries and candidate source/KP links, but
it never writes a pedagogical gold label.  Candidate suggestions live under
explicit ``candidate_*`` keys; annotator fields start as null or empty lists.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from textbook2video.pipeline.subtitles import build_subtitle_cues
from textbook2video.research.snapshot import sha256_file


GOLD_SCALAR_FIELDS = {
    "proposition_id",
    "proposition_text",
    "narration_start",
    "narration_end",
    "boundary_status",
    "annotator_confidence",
    "visual_applicability",
    "visual_relation",
    "visual_reason",
    "temporal_label",
    "acceptable_start_min",
    "acceptable_start_max",
    "observed_visible_start",
    "observed_visible_end",
    "visibility_status",
    "signal_applicability",
    "signal_label",
    "signal_reason",
    "uncertainty_reason",
}
GOLD_LIST_FIELDS = {
    "knowledge_point_ids",
    "source_evidence_ids",
    "visual_element_ids",
    "visual_source_support_ids",
    "expected_target_element_ids",
    "observed_signal_event_ids",
    "observed_target_ids",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _artifact_path(snapshot_root: Path, manifest: dict[str, Any], role: str) -> Path | None:
    for item in manifest.get("artifacts", []):
        if item.get("role") == role and item.get("status") == "AVAILABLE":
            return snapshot_root / str(item["snapshot_path"])
    return None


def _normalize(text: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").lower())


def _features(text: Any) -> set[str]:
    value = _normalize(text)
    chars = set(value)
    chars.update(value[i : i + 2] for i in range(max(0, len(value) - 1)))
    return chars


def _similarity(left: Any, right: Any) -> float:
    a, b = _features(left), _features(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def _candidate_links(text: str, concepts: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    scored = []
    for concept in concepts:
        score = _similarity(text, concept.get("statement"))
        scored.append({
            "knowledge_point_id": concept.get("id"),
            "statement": concept.get("statement"),
            "source_evidence_ids": list(concept.get("evidence_paragraphs") or []),
            "candidate_score": round(score, 4),
            "suggestion_status": "MACHINE_CANDIDATE_NOT_GOLD",
        })
    scored.sort(key=lambda item: (-item["candidate_score"], str(item["knowledge_point_id"])))
    return scored[:limit]


def _segment_candidates(segment: dict[str, Any], concepts: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
    cues = build_subtitle_cues({"segments": [segment]})
    result = []
    for cue_index, cue in enumerate(cues, start=1):
        result.append({
            "candidate_id": f"s{index:02d}-pc{cue_index:02d}",
            "candidate_text": cue.text,
            "candidate_start_sec": round(float(cue.start_sec), 6),
            "candidate_end_sec": round(float(cue.end_sec), 6),
            "candidate_boundary_source": "deterministic_subtitle_chunk",
            "candidate_knowledge_point_links": _candidate_links(cue.text, concepts),
            "candidate_status": "MACHINE_CANDIDATE_NOT_GOLD",
        })
    return result


def _trace_by_slide(trace: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in trace.get("events", []) or []:
        if isinstance(event, dict):
            try:
                slide = int(event.get("slide") or event.get("slide_id") or 0)
            except (TypeError, ValueError):
                slide = 0
            result[slide].append(event)
    return result


def _event_fact(event: dict[str, Any], segment_start: float) -> dict[str, Any]:
    planned = event.get("planned") if isinstance(event.get("planned"), dict) else {}
    actual = event.get("actual") if isinstance(event.get("actual"), dict) else {}
    planned_ms = planned.get("start_ms")
    actual_ms = actual.get("start_ms")
    planned_global = None if planned_ms is None else segment_start + float(planned_ms) / 1000.0
    actual_global = None if actual_ms is None else segment_start + float(actual_ms) / 1000.0
    return {
        "event_id": event.get("event_id"),
        "slide": event.get("slide"),
        "target": event.get("target"),
        "target_resolved": event.get("target_resolved"),
        "runtime_status": event.get("status"),
        "target_missing": event.get("error_code") == "TARGET_MISSING",
        "error_code": event.get("error_code"),
        "message": event.get("message"),
        "plan": {
            "trigger": planned.get("trigger"),
            "effect": planned.get("effect"),
            "compiled_start_ms": planned_ms,
            "duration_ms": planned.get("duration_ms"),
            "easing": planned.get("easing"),
            "candidate_global_time_sec": round(planned_global, 6) if planned_global is not None else None,
        },
        "runtime": {
            "actual_start_ms": actual_ms,
            "trigger": actual.get("trigger"),
            "effect": actual.get("effect"),
            "duration_ms": actual.get("duration_ms"),
            "candidate_global_time_sec": round(actual_global, 6) if actual_global is not None else None,
        },
    }


def _empty_annotation_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_boundary": candidate,
        "proposition_id": None,
        "proposition_text": None,
        "narration_start": None,
        "narration_end": None,
        "boundary_status": None,
        "knowledge_point_ids": [],
        "source_evidence_ids": [],
        "annotator_confidence": None,
        "notes": "",
        "visual_applicability": None,
        "visual_relation": None,
        "visual_element_ids": [],
        "visual_source_support_ids": [],
        "visual_reason": None,
        "temporal_label": None,
        "acceptable_start_min": None,
        "acceptable_start_max": None,
        "observed_visible_start": None,
        "observed_visible_end": None,
        "visibility_status": None,
        "signal_applicability": None,
        "signal_label": None,
        "expected_target_element_ids": [],
        "observed_signal_event_ids": [],
        "observed_target_ids": [],
        "signal_reason": None,
        "uncertainty_reason": None,
    }


def _annotation_template(case_id: str, annotator_id: str, segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "t2v-pilot-v1-human-annotation-v0.1",
        "case_id": case_id,
        "annotator_id": annotator_id,
        "annotation_status": "NOT_STARTED",
        "gold_labels_initialized": False,
        "independence_rule": "Do not inspect the other annotator file before first-pass completion.",
        "segments": [
            {
                "segment_id": segment["segment_id"],
                "propositions": [_empty_annotation_row(candidate) for candidate in segment["proposition_candidates"]],
            }
            for segment in segments
        ],
    }


def validate_empty_gold(annotation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for segment in annotation.get("segments", []) or []:
        for index, row in enumerate(segment.get("propositions", []) or [], start=1):
            location = f"{segment.get('segment_id')}/row-{index}"
            for field in GOLD_SCALAR_FIELDS:
                if row.get(field) is not None:
                    errors.append(f"{location}:{field} must be null")
            for field in GOLD_LIST_FIELDS:
                if row.get(field) != []:
                    errors.append(f"{location}:{field} must be an empty list")
            if row.get("notes") != "":
                errors.append(f"{location}:notes must start empty")
    return errors


def _select_frame_events(event_facts: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    if len(event_facts) <= limit:
        return event_facts
    priority = [
        event for event in event_facts
        if event.get("target_missing") or (event.get("plan") or {}).get("trigger") not in {None, "show"}
    ]
    chosen: list[dict[str, Any]] = []
    seen = set()
    for event in priority:
        if event.get("event_id") not in seen:
            chosen.append(event)
            seen.add(event.get("event_id"))
        if len(chosen) >= limit:
            return chosen
    remaining = [event for event in event_facts if event.get("event_id") not in seen]
    slots = limit - len(chosen)
    if slots > 0 and remaining:
        indexes = [round(i * (len(remaining) - 1) / max(1, slots - 1)) for i in range(slots)]
        for index in indexes:
            event = remaining[index]
            if event.get("event_id") not in seen:
                chosen.append(event)
                seen.add(event.get("event_id"))
    return chosen[:limit]


def _ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return shutil.which("ffmpeg")


def _extract_frames(video: Path, destination: Path, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ffmpeg = _ffmpeg_executable()
    sets: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "event")
        center = (event.get("plan") or {}).get("candidate_global_time_sec")
        item = {
            "event_id": event_id,
            "center_source": "compiled_plan_global_time",
            "center_sec": center,
            "frames": [],
        }
        if center is None or ffmpeg is None:
            item["status"] = "MISSING"
            item["reason"] = "event time or ffmpeg unavailable"
            sets.append(item)
            continue
        event_dir = destination / re.sub(r"[^A-Za-z0-9_.-]+", "_", event_id)
        event_dir.mkdir(parents=True, exist_ok=True)
        for offset in (-2, -1, 0, 1, 2):
            timestamp = max(0.0, float(center) + offset)
            output = event_dir / f"offset_{offset:+d}.jpg"
            command = [
                ffmpeg, "-y", "-ss", f"{timestamp:.3f}", "-i", str(video),
                "-frames:v", "1", "-q:v", "3", str(output),
            ]
            result = subprocess.run(command, capture_output=True)
            status = "AVAILABLE" if result.returncode == 0 and output.is_file() else "MISSING"
            item["frames"].append({
                "offset_sec": offset,
                "timestamp_sec": round(timestamp, 3),
                "status": status,
                "path": str(output.relative_to(destination.parent.parent)).replace("\\", "/") if output.exists() else None,
            })
        item["status"] = "AVAILABLE" if any(frame["status"] == "AVAILABLE" for frame in item["frames"]) else "MISSING"
        sets.append(item)
    return sets


def export_case(snapshot_root: str | Path, output_root: str | Path) -> dict[str, Any]:
    snapshot_root = Path(snapshot_root).resolve()
    output_root = Path(output_root).resolve()
    snapshot_manifest = _read_json(snapshot_root / "manifest.json")
    case_id = str(snapshot_manifest["case_id"])
    case_root = output_root / case_id
    if case_root.exists() and any(case_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite annotation package: {case_root}")
    case_root.mkdir(parents=True, exist_ok=False)

    source_path = _artifact_path(snapshot_root, snapshot_manifest, "source:source.json")
    storyboard_path = _artifact_path(snapshot_root, snapshot_manifest, "storyboard_timed")
    trace_path = _artifact_path(snapshot_root, snapshot_manifest, "animation_trace")
    video_path = _artifact_path(snapshot_root, snapshot_manifest, "final_mp4")
    html_path = _artifact_path(snapshot_root, snapshot_manifest, "html")
    reference_path = _artifact_path(snapshot_root, snapshot_manifest, "source_reference_annotation")
    if not source_path or not storyboard_path or not trace_path or not video_path:
        raise FileNotFoundError(f"case lacks required source/storyboard/trace/video evidence: {case_id}")

    source = _read_json(source_path)
    storyboard = _read_json(storyboard_path)
    trace = _read_json(trace_path)
    reference = _read_json(reference_path) if reference_path else {}
    concepts = [item for item in reference.get("core_concepts", []) or [] if isinstance(item, dict)]

    shutil.copy2(source_path, case_root / "source.json")
    media_dir = case_root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(video_path, media_dir / "final.mp4")
    if html_path:
        shutil.copy2(html_path, media_dir / "animation.html")

    lesson_context = {
        "case_id": case_id,
        "title": source.get("title"),
        "source_locator": source.get("source_locator"),
        "source_paragraphs": source.get("paragraphs", []),
        "source_images": source.get("images", []),
        "knowledge_point_candidates": [
            {
                "id": concept.get("id"),
                "statement": concept.get("statement"),
                "candidate_source_evidence_ids": concept.get("evidence_paragraphs", []),
                "importance": concept.get("importance"),
                "candidate_status": "EXISTING_DATASET_REFERENCE_NOT_PILOT_GOLD",
            }
            for concept in concepts
        ],
        "warning": "Knowledge points and evidence links are editable references, not final Pilot bindings.",
    }
    _write_json(case_root / "lesson_context.json", lesson_context)

    trace_slides = _trace_by_slide(trace)
    segments_context: list[dict[str, Any]] = []
    machine_segments: list[dict[str, Any]] = []
    global_start = 0.0
    all_event_facts: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    requested_modes: Counter[str] = Counter()
    for index, segment in enumerate(storyboard.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        duration = float(segment.get("audio_duration_sec") or 0.0)
        candidates = _segment_candidates(segment, concepts, index)
        segment_id = str(segment.get("id") or index)
        events = [_event_fact(event, global_start) for event in trace_slides.get(index, [])]
        all_event_facts.extend(events)
        for item in segment.get("timeline", []) or []:
            if isinstance(item, dict):
                action_counts[str(item.get("action") or "unspecified")] += 1
        requested_modes[str(segment.get("render_mode") or "unspecified")] += 1
        elements = list(segment.get("elements", []) or [])
        animations = list(segment.get("animations", []) or [])
        timeline = list(segment.get("timeline", []) or [])
        signaling_actions = {
            "highlight", "pulse", "focus", "dim", "arrow", "emphasize",
            "color_change",
        }
        richness_observation = {
            "fact_status": "DETERMINISTIC_COUNT_NOT_PEDAGOGICAL_LABEL",
            "element_count": len(elements),
            "animation_count": len(animations),
            "timeline_event_count": len(timeline),
            "events_per_10_sec": round((len(timeline) * 10.0 / duration), 4) if duration > 0 else None,
            "signaling_event_count": sum(
                1
                for item in timeline
                if isinstance(item, dict)
                and str(item.get("action") or "").lower() in signaling_actions
            ),
            "warning": (
                "Counts describe authored richness only; show is not automatically signaling, "
                "and no coherence, redundancy, or overload label is inferred."
            ),
        }
        segments_context.append({
            "segment_id": segment_id,
            "segment_index": index,
            "narration": segment.get("narration"),
            "audio_duration_sec": duration,
            "candidate_global_start_sec": round(global_start, 6),
            "candidate_global_end_sec": round(global_start + duration, 6),
            "system_knowledge_point_ids": list(segment.get("knowledge_point_ids") or []),
            "proposition_candidates": candidates,
        })
        machine_segments.append({
            "segment_id": segment_id,
            "segment_index": index,
            "render_mode": segment.get("render_mode"),
            "visual_type": segment.get("visual_type"),
            "audio_duration_sec": duration,
            "elements": elements,
            "animations": animations,
            "timeline": timeline,
            "runtime_events": events,
            "richness_observation": richness_observation,
        })
        global_start += duration

    _write_json(case_root / "segment_context.json", {"case_id": case_id, "segments": segments_context})
    machine_observations = {
        "schema_version": "t2v-pilot-v1-machine-observations-v0.1",
        "case_id": case_id,
        "fact_status": "OBSERVED_OR_DETERMINISTIC_DERIVATION_NOT_GOLD",
        "segments": machine_segments,
    }
    _write_json(case_root / "machine_observations.json", machine_observations)

    annotation_dir = case_root / "annotations"
    empty_validation: dict[str, list[str]] = {}
    for annotator in ("A", "B"):
        template = _annotation_template(case_id, annotator, segments_context)
        errors = validate_empty_gold(template)
        if errors:
            raise ValueError("non-empty gold fields: " + "; ".join(errors[:5]))
        _write_json(annotation_dir / f"annotator_{annotator}.json", template)
        empty_validation[annotator] = errors

    selected_frames = _select_frame_events(all_event_facts, limit=5)
    frame_sets = _extract_frames(media_dir / "final.mp4", media_dir / "frames", selected_frames)
    _write_json(case_root / "three_layer_frame_index.json", {
        "case_id": case_id,
        "selection_rule": "Prioritize non-show and target-missing events, then evenly sample remaining runtime events.",
        "frame_sets": frame_sets,
    })

    package_manifest = {
        "schema_version": "t2v-pilot-v1-annotation-package-v0.1",
        "case_id": case_id,
        "snapshot_manifest": str((snapshot_root / "manifest.json").resolve()),
        "snapshot_manifest_sha256": sha256_file(snapshot_root / "manifest.json"),
        "counts": {
            "segments": len(segments_context),
            "proposition_candidates": sum(len(item["proposition_candidates"]) for item in segments_context),
            "elements": sum(len(item["elements"]) for item in machine_segments),
            "animations": sum(len(item["animations"]) for item in machine_segments),
            "timeline_items": sum(len(item["timeline"]) for item in machine_segments),
            "runtime_events": len(all_event_facts),
            "source_paragraphs": len(source.get("paragraphs", []) or []),
            "knowledge_point_candidates": len(concepts),
        },
        "coverage": {
            "requested_render_modes": dict(requested_modes),
            "timeline_actions": dict(action_counts),
            "runtime_trace": "AVAILABLE",
            "final_mp4": "AVAILABLE",
            "source_evidence": "AVAILABLE",
            "sentence_cues": "MISSING",
            "before_timing_storyboard": "MISSING",
        },
        "machine_prefilled_fields": [
            "lesson/segment IDs", "narration", "candidate subtitle chunks/times",
            "system KP IDs", "candidate KP/source links", "elements", "animations",
            "timeline", "runtime trace", "audio duration", "source paragraphs",
            "HTML/MP4 paths", "candidate event-neighborhood frames",
            "per-segment richness counts",
        ],
        "human_gold_fields": sorted(GOLD_SCALAR_FIELDS | GOLD_LIST_FIELDS | {"notes"}),
        "gold_validation": {"status": "EMPTY", "annotators": empty_validation},
        "files": {
            "source": "source.json",
            "lesson_context": "lesson_context.json",
            "segment_context": "segment_context.json",
            "machine_observations": "machine_observations.json",
            "video": "media/final.mp4",
            "html": "media/animation.html" if html_path else None,
            "frame_index": "three_layer_frame_index.json",
            "annotator_A": "annotations/annotator_A.json",
            "annotator_B": "annotations/annotator_B.json",
        },
    }
    _write_json(case_root / "manifest.json", package_manifest)
    return package_manifest


def _task_candidates(cases_root: Path) -> list[dict[str, Any]]:
    result = []
    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        context = _read_json(case_dir / "segment_context.json")
        for segment in context.get("segments", []) or []:
            for candidate in segment.get("proposition_candidates", []) or []:
                result.append({
                    "case_id": case_dir.name,
                    "segment_id": segment.get("segment_id"),
                    "candidate_id": candidate.get("candidate_id"),
                    "candidate_text": candidate.get("candidate_text"),
                    "candidate_start_sec": candidate.get("candidate_start_sec"),
                    "candidate_end_sec": candidate.get("candidate_end_sec"),
                    "candidate_knowledge_point_links": candidate.get("candidate_knowledge_point_links", []),
                })
    return result


def build_pilot_tasks(pilot_root: str | Path, *, source_task_count: int = 30) -> None:
    pilot_root = Path(pilot_root).resolve()
    cases_root = pilot_root / "cases"
    tasks_root = pilot_root / "tasks"
    candidates = _task_candidates(cases_root)
    if candidates:
        indexes = [round(i * (len(candidates) - 1) / max(1, source_task_count - 1)) for i in range(min(source_task_count, len(candidates)))]
        selected = [candidates[index] for index in indexes]
    else:
        selected = []
    for annotator in ("A", "B"):
        rows = []
        for index, item in enumerate(selected):
            version = "NO_SOURCE" if (index + (annotator == "B")) % 2 == 0 else "WITH_SOURCE"
            visible_item = {key: value for key, value in item.items() if key != "candidate_knowledge_point_links"}
            rows.append({
                **visible_item,
                "version": version,
                "source_visible": version == "WITH_SOURCE",
                "source_context_path": (
                    f"../../cases/{item['case_id']}/lesson_context.json"
                    if version == "WITH_SOURCE" else None
                ),
                "candidate_knowledge_point_links": (
                    item.get("candidate_knowledge_point_links", [])
                    if version == "WITH_SOURCE" else None
                ),
                "video_path": f"../../cases/{item['case_id']}/media/final.mp4",
                "machine_observations_path": f"../../cases/{item['case_id']}/machine_observations.json",
                "visual_applicability": None,
                "visual_relation": None,
                "visual_element_ids": [],
                "reason": None,
                "annotator_confidence": None,
                "uncertainty_reason": None,
            })
        _write_json(tasks_root / "source_ablation" / f"annotator_{annotator}_round1.json", {
            "schema_version": "t2v-pilot-v1-source-ablation-v0.1",
            "annotator_id": annotator,
            "round": 1,
            "status": "NOT_STARTED",
            "assignment_rule": "Cross-annotator A/B assignment; do not reveal the alternate version in round 1.",
            "tasks": rows,
        })

    timing_tasks = []
    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        frame_index = _read_json(case_dir / "three_layer_frame_index.json")
        observations = _read_json(case_dir / "machine_observations.json")
        segment_context = _read_json(case_dir / "segment_context.json")
        context_by_index = {
            int(segment.get("segment_index")): segment
            for segment in segment_context.get("segments", []) or []
            if segment.get("segment_index") is not None
        }
        observation_by_index = {
            int(segment.get("segment_index")): segment
            for segment in observations.get("segments", []) or []
            if segment.get("segment_index") is not None
        }
        events = {
            str(event.get("event_id")): event
            for segment in observations.get("segments", []) or []
            for event in segment.get("runtime_events", []) or []
        }
        for frame_set in frame_index.get("frame_sets", []) or []:
            event_id = str(frame_set.get("event_id"))
            event = events.get(event_id, {})
            segment_index = int(event.get("slide") or 0)
            context = context_by_index.get(segment_index, {})
            observation = observation_by_index.get(segment_index, {})
            target = event.get("target")
            target_element = next(
                (
                    element
                    for element in observation.get("elements", []) or []
                    if isinstance(element, dict) and str(element.get("id")) == str(target)
                ),
                None,
            )
            timing_tasks.append({
                "case_id": case_dir.name,
                "segment_id": context.get("segment_id"),
                "narration_context": context.get("narration"),
                "proposition_candidates": context.get("proposition_candidates", []),
                "event_id": event_id,
                "target": target,
                "target_element": target_element,
                "plan_panel": event.get("plan"),
                "runtime_panel": event.get("runtime"),
                "runtime_status": event.get("runtime_status"),
                "target_missing": event.get("target_missing"),
                "rendered_panel": frame_set,
                "panel_A_label": None,
                "panel_B_label": None,
                "panel_C_label": None,
                "label_changed_A_to_B": None,
                "label_changed_B_to_C": None,
                "change_reason": None,
                "uncertainty_reason": None,
            })
    timing_root = tasks_root / "three_layer"
    for legacy in timing_root.glob("*.json") if timing_root.exists() else []:
        legacy.unlink()
    for panel, visible_keys in (
        ("A_plan_only", {"case_id", "segment_id", "narration_context", "proposition_candidates", "event_id", "target", "target_element", "plan_panel", "panel_A_label", "uncertainty_reason"}),
        ("B_plan_runtime", {"case_id", "segment_id", "narration_context", "proposition_candidates", "event_id", "target", "target_element", "plan_panel", "runtime_panel", "runtime_status", "target_missing", "panel_B_label", "label_changed_A_to_B", "change_reason", "uncertainty_reason"}),
        ("C_rendered", set()),
    ):
        rows = timing_tasks if panel == "C_rendered" else [
            {key: value for key, value in row.items() if key in visible_keys}
            for row in timing_tasks
        ]
        for annotator in ("A", "B"):
            _write_json(timing_root / f"annotator_{annotator}" / f"{panel}.json", {
                "schema_version": "t2v-pilot-v1-three-layer-v0.1",
                "annotator_id": annotator,
                "panel": panel,
                "status": "NOT_STARTED",
                "tasks": rows,
            })


def export_pilot(
    baseline_root: str | Path,
    output_root: str | Path,
    case_ids: list[str],
) -> Path:
    baseline_root = Path(baseline_root).resolve()
    output_root = Path(output_root).resolve()
    cases_root = output_root / "cases"
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite pilot package: {output_root}")
    cases_root.mkdir(parents=True, exist_ok=True)
    manifests = [export_case(baseline_root / case_id, cases_root) for case_id in case_ids]
    build_pilot_tasks(output_root)
    index = {
        "schema_version": "t2v-pilot-v1-index-v0.1",
        "pilot_id": "pilot_v1",
        "status": "READY_FOR_HUMAN_ANNOTATION",
        "case_ids": case_ids,
        "totals": {
            key: sum(int(manifest["counts"].get(key, 0)) for manifest in manifests)
            for key in (
                "segments", "proposition_candidates", "elements", "animations",
                "timeline_items", "runtime_events", "source_paragraphs", "knowledge_point_candidates",
            )
        },
        "gold_labels": "EMPTY",
        "case_manifests": [f"cases/{case_id}/manifest.json" for case_id in case_ids],
    }
    path = output_root / "pilot_index.json"
    _write_json(path, index)
    return path


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Pilot v1 annotation packages")
    parser.add_argument("--baseline-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--case", action="append", dest="cases", required=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    path = export_pilot(args.baseline_root, args.output_root, args.cases)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
