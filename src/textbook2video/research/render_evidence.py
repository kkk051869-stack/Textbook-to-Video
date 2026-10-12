"""Final-video evidence sidecar, deliberately separate from browser trace."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .proposition_schema import SCHEMA_VERSION, stable_case_id


def write_render_evidence(
    *,
    video_path: str | Path,
    runtime_trace: dict[str, Any] | None,
    planned_events: list[dict[str, Any]],
    output_path: str | Path,
    case_id: str,
) -> Path:
    """Write conservative frame-sampling observations.

    Runtime execution is evidence of dispatched DOM events, not proof of
    visibility.  This artifact therefore records ``not_reviewed`` until a
    human/video or CV observer supplies a measured interval.
    """
    video = Path(video_path)
    by_event = {str(item.get("event_id") or item.get("id") or ""): item
                for item in (runtime_trace or {}).get("events", []) if isinstance(item, dict)}
    observations = []
    for index, event in enumerate(planned_events, 1):
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or event.get("event_id") or "")
        runtime = by_event.get(event_id, {})
        status = "not_reviewed" if runtime.get("status") == "executed" else "unobservable"
        observations.append({
            "id": f"{stable_case_id(case_id)}-obs-{index:03d}", "event_id": event_id,
            "target_element_id": str(event.get("target_element_id") or event.get("target") or ""),
            "status": status, "observed_visible_start_sec": None, "observed_visible_end_sec": None,
            "method": "frame_sampling", "confidence": None, "observer_id": "system_pending_review",
            "notes": "Runtime trace recorded execution only; visibility interval requires video observation.",
            "runtime_status": runtime.get("status"), "runtime_actual_ms": runtime.get("actual_ms"),
        })
    document = {"schema_version": SCHEMA_VERSION, "artifact_type": "render_evidence_v0.1",
                "case_id": stable_case_id(case_id), "video_path": str(video),
                "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest() if video.is_file() else None,
                "observations": observations,
                "claim": "Observed visibility fields remain null until an explicit human/CV video review."}
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


__all__ = ["write_render_evidence"]
