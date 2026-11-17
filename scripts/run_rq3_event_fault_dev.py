"""One fixed-clip event fault diagnostic, reusing existing media/evidence tools."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path

import extract_rendered_video_evidence as frames
import run_rq2_auto_binding_video as auto
import run_rq2_native_timing as media

SAMPLES = (4.5, 6.5, 8.0, 9.5, 11.0, 12.5, 18.0, 20.8, 38.6)
CASES = {"c17": "late", "c42": "reference", "c06": "wrong_target", "c83": "missing", "c29": "early"}


def perturb(board, fault):
    result = copy.deepcopy(board)
    events = result["segments"][0]["animations"]
    selected = [e for e in events if e.get("event_id") == "p0-dynamic-n2-show"]
    if len(selected) != 1 or selected[0]["target"] != "v08":
        raise ValueError("Expected unique reference event absent")
    event = selected[0]
    if abs(event["trigger_at_sec"] - 8.701) > 0.001:
        raise ValueError("Reference timing changed")
    if fault == "early":
        event["trigger_at_sec"] -= 3
    elif fault == "late":
        event["trigger_at_sec"] += 3
    elif fault == "wrong_target":
        event["target"] = "v17"
    elif fault != "missing":
        raise ValueError("Unknown fault")
    result.setdefault("metadata", {})["development_fault_injection"] = fault
    return result


def prepare(source, out):
    auto.verify_inputs(source)
    auto.verify_predictions(source)
    media.verify(source)
    if out.exists():
        raise FileExistsError(out)
    compiled = media.read(source / "auto/compiled.json")
    if media.sha(compiled["html"]) != compiled["html_sha256"]:
        raise ValueError("Source HTML changed")
    expected = media.read(source / "evidence/summary.json")["auto"]
    if media.sha(source / "auto/voiced.mp4") != expected["video_sha256"]:
        raise ValueError("Source video changed")
    out.mkdir(parents=True)
    shutil.copytree(source / "audio", out / "audio")
    board = media.read(source / "auto/storyboard.json")
    media.write(out / "reference_storyboard.json", board)
    for case, fault in CASES.items():
        directory = out / case
        if fault == "reference":
            directory.mkdir()
            for name in ("storyboard.json", "voiced.mp4", "runtime.json", "silent.clock.json"):
                shutil.copy2(source / "auto" / name, directory / name)
            # Original HTML remains at its hash-verified source path.
            media.write(directory / "compiled.json", compiled)
        else:
            media.write(directory / "storyboard.json", perturb(board, fault))
    shutil.copy2(__file__, out / "runner_snapshot.py")
    media.write(
        out / "contract.json",
        {
            "source_run": str(source.resolve()),
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True
            ).strip(),
            "cases": CASES,
            "samples": SAMPLES,
            "source_video_sha256": expected["video_sha256"],
            "source_audio_sha256": media.sha(source / "audio/s1.wav"),
            "reference_event": "p0-dynamic-n2-show",
            "reference_target": "v08",
            "reference_time_sec": 8.701,
            "time_fault_sec": 3,
            "budget": {
                "external_model_calls": 0,
                "new_audio": 0,
                "recordings": 4,
                "automatic_retries": 0,
            },
            "claim": "Known deviations from frozen plan; "
            "not semantic gold or general detector accuracy.",
        },
    )
    media.write(
        out / "inputs.json",
        {
            "duration_sec": board["segments"][0]["audio_duration_sec"],
            "files": {
                p.relative_to(out).as_posix(): media.sha(p) for p in out.rglob("*") if p.is_file()
            },
        },
    )


def render(out):
    from textbook2video.animation_gen import build_slide_timelines, generate

    media.verify(out)
    if (out / "render_manifest.json").exists():
        raise FileExistsError("Compilation already frozen")
    with (out / "render.attempt").open("x") as handle:
        handle.write("Single preparation attempt; preserve partial failures.\n")
    frozen = {}
    for case, fault in CASES.items():
        if fault == "reference":
            continue
        directory = out / case
        html = generate(
            directory / "storyboard.json",
            output_dir=directory / "render",
            theme_id="bright",
            skip_image_gen=True,
            visual_tools_enabled=False,
            layout_repair_attempts=0,
        )
        if fault == "missing":
            text = html.read_text(encoding="utf-8")
            if text.count("</head>") != 1:
                raise ValueError("Cannot attach controlled rendering fault")
            text = text.replace(
                "</head>", '<style>[data-anim-id="v08"]{visibility:hidden!important}</style></head>'
            )
            html.write_text(text, encoding="utf-8")
        media.write(
            directory / "compiled.json",
            {
                "events": build_slide_timelines(
                    media.read(directory / "storyboard.json")["segments"]
                )[0],
                "html": str(html.resolve()),
                "html_sha256": media.sha(html),
            },
        )
        for path in directory.rglob("*"):
            if path.is_file():
                frozen[path.relative_to(out).as_posix()] = media.sha(path)
    media.write(out / "render_manifest.json", frozen)


def verify_render(out):
    media.verify(out)
    for name, digest in media.read(out / "render_manifest.json").items():
        if media.sha(out / name) != digest:
            raise ValueError(f"Compiled input changed: {name}")


def record(out):
    verify_render(out)
    for case, fault in CASES.items():
        if fault == "reference":
            continue
        with (out / case / "recording.attempt").open("x") as handle:
            handle.write("One attempt; never resume or repeat this diagnostic run.\n")
        media.record(out, case)


def extract(out, destination, ffmpeg, ffprobe):
    verify_render(out)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    packet = {}
    for case in sorted(CASES):
        directory = out / case
        clock = media.read(directory / "silent.clock.json")
        if clock["status"] != "CALIBRATED":
            raise ValueError("Uncalibrated media")
        video = directory / "voiced.mp4"
        data = json.loads(
            subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "frame=best_effort_timestamp_time",
                    "-of",
                    "json",
                    str(video),
                ]
            )
        )
        times = [float(f["best_effort_timestamp_time"]) for f in data["frames"]]
        windows = [
            frames.window(
                f"lesson={t}",
                min(times, key=lambda p: abs(p - times[0] - t)),
                0.0005,
                requested_lesson_sec=t,
            )
            for t in SAMPLES
        ]
        target = destination / case
        target.mkdir()
        rows = frames.extract(video, windows, target, ffmpeg=ffmpeg)
        if frames.missing_samples(windows, rows):
            raise ValueError("Sampling incomplete")
        frames.contact_sheets(rows, target, "msedge")
        packet[case] = {
            "sheets": [str(p.resolve()) for p in sorted(target.glob("sheet-*.png"))],
            "frames": rows,
        }
    media.write(
        destination / "packet.json",
        {
            "claim": "Blind pixel observations only; "
            "do not inspect schedules or injection mapping.",
            "cases": packet,
        },
    )


def classify(observations):
    required = [
        ("6.5", "entropy"),
        ("9.5", "entropy"),
        ("9.5", "reconstruction"),
        ("12.5", "entropy"),
        ("18.0", "entropy"),
    ]
    if any(type(observations.get(t, {}).get(k)) is not bool for t, k in required):
        return "unobservable"

    def at(t, k="entropy"):
        return observations[t][k]

    if at("6.5"):
        return "early"
    if not at("9.5") and at("9.5", "reconstruction"):
        return "wrong_target"
    if not at("9.5") and at("12.5"):
        return "late"
    if not any(at(t) for t in ("9.5", "12.5", "18.0")):
        return "missing_in_sampled_window"
    if at("9.5") and not at("9.5", "reconstruction"):
        return "reference_checkpoints_consistent"
    return "unobservable"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "render", "record", "extract"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-run", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args()
    media.offline()
    out = args.output.resolve()
    if args.command == "prepare":
        if args.from_run is None:
            parser.error("prepare requires --from-run")
        prepare(args.from_run.resolve(), out)
    elif args.command == "render":
        render(out)
    elif args.command == "record":
        record(out)
    else:
        if not all((args.evidence, args.ffmpeg, args.ffprobe)):
            parser.error("extract requires --evidence --ffmpeg --ffprobe")
        extract(out, args.evidence.resolve(), args.ffmpeg, args.ffprobe)
