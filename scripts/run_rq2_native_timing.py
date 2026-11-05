"""Source-grounded native-component timing control; no model requests.

Bindings are explicit experimental controls, not method predictions or gold.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def offline():
    import httpx

    def forbidden(*args, **kwargs):
        raise RuntimeError("Model/HTTP transport forbidden in offline timing control")

    httpx.Client.send = forbidden
    httpx.AsyncClient.send = forbidden


def prepare(out, reuse_audio=None):
    import pymupdf

    from textbook2video.pipeline.narrator import generate_sentence_audio
    from textbook2video.pipeline.timing import build_segment_timing
    from textbook2video.research.dynamic_planner import plan_dynamic_events
    from textbook2video.research.p0_integration import P0IntegrationPaths, apply_p0_event_schedule

    if out.exists():
        raise FileExistsError(out)
    source = Path("D:/Code/vibe coding/datasets/Doc2Present") / (
        "DVC An End-to-end Deep Video Compression Framework.pdf"
    )
    expected = "dbbb939fe2a167419b60aa8dc4326c8439b531684ecd6b7e91d150e807d4ba3e"
    if sha(source) != expected:
        raise ValueError("Frozen PDF hash mismatch")
    out.mkdir(parents=True)
    with pymupdf.open(source) as pdf:
        raw = pdf[2].get_text()
    # Exact PDF extraction, except layout whitespace and line-end hyphenation.
    import re

    text = re.sub(r"(?<=\w)-\n(?=\w)", "", raw)
    text = re.sub(r"\s+", " ", text)
    titles = ["Motion estimation", "Motion compensation", "Transform and quantization"]
    groups = []
    spans = []
    for i in range(1, 4):
        start = text.index(f"Step {i}.", text.index("3.1. Brief"))
        end = text.index(f"Step {i + 1}.", start)
        spans.append([start, end])
        groups.append(text[start:end].strip())
    write(
        out / "source.json",
        {
            "pdf": str(source),
            "sha256": expected,
            "page": 3,
            "raw_text": raw,
            "normalized_text": text,
            "step_spans": spans,
            "claim": "Traditional encoder steps, not DVC-specific deep-network stages",
        },
    )
    if reuse_audio is not None:
        saved = read(reuse_audio / "sentence_cues.json")
        if (
            len(saved["segments"]) != 1
            or [c["text"] for c in saved["segments"][0]["cues"]] != groups
        ):
            raise ValueError("Reusable audio narration does not match source steps")
        shutil.copytree(reuse_audio, out / "audio")
        audio = {"segments": saved["segments"]}
    else:
        audio = generate_sentence_audio(
            [groups],
            output_dir=out / "audio",
            backend="sapi",
            segment_ids=["dvc-steps"],
            voice="en-US",
            rate="+0%",
        )
    duration = round(audio["segments"][0]["duration_sec"] + 1, 3)
    segment = {
        "id": "dvc-steps",
        "narration": " ".join(groups),
        "audio_duration_sec": duration,
        "visual_type": "process",
        "elements": [
            {"id": "heading", "type": "heading", "text": "Traditional video encoding: steps 1–3"}
        ]
        + [
            {
                "id": f"dvc-step-{i}",
                "type": "highlight_box",
                "text": f"Step {i}: {title}",
                "source_refs": [f"pdf-page3-step{i}"],
                "source_quote": groups[i - 1],
            }
            for i, title in enumerate(titles, 1)
        ],
    }
    storyboard = {
        "lesson_title": "RQ2 source-grounded timing control",
        "segments": [segment],
        "metadata": {
            "total_slides": 1,
            "research_control": (
                "Source-grounded authored controls; not binding predictions, "
                "not human gold; no paper figure pixels"
            ),
        },
    }
    props, bindings = [], []
    for i, cue in enumerate(audio["segments"][0]["cues"], 1):
        props.append(
            {
                "id": f"p{i}",
                "segment_id": "dvc-steps",
                "text": groups[i - 1],
                "start_sec": cue["start_sec"],
                "end_sec": cue["end_sec"],
                "source_refs": [f"pdf-page3-step{i}"],
            }
        )
        bindings.append(
            {
                "proposition_id": f"p{i}",
                "segment_id": "dvc-steps",
                "selected_candidate_id": f"dvc-step-{i}",
                "status": "BOUND",
                "score": 1,
                "confidence": 1,
                "method": "AUTHORED_TIMING_CONTROL_NOT_PREDICTION",
            }
        )
    plan = plan_dynamic_events(
        propositions=props, bindings=bindings, segment_durations={"dvc-steps": duration}
    )
    write(out / "dynamic_plan.json", plan)
    write(
        out / "controls.json",
        {
            "propositions": props,
            "bindings": bindings,
            "claim": "Controlled timing inputs, not evidence of binding method accuracy",
        },
    )
    for mode in ("legacy", "simple_rule", "proposition_aware"):
        directory = out / mode
        directory.mkdir()
        candidate = copy.deepcopy(storyboard)
        local = candidate["segments"][0]
        if mode == "legacy":
            local["animations"] = build_segment_timing(local, timing_mode="legacy")
        else:
            local["animations"] = [
                {"target": "heading", "action": "show", "effect": "fadeInUp", "trigger_at_sec": 0}
            ]
            if mode == "simple_rule":
                local["animations"] += [
                    {
                        "target": f"dvc-step-{i + 1}",
                        "action": "show",
                        "effect": "fadeInUp",
                        "trigger_at_sec": round(i * audio["segments"][0]["duration_sec"] / 3, 3),
                    }
                    for i in range(3)
                ]
        path = directory / "storyboard.json"
        write(path, candidate)
        if mode == "proposition_aware":
            events = [
                {**event, "effect": event.get("effect", "fadeIn")} for event in plan["events"]
            ]
            sidecar = directory / "p0_sidecar.json"
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
                sentence_cues=read(out / "audio/sentence_cues.json"),
            )
        # Bind existing compiler IDs to condition-specific source events explicitly.
        candidate = read(path)
        seg = candidate["segments"][0]
        for collection in ("animations", "timeline"):
            for i, event in enumerate(seg.get(collection, [])):
                event["event_id"] = (
                    event.get("research_p0", {}).get("event_id") or f"{mode}-{event['target']}-{i}"
                )
        write(path, candidate)
    shutil.copy2(__file__, out / "runner_snapshot.py")
    write(
        out / "inputs.json",
        {
            "duration_sec": duration,
            "source_sha256": expected,
            "files": {p.relative_to(out).as_posix(): sha(p) for p in out.rglob("*") if p.is_file()},
            "new_llm_calls": 0,
            "new_vlm_calls": 0,
            "new_image_calls": 0,
            "local_sapi_utterances": 0 if reuse_audio else 3,
            "reused_audio_source": str(reuse_audio.resolve()) if reuse_audio else None,
        },
    )


def verify(out):
    manifest = read(out / "inputs.json")
    for name, digest in manifest["files"].items():
        if sha(out / name) != digest:
            raise ValueError(f"Frozen input changed: {name}")
    return manifest


def render(out):
    from textbook2video.animation_gen import build_slide_timelines, generate

    for mode in ("legacy", "simple_rule", "proposition_aware"):
        directory = out / mode
        candidate = read(directory / "storyboard.json")
        html = generate(
            directory / "storyboard.json",
            output_dir=directory / "render",
            theme_id="bright",
            skip_image_gen=True,
            visual_tools_enabled=False,
            layout_repair_attempts=0,
        )
        write(
            directory / "compiled.json",
            {
                "events": build_slide_timelines(candidate["segments"])[0],
                "html": str(html.resolve()),
                "html_sha256": sha(html),
            },
        )


def record(out, mode):
    from textbook2video.pipeline.compose import compose_video
    from textbook2video.pipeline.recorder import record_html_to_video
    from textbook2video.pipeline.subtitles import generate_srt

    manifest = verify(out)
    directory = out / mode
    compiled = read(directory / "compiled.json")
    if sha(compiled["html"]) != compiled["html_sha256"]:
        raise ValueError("HTML changed since compilation")
    silent = directory / "silent.mp4"
    if silent.exists() or silent.with_suffix(".clock.json").exists():
        raise FileExistsError("Recording already attempted; preserve evidence")
    record_html_to_video(
        compiled["html"],
        str(silent),
        duration=manifest["duration_sec"],
        fps=15,
        viewport_width=1600,
        viewport_height=900,
        trace_path=str(directory / "runtime.json"),
    )
    subtitles = generate_srt(
        directory / "storyboard.json",
        directory / "subtitles.srt",
        sentence_cues=read(out / "audio/sentence_cues.json"),
        max_chars=90,
    )
    compose_video(silent, out / "audio", directory / "voiced.mp4", subtitle_path=subtitles)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "render", "record"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-audio", type=Path)
    parser.add_argument("--mode", choices=["legacy", "simple_rule", "proposition_aware"])
    args = parser.parse_args()
    offline()
    args.output = args.output.resolve()
    if args.command == "prepare":
        prepare(args.output, args.reuse_audio)
    elif args.command == "render":
        verify(args.output)
        render(args.output)
    else:
        if not args.mode:
            parser.error("record requires --mode")
        record(args.output, args.mode)
