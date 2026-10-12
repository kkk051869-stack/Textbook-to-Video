"""Freeze existing artifacts for the event-alignment annotation pilot.

This module is intentionally read-only with respect to source artifacts.  It
copies available files into a new case directory, records missing evidence
explicitly, and refuses to overwrite an existing manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

STATUS_AVAILABLE = "AVAILABLE"
STATUS_MISSING = "MISSING"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
VALID_STATUSES = {STATUS_AVAILABLE, STATUS_MISSING, STATUS_NOT_APPLICABLE}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _git_commit(workspace: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _entry(
    role: str,
    *,
    status: str,
    source: Path | None = None,
    snapshot: Path | None = None,
    root: Path | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid artifact status: {status}")
    item: dict[str, Any] = {"role": role, "status": status}
    if source is not None:
        item["source_path"] = str(source.resolve())
    if snapshot is not None:
        item["snapshot_path"] = str(snapshot.relative_to(root or snapshot.parent)).replace("\\", "/")
    if status == STATUS_AVAILABLE and snapshot is not None:
        item["sha256"] = sha256_file(snapshot)
        item["bytes"] = snapshot.stat().st_size
    if note:
        item["note"] = note
    return item


def _copy_file(
    role: str,
    source: Path,
    destination: Path,
    *,
    root: Path,
    required: bool = False,
    note: str | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        suffix = "required artifact absent" if required else "artifact absent in archived run"
        return _entry(role, status=STATUS_MISSING, source=source, note=note or suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return _entry(
        role,
        status=STATUS_AVAILABLE,
        source=source,
        snapshot=destination,
        root=root,
        note=note,
    )


def _copy_tree(
    role_prefix: str,
    source: Path,
    destination: Path,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    if not source.is_dir():
        return [_entry(role_prefix, status=STATUS_MISSING, source=source, note="directory absent")]
    result: list[dict[str, Any]] = []
    for file_path in sorted(path for path in source.rglob("*") if path.is_file()):
        relative = file_path.relative_to(source)
        role = f"{role_prefix}:{relative.as_posix()}"
        result.append(_copy_file(role, file_path, destination / relative, root=root))
    if not result:
        result.append(_entry(role_prefix, status=STATUS_MISSING, source=source, note="directory empty"))
    return result


def _prompt_reference_hashes(workspace: Path) -> dict[str, Any]:
    prompt_dir = workspace / "src" / "textbook2video" / "llm" / "prompts"
    files = {}
    if prompt_dir.is_dir():
        for path in sorted(prompt_dir.glob("*.md")):
            files[str(path.relative_to(workspace)).replace("\\", "/")] = sha256_file(path)
    return {
        "status": STATUS_MISSING,
        "reason": "Exact generation-time prompt bytes were not archived; current workspace hashes are reference-only.",
        "current_workspace_reference_hashes": files,
    }


def _runtime_sources(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for index, segment in enumerate(storyboard.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        timeline = segment.get("timeline")
        source = "timeline" if isinstance(timeline, list) and timeline else "animations"
        sources.append({
            "segment_id": str(segment.get("id") or index),
            "runtime_timeline_source": source,
            "timeline_event_count": len(timeline) if isinstance(timeline, list) else 0,
            "animation_count": len(segment.get("animations") or []),
        })
    return sources


def freeze_case(
    *,
    case_id: str,
    workspace: str | Path,
    source_case_dir: str | Path,
    artifact_dir: str | Path,
    execution_dir: str | Path,
    output_root: str | Path,
) -> Path:
    """Copy one existing case into an immutable research snapshot."""
    workspace = Path(workspace).resolve()
    source_case_dir = Path(source_case_dir).resolve()
    artifact_dir = Path(artifact_dir).resolve()
    execution_dir = Path(execution_dir).resolve()
    output_root = Path(output_root).resolve()
    case_root = output_root / case_id
    manifest_path = case_root / "manifest.json"
    if manifest_path.exists() or (case_root.exists() and any(case_root.iterdir())):
        raise FileExistsError(f"refusing to overwrite immutable snapshot: {case_root}")
    case_root.mkdir(parents=True, exist_ok=False)

    artifacts: list[dict[str, Any]] = []
    artifacts.extend(_copy_tree("source", source_case_dir / "source", case_root / "source", root=case_root))
    artifacts.append(_copy_file(
        "source_case_manifest",
        source_case_dir / "case_manifest.json",
        case_root / "source" / "case_manifest.json",
        root=case_root,
        required=True,
    ))
    artifacts.append(_copy_file(
        "source_reference_annotation",
        source_case_dir / "private" / "annotation.json",
        case_root / "source" / "reference_annotation.json",
        root=case_root,
        required=True,
        note="Existing dataset source/KP reference; not a Pilot pedagogical gold label.",
    ))

    before_path = artifact_dir / "storyboard_before_timing.json"
    artifacts.append(_copy_file(
        "storyboard_before_timing",
        before_path,
        case_root / "before_timing" / "storyboard.json",
        root=case_root,
        note="No distinct pre-timing storyboard was preserved in the archived pilot3 run.",
    ))

    for role, name in (
        ("storyboard_after_timing", "storyboard.json"),
        ("storyboard_timed", "storyboard_timed.json"),
        ("lesson_plan", "lesson_plan.json"),
        ("script", "script.txt"),
    ):
        artifacts.append(_copy_file(
            role,
            artifact_dir / name,
            case_root / "after_timing" / name,
            root=case_root,
            required=role in {"storyboard_after_timing", "storyboard_timed", "script"},
            note=("File exists but the archived pilot3 lesson plan is disabled." if role == "lesson_plan" else None),
        ))

    artifacts.extend(_copy_tree("audio", execution_dir / "audio", case_root / "audio", root=case_root))
    artifacts.append(_copy_file(
        "sentence_cues",
        execution_dir / "audio" / "sentence_cues.json",
        case_root / "audio" / "sentence_cues.json",
        root=case_root,
        note="Sentence-level sidecar was not preserved for this archived run.",
    ))

    render_files = (
        ("html", execution_dir / "animation.html", "animation.html"),
        ("final_mp4", execution_dir / "final.mp4", "final.mp4"),
        ("silent_mp4", execution_dir / "video_silent.mp4", "video_silent.mp4"),
        ("srt", execution_dir / "subtitles.srt", "subtitles.srt"),
        ("layout_1920", execution_dir / "storyboard.layout.json", "storyboard.layout.json"),
        ("layout_1366", execution_dir / "storyboard.layout-1366x768.json", "storyboard.layout-1366x768.json"),
        ("video_probe", execution_dir / "video_probe.json", "video_probe.json"),
        ("animation_manifest", artifact_dir / "animation.manifest.json", "animation.manifest.json"),
        ("quality_report", artifact_dir / "quality_report.json", "quality_report.json"),
    )
    for role, source, name in render_files:
        artifacts.append(_copy_file(
            role,
            source,
            case_root / "render" / name,
            root=case_root,
            required=role in {"html", "final_mp4", "srt"},
        ))
    artifacts.extend(_copy_tree("render_images", execution_dir / "images", case_root / "render" / "images", root=case_root))
    artifacts.extend(_copy_tree("render_fonts", execution_dir / "fonts", case_root / "render" / "fonts", root=case_root))

    for role, name in (
        ("animation_trace", "animation_trace.json"),
        ("animation_trace_raw", "animation_trace.raw.json"),
        ("browser_runtime", "browser_runtime.json"),
    ):
        artifacts.append(_copy_file(
            role,
            execution_dir / name,
            case_root / "eval" / name,
            root=case_root,
            required=role == "animation_trace",
        ))
    for role, source in (
        ("run_config", execution_dir / "run_config.json"),
        ("candidate_manifest", execution_dir / "candidate_manifest.json"),
        ("audio_provenance", execution_dir / "audio_provenance.json"),
    ):
        artifacts.append(_copy_file(role, source, case_root / "metadata" / source.name, root=case_root))

    run_config = _read_json(execution_dir / "run_config.json")
    candidate_manifest = _read_json(execution_dir / "candidate_manifest.json")
    source_json = _read_json(source_case_dir / "source" / "source.json")
    storyboard = _read_json(artifact_dir / "storyboard_timed.json")
    requested_modes: dict[str, int] = {}
    for segment in storyboard.get("segments", []) or []:
        if isinstance(segment, dict):
            mode = str(segment.get("render_mode") or "unspecified")
            requested_modes[mode] = requested_modes.get(mode, 0) + 1

    counts = {status: sum(item["status"] == status for item in artifacts) for status in VALID_STATUSES}
    manifest = {
        "schema_version": "t2v-research-baseline-snapshot-v0.1",
        "case_id": case_id,
        "snapshot_status": "FROZEN",
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace_commit": _git_commit(workspace),
        "generation": {
            "generation_commit": run_config.get("commit"),
            "candidate_commit": candidate_manifest.get("candidate_commit") or run_config.get("candidate_commit"),
            "model": run_config.get("model"),
            "generation_time": {
                "status": STATUS_MISSING,
                "reason": "No explicit generation timestamp was preserved in the archived run.",
                "archive_mtime_utc": datetime.fromtimestamp(
                    (execution_dir / "candidate_manifest.json").stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(timespec="seconds"),
            },
            "prompt_hashes": _prompt_reference_hashes(workspace),
        },
        "tts": {
            "backend": run_config.get("tts_backend"),
            "voice": run_config.get("tts_voice"),
            "rate": run_config.get("tts_rate"),
            "sentence_sync": {"status": STATUS_MISSING, "reason": "not recorded"},
        },
        "timing": {
            "mode": {"status": STATUS_MISSING, "reason": "run_config records timed_reveal but not legacy/semantic mode"},
            "timed_reveal": run_config.get("timed_reveal"),
            "before_timing_preserved": False,
            "storyboard_and_timed_storyboard_identical": (
                sha256_file(artifact_dir / "storyboard.json")
                == sha256_file(artifact_dir / "storyboard_timed.json")
            ),
            "runtime_sources": _runtime_sources(storyboard),
        },
        "renderer": {
            "candidate_system_id": candidate_manifest.get("candidate_system_id"),
            "deterministic_renderer": candidate_manifest.get("deterministic_renderer"),
            "llm_fallback_used": candidate_manifest.get("llm_fallback_used"),
            "requested_segment_render_modes": requested_modes,
            "theme": run_config.get("theme"),
            "browser": run_config.get("browser"),
            "fps": run_config.get("fps"),
        },
        "source": {
            "archived_case_path": str(source_case_dir),
            "source_locator": source_json.get("source_locator"),
            "source_document": source_json.get("source_document"),
            "normalized_text_sha256": source_json.get("normalized_text_sha256"),
        },
        "artifact_status_counts": counts,
        "missing_artifacts": [item["role"] for item in artifacts if item["status"] == STATUS_MISSING],
        "artifacts": artifacts,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze a research-only baseline case")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--source-case-dir", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--execution-dir", required=True)
    parser.add_argument("--output-root", required=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    path = freeze_case(
        case_id=args.case_id,
        workspace=args.workspace,
        source_case_dir=args.source_case_dir,
        artifact_dir=args.artifact_dir,
        execution_dir=args.execution_dir,
        output_root=args.output_root,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
