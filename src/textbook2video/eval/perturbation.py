"""Small local metamorphic perturbations that preserve caller inputs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def perturb_viewport(report: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    """Change only the recorded viewport metadata in a report copy."""

    if width < 1 or height < 1:
        raise ValueError("viewport dimensions must be positive")
    value = deepcopy(report)
    metadata = value.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        value["metadata"] = metadata
    metadata["viewport"] = {"width": int(width), "height": int(height)}
    return value


def perturb_tts_durations(storyboard: dict[str, Any], *, factor: float) -> dict[str, Any]:
    """Apply a synthetic duration factor without invoking TTS or editing input."""

    if factor <= 0:
        raise ValueError("duration factor must be positive")
    value = deepcopy(storyboard)
    for segment in value.get("segments", []) if isinstance(value.get("segments"), list) else []:
        if not isinstance(segment, dict):
            continue
        duration = segment.get("audio_duration_sec")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            segment["audio_duration_sec"] = round(float(duration) * factor, 3)
    return value


__all__ = ["perturb_tts_durations", "perturb_viewport"]
