"""Offline plan comparison using verified Direct controls and measured audio.

This does not render unapproved paper figures or claim video visibility.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_rq2_binding_dev as runner

from textbook2video.pipeline.timing import build_segment_timing
from textbook2video.research.dynamic_planner import plan_dynamic_events


def compare(package: Path, audio: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    runner.verify(package)
    run = package / "run-01"
    if not (run / "output_manifest.json").is_file():
        raise ValueError("Require a completed immutable binding run")
    protocol = runner.read(package / "protocol.json")
    cues = runner.read(audio / "sentence_cues.json")["segments"]
    tasks = runner.read(package / "inputs/tasks.json")
    props, bindings, excluded, source_hashes = [], [], [], {}
    plans = {"legacy": [], "simple_rule": []}
    durations = {}
    for group in cues:
        wav = audio / group["audio_path"]
        import wave

        with wave.open(str(wav), "rb") as stream:
            measured = stream.getnframes() / stream.getframerate()
        if abs(measured - group["duration_sec"]) > 0.002:
            raise ValueError("Measured WAV duration differs from cues")
        source_hashes[str(wav.resolve())] = runner.sha(wav)
        durations[group["segment_id"]] = measured
    source_hashes[str((audio / "sentence_cues.json").resolve())] = runner.sha(
        audio / "sentence_cues.json"
    )
    for task in tasks:
        results = runner.read(run / "bindings" / f"{task['id']}.json")
        binding = results["direct_llm_vlm"]
        verdicts = []
        for alias in protocol["models"]["judge_models"]:
            for order in ("forward", "reverse"):
                path = run / "judges" / f"{task['id']}-{alias}-{order}.json"
                row = runner.read(path) if path.exists() else {}
                if row.get("status") == "OK":
                    verdicts.append(
                        row["judgment"]["assessment_by_option"][row["mapping"]["direct_llm_vlm"]][
                            "verdict"
                        ]
                    )
        if binding.get("status") != "BOUND" or verdicts != ["BOUND_SUPPORTED"] * 4:
            excluded.append(
                {
                    "id": task["id"],
                    "verdicts": verdicts,
                    "reason": "control_not_supported_in_all_four_planned_proxy_slots",
                }
            )
            continue
        matching = [
            c
            for g in cues
            if g["segment_id"] == task["document_id"]
            for c in g["cues"]
            if c["text"] == task["proposition"]["text"]
        ]
        if len(matching) != 1:
            raise ValueError("Narration must match exactly one measured sentence")
        cue = matching[0]
        props.append(
            {**task["proposition"], "start_sec": cue["start_sec"], "end_sec": cue["end_sec"]}
        )
        bindings.append(binding)
    for segment_id, duration in durations.items():
        local = [b for b in bindings if b["segment_id"] == segment_id]
        ids = list(dict.fromkeys(b["selected_candidate_id"] for b in local))
        candidates = {
            c["id"]: c for t in tasks if t["document_id"] == segment_id for c in t["candidates"]
        }
        elements = [
            {
                "id": key,
                "type": "image",
                "caption": candidates[key].get("text", candidates[key].get("label", "")),
            }
            for key in ids
        ]
        segment = {
            "id": segment_id,
            "audio_duration_sec": duration,
            "narration": " ".join(
                g["text"] for c in cues if c["segment_id"] == segment_id for g in c["cues"]
            ),
            "elements": elements,
        }
        plans["legacy"].extend(
            {"segment_id": segment_id, **event}
            for event in build_segment_timing(segment, timing_mode="legacy")
        )
        plans["simple_rule"].extend(
            {
                "segment_id": segment_id,
                "target": target,
                "trigger_at_sec": round(i * duration / len(ids), 4),
                "effect": "fadeInUp",
            }
            for i, target in enumerate(ids)
        )
    plans["proposition_aware"] = plan_dynamic_events(
        propositions=props, bindings=bindings, segment_durations=durations
    )
    result = {
        "controls": bindings,
        "measured_propositions": props,
        "excluded_controls": excluded,
        "source_hashes": source_hashes,
        "binding_output_manifest_sha256": runner.sha(run / "output_manifest.json"),
        "plans": plans,
        "claim": "Offline planned timing only; Direct controls, model proxy support, no binding-method gain or video evidence",
        "media_status": "NOT_RENDERED_SOURCE_FIGURE_PERMISSION_UNVERIFIED",
        "new_model_calls": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    runner.write(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compare(args.package, args.audio, args.output)
