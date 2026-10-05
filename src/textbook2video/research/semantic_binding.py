"""Build explicit narration-proposition to visual-element binding predictions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .binding_baselines import (
    DEFAULT_THRESHOLD,
    DEFAULT_TIE_MARGIN,
    METHOD_NAME,
    METHOD_VERSION,
    lexical_jaccard_bind,
)

SCHEMA_VERSION = "proposition-visual-binding-v0.1"


def _key(value: Any) -> str:
    return str(value or "").strip()


def _storyboard_segments(storyboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, segment in enumerate(storyboard.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        stable_id = _key(segment.get("id"))
        legacy_id = _key(segment.get("legacy_segment_id"))
        if stable_id:
            result[stable_id] = segment
        if legacy_id:
            result.setdefault(legacy_id, segment)
        result.setdefault(str(index), segment)
    return result


def build_binding_report(
    script: dict[str, Any],
    storyboard: dict[str, Any],
    *,
    case_id: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    tie_margin: float = DEFAULT_TIE_MARGIN,
    max_targets: int = 1,
) -> dict[str, Any]:
    """Run the deterministic lexical baseline against one structured case."""
    resolved_case_id = _key(case_id or script.get("case_id") or storyboard.get("case_id"))
    if not resolved_case_id:
        raise ValueError("case_id is required")

    storyboard_by_segment = _storyboard_segments(storyboard)
    bindings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_propositions: set[str] = set()

    for segment_index, script_segment in enumerate(script.get("segments", []) or [], start=1):
        if not isinstance(script_segment, dict):
            continue
        segment_id = _key(
            script_segment.get("id") or script_segment.get("segment_id") or segment_index
        )
        legacy_id = _key(script_segment.get("legacy_segment_id"))
        visual_segment = storyboard_by_segment.get(segment_id) or storyboard_by_segment.get(
            legacy_id
        )
        propositions = script_segment.get("narration_propositions", []) or []
        if visual_segment is None:
            for proposition in propositions:
                proposition_id = (
                    _key(proposition.get("id")) if isinstance(proposition, dict) else ""
                )
                failures.append(
                    {
                        "type": "missing_storyboard_segment",
                        "segment_id": segment_id,
                        "narration_proposition_id": proposition_id or None,
                    }
                )
            continue
        elements = [
            item for item in visual_segment.get("elements", []) or [] if isinstance(item, dict)
        ]
        element_ids = [_key(item.get("id")) for item in elements]
        if len([item for item in element_ids if item]) != len(
            set(item for item in element_ids if item)
        ):
            raise ValueError(f"duplicate visual element ID in segment {segment_id}")

        for proposition_index, proposition in enumerate(propositions, start=1):
            if not isinstance(proposition, dict):
                continue
            proposition_id = _key(proposition.get("id"))
            proposition_text = _key(proposition.get("text"))
            if not proposition_id or not proposition_text:
                failures.append(
                    {
                        "type": "invalid_narration_proposition",
                        "segment_id": segment_id,
                        "position": proposition_index,
                    }
                )
                continue
            if proposition_id in seen_propositions:
                raise ValueError(f"duplicate narration proposition ID: {proposition_id}")
            seen_propositions.add(proposition_id)
            prediction = lexical_jaccard_bind(
                proposition_text,
                elements,
                threshold=threshold,
                tie_margin=tie_margin,
                max_targets=max_targets,
            )
            bindings.append(
                {
                    "binding_id": f"{resolved_case_id}-binding-{len(bindings) + 1:04d}",
                    "segment_id": _key(visual_segment.get("id") or segment_id),
                    "narration_proposition_id": proposition_id,
                    **prediction,
                }
            )

    bound_count = sum(item["status"] == "bound" for item in bindings)
    count = len(bindings)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "semantic_binding_predictions",
        "case_id": resolved_case_id,
        "method": {
            "name": METHOD_NAME,
            "version": METHOD_VERSION,
            "uses_external_model": False,
            "threshold": float(threshold),
            "tie_margin": float(tie_margin),
            "max_targets": max(1, int(max_targets)),
        },
        "bindings": bindings,
        "metrics": {
            "proposition_count": count,
            "bound_count": bound_count,
            "abstained_count": count - bound_count,
            "binding_coverage": round(bound_count / count, 6) if count else 0.0,
        },
        "failures": failures,
    }


def write_binding_report(report: dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


__all__ = ["SCHEMA_VERSION", "build_binding_report", "write_binding_report"]
