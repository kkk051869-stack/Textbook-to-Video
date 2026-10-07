"""Convert selected A visual decisions into isolated B render candidates."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def build_handoff_candidate(
    *,
    bridge: dict[str, Any],
    legacy_storyboard: dict[str, Any],
    asset_path: str | Path,
) -> dict[str, Any]:
    """Build one renderable segment candidate from one explicit bridge record.

    The bridge is authoritative for segment, narration proposition and planned
    trigger.  No lexical matching is performed here.
    """
    segment_id = str(bridge["segment_id"])
    source_segment = next(
        (
            item
            for item in legacy_storyboard.get("segments", [])
            if str(item.get("id")) == segment_id
        ),
        None,
    )
    if source_segment is None:
        raise ValueError(f"segment {segment_id} is absent from storyboard")
    case_id = str(bridge["case_id"])
    canonical_segment_id = f"{case_id.replace('_', '-')}-seg-{int(segment_id):03d}"
    visual_id = str(bridge["visual_element_id"])
    heading = next(
        (
            item.get("text")
            for item in source_segment.get("elements", [])
            if item.get("type") == "heading"
        ),
        bridge["knowledge_proposition_id"],
    )
    duration = float(source_segment.get("audio_duration_sec") or 1.0)
    return {
        "schema_version": "a-to-b-render-candidate-v0.1",
        "case_id": case_id,
        "baseline_mutated": False,
        "bridge": bridge,
        "renderer_segments": [
            {
                "id": canonical_segment_id,
                "visual_type": "text",
                "audio_duration_sec": duration,
                "narration": source_segment.get("narration", ""),
                "elements": [
                    {"id": f"{canonical_segment_id}-heading", "type": "heading", "text": heading},
                    {
                        "id": visual_id,
                        "type": "image",
                        "src": str(Path(asset_path).resolve()),
                        "description": bridge["asset_caption"],
                        "narration_proposition_ids": [bridge["narration_proposition_id"]],
                        "source_evidence_ids": bridge["source_evidence_ids"],
                    },
                ],
                "animations": [
                    {
                        "target": visual_id,
                        "effect": "fadeInUp",
                        "trigger_at_sec": bridge["trigger_at_sec"],
                    }
                ],
            }
        ],
        "time_claim": "planned_event_times_only_not_rendered_visibility",
    }


def write_handoff_candidate(candidate: dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def copy_handoff_asset(asset_path: str | Path, output_dir: str | Path) -> Path:
    source = Path(asset_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    target = Path(output_dir) / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


__all__ = ["build_handoff_candidate", "copy_handoff_asset", "write_handoff_candidate"]
