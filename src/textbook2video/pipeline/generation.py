"""Shared generation/file steps; entry points retain their compatibility policies."""

from __future__ import annotations

import json
from pathlib import Path


def generate_lesson_plan_file(text: str, path: Path, **kwargs) -> dict:
    from textbook2video.pipeline.lesson_plan import generate_lesson_plan

    plan = generate_lesson_plan(text, **kwargs)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def write_script_segments(path: Path, segments: list[str], *, header: str) -> None:
    """Keep historical headers explicit, including the two DOCX spellings."""
    with open(path, "w", encoding="utf-8") as stream:
        for index, segment in enumerate(segments, 1):
            stream.write(f"{header.format(index=index)}\n{segment}\n\n")


def write_generation_json(storyboard: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(storyboard, stream, ensure_ascii=False, indent=2)


def measure_audio_durations(
    audio_files, *, precision: int, failure_value: float = 0.0,
) -> list[float]:
    from textbook2video.pipeline.narrator import get_audio_duration

    durations = []
    for audio_file in audio_files:
        try:
            durations.append(round(get_audio_duration(str(audio_file)), precision))
        except ValueError:
            durations.append(failure_value)
    return durations


def write_timing_outputs(storyboard: dict, path: Path) -> Path:
    """Persist already-timed data without reapplying or selecting a timing mode."""
    from textbook2video.pipeline.timing import timed_storyboard_path

    write_generation_json(storyboard, path)
    timed_path = timed_storyboard_path(path)
    timed_path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    return timed_path


def run_legacy_cli_tts(storyboard: dict, audio_dir: Path) -> tuple[dict, list[float]]:
    """Preserve CLI segment TTS, tenth-second durations and default timing.

    Deliberately separate from orchestrator.run_tts: no sentence audio,
    frozen-audio handling, research dual writes, or in-place timed replacement.
    """
    from textbook2video.pipeline.narrator import generate_audio
    from textbook2video.pipeline.timing import apply_timing

    narrations = [segment["narration"] for segment in storyboard["segments"]]
    files = generate_audio(narrations, output_dir=str(audio_dir))
    durations = measure_audio_durations(files, precision=1, failure_value=0)
    for index, segment in enumerate(storyboard["segments"]):
        segment["audio_duration_sec"] = durations[index]
    return apply_timing(storyboard), durations
