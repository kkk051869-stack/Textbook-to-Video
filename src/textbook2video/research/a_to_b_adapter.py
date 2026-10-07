"""Convert selected A visual decisions into isolated B render candidates."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
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


def build_full_segment_handoff_candidate(
    *,
    bridge: dict[str, Any],
    legacy_storyboard: dict[str, Any],
    asset_path: str | Path,
) -> dict[str, Any]:
    """Preserve a legacy segment's elements while replacing its primary visual.

    This is intentionally a candidate-only transformation: original IDs and
    timing remain untouched in the legacy storyboard, while the candidate gets
    canonical IDs and the bridge's explicit trigger for the selected visual.
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
    source_elements = source_segment.get("elements", []) or []
    image = next((item for item in source_elements if item.get("type") == "image"), None)
    if image is None:
        raise ValueError(f"segment {segment_id} has no image element to replace")

    case_id = str(bridge["case_id"])
    canonical_segment_id = f"{case_id.replace('_', '-')}-seg-{int(segment_id):03d}"
    source_image_id = str(image["id"])
    visual_id = str(bridge["visual_element_id"])
    element_ids = {
        str(element["id"]): (
            visual_id
            if str(element["id"]) == source_image_id
            else f"{canonical_segment_id}-el-{str(element['id']).removeprefix('e').zfill(3)}"
        )
        for element in source_elements
    }
    elements: list[dict[str, Any]] = []
    for raw in source_elements:
        element = deepcopy(raw)
        old_id = str(element["id"])
        element["id"] = element_ids[old_id]
        if old_id == source_image_id:
            element["src"] = str(Path(asset_path).resolve())
            element["description"] = bridge["asset_caption"]
            element["narration_proposition_ids"] = [bridge["narration_proposition_id"]]
            element["source_evidence_ids"] = bridge["source_evidence_ids"]
        for target_key in ("target", "target_image", "image_id"):
            if str(element.get(target_key) or "") in element_ids:
                element[target_key] = element_ids[str(element[target_key])]
        elements.append(element)

    animations: list[dict[str, Any]] = []
    for raw in source_segment.get("animations", []) or []:
        animation = deepcopy(raw)
        old_target = str(animation.get("target") or "")
        if old_target in element_ids:
            animation["target"] = element_ids[old_target]
        if old_target == source_image_id:
            animation["trigger_at_sec"] = bridge["trigger_at_sec"]
        animations.append(animation)
    return {
        "schema_version": "a-to-b-full-segment-candidate-v0.1",
        "case_id": case_id,
        "baseline_mutated": False,
        "bridge": bridge,
        "renderer_segments": [
            {
                "id": canonical_segment_id,
                "visual_type": "text",
                "audio_duration_sec": float(source_segment.get("audio_duration_sec") or 1.0),
                "narration": source_segment.get("narration", ""),
                "elements": elements,
                "animations": animations,
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


__all__ = [
    "build_full_segment_handoff_candidate",
    "build_handoff_candidate",
    "copy_handoff_asset",
    "write_handoff_candidate",
]
