"""Reproducible, model-free B-track experiment and Pilot v1 dry-run runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .dynamic_planner import build_event_schedule_report
from .event_evaluator import evaluate_events
from .metrics import aggregate_event_reports
from .semantic_binding import build_binding_report
from .signaling_policy import audit_signaling_policy

RUNNER_VERSION = "b-track-local-runner-v0.1"


def _load(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {source}")
    return value


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _slug(value: Any) -> str:
    text = "".join(character.lower() if character.isalnum() else "-" for character in str(value))
    return "-".join(part for part in text.split("-") if part) or "case"


def _stable(case_slug: str, kind: str, suffix: str) -> str:
    return f"{case_slug}-{kind}-{_slug(suffix)}"


def _pilot_inputs(case_dir: Path) -> dict[str, Any]:
    """Adapt Pilot v1 candidates to neutral in-memory B-track inputs.

    The adapter does not write canonical v2 source artifacts and does not turn
    machine candidates into gold.  It exists solely to exercise interfaces on
    five already-rendered cases without calling a model.
    """
    segment_context = _load(case_dir / "segment_context.json")
    observations = _load(case_dir / "machine_observations.json")
    case_id = str(segment_context.get("case_id") or observations.get("case_id") or case_dir.name)
    case_slug = _slug(case_id)
    observed_by_segment = {
        str(item.get("segment_id")): item
        for item in observations.get("segments", []) or []
        if isinstance(item, dict)
    }

    script_segments: list[dict[str, Any]] = []
    storyboard_segments: list[dict[str, Any]] = []
    timed_segments: list[dict[str, Any]] = []
    compiled_segments: list[dict[str, Any]] = []
    trace_events: list[dict[str, Any]] = []
    proposition_count = 0

    for segment_position, context in enumerate(segment_context.get("segments", []) or [], start=1):
        if not isinstance(context, dict):
            continue
        legacy_segment_id = str(context.get("segment_id") or segment_position)
        segment_id = _stable(case_slug, "seg", f"{segment_position:03d}")
        narration_propositions: list[dict[str, Any]] = []
        for proposition_position, candidate in enumerate(
            context.get("proposition_candidates", []) or [], start=1
        ):
            if not isinstance(candidate, dict):
                continue
            proposition_count += 1
            proposition_id = _stable(
                case_slug,
                "nprop",
                f"s{segment_position:03d}-p{proposition_position:03d}",
            )
            kp_ids = []
            for link in candidate.get("candidate_knowledge_point_links", []) or []:
                if isinstance(link, dict) and link.get("knowledge_point_id"):
                    kp_ids.append(_stable(case_slug, "kprop", str(link["knowledge_point_id"])))
            narration_propositions.append(
                {
                    "id": proposition_id,
                    "knowledge_proposition_ids": kp_ids[:1]
                    or [_stable(case_slug, "kprop", "unknown")],
                    "text": str(candidate.get("candidate_text") or ""),
                    "candidate_start_sec": candidate.get("candidate_start_sec"),
                    "candidate_end_sec": candidate.get("candidate_end_sec"),
                    "candidate_status": "MACHINE_CANDIDATE_NOT_GOLD",
                }
            )
        script_segments.append(
            {
                "id": segment_id,
                "legacy_segment_id": legacy_segment_id,
                "narration_text": str(context.get("narration") or ""),
                "narration_propositions": narration_propositions,
            }
        )

        observed = observed_by_segment.get(legacy_segment_id, {})
        element_map: dict[str, str] = {}
        elements: list[dict[str, Any]] = []
        for element_position, original in enumerate(observed.get("elements", []) or [], start=1):
            if not isinstance(original, dict):
                continue
            legacy_element_id = str(original.get("id") or f"e{element_position}")
            element_id = _stable(segment_id, "el", f"{element_position:03d}")
            element_map[legacy_element_id] = element_id
            element = dict(original)
            element.update(
                {
                    "id": element_id,
                    "legacy_id": legacy_element_id,
                    "semantic_role": "explain",
                    "acquisition": "system-authored",
                }
            )
            elements.append(element)

        events: list[dict[str, Any]] = []
        scheduled_events: list[dict[str, Any]] = []
        compiled_events: list[dict[str, Any]] = []
        for event_position, runtime in enumerate(observed.get("runtime_events", []) or [], start=1):
            if not isinstance(runtime, dict):
                continue
            legacy_event_id = str(runtime.get("event_id") or f"event-{event_position}")
            event_id = _stable(segment_id, "evt", f"{event_position:03d}")
            legacy_target = str(runtime.get("target") or "")
            target_id = element_map.get(legacy_target, _stable(segment_id, "el", "unresolved"))
            plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
            actual = runtime.get("runtime") if isinstance(runtime.get("runtime"), dict) else {}
            action = str(plan.get("trigger") or "show")
            planned_ms = plan.get("compiled_start_ms")
            duration_ms = plan.get("duration_ms")
            events.append(
                {
                    "id": event_id,
                    "legacy_event_id": legacy_event_id,
                    "action": action,
                    "target_element_id": target_id,
                    "narration_proposition_ids": [],
                    "semantic_role": "content_reveal" if action == "show" else "signaling",
                }
            )
            trigger_sec = (
                float(planned_ms) / 1000.0 if isinstance(planned_ms, (int, float)) else None
            )
            scheduled_events.append(
                {
                    "event_id": event_id,
                    "target_element_id": target_id,
                    "action": action,
                    "trigger_at_sec": trigger_sec,
                    "planned_duration_sec": (
                        float(duration_ms) / 1000.0
                        if isinstance(duration_ms, (int, float))
                        else None
                    ),
                    "timing_source": "pilot_v1_compiled_plan_proxy",
                }
            )
            compiled_events.append(
                {
                    "event_id": event_id,
                    "target_element_id": target_id,
                    "action": action,
                    "start_ms": int(planned_ms) if isinstance(planned_ms, (int, float)) else 0,
                    "duration_ms": int(duration_ms) if isinstance(duration_ms, (int, float)) else 0,
                    "easing": str(plan.get("easing") or "unknown"),
                }
            )
            actual_ms = actual.get("actual_start_ms")
            runtime_status = str(runtime.get("runtime_status") or "skipped")
            trace_events.append(
                {
                    "event_id": event_id,
                    "slide": segment_position,
                    "target": target_id,
                    "target_resolved": bool(runtime.get("target_resolved")),
                    "executed": runtime_status == "executed",
                    "effect_realized": None,
                    "status": runtime_status
                    if runtime_status in {"executed", "degraded", "skipped", "error"}
                    else "error",
                    "planned": {
                        "trigger": action,
                        "effect": plan.get("effect"),
                        "start_ms": planned_ms,
                        "duration_ms": duration_ms,
                        "easing": plan.get("easing"),
                    },
                    "actual": (
                        {
                            "trigger": actual.get("trigger"),
                            "effect": actual.get("effect"),
                            "start_ms": actual_ms,
                            "duration_ms": actual.get("duration_ms"),
                            "easing": None,
                        }
                        if isinstance(actual_ms, (int, float))
                        else None
                    ),
                    "fallback": None,
                    "error_code": runtime.get("error_code"),
                    "message": runtime.get("message"),
                }
            )

        storyboard_segments.append(
            {
                "id": segment_id,
                "legacy_segment_id": legacy_segment_id,
                "elements": elements,
                "events": events,
            }
        )
        timed_segments.append(
            {
                "segment_id": segment_id,
                "audio_duration_sec": float(context.get("audio_duration_sec") or 0),
                "scheduled_events": scheduled_events,
            }
        )
        compiled_segments.append({"segment_id": segment_id, "events": compiled_events})

    return {
        "case_id": case_id,
        "script": {"case_id": case_id, "segments": script_segments},
        "storyboard": {"case_id": case_id, "segments": storyboard_segments},
        "timed": {"case_id": case_id, "segments": timed_segments},
        "compiled": {"case_id": case_id, "segments": compiled_segments},
        "trace": {
            "schema_version": "animation-trace-v0.1",
            "case_id": case_id,
            "lesson_id": case_id,
            "events": trace_events,
        },
        "render": {
            "case_id": case_id,
            "observations": [],
            "fact_status": "NO_FINAL_VIDEO_VISIBILITY_MEASUREMENT",
        },
        "adapter": {
            "name": "pilot-v1-to-b-track-v0.1",
            "proposition_count": proposition_count,
            "warning": (
                "Pilot proposition boundaries and KP links are machine candidates, not gold."
            ),
        },
    }


def _runtime_projection(evaluation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "runtime-comparison-v0.1",
        "report_type": "planned_compiled_runtime_comparison",
        "case_id": evaluation.get("case_id"),
        "events": [
            {
                key: row.get(key)
                for key in (
                    "event_id",
                    "segment_id",
                    "target_element_id",
                    "planned_start_sec",
                    "compiled_start_sec",
                    "runtime_start_sec",
                    "planned_to_compiled_delta_sec",
                    "compiled_to_runtime_delta_sec",
                    "target_resolved",
                    "target_match",
                    "runtime_status",
                )
            }
            for row in evaluation.get("events", []) or []
        ],
        "metrics": {
            key: evaluation.get("metrics", {}).get(key)
            for key in (
                "event_count",
                "compiled_coverage",
                "runtime_coverage",
                "target_resolution_rate",
                "planned_to_compiled_mae_sec",
                "compiled_to_runtime_mae_sec",
                "missing_runtime_count",
                "wrong_target_count",
            )
        },
        "warning": "Runtime execution evidence is not final-video visibility evidence.",
    }


def run_b_case(
    inputs: dict[str, Any],
    output_dir: str | Path,
    *,
    input_paths: list[Path] | None = None,
    repository_root: Path | None = None,
    threshold: float = 0.08,
) -> dict[str, Any]:
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"result bundle already exists: {output}")
    output.mkdir(parents=True)

    case_id = str(inputs["case_id"])
    binding = build_binding_report(
        inputs["script"],
        inputs["storyboard"],
        case_id=case_id,
        threshold=threshold,
    )
    schedule = build_event_schedule_report(
        inputs["script"],
        inputs["storyboard"],
        inputs["timed"],
        binding,
        case_id=case_id,
    )
    signaling = audit_signaling_policy(inputs["storyboard"], schedule)
    evaluation = evaluate_events(
        schedule,
        compiled_timeline=inputs.get("compiled"),
        runtime_trace=inputs.get("trace"),
        render_evidence=inputs.get("render"),
    )
    failures = [
        {"stage": stage, **failure}
        for stage, rows in (
            ("binding", binding.get("failures", [])),
            ("schedule", schedule.get("failures", [])),
            ("evaluation", evaluation.get("failures", [])),
        )
        for failure in rows
    ]
    metrics = {
        "schema_version": "b-track-case-metrics-v0.1",
        "case_id": case_id,
        "binding": binding["metrics"],
        "schedule": schedule["metrics"],
        "signaling": signaling["metrics"],
        "event_evaluation": evaluation["metrics"],
    }
    input_records = []
    for path in input_paths or []:
        input_records.append({"path": str(path), "sha256": _sha256(path)})
    root = repository_root or Path(__file__).resolve().parents[3]
    manifest = {
        "schema_version": "b-track-run-manifest-v0.1",
        "case_id": case_id,
        "runner_version": RUNNER_VERSION,
        "commit": _git_commit(root),
        "uses_external_model": False,
        "model": None,
        "threshold": threshold,
        "input_adapter": inputs.get("adapter"),
        "inputs": input_records,
        "outputs": [
            "binding_predictions.json",
            "event_schedule_predictions.json",
            "runtime_comparison.json",
            "rendered_evaluation.json",
            "signaling_audit.json",
            "metrics.json",
            "failures.json",
        ],
    }

    _write(output / "binding_predictions.json", binding)
    _write(output / "event_schedule_predictions.json", schedule)
    _write(output / "runtime_comparison.json", _runtime_projection(evaluation))
    _write(output / "rendered_evaluation.json", evaluation)
    _write(output / "signaling_audit.json", signaling)
    _write(output / "metrics.json", metrics)
    _write(output / "failures.json", {"case_id": case_id, "failures": failures})
    _write(output / "run_manifest.json", manifest)
    (output / "README.md").write_text(
        "\n".join(
            [
                f"# B-track result bundle: {case_id}",
                "",
                "This bundle was generated locally without an LLM/VLM.",
                "",
                "- Binding is a lexical/Jaccard baseline prediction, not gold.",
                "- Runtime trace proves browser execution only.",
                (
                    "- Render coverage remains zero unless final-video visibility "
                    "was independently observed."
                ),
                "- Machine proposition candidates are not formal annotation labels.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "case_id": case_id,
        "output_dir": str(output),
        "binding": binding,
        "schedule": schedule,
        "evaluation": evaluation,
        "failures": failures,
    }


def run_pilot_dry_run(
    pilot_root: str | Path,
    output_root: str | Path,
    *,
    case_ids: Sequence[str] | None = None,
    threshold: float = 0.08,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    pilot = Path(pilot_root)
    output = Path(output_root)
    if output.exists():
        raise FileExistsError(f"dry-run output already exists: {output}")
    available = sorted(path.name for path in (pilot / "cases").iterdir() if path.is_dir())
    selected = list(case_ids or available[:5])
    if not selected:
        raise ValueError("no Pilot cases selected")
    output.mkdir(parents=True)
    cases = []
    for case_id in selected:
        case_dir = pilot / "cases" / case_id
        if not case_dir.is_dir():
            raise FileNotFoundError(f"Pilot case not found: {case_dir}")
        input_paths = [
            case_dir / "segment_context.json",
            case_dir / "machine_observations.json",
            case_dir / "manifest.json",
        ]
        cases.append(
            run_b_case(
                _pilot_inputs(case_dir),
                output / "cases" / case_id / "result_bundle",
                input_paths=input_paths,
                repository_root=repository_root,
                threshold=threshold,
            )
        )

    aggregate = aggregate_event_reports([item["evaluation"] for item in cases])
    summary = {
        "schema_version": "b-track-dry-run-summary-v0.1",
        "runner_version": RUNNER_VERSION,
        "uses_external_model": False,
        "case_ids": selected,
        "case_count": len(cases),
        "metrics": {
            "proposition_count": sum(
                item["binding"]["metrics"]["proposition_count"] for item in cases
            ),
            "bound_count": sum(item["binding"]["metrics"]["bound_count"] for item in cases),
            "scheduled_event_count": sum(
                item["schedule"]["metrics"]["unique_event_count"] for item in cases
            ),
            "runtime_event_count": sum(
                item["evaluation"]["metrics"]["event_count"] for item in cases
            ),
            "render_observed_event_count": sum(
                round(
                    item["evaluation"]["metrics"]["render_coverage"]
                    * item["evaluation"]["metrics"]["event_count"]
                )
                if item["evaluation"]["metrics"]["render_coverage"] is not None
                else 0
                for item in cases
            ),
            "failure_count": sum(len(item["failures"]) for item in cases),
        },
        "limitations": [
            "Pilot proposition boundaries and KP links are machine candidates, not gold.",
            "Lexical binding is a local baseline, not the proposed semantic method.",
            "Pilot v1 has runtime traces but no measured final-video object visibility interval.",
            "No early/late semantic claim is made without acceptable-window gold.",
        ],
    }
    _write(output / "aggregate_metrics.json", aggregate)
    _write(output / "dry_run_summary.json", summary)
    (output / "README.md").write_text(
        "# B-track local dry run\n\n"
        "This run exercises interfaces and evidence separation only. "
        "It is not a formal experiment and used no LLM/VLM.\n",
        encoding="utf-8",
    )
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the model-free B-track Pilot v1 dry run")
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--threshold", type=float, default=0.08)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repository_root = Path(__file__).resolve().parents[3]
    summary = run_pilot_dry_run(
        args.pilot_root,
        args.output,
        case_ids=args.cases,
        threshold=args.threshold,
        repository_root=repository_root,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RUNNER_VERSION", "run_b_case", "run_pilot_dry_run"]
