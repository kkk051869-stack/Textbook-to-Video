"""Consume saved binding predictions using existing timing/render/media modules.

No planner, binding or Judge requests are issued by this script. Comparison
outputs remain immutable. MP4 frames are evidence inputs, never auto-reviewed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
MODES = ("legacy", "semantic", "simple_rule", "proposition_aware", "without_signaling")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def offline():
    # Browser localhost traffic is permitted; model transport is not.
    import httpx

    from textbook2video.llm import client

    def forbidden(*args, **kwargs):
        raise RuntimeError("Model/HTTP requests forbidden in saved-prediction media stage")

    httpx.Client.send = forbidden
    httpx.AsyncClient.send = forbidden
    client.chat_with_system = forbidden
    client.chat_with_images = forbidden


def groups(package):
    import run_rq2_binding_dev as runner

    runner.verify(package)
    result = {}
    for task in read(package / "inputs/tasks.json"):
        result.setdefault(task["document_id"], []).append(task)
    return result


def verify_audio(directory, tasks, doc):
    manifest = read(directory / "manifest.json")
    for rel, digest in manifest["files"].items():
        if sha(directory / rel) != digest:
            raise ValueError(f"Audio hash drift: {rel}")
    cues = read(directory / "sentence_cues.json")["segments"]
    if len(cues) != 1 or str(cues[0]["segment_id"]) != doc:
        raise ValueError("Audio document mapping mismatch")
    group = cues[0]
    if [c["text"] for c in group["cues"]] != [t["proposition"]["text"] for t in tasks]:
        raise ValueError("Measured audio does not match complete frozen narration")
    return group


def prepare_audio(package, output):
    from textbook2video.pipeline.narrator import generate_sentence_audio

    output.mkdir(parents=True, exist_ok=True)
    contract = {
        "runner_sha256": sha(Path(__file__)),
        "binding_protocol_sha256": sha(package / "protocol.json"),
        "modes": list(MODES),
        "audio_backend": "sapi",
        "voice": "Microsoft Zira Desktop",
    }
    contract_path = output / "media-execution-contract.json"
    if contract_path.exists():
        previous = read(contract_path)
        if any(
            previous.get(k) != contract[k]
            for k in ("binding_protocol_sha256", "audio_backend", "voice")
        ):
            raise ValueError(
                "Audio source or voice changed; preserve output and use a new directory"
            )
    else:
        write(contract_path, contract)
    for doc, tasks in groups(package).items():
        directory = output / "audio" / doc
        if directory.exists():
            verify_audio(directory, tasks, doc)
            continue
        directory.mkdir(parents=True)
        try:
            generate_sentence_audio(
                [[t["proposition"]["text"] for t in tasks]],
                output_dir=directory,
                backend="sapi",
                segment_ids=[doc],
                voice="Microsoft Zira Desktop",
                rate="+0%",
            )
            write(
                directory / "manifest.json",
                {
                    "files": {
                        p.relative_to(directory).as_posix(): sha(p)
                        for p in directory.rglob("*")
                        if p.is_file()
                    },
                    "proposition_ids": [t["id"] for t in tasks],
                    "producer": "existing_generate_sentence_audio_sapi",
                },
            )
            verify_audio(directory, tasks, doc)
        except Exception as exc:
            write(directory / "failure.json", {"error": str(exc), "retry": False})
            raise


def condition_inputs(tasks, results, audio, method):
    """Pure adapter: never infer a better target than the saved prediction."""
    from textbook2video.pipeline.timing import build_segment_timing
    from textbook2video.research.dynamic_planner import plan_dynamic_events

    doc = tasks[0]["document_id"]
    if len(tasks) != len(audio["cues"]):
        raise ValueError("Incomplete measured audio")
    candidates = {c["id"]: c for t in tasks for c in t["candidates"]}
    props, predictions, selected = [], [], []
    for task, cue in zip(tasks, audio["cues"], strict=True):
        if cue["text"] != task["proposition"]["text"]:
            raise ValueError("Sentence/audio mapping mismatch")
        if cue["end_sec"] <= cue["start_sec"] or cue["end_sec"] > audio["duration_sec"] + 0.002:
            raise ValueError("Invalid measured cue interval")
        if task["id"] not in results or method not in results[task["id"]]:
            raise ValueError(f"Missing actual prediction: {task['id']}/{method}")
        prediction = copy.deepcopy(results[task["id"]][method])
        prediction.update(proposition_id=task["id"], segment_id=doc)
        target = prediction.get("selected_candidate_id")
        if prediction.get("status") == "BOUND":
            if target not in {c["id"] for c in task["candidates"]}:
                raise ValueError(f"Unknown predicted target: {target}")
            if target not in selected:
                selected.append(target)
        elif target is not None:
            raise ValueError("Unbound/invalid prediction must not imply a rendered target")
        predictions.append(prediction)
        props.append(
            {
                **task["proposition"],
                "id": task["id"],
                "segment_id": doc,
                "start_sec": cue["start_sec"],
                "end_sec": cue["end_sec"],
            }
        )
    narration = " ".join(t["proposition"]["text"] for t in tasks)
    elements = [
        {"id": "heading", "type": "heading", "text": doc},
        {"id": "narration", "type": "text", "text": narration},
    ]
    for ident in selected:
        c = candidates[ident]
        elements.append(
            {
                "id": ident,
                "type": "image",
                "src": ident + ".png",
                "caption": c["text"],
                "description": c["text"],
                "source_refs": c.get("source_refs", []),
                "sha256": c["sha256"],
            }
        )
    segment = {
        "id": doc,
        "narration": narration,
        "visual_type": "mixed",
        "audio_duration_sec": audio["duration_sec"],
        "elements": elements,
        "visual_timing_rebuild": {"page_strategy": "preserve-components-with-acquisition"},
    }
    dynamic = plan_dynamic_events(
        propositions=props, bindings=predictions, segment_durations={doc: audio["duration_sec"]}
    )
    boards = {}
    for mode in MODES:
        page = copy.deepcopy(segment)
        fixed = [
            {"target": key, "action": "show", "effect": "fadeIn", "trigger_at_sec": 0}
            for key in ("heading", "narration")
        ]
        if mode in ("legacy", "semantic"):
            # Structural text is shared, while only predicted visual targets vary.
            visual = {**page, "elements": [e for e in elements if e["id"] in selected]}
            fixed += build_segment_timing(visual, {"segments": [audio]}, timing_mode=mode)
        elif mode == "simple_rule":
            fixed += [
                {
                    "target": target,
                    "action": "show",
                    "effect": "fadeIn",
                    "trigger_at_sec": i * audio["duration_sec"] / len(selected),
                }
                for i, target in enumerate(selected)
            ]
        page["animations"] = fixed
        boards[mode] = {
            "lesson_title": doc,
            "segments": [page],
            "metadata": {
                "selected_binding_method": method,
                "prediction_origin": "SAVED_ACTUAL_OUTPUT",
                "unselected_candidates": sorted(set(candidates) - set(selected)),
                "source_figure_context_not_rendered": True,
                "claim": "Cropped object presentation; not a complete source-figure reconstruction",
            },
        }
    return boards, dynamic, props, predictions


def require_completed_comparison(package, method):
    if read(package / "run-01/execution.json").get("status") != "COMPLETE":
        raise ValueError("A completed actual comparison is required")
    if not (package / "run-01/output_manifest.json").is_file():
        raise ValueError("Actual prediction output manifest required")
    if method not in read(package / "protocol.json")["methods"]:
        raise ValueError("Method was not part of the frozen comparison")


def prepare_conditions(package, output, method, only_doc=None):
    from textbook2video.research.p0_integration import P0IntegrationPaths, apply_p0_event_schedule

    require_completed_comparison(package, method)
    for doc, tasks in groups(package).items():
        if only_doc is not None and doc != only_doc:
            continue
        directory = output / doc
        if directory.exists():
            raise FileExistsError(f"Preserve existing media attempt: {directory}")
        audio = verify_audio(output / "audio" / doc, tasks, doc)
        results = {t["id"]: read(package / "run-01/bindings" / (t["id"] + ".json")) for t in tasks}
        boards, dynamic, props, predictions = condition_inputs(tasks, results, audio, method)
        directory.mkdir(parents=True)
        write(directory / "actual-predictions.json", predictions)
        write(directory / "dynamic-plan.json", dynamic)
        write(directory / "measured-propositions.json", props)
        candidates = {c["id"]: c for t in tasks for c in t["candidates"]}
        for mode, board in boards.items():
            mode_dir = directory / mode
            for element in board["segments"][0]["elements"]:
                if element["type"] != "image":
                    continue
                candidate = candidates[element["id"]]
                source = package / candidate["local_path"]
                if sha(source) != candidate["sha256"]:
                    raise ValueError("Predicted candidate pixel hash drift")
                target = mode_dir / "images" / element["src"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            path = mode_dir / "storyboard.json"
            write(path, board)
            if mode in ("proposition_aware", "without_signaling"):
                events = [{**e, "effect": e.get("effect", "fadeIn")} for e in dynamic["events"]]
                if mode == "without_signaling":
                    events = [e for e in events if e["action"] != "focus"]
                sidecar = mode_dir / "p0_sidecar.json"
                write(
                    sidecar,
                    {
                        "schema_version": "p0-production-sidecar-v0.1",
                        "propositions": props,
                        "events": events,
                    },
                )
                apply_p0_event_schedule(
                    P0IntegrationPaths(path, path, sidecar),
                    sentence_cues=read(output / "audio" / doc / "sentence_cues.json"),
                )
            final = read(path)
            for collection in ("timeline", "animations"):
                for i, event in enumerate(final["segments"][0].get(collection, [])):
                    event["event_id"] = (
                        event.get("research_p0", {}).get("event_id") or f"{mode}-{i}"
                    )
            write(path, final)
        shutil.copy2(Path(__file__), directory / "runner_snapshot.py")
        write(
            directory / "inputs.json",
            {
                "files": {
                    p.relative_to(directory).as_posix(): sha(p)
                    for p in directory.rglob("*")
                    if p.is_file()
                },
                "audio_manifest_sha256": sha(output / "audio" / doc / "manifest.json"),
                "prediction_files": {
                    t["id"]: sha(package / "run-01/bindings" / (t["id"] + ".json")) for t in tasks
                },
                "method": method,
                "modes": list(MODES),
                "media_runner_sha256": sha(Path(__file__)),
            },
        )


def verify_case(package, output, doc):
    contract = read(output / "media-execution-contract.json")
    if contract["binding_protocol_sha256"] != sha(package / "protocol.json"):
        raise ValueError("Binding protocol changed")
    manifest = read(output / doc / "inputs.json")
    if manifest["media_runner_sha256"] != sha(Path(__file__)):
        raise ValueError("Media implementation changed after condition preparation")
    for rel, digest in manifest["files"].items():
        if sha(output / doc / rel) != digest:
            raise ValueError(f"Frozen media input changed: {rel}")
    if sha(output / "audio" / doc / "manifest.json") != manifest["audio_manifest_sha256"]:
        raise ValueError("Audio manifest changed")
    for ident, digest in manifest["prediction_files"].items():
        if sha(package / "run-01/bindings" / (ident + ".json")) != digest:
            raise ValueError("Saved predictions changed")
    tasks = groups(package)[doc]
    return verify_audio(output / "audio" / doc, tasks, doc)


def render_case(package, output, doc, browser):
    from textbook2video.animation_gen import build_slide_timelines, generate
    from textbook2video.pipeline.visual_page_render import select_local_page_layout

    verify_case(package, output, doc)
    selected = None
    reference_elements = None
    for mode in MODES:
        directory = output / doc / mode
        board = read(directory / "storyboard.json")
        page = board["segments"][0]
        images = {
            f"{doc}:{e['id']}": str(directory / "images" / e["src"])
            for e in page["elements"]
            if e["type"] == "image"
        }
        if selected is None:
            selected = select_local_page_layout(
                page, images, output_dir=directory / "layout", theme="bright", browser=browser
            )
            reference_elements = copy.deepcopy(page["elements"])
        elif page["elements"] != reference_elements:
            raise ValueError("Conditions changed content; shared layout validation is invalid")
        page.update(
            {k: selected[k] for k in ("local_visual_layout", "local_visual_compact_spacing")}
        )
        # Derived layout board preserves all original semantic/event data.
        render_board = directory / "render-storyboard.json"
        write(render_board, board)
        html = generate(
            render_board,
            output_dir=directory / "render",
            theme_id="bright",
            skip_image_gen=True,
            visual_tools_enabled=False,
            layout_repair_attempts=0,
            layout_browser_channel=browser,
        )
        write(
            directory / "compiled.json",
            {
                "html": str(Path(html).resolve()),
                "html_sha256": sha(html),
                "events": build_slide_timelines(board["segments"])[0],
                "render_board_sha256": sha(render_board),
            },
        )


def record_case(package, output, doc, mode):
    from textbook2video.pipeline.compose import compose_video
    from textbook2video.pipeline.recorder import record_html_to_video
    from textbook2video.pipeline.subtitles import generate_srt

    audio = verify_case(package, output, doc)
    directory = output / doc / mode
    compiled = read(directory / "compiled.json")
    if sha(compiled["html"]) != compiled["html_sha256"]:
        raise ValueError("Compiled HTML changed")
    if sha(directory / "render-storyboard.json") != compiled["render_board_sha256"]:
        raise ValueError("Rendered storyboard changed")
    silent = directory / "silent.mp4"
    if silent.exists() or silent.with_suffix(".clock.json").exists():
        raise FileExistsError("Recording already attempted; preserve failure")
    record_html_to_video(
        compiled["html"],
        str(silent),
        duration=audio["duration_sec"],
        fps=30,
        viewport_width=1600,
        viewport_height=900,
        trace_path=str(directory / "runtime.json"),
    )
    subtitle = generate_srt(
        directory / "render-storyboard.json",
        directory / "subtitles.srt",
        sentence_cues=read(output / "audio" / doc / "sentence_cues.json"),
        max_chars=90,
    )
    compose_video(silent, output / "audio" / doc, directory / "voiced.mp4", subtitle_path=subtitle)
    extract_evidence(directory, compiled, audio["duration_sec"])


def extract_evidence(directory, compiled, duration):
    from textbook2video.pipeline.compose import _ffmpeg_executable

    ffmpeg = _ffmpeg_executable()
    video = directory / "voiced.mp4"
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(video), "-f", "null", "-"], capture_output=True, text=True
    )
    write(directory / "decode.json", {"returncode": decoded.returncode, "stderr": decoded.stderr})
    if decoded.returncode:
        raise ValueError("Final MP4 decoding failed; evidence preserved")
    records = []
    frames = directory / "frames"
    frames.mkdir(exist_ok=False)
    for i, event in enumerate(compiled["events"]):
        onset = event["start_ms"] / 1000
        for phase, offset in [("before", -0.15), ("onset", 0), ("after", 0.65)]:
            at = max(0, min(onset + offset, max(0, duration - 0.05)))
            target = frames / f"{i:03d}-{phase}.png"
            subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    str(at),
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    str(target),
                ],
                check=True,
                capture_output=True,
            )
            if not target.is_file():
                raise ValueError("Expected MP4 evidence frame not produced")
            records.append(
                {
                    "event_id": event["event_id"],
                    "target": event["target"],
                    "compiled_action": event["action"],
                    "requested_action": event.get("requested_action"),
                    "time_sec": at,
                    "phase": phase,
                    "path": str(target.resolve()),
                    "sha256": sha(target),
                    "visibility_verdict": "NOT_REVIEWED",
                }
            )
    write(
        directory / "frame-index.json",
        {
            "frames": records,
            "video_sha256": sha(video),
            "claim": "Frames are unreviewed; requested times are not observed object onsets.",
        },
    )


def report(package, output, rq1_package=None):
    rows = []
    for doc, tasks in groups(package).items():
        for mode in MODES:
            directory = output / doc / mode
            row = {
                "document_id": doc,
                "condition": mode,
                "proposition_ids": [t["id"] for t in tasks],
                "video_visibility_review": "NOT_REVIEWED",
                "audio_continuous_review": "NOT_REVIEWED",
            }
            for key, path in {
                "predictions": output / doc / "actual-predictions.json",
                "measured_propositions": output / doc / "measured-propositions.json",
                "planned": directory / "storyboard.json",
                "compiled": directory / "compiled.json",
                "runtime": directory / "runtime.json",
                "clock": directory / "silent.clock.json",
                "mp4": directory / "voiced.mp4",
                "frames": directory / "frame-index.json",
                "decode": directory / "decode.json",
                "audio": output / "audio" / doc / "manifest.json",
                "binding_judge_report": package / "run-01/report.json",
            }.items():
                row[key] = (
                    {"path": str(path.resolve()), "sha256": sha(path)} if path.is_file() else None
                )
            if row["mp4"]:
                probe_tool = os.environ.get("T2V_FFPROBE") or shutil.which("ffprobe")
                if not probe_tool:
                    raise RuntimeError("ffprobe unavailable")
                probe = subprocess.run(
                    [
                        probe_tool,
                        "-v",
                        "error",
                        "-show_format",
                        "-show_streams",
                        "-of",
                        "json",
                        str(directory / "voiced.mp4"),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                write(directory / "ffprobe.json", json.loads(probe.stdout))
            rows.append(row)
    write(
        output / "evidence-index.json",
        {
            "cases": rows,
            "rq1_report": (
                {
                    "path": str((rq1_package / "run-01/report.json").resolve()),
                    "sha256": sha(rq1_package / "run-01/report.json"),
                }
                if rq1_package and (rq1_package / "run-01/report.json").is_file()
                else None
            ),
            "new_model_calls": 0,
            "claim": "Evidence links are not semantic or final-video visibility verdicts.",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audio", "prepare", "render", "record", "report"])
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rq1-package-root", type=Path)
    parser.add_argument("--method", default="source_conditioned_context")
    parser.add_argument("--document")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--browser", default="msedge")
    args = parser.parse_args()
    offline()
    package, out = args.package_root.resolve(), args.output.resolve()
    if args.command == "audio":
        prepare_audio(package, out)
    elif args.command in ("prepare", "render"):
        failures = []
        for doc in [args.document] if args.document else groups(package):
            try:
                if args.command == "prepare":
                    prepare_conditions(package, out, args.method, only_doc=doc)
                else:
                    render_case(package, out, doc, args.browser)
            except Exception as exc:
                failure = {
                    "document_id": doc,
                    "stage": args.command,
                    "error": str(exc),
                    "retry": False,
                }
                failures.append(failure)
                write(out / "failures" / f"{args.command}-{doc}.json", failure)
        if failures:
            report(package, out)
            raise RuntimeError(
                f"{len(failures)} case(s) failed; independent cases processed, evidence preserved"
            )
    elif args.command == "record":
        if not args.document or not args.mode:
            parser.error("record requires --document and --mode; one explicit attempt")
        try:
            record_case(package, out, args.document, args.mode)
        except Exception as exc:
            write(
                out / "failures" / f"record-{args.document}-{args.mode}.json",
                {
                    "document_id": args.document,
                    "condition": args.mode,
                    "stage": "record",
                    "error": str(exc),
                    "retry": False,
                },
            )
            report(package, out, args.rq1_package_root)
            raise
    report(package, out, args.rq1_package_root)


if __name__ == "__main__":
    main()
