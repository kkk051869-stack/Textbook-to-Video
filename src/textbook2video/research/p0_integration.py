"""P0 research adapter for the production Textbook-to-Video pipeline.

The adapter deliberately does *not* render HTML, synthesize audio, or create
an alternative storyboard schema.  It copies an ordinary production storyboard,
attaches research-only provenance, and optionally adjusts animations that
target elements already present in that storyboard.  The caller then continues
through the normal TTS, animation, recording, and composition pipeline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textbook2video.pipeline.subtitles import SentenceSplitter, build_subtitle_cues
from textbook2video.pipeline.timing import timed_storyboard_path

from .source_evidence import link_propositions

P0_PLAN_VERSION = "p0-event-plan-v0.1"
P0_SIDECAR_VERSION = "p0-production-sidecar-v0.1"
P0_CASE_BUNDLE_VERSION = "p0-case-bundle-v0.1"
_P0_EVENT_ACTIONS = frozenset({"show", "focus", "highlight", "dim", "remove"})


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_p0_case_manifest(
    output_path: str | Path,
    *,
    case_id: str,
    artifacts: dict[str, str | Path],
    baseline_video_path: str | Path | None = None,
    candidate_video_path: str | Path | None = None,
) -> Path:
    """Write and validate one self-contained, non-mixable P0 case bundle.

    The manifest stores hashes for every input sidecar and source artifact.  It
    is intentionally research-only: a production renderer never discovers
    files by globbing a parent directory, so an old visual-decision file cannot
    silently be paired with a newer storyboard.
    """
    manifest_path = Path(output_path)
    records: dict[str, dict[str, Any]] = {}
    for label, supplied in artifacts.items():
        path = Path(supplied)
        if not path.is_file():
            raise FileNotFoundError(f"case bundle artifact {label!r} is missing: {path}")
        records[label] = {
            "path": str(path),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    manifest: dict[str, Any] = {
        "schema_version": P0_CASE_BUNDLE_VERSION,
        "case_id": str(case_id),
        "artifacts": records,
        "videos": {
            "baseline": str(baseline_video_path) if baseline_video_path else None,
            "candidate": str(candidate_video_path) if candidate_video_path else None,
        },
        "invariants": {
            "same_source_artifacts": True,
            "same_frozen_audio_and_renderer": True,
            "candidate_only_research_intervention": True,
        },
    }
    _write_json(manifest_path, manifest)
    validation = validate_p0_case_bundle(manifest_path)
    manifest["validation"] = validation
    _write_json(manifest_path, manifest)
    return manifest_path


def validate_p0_case_bundle(manifest_path: str | Path) -> dict[str, Any]:
    """Run cross-artifact provenance and target checks for one case bundle."""
    path = Path(manifest_path)
    manifest = _read_json(path)
    if manifest.get("schema_version") != P0_CASE_BUNDLE_VERSION:
        raise ValueError(f"unsupported P0 case bundle schema: {manifest.get('schema_version')!r}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("P0 case bundle artifacts must be an object")
    loaded: dict[str, Path] = {}
    for label, record in artifacts.items():
        if not isinstance(record, dict):
            raise ValueError(f"P0 case bundle artifact record is invalid: {label}")
        artifact_path = Path(str(record.get("path") or ""))
        if not artifact_path.is_file():
            raise ValueError(f"P0 case bundle artifact is missing: {label}: {artifact_path}")
        actual_hash = _sha256_file(artifact_path)
        if actual_hash != str(record.get("sha256") or ""):
            raise ValueError(f"P0 case bundle artifact hash changed: {label}: {artifact_path}")
        loaded[label] = artifact_path

    required = {"candidate_storyboard", "p0_plan", "proposition_graph", "visual_decisions"}
    missing = sorted(required - loaded.keys())
    if missing:
        raise ValueError(f"P0 case bundle is incomplete; missing artifacts: {missing}")
    storyboard = _read_json(loaded["candidate_storyboard"])
    plan = _read_json(loaded["p0_plan"])
    graph = _read_json(loaded["proposition_graph"])
    decisions_doc = _read_json(loaded["visual_decisions"])
    segments = {
        _segment_id(segment, index): segment
        for index, segment in enumerate(storyboard.get("segments", []) or [], start=1)
        if isinstance(segment, dict)
    }
    propositions = {
        str(item.get("id") or ""): item
        for item in graph.get("narration_propositions", []) or []
        if isinstance(item, dict) and item.get("id")
    }
    decisions = {
        str(item.get("narration_proposition_id") or ""): item
        for item in decisions_doc.get("decisions", []) or []
        if isinstance(item, dict) and item.get("narration_proposition_id")
    }
    events = plan.get("events", []) or []
    bindings = plan.get("bindings", []) or []
    if not isinstance(events, list) or not isinstance(bindings, list):
        raise ValueError("P0 case bundle plan events/bindings must be lists")
    checked_events = 0
    checked_bindings = 0
    for item in [*bindings, *events]:
        proposition_id = str(item.get("proposition_id") or "")
        segment_id = str(item.get("segment_id") or "")
        target_id = str(item.get("target_element_id") or "")
        proposition = propositions.get(proposition_id)
        segment = segments.get(segment_id)
        if proposition is None or segment is None:
            raise ValueError(
                f"P0 case bundle has dangling relation: proposition={proposition_id!r}, "
                f"segment={segment_id!r}"
            )
        element = _find_element(segment, target_id)
        if not isinstance(element, dict):
            raise ValueError(
                f"P0 case bundle event/binding target is missing: {segment_id}/{target_id}"
            )
        decision = decisions.get(proposition_id)
        _validate_visual_decision_target(
            decision=decision,
            element=element,
            proposition_id=proposition_id,
            event_id=str(item.get("id") or f"binding:{proposition_id}"),
        )
        if item in events:
            checked_events += 1
        else:
            checked_bindings += 1
    source_ref_count = sum(
        len(item.get("source_refs") or [])
        for item in propositions.values()
        if isinstance(item, dict)
    )
    runtime_status_counts: dict[str, int] = {}
    runtime_event_count = 0
    if "p0_runtime_trace" in loaded:
        runtime_trace = _read_json(loaded["p0_runtime_trace"])
        runtime_by_id = {
            str(item.get("event_id") or ""): item
            for item in runtime_trace.get("events", []) or []
            if isinstance(item, dict)
        }
        plan_event_ids = {
            str(item.get("id") or "") for item in events if isinstance(item, dict)
        }
        missing_runtime = sorted(event_id for event_id in plan_event_ids if event_id not in runtime_by_id)
        if missing_runtime:
            raise ValueError(f"P0 runtime trace is missing planned events: {missing_runtime}")
        for event_id in plan_event_ids:
            status = str(runtime_by_id[event_id].get("status") or "")
            runtime_status_counts[status] = runtime_status_counts.get(status, 0) + 1
            if status != "executed":
                raise ValueError(
                    f"P0 planned event {event_id} did not execute in runtime trace: {status or '<missing>'}"
                )
        runtime_event_count = len(plan_event_ids)
    render_observation_count = 0
    if "p0_render_evidence" in loaded:
        render_evidence = _read_json(loaded["p0_render_evidence"])
        observations = {
            str(item.get("event_id") or ""): item
            for item in render_evidence.get("observations", []) or []
            if isinstance(item, dict)
        }
        for event_id in {str(item.get("id") or "") for item in events if isinstance(item, dict)}:
            observation = observations.get(event_id)
            if observation is None or observation.get("runtime_status") != "executed":
                raise ValueError(f"P0 render evidence is missing an executed observation: {event_id}")
            if len(observation.get("mp4_frame_samples") or []) < 2:
                raise ValueError(f"P0 render evidence has fewer than two MP4 samples: {event_id}")
        render_observation_count = len(observations)
    return {
        "valid": True,
        "case_id": str(manifest.get("case_id") or ""),
        "proposition_count": len(propositions),
        "decision_count": len(decisions),
        "binding_count": checked_bindings,
        "event_count": checked_events,
        "source_ref_count": source_ref_count,
        "runtime_event_count": runtime_event_count,
        "runtime_status_counts": runtime_status_counts,
        "render_observation_count": render_observation_count,
        "checks": [
            "artifact_sha256",
            "proposition_to_segment",
            "proposition_to_visual_decision",
            "visual_decision_to_storyboard_source_image",
            "event_target_exists",
            "p0_runtime_event_executed",
            "p0_mp4_frame_samples",
        ],
    }


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
    knowledge_point_ids = [
        str(value) for value in segment.get("knowledge_point_ids", []) or []
        if str(value).strip()
    ]
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
                "knowledge_point_ids": knowledge_point_ids,
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


def _find_element(segment: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    return next(
        (
            element
            for element in segment.get("elements", []) or []
            if isinstance(element, dict) and str(element.get("id") or "") == element_id
        ),
        None,
    )


def _element_target_aliases(segment: dict[str, Any], element_id: str) -> set[str]:
    """Return production target aliases that refer to one storyboard element.

    Older storyboards commonly used the source-image id as an animation target,
    while the clean staged storyboard uses a stable element id (for example
    ``brief-pdf-p004-fig02``).  Treating those values as unrelated leaves a
    dead legacy event in the runtime timeline and produces ``target_missing``
    even though the intended element is present.  P0 canonicalizes all aliases
    to the actual element id without changing the baseline storyboard.
    """
    aliases = {str(element_id)}
    element = _find_element(segment, str(element_id))
    if not isinstance(element, dict):
        return aliases
    for key in ("source_image_id", "figure_id"):
        value = str(element.get(key) or "").strip()
        if value:
            aliases.add(value)
    source = str(element.get("src") or "").strip()
    if source:
        aliases.add(source)
        aliases.add(Path(source).stem)
    return aliases


def _validate_visual_decision_target(
    *,
    decision: dict[str, Any] | None,
    element: dict[str, Any] | None,
    proposition_id: str,
    event_id: str,
) -> None:
    """Reject cross-run visual decisions instead of silently rebinding them.

    A proposition-level decision is only valid for the source image that is
    actually present on the target storyboard element.  This catches the
    common failure mode where a new clean storyboard is paired with an old
    decision sidecar from a different storyboard revision.
    """
    if decision is None:
        raise ValueError(
            f"P0 event {event_id} has no visual decision for proposition {proposition_id}"
        )
    action = str(decision.get("action") or "").lower()
    if not isinstance(element, dict):
        raise ValueError(f"P0 event {event_id} target element is unavailable")
    if action in {"retrieve", "generate"}:
        materialized = (
            element.get("research_p0")
            if isinstance(element.get("research_p0"), dict)
            else {}
        )
        if (
            str(materialized.get("proposition_id") or "") != proposition_id
            or str(materialized.get("acquisition") or "")
            not in {"RETRIEVE_LOCAL_RAG", "GENERATE_VLM_ACCEPTED"}
        ):
            raise ValueError(
                f"P0 event {event_id} targets an unapproved {action!r} asset; "
                "it must be materialized for this proposition and VLM-accepted first"
            )
        return
    if action != "reuse":
        raise ValueError(
            f"P0 event {event_id} targets an element but decision action is {action!r}"
        )
    decided_source = str(decision.get("source_image_id") or "").strip()
    target_source = str(element.get("source_image_id") or "").strip()
    if decided_source and target_source and decided_source != target_source:
        raise ValueError(
            f"P0 event {event_id} mixes visual decision source {decided_source!r} "
            f"with target element source {target_source!r}"
        )


def _merge_unique(existing: list[Any] | None, additions: list[Any] | None) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in list(existing or []) + list(additions or []):
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


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


def _segment_sentence_cues(
    sentence_cues: dict[str, Any] | list[dict[str, Any]] | None,
    segment_id: str,
) -> tuple[dict[str, Any] | list[dict[str, Any]] | None, bool]:
    """Return one segment's measured TTS cues on its local clock, if present."""
    if isinstance(sentence_cues, dict):
        groups = sentence_cues.get("segments")
        if isinstance(groups, list):
            matched = [
                group for group in groups
                if isinstance(group, dict) and str(group.get("segment_id")) == segment_id
            ]
            if matched and isinstance(matched[0].get("cues"), list):
                return {"segments": matched}, True
    if isinstance(sentence_cues, list) and sentence_cues:
        return sentence_cues, True
    return None, False


def _normalized_alignment_text(value: Any) -> str:
    """Normalize only presentation differences, never semantic content."""
    return re.sub(r"[\s，。！？；：、,.!?;:\-—_()（）\[\]【】]+", "", str(value or "")).lower()


def _resolve_proposition_cue(
    *,
    segment: dict[str, Any],
    proposition: dict[str, Any],
    local_cues: dict[str, Any] | list[dict[str, Any]] | None,
    has_measured_cues: bool,
    allow_approximate_cues: bool,
) -> tuple[Any, float, str]:
    """Bind one proposition span to the measured cue that actually contains it.

    Narration propositions and subtitle chunks are different representations.
    Their array indexes are therefore not interchangeable.  The binding uses
    the exact proposition span in the frozen narration and the exact text saved
    with sentence-level TTS cues.  Approximate subtitle timing is available only
    behind an explicit diagnostic opt-in and is never used by formal P0 runs.
    """
    segment_id = str(segment.get("id") or "")
    if not has_measured_cues and not allow_approximate_cues:
        raise ValueError(
            f"P0 requires measured sentence cues for segment {segment_id}; "
            "duration-weighted subtitle estimates are not valid research timing"
        )
    cues = build_subtitle_cues({"segments": [segment]}, sentence_cues=local_cues)
    if not cues:
        raise ValueError(f"P0 has no usable sentence cues for segment {segment_id}")

    narration = str(segment.get("narration") or "")
    proposition_text = str(proposition.get("text") or "")
    span = proposition.get("span") if isinstance(proposition.get("span"), dict) else {}
    prop_start = span.get("start")
    prop_end = span.get("end")
    exact_span = (
        isinstance(prop_start, int)
        and not isinstance(prop_start, bool)
        and isinstance(prop_end, int)
        and not isinstance(prop_end, bool)
        and 0 <= prop_start < prop_end <= len(narration)
        and narration[prop_start:prop_end] == proposition_text
    )

    cursor = 0
    for cue in cues:
        cue_text = str(cue.text or "")
        if has_measured_cues and not cue_text.strip():
            raise ValueError(
                f"measured sentence cue {cue.sentence_id!r} in segment {segment_id} "
                "has no text and cannot be bound to a proposition"
            )
        cue_start = narration.find(cue_text, cursor) if cue_text else -1
        if cue_start < 0 and cue_text:
            cue_start = narration.find(cue_text)
        if cue_start >= 0:
            cue_end = cue_start + len(cue_text)
            cursor = cue_end
            if exact_span and cue_start <= prop_start < cue_end:
                fraction = (prop_start - cue_start) / max(1, len(cue_text))
                return cue, max(0.0, min(1.0, fraction)), "exact_narration_span"
        if proposition_text and proposition_text in cue_text:
            local = cue_text.find(proposition_text)
            return cue, max(0.0, local / max(1, len(cue_text))), "exact_cue_text"
        if (
            proposition_text
            and _normalized_alignment_text(proposition_text)
            and _normalized_alignment_text(proposition_text) in _normalized_alignment_text(cue_text)
        ):
            # Formatting-only normalization is acceptable for TTS text (for
            # example spaces inserted around an abbreviation), but the match is
            # explicitly recorded instead of being presented as an exact span.
            return cue, 0.0, "normalized_cue_text"

    if allow_approximate_cues:
        sentence_index = proposition.get("sentence_index")
        if isinstance(sentence_index, int) and 1 <= sentence_index <= len(cues):
            return cues[sentence_index - 1], 0.0, "diagnostic_sentence_index_fallback"
    raise ValueError(
        f"P0 proposition {proposition.get('id')!r} does not map to a measured "
        f"sentence cue in segment {segment_id}"
    )


def measure_proposition_intervals(
    *,
    storyboard_path: str | Path,
    proposition_graph_path: str | Path,
    sentence_cues: dict[str, Any] | list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Project frozen narration propositions onto measured TTS intervals.

    This is deliberately a read-only bridge: it neither estimates timing from
    character counts nor alters a storyboard.  The returned slide-local
    intervals are the only timing input accepted by the phase-two dynamic
    planner.
    """
    storyboard = _read_json(Path(storyboard_path))
    graph = _read_json(Path(proposition_graph_path))
    segments = {
        _segment_id(segment, index): segment
        for index, segment in enumerate(storyboard.get("segments", []), start=1)
        if isinstance(segment, dict)
    }
    measured: list[dict[str, Any]] = []
    durations: dict[str, float] = {}
    for segment_id, segment in segments.items():
        duration = float(segment.get("audio_duration_sec") or 0.0)
        if duration > 0:
            durations[segment_id] = duration
    for proposition in graph.get("narration_propositions", []):
        if not isinstance(proposition, dict):
            continue
        segment_id = str(proposition.get("segment_id") or "")
        segment = segments.get(segment_id)
        if segment is None:
            raise ValueError(f"proposition references unknown storyboard segment: {segment_id}")
        local_cues, has_measured_cues = _segment_sentence_cues(sentence_cues, segment_id)
        cue, fraction, match_kind = _resolve_proposition_cue(
            segment=segment,
            proposition=proposition,
            local_cues=local_cues,
            has_measured_cues=has_measured_cues,
            allow_approximate_cues=False,
        )
        start = max(0.0, cue.start_sec + (cue.end_sec - cue.start_sec) * fraction)
        # A proposition ending inside a sentence does not have an observed
        # forced-alignment boundary.  Its cue end is the conservative visible
        # interval end, explicitly recorded as such.
        end = max(start + 0.05, float(cue.end_sec))
        measured.append(
            {
                **proposition,
                "start_sec": round(start, 4),
                "end_sec": round(end, 4),
                "timing_source": "measured_sentence_cue",
                "cue_sentence_id": str(cue.sentence_id),
                "cue_match_kind": match_kind,
            }
        )
    return measured, durations


def _set_runtime_timeline_event(
    segment: dict[str, Any],
    *,
    target: str,
    action: str,
    effect: str,
    trigger: float,
    hold_sec: float | None,
    research_p0: dict[str, Any],
) -> None:
    """Update the runtime-precedence ``timeline`` without changing other targets.

    ``animation_gen.build_slide_timelines`` gives a non-empty ``timeline``
    precedence over legacy ``animations``.  P0 must therefore edit both
    representations.  A grouped timeline target is split so only the planned
    object receives the intervention.
    """
    timeline = segment.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        return
    updated: list[Any] = []
    current_event_id = str(research_p0.get("event_id") or "")
    target_aliases = _element_target_aliases(segment, target)
    has_existing_p0_target = any(
        isinstance(item, dict)
        and target_aliases.intersection(
            [part.strip() for part in str(item.get("target") or "").split(",") if part.strip()]
        )
        and isinstance(item.get("research_p0"), dict)
        and str(item["research_p0"].get("event_id") or "")
        for item in timeline
    )
    replaced_legacy_target = False
    updated_current_event = False
    for item in timeline:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        targets = [part.strip() for part in str(item.get("target") or "").split(",") if part.strip()]
        if not target_aliases.intersection(targets):
            updated.append(item)
            continue

        item_research = item.get("research_p0")
        item_event_id = (
            str(item_research.get("event_id") or "")
            if isinstance(item_research, dict) else ""
        )
        # Re-applying the same event is idempotent.
        if item_event_id == current_event_id:
            clone = copy.deepcopy(item)
            clone.update({
                "event_id": current_event_id,
                "target": target,
                "action": action,
                "effect": effect,
                "at_sec": trigger,
                "trigger_at_sec": trigger,
                "research_p0": research_p0,
            })
            if hold_sec is not None:
                clone["hold_sec"] = hold_sec
            updated.append(clone)
            updated_current_event = True
            continue

        # Preserve a different P0 event already attached to this target.  It
        # is a real independent intervention (for example the reveal that
        # precedes this focus), not a legacy item to be replaced.
        if item_event_id:
            updated.append(copy.deepcopy(item))
            continue

        # Remove all aliases from the legacy item.  If it also targets an
        # unrelated element, retain that unrelated target in the grouped item.
        remaining_targets = [
            item_target for item_target in targets if item_target not in target_aliases
        ]
        if remaining_targets:
            untouched = copy.deepcopy(item)
            untouched["target"] = ",".join(remaining_targets)
            updated.append(untouched)

        # The first P0 event replaces the old production event for this
        # target.  Later P0 events (e.g. focus after show) are appended and
        # therefore remain independently observable.
        if not has_existing_p0_target and not replaced_legacy_target:
            clone = copy.deepcopy(item)
            clone.update({
                "event_id": current_event_id,
                "target": target,
                "action": action,
                "effect": effect,
                "at_sec": trigger,
                "trigger_at_sec": trigger,
                "research_p0": research_p0,
            })
            if hold_sec is not None:
                clone["hold_sec"] = hold_sec
            updated.append(clone)
            replaced_legacy_target = True
    if not updated_current_event and (has_existing_p0_target or not replaced_legacy_target):
        event: dict[str, Any] = {
            "event_id": research_p0["event_id"],
            "target": target,
            "action": action,
            "effect": effect,
            "at_sec": trigger,
            "trigger_at_sec": trigger,
            "research_p0": research_p0,
        }
        if hold_sec is not None:
            event["hold_sec"] = hold_sec
        updated.append(event)
    # Keep the runtime list chronologically ordered after appending a second
    # P0 event to an existing target.  Browser scheduling uses this list as the
    # source of deterministic event order, so focus must never precede reveal.
    def _timeline_time(item: Any) -> float:
        if not isinstance(item, dict):
            return float("inf")
        try:
            return float(item.get("at_sec", item.get("trigger_at_sec", float("inf"))))
        except (TypeError, ValueError):
            return float("inf")

    segment["timeline"] = sorted(updated, key=_timeline_time)


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
        local_path = Path(str(visual.get("local_path") or ""))
        externally_materialized = (
            local_path.is_file()
            and bool(str(visual.get("license") or visual.get("provenance") or "").strip())
            and str(visual.get("vlm_verdict") or "").upper() == "ACCEPT"
        )
        if segment is None or not element_id or (
            (image_id, filename) not in allowed and not externally_materialized
        ):
            raise ValueError("P0 retrieved visual is not a whitelisted available textbook image")
        if Path(filename).name != filename:
            raise ValueError("P0 retrieved visual filename must not contain a path")
        elements = segment.setdefault("elements", [])
        existing_ids = {
            str(item.get("id") or "") for item in elements if isinstance(item, dict)
        }
        if element_id in existing_ids:
            continue
        source = allowed.get((image_id, filename), {})
        metadata = candidate.setdefault("metadata", {})
        if externally_materialized:
            metadata.setdefault("available_images", []).append(
                {
                    "id": image_id,
                    "filename": filename,
                    "description": str(visual.get("description") or "retrieved teaching visual"),
                    "license": visual.get("license"),
                    "provenance": visual.get("provenance"),
                }
            )
            metadata.setdefault("research_p0_acquired_asset_paths", {})[filename] = str(local_path)
        elements.append(
            {
                "id": element_id,
                "type": "image",
                "src": filename,
                "description": str(
                    visual.get("description") or source.get("description") or "教材原图"
                ),
                "research_p0": {
                    "acquisition": (
                        "RETRIEVE_LOCAL_RAG" if externally_materialized
                        else "RETRIEVE_LOCAL_TEXTBOOK_IMAGE"
                    ),
                    "source_image_id": image_id,
                    "proposition_id": str(visual.get("proposition_id") or ""),
                    "vlm_verdict": visual.get("vlm_verdict"),
                },
            }
        )


def _sanitize_research_runtime_targets(candidate: dict[str, Any]) -> None:
    """Remove dead legacy annotation targets from the P0 copy only.

    Production storyboards may contain a focus box whose target was removed by
    a later storyboard revision (or a timeline item that still names the old
    source-image id).  The mature renderer quite correctly reports those as
    ``target_missing``.  They are not a P0 intervention, so keeping them in the
    treatment would contaminate the runtime evidence.  Canonicalize aliases
    that resolve to a real element and drop only unresolved items; the frozen
    baseline file is never touched.
    """
    for segment in candidate.get("segments", []) or []:
        if not isinstance(segment, dict):
            continue
        raw_elements = [item for item in segment.get("elements", []) or [] if isinstance(item, dict)]
        element_ids = {
            str(item.get("id") or "") for item in raw_elements if str(item.get("id") or "").strip()
        }
        elements: list[dict[str, Any]] = []
        for element in raw_elements:
            element_type = str(element.get("type") or "")
            target = str(element.get("target") or "").strip()
            if element_type in {"focus_box", "callout"} and target and target not in element_ids:
                continue
            elements.append(element)
        segment["elements"] = elements
        element_ids = {
            str(item.get("id") or "") for item in elements if str(item.get("id") or "").strip()
        }
        aliases: dict[str, str] = {}
        for element_id in sorted(element_ids):
            for alias in _element_target_aliases(segment, element_id):
                aliases.setdefault(alias, element_id)

        def canonical_targets(value: Any) -> list[str]:
            result: list[str] = []
            for token in str(value or "").split(","):
                token = token.strip()
                if not token:
                    continue
                canonical = aliases.get(token)
                if canonical and canonical not in result:
                    result.append(canonical)
            return result

        for key in ("animations", "timeline"):
            cleaned: list[dict[str, Any]] = []
            for item in segment.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                targets = canonical_targets(item.get("target"))
                if not targets:
                    continue
                clone = copy.deepcopy(item)
                clone["target"] = ",".join(targets)
                cleaned.append(clone)
            segment[key] = cleaned


def prepare_p0_candidate(
    storyboard_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    plan_path: str | Path | None = None,
    proposition_graph_path: str | Path | None = None,
    visual_decision_path: str | Path | None = None,
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

    if proposition_graph_path:
        graph = _read_json(Path(proposition_graph_path))
        graph_props = [
            dict(item) for item in graph.get("narration_propositions", [])
            if isinstance(item, dict)
        ]
        if not graph_props:
            raise ValueError("proposition graph contains no narration propositions")
        for proposition in graph_props:
            segment_id = str(proposition.get("segment_id") or "")
            if segment_id not in segments_by_id:
                raise ValueError(f"proposition graph references unknown segment: {segment_id}")
            if not proposition.get("id") or not proposition.get("text"):
                raise ValueError("proposition graph contains incomplete narration proposition")
        propositions = graph_props
        proposition_ids = {str(item["id"]) for item in propositions}

    candidate = copy.deepcopy(storyboard)
    visual_decisions: dict[str, dict[str, Any]] = {}
    if visual_decision_path:
        decision_document = _read_json(Path(visual_decision_path))
        visual_decisions = {
            str(item.get("narration_proposition_id") or ""): item
            for item in decision_document.get("decisions", []) if isinstance(item, dict)
        }
    _materialize_retrieved_visuals(candidate, plan.get("retrieved_visuals", []))
    _sanitize_research_runtime_targets(candidate)
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
        proposition_record = next(
            (item for item in propositions if str(item.get("id") or "") == proposition_id), None
        )
        if (
            proposition_id not in proposition_ids
            or not isinstance(proposition_record, dict)
            or str(proposition_record.get("segment_id") or "") != segment_id
        ):
            raise ValueError(
                f"P0 event {event_id} references unknown proposition: {proposition_id}"
            )
        if target_element_id not in _element_ids(segment):
            raise ValueError(
                f"P0 event {event_id} references missing production element: {target_element_id}"
            )
        target_element = _find_element(segment, target_element_id)
        if visual_decision_path:
            _validate_visual_decision_target(
                decision=visual_decisions.get(proposition_id),
                element=target_element,
                proposition_id=proposition_id,
                event_id=event_id,
            )
        try:
            lead_sec = float(event.get("lead_sec", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"P0 event {event_id} lead_sec must be numeric") from exc
        requested_action = str(event.get("action") or "show")
        action = requested_action
        if requested_action not in _P0_EVENT_ACTIONS:
            raise ValueError(
                f"P0 event {event_id} uses unsupported action: {requested_action!r}"
            )
        # The mature renderer has no public ``remove`` action.  Keep the
        # research decision verbatim, but apply a renderer-safe fade/dim at
        # execution time and record the requested action for later analysis.
        runtime_action = "dim" if requested_action == "remove" else requested_action
        try:
            hold_sec = float(event.get(
                "duration_sec",
                event.get("hold_sec", 2.0 if action == "focus" else 0.0),
            ))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"P0 event {event_id} hold_sec must be numeric") from exc
        if hold_sec < 0:
            raise ValueError(f"P0 event {event_id} hold_sec must be non-negative")
        validated_events.append(
            {
                "id": event_id,
                "segment_id": segment_id,
                "proposition_id": proposition_id,
                "target_element_id": target_element_id,
                "lead_sec": lead_sec,
                "action": action,
                "runtime_action": runtime_action,
                "hold_sec": hold_sec,
                "duration_sec": hold_sec,
                "effect": str(event.get(
                    "effect",
                    "fadeOut" if requested_action == "remove" else (
                        "fadeIn" if requested_action == "dim" else "fadeInUp"
                    ),
                )),
                "signal": event.get("signal"),
                "visual_decision": visual_decisions.get(proposition_id),
                "status": "VALIDATED_PENDING_MEASURED_TTS",
            }
        )

        # Persist the graph edge on the actual production element.  This is a
        # research namespace only; normal renderers keep reading their legacy
        # fields, while later diagnosis can recover source -> proposition ->
        # element without guessing from text similarity again.
        element = target_element
        if isinstance(element, dict):
            research = element.setdefault("research_p0", {})
            research["narration_proposition_ids"] = _merge_unique(
                research.get("narration_proposition_ids"), [proposition_id]
            )
            research["knowledge_proposition_ids"] = _merge_unique(
                research.get("knowledge_proposition_ids"),
                list(proposition_record.get("knowledge_proposition_ids") or []),
            )
            research["source_refs"] = _merge_unique(
                research.get("source_refs"), list(proposition_record.get("source_refs") or [])
            )
            research.setdefault("visual_decisions", {})[proposition_id] = visual_decisions.get(proposition_id)

    # Multiple narration propositions may legitimately be explained by one
    # persistent Figure.  The planner emits only the first reveal/focus event,
    # but every proposition-to-element edge remains explicit on the element.
    propositions_by_id = {
        str(item.get("id") or ""): item for item in propositions if isinstance(item, dict)
    }
    for binding in plan.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        segment_id = str(binding.get("segment_id") or "")
        proposition_id = str(binding.get("proposition_id") or "")
        target_element_id = str(binding.get("target_element_id") or "")
        segment = candidate_segments_by_id.get(segment_id)
        proposition_record = propositions_by_id.get(proposition_id)
        if segment is None or proposition_record is None:
            raise ValueError(f"P0 binding has invalid context: {binding!r}")
        element = next(
            (
                item for item in segment.get("elements", []) or []
                if isinstance(item, dict) and str(item.get("id") or "") == target_element_id
            ),
            None,
        )
        if not isinstance(element, dict):
            raise ValueError(f"P0 binding references missing element: {binding!r}")
        if visual_decision_path:
            _validate_visual_decision_target(
                decision=visual_decisions.get(proposition_id),
                element=element,
                proposition_id=proposition_id,
                event_id=f"binding:{proposition_id}",
            )
        research = element.setdefault("research_p0", {})
        research["narration_proposition_ids"] = _merge_unique(
            research.get("narration_proposition_ids"), [proposition_id]
        )
        research["knowledge_proposition_ids"] = _merge_unique(
            research.get("knowledge_proposition_ids"),
            list(proposition_record.get("knowledge_proposition_ids") or []),
        )
        research["source_refs"] = _merge_unique(
            research.get("source_refs"), list(proposition_record.get("source_refs") or [])
        )
        research.setdefault("visual_decisions", {})[proposition_id] = visual_decisions.get(proposition_id)

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
            if not proposition_graph_path:
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
        "proposition_graph": {
            "path": str(proposition_graph_path) if proposition_graph_path else None,
            "status": "LLM_VALIDATED_GRAPH" if proposition_graph_path else "LEGACY_SENTENCE_DERIVATION",
        },
        "visual_decisions": {
            "path": str(visual_decision_path) if visual_decision_path else None,
            "bound_event_count": sum(1 for event in validated_events if event.get("visual_decision") is not None),
        },
        "render": {
            "renderer": "production_animation_gen",
            "rendered_visibility_claim": "NOT_MEASURED_BY_P0_INTEGRATION",
        },
    }
    from .signaling_diagnostics import diagnose_signaling

    sidecar["signaling_diagnostics"] = diagnose_signaling(
        events=validated_events,
        elements_by_segment={
            segment_id: _element_ids(segment)
            for segment_id, segment in candidate_segments_by_id.items()
        },
        propositions={str(item.get("id")): item for item in propositions if isinstance(item, dict)},
    )
    if not sidecar["signaling_diagnostics"]["pass"]:
        raise ValueError("P0 signaling diagnostics rejected invalid signal bindings")
    # The production renderer intentionally resolves textbook figures relative
    # to the storyboard it receives.  A P0 candidate lives in a new directory,
    # so preserve every referenced local figure there instead of silently
    # degrading it to a placeholder or an unrelated generated image.
    source_image_dir = baseline.parent / "images"
    candidate_image_dir = candidate_path.parent / "images"
    acquired_paths = candidate.get("metadata", {}).get("research_p0_acquired_asset_paths", {})
    referenced_images = {
        str(element.get("src"))
        for segment in candidate.get("segments", [])
        if isinstance(segment, dict)
        for element in segment.get("elements", [])
        if isinstance(element, dict)
        and element.get("type") == "image"
        and str(element.get("src") or "").strip()
        and Path(str(element.get("src"))).name == str(element.get("src"))
    }
    copied_images: list[str] = []
    for filename in sorted(referenced_images):
        source = Path(str(acquired_paths.get(filename) or ""))
        if not source.is_file():
            source = source_image_dir / filename
        if not source.is_file():
            continue
        candidate_image_dir.mkdir(parents=True, exist_ok=True)
        destination = candidate_image_dir / filename
        if not destination.exists():
            shutil.copy2(source, destination)
        copied_images.append(filename)
    candidate["metadata"]["research_p0"]["copied_source_images"] = copied_images
    _write_json(candidate_path, candidate)
    _write_json(sidecar_path, sidecar)
    return P0IntegrationPaths(baseline, candidate_path, sidecar_path)


def apply_p0_event_schedule(
    paths: P0IntegrationPaths,
    *,
    sentence_cues: dict[str, Any] | list[dict[str, Any]] | None = None,
    allow_approximate_cues: bool = False,
) -> dict[str, Any]:
    """Apply validated P0 events after production TTS has measured duration.

    Existing production elements and the production renderer remain canonical.
    An event changes only an existing target's production animation.  Besides
    its sentence-derived trigger, the research plan may explicitly set a
    supported action (``show``, ``focus``, or ``highlight``).  This makes the
    treatment observable in the original renderer instead of merely changing
    a hidden timing number.  The final video is still rendered by
    ``animation_gen.generate``.
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
        # Backward compatibility for sidecars written before P0 actions and
        # finite focus holds were made explicit.
        requested_action = str(event.get("action") or "show")
        action = str(event.get("runtime_action") or ("dim" if requested_action == "remove" else requested_action))
        hold_sec = event.get("duration_sec", event.get("hold_sec", 2.0 if action == "focus" else 0.0))
        segment = segment_map.get(str(event.get("segment_id") or ""))
        proposition = propositions.get(str(event.get("proposition_id") or ""))
        if segment is None or proposition is None:
            event["status"] = "SKIPPED_MISSING_CANDIDATE_CONTEXT"
            continue
        local_cues, has_measured_cues = _segment_sentence_cues(sentence_cues, str(event["segment_id"]))
        direct_at = event.get("at_sec", event.get("measured_at_sec"))
        if direct_at is not None:
            try:
                direct_at = float(direct_at)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"P0 event {event.get('id')} at_sec must be numeric") from exc
            cue = None
            cue_fraction = 0.0
            cue_match_kind = "measured_proposition_interval"
        else:
            cue, cue_fraction, cue_match_kind = _resolve_proposition_cue(
                segment=segment,
                proposition=proposition,
                local_cues=local_cues,
                has_measured_cues=has_measured_cues,
                allow_approximate_cues=allow_approximate_cues,
            )
        duration = float(segment.get("audio_duration_sec") or 0.0)
        target = str(event["target_element_id"])
        if direct_at is not None:
            trigger = max(0.0, direct_at)
        else:
            trigger = max(
                0.0,
                cue.start_sec + (cue.end_sec - cue.start_sec) * cue_fraction
                + float(event.get("lead_sec") or 0.0),
            )
        if duration > 0:
            trigger = min(trigger, max(0.0, duration - 0.2))
        trigger = round(trigger, 3)
        animations = segment.setdefault("animations", [])
        event_id = str(event.get("id") or "")
        target_aliases = _element_target_aliases(segment, target)
        animation = next(
            (
                item
                for item in animations
                if isinstance(item, dict)
                and str(item.get("target") or "") == target
                and isinstance(item.get("research_p0"), dict)
                and str(item["research_p0"].get("event_id") or "") == event_id
            ),
            None,
        )
        if animation is None:
            # The first P0 event replaces the legacy target animation. A
            # subsequent show/focus event gets its own record.
            animation = next(
                (
                    item for item in animations
                    if isinstance(item, dict)
                    and str(item.get("target") or "") in target_aliases
                    and not isinstance(item.get("research_p0"), dict)
                ),
                None,
            )
        research_p0 = {
            "event_id": event_id,
            "proposition_id": event["proposition_id"],
            "timing_source": (
                "p0_measured_proposition_interval"
                if direct_at is not None else (
                    "p0_proposition_to_measured_sentence_cue"
                    if has_measured_cues else "p0_proposition_to_duration_weighted_sentence_cue"
                )
            ),
            "action_source": "p0_event_plan",
            "requested_action": requested_action,
            "runtime_action": action,
        }
        if animation is None:
            animation = {
                "target": target,
                "action": action,
                "effect": event["effect"],
            }
            animations.append(animation)
        else:
            # A P0 event is an experimental intervention, not metadata on an
            # otherwise unchanged baseline animation.  Preserve the target but
            # make the planned visual action explicit for the runtime.
            animation["target"] = target
            animation["action"] = action
            animation["effect"] = event["effect"]
        animation["trigger_at_sec"] = trigger
        animation["research_p0"] = research_p0
        if hold_sec is not None:
            animation["hold_sec"] = hold_sec
        _set_runtime_timeline_event(
            segment,
            target=target,
            action=action,
            effect=event["effect"],
            trigger=trigger,
            hold_sec=hold_sec,
            research_p0=research_p0,
        )
        event.update(
            {
                "status": "SCHEDULED_ON_PRODUCTION_ANIMATION",
                "planned_trigger_at_sec": trigger,
                "cue_text": cue.text if cue is not None else str(proposition.get("text") or ""),
                "cue_timing_kind": (
                    "measured_proposition_interval" if direct_at is not None else (
                        "measured_sentence_cue" if has_measured_cues else "duration_weighted_estimate"
                    )
                ),
                "cue_match_kind": cue_match_kind,
                "cue_sentence_id": cue.sentence_id if cue is not None else None,
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
    runtime_trace_path: str | Path | None = None,
) -> None:
    """Persist browser and MP4 evidence for every scheduled P0 event.

    The browser trace is the runtime observation: it records the resolved DOM
    target, its computed visibility and geometry on the animation clock.  The
    MP4 samples are independently extracted from the muxed output at the same
    global timestamps, so a later VLM/human review does not have to trust a
    planned ``trigger_at_sec``.
    """
    sidecar = _read_json(paths.sidecar_path)
    trace_path = Path(runtime_trace_path) if runtime_trace_path else None
    trace: dict[str, Any] = {}
    if trace_path and trace_path.is_file():
        try:
            trace = _read_json(trace_path)
        except (OSError, json.JSONDecodeError):
            trace = {}
    trace_by_event = {
        str(item.get("event_id") or ""): item
        for item in trace.get("events", []) if isinstance(item, dict)
    }
    video = Path(video_path)
    evidence_path = paths.sidecar_path.with_name(
        paths.sidecar_path.name.replace("_research_p0.json", "_render_evidence.json")
    )
    frame_root = evidence_path.with_name(evidence_path.stem + "_frames")
    observations: list[dict[str, Any]] = []
    # P0 event times are slide-local.  Resolve a deterministic global clock
    # from the candidate storyboard so the sampled MP4 timestamps are exact.
    candidate = _read_json(paths.candidate_storyboard_path)
    offsets: dict[str, float] = {}
    cursor = 0.0
    for index, segment in enumerate(candidate.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        sid = _segment_id(segment, index)
        offsets[sid] = cursor
        cursor += float(segment.get("audio_duration_sec") or 0.0)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            ffmpeg = None
    for event in sidecar.get("events", []):
        if not isinstance(event, dict) or event.get("status") != "SCHEDULED_ON_PRODUCTION_ANIMATION":
            continue
        event_id = str(event.get("id") or "")
        runtime = trace_by_event.get(event_id, {})
        visual = runtime.get("visible_observation") if isinstance(runtime, dict) else None
        visual = visual if isinstance(visual, dict) else {}
        base = offsets.get(str(event.get("segment_id") or ""), 0.0)
        start_ms = visual.get("observed_visible_start_ms")
        end_ms = visual.get("expected_visible_end_ms")
        start = base + float(start_ms) / 1000.0 if isinstance(start_ms, (int, float)) else None
        end = base + float(end_ms) / 1000.0 if isinstance(end_ms, (int, float)) else None
        samples: list[dict[str, Any]] = []
        if ffmpeg and video.is_file() and start is not None:
            frame_root.mkdir(parents=True, exist_ok=True)
            for label, timestamp in (("visible_start", start), ("visible_end", end)):
                if timestamp is None:
                    continue
                output = frame_root / f"{event_id}_{label}.png"
                result = subprocess.run(
                    [ffmpeg, "-y", "-ss", f"{max(0.0, timestamp):.3f}", "-i", str(video),
                     "-frames:v", "1", "-q:v", "2", str(output)],
                    capture_output=True,
                )
                samples.append({
                    "label": label,
                    "timestamp_sec": round(timestamp, 3),
                    "path": str(output) if result.returncode == 0 and output.is_file() else None,
                    "status": "EXTRACTED" if result.returncode == 0 and output.is_file() else "FAILED",
                })
        observations.append({
            "event_id": event_id,
            "segment_id": event.get("segment_id"),
            "target_element_id": event.get("target_element_id"),
            "runtime_status": runtime.get("status") if isinstance(runtime, dict) else "TRACE_MISSING",
            "runtime_target": runtime.get("target") if isinstance(runtime, dict) else None,
            "dom_visibility": visual,
            "observed_visible_start_sec": round(start, 3) if start is not None else None,
            "observed_visible_end_sec": round(end, 3) if end is not None else None,
            "mp4_frame_samples": samples,
            "status": "BROWSER_AND_MP4_EVIDENCE" if samples else "BROWSER_EVIDENCE_ONLY",
        })
    digest = None
    if video.is_file():
        hasher = hashlib.sha256()
        with video.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        digest = hasher.hexdigest()
    _write_json(evidence_path, {
        "schema_version": "p0-render-evidence-v0.2",
        "video_path": str(video),
        "video_sha256": digest,
        "runtime_trace_path": str(trace_path) if trace_path else None,
        "observations": observations,
        "claim": "Intervals are browser-observed rendered DOM visibility; MP4 samples are retained for independent frame-level review.",
    })
    sidecar.setdefault("render", {}).update(
        {
            "html_path": str(html_path),
            "video_path": str(video_path),
            "runtime_trace_path": str(trace_path) if trace_path else None,
            "render_evidence_path": str(evidence_path),
            "rendered_visibility_claim": "BROWSER_DOM_OBSERVED_WITH_MP4_FRAME_SAMPLES",
        }
    )
    _write_json(paths.sidecar_path, sidecar)


__all__ = [
    "P0IntegrationPaths",
    "P0_PLAN_VERSION",
    "P0_SIDECAR_VERSION",
    "P0_CASE_BUNDLE_VERSION",
    "apply_p0_event_schedule",
    "finalize_p0_render_evidence",
    "measure_proposition_intervals",
    "prepare_p0_candidate",
    "validate_p0_case_bundle",
    "write_p0_case_manifest",
]
