"""Freeze three timing conditions from one saved automatic run; no model or TTS."""

from __future__ import annotations

import argparse
import copy
import shutil
from pathlib import Path

import run_rq2_auto_binding_video as auto
import run_rq2_native_timing as media

from textbook2video.pipeline.timing import build_segment_timing


def prepare(source: Path, out: Path):
    auto.verify_inputs(source)
    auto.verify_predictions(source)
    media.verify(source)
    if out.exists():
        raise FileExistsError(out)
    board = media.read(source / "auto/storyboard.json")
    props = media.read(source / "graph.json")["narration_propositions"]
    predictions = media.read(source / "run/predictions.json")
    if len(predictions) != len(props) or {p["id"] for p in props} != {
        p["proposition_id"] for p in predictions
    }:
        raise ValueError("Incomplete prediction coverage")
    selected = {p["selected_candidate_id"] for p in predictions if p["status"] == "BOUND"}
    segment = board["segments"][0]
    objects = [e for e in segment["elements"] if e["id"] != "heading"]
    if not selected or selected != {e["id"] for e in objects}:
        raise ValueError("Page objects differ from actual selected predictions")
    if segment["narration"] != " ".join(p["text"] for p in props):
        raise ValueError("Narration changed")
    cues = media.read(source / "audio/sentence_cues.json")["segments"][0]
    if [c["text"] for c in cues["cues"]] != [p["text"] for p in props]:
        raise ValueError("Measured audio does not match complete narration")
    out.mkdir(parents=True)
    shutil.copytree(source / "audio", out / "audio")
    for name in (
        "graph.json",
        "candidates.json",
        "dynamic_plan.json",
        "measured_propositions.json",
    ):
        shutil.copy2(source / name, out / name)
    shutil.copy2(source / "run/predictions.json", out / "predictions.json")
    for mode in ("legacy", "simple_rule", "proposition_aware"):
        candidate = copy.deepcopy(board)
        local = candidate["segments"][0]
        if mode != "proposition_aware":
            local.pop("timeline", None)
            local["animations"] = []
            if mode == "legacy":
                local["animations"] = build_segment_timing(local, timing_mode="legacy")
            else:
                local["animations"] = [
                    {
                        "target": "heading",
                        "action": "show",
                        "effect": "fadeInUp",
                        "trigger_at_sec": 0,
                    }
                ] + [
                    {
                        "target": e["id"],
                        "action": "show",
                        "effect": "fadeInUp",
                        "trigger_at_sec": round(i * cues["duration_sec"] / len(objects), 3),
                    }
                    for i, e in enumerate(objects)
                ]
        for collection in ("animations", "timeline"):
            for i, event in enumerate(local.get(collection, [])):
                event["event_id"] = event.get("event_id") or f"{mode}-{event['target']}-{i}"
        media.write(out / mode / "storyboard.json", candidate)
    shutil.copy2(__file__, out / "runner_snapshot.py")
    media.write(
        out / "comparison_contract.json",
        {
            "source_run": str(source.resolve()),
            "source_input_manifest_sha256": media.sha(source / "inputs.json"),
            "source_predictions_sha256": media.sha(source / "run/predictions.json"),
            "proposition_denominator": len(props),
            "bound_count": len(selected),
            "unbound": [p for p in predictions if p["status"] != "BOUND"],
            "budget": {"model_calls": 0, "new_audio": 0, "recordings_per_condition": 1},
            "claim": "Timing/signaling control with fixed predictions; "
            "not binding accuracy or gold. "
            "Simple rule evenly spaces actual selected objects across measured full audio. "
            "Proposition-aware retains existing dim events; this is not isolated onset ablation.",
        },
    )
    media.write(
        out / "inputs.json",
        {
            "duration_sec": segment["audio_duration_sec"],
            "files": {
                p.relative_to(out).as_posix(): media.sha(p) for p in out.rglob("*") if p.is_file()
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    media.offline()
    prepare(args.from_run.resolve(), args.output.resolve())
