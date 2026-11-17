"""One bounded automatic source-conditioned binding → voiced video run.

No expected targets are supplied. Evaluation cannot alter predictions or plans.
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

shared = importlib.import_module("run_rq1_doc2present_v2")
media = importlib.import_module("run_rq2_native_timing")
binding = importlib.import_module("textbook2video.research.binding_methods")
visual_decision = importlib.import_module("textbook2video.research.visual_decision")

read, write, sha = media.read, media.write, media.sha
CONFIG = ROOT / "configs/research/rq2_auto_binding_video_20261105.json"


def prepare(out, source):
    import pymupdf

    if out.exists():
        raise FileExistsError(out)
    config = read(CONFIG)
    if sha(source) != config["source_sha256"]:
        raise ValueError("Source PDF hash mismatch")
    with pymupdf.open(source) as doc:
        raw = doc[config["page"] - 1].get_text()
    normalized = re.sub(r"\s+", " ", re.sub(r"(?<=\w)-\n(?=\w)", "", raw))
    section = normalized[normalized.index("3.1. Brief") : normalized.index("3.2. Overview")]
    starts = [section.index(f"Step {i}.") for i in (4, 5, 6)]
    chunks = [
        section[starts[0] : starts[1]],
        section[starts[1] : starts[2]],
        section[starts[2] : section.index("For the decoder,")],
    ]
    prose = [chunk[chunk.index(". ", chunk.index(". ") + 2) + 2 :].strip() for chunk in chunks]
    last = prose.pop()
    split = last.index("The reconstructed frame will be used")
    prose.extend([last[:split].strip(), last[split:].strip()])
    if len(prose) != 4 or any(not t for t in prose):
        raise ValueError("Source selection did not produce four complete source sentences")
    props = [
        {
            "id": f"n{i}",
            "segment_id": "auto",
            "text": text,
            "source_refs": ["passage"],
            "source_context": section,
        }
        for i, text in enumerate(prose, 1)
    ]
    candidates = []
    units = [{"id": "passage", "text": section, "source_locator": "DVC PDF page 3 section 3.1"}]
    for key in config["candidate_order"]:
        item = config["candidates"][key]
        position = section.index(item["label"])
        units.append(
            {
                "id": f"native-{key}",
                "text": item["label"],
                "source_locator": "DVC PDF page 3 section 3.1",
                "char_span": {"start": position, "end": position + len(item["label"])},
            }
        )
        candidates.append(
            {
                "id": key,
                "segment_id": "auto",
                **item,
                "source_refs": [f"native-{key}"],
                "source_locator": "page3/native-operation-summary",
                "type": "highlight_box",
                "rights_status": config["rights"],
            }
        )
    out.mkdir(parents=True)
    shutil.copy2(source, out / "source.pdf")
    write(
        out / "source.json",
        {
            "raw_page": raw,
            "normalized_section": section,
            "source_sha256": sha(source),
            "narration_source_spans": [
                [section.index(t), section.index(t) + len(t)] for t in prose
            ],
            "narration_policy": (
                "All prose sentences of steps 4–6 retained; section headings not spoken. "
                "No model-dependent selection."
            ),
        },
    )
    write(
        out / "graph.json",
        {
            "narration_propositions": props,
            "knowledge_propositions": [],
            "producer": "deterministic_source_sentence_excerpts_not_gold",
        },
    )
    write(out / "source_evidence.json", {"source_units": units, "source_images": []})
    write(out / "candidates.json", candidates)
    write(
        out / "catalog.json",
        {
            "summary": {
                "scope": config["visual_decision_scope"],
                "existing_native_components": candidates,
            }
        },
    )
    write(out / "config.json", config)
    protocol = {
        "models": {
            "temperature": config["models"]["temperature"],
            "timeout_sec": config["models"]["timeout_sec"],
        },
        "budget": config["budget"],
    }
    write(out / "protocol.json", protocol)
    snapshot = out / "code_snapshot"
    for rel in (
        "scripts/run_rq2_auto_binding_video.py",
        "scripts/run_rq2_native_timing.py",
        "scripts/review_rq2_native_timing.py",
        "src/textbook2video/research/binding_methods.py",
        "src/textbook2video/research/visual_decision.py",
        "src/textbook2video/research/dynamic_planner.py",
        "src/textbook2video/research/p0_integration.py",
        "src/textbook2video/pipeline/timing.py",
        "src/textbook2video/animation_gen.py",
        "src/textbook2video/template_renderer.py",
        "src/textbook2video/templates/slide-controller.js",
    ):
        target = snapshot / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    write(
        out / "input_manifest.json",
        {p.relative_to(out).as_posix(): sha(p) for p in out.rglob("*") if p.is_file()},
    )


def verify_inputs(out):
    for name, digest in read(out / "input_manifest.json").items():
        if sha(out / name) != digest:
            raise ValueError(f"Frozen input changed: {name}")


def verify_predictions(out):
    for name, digest in read(out / "run/prediction_manifest.json").items():
        if sha(out / "run" / name) != digest:
            raise ValueError(f"Original prediction changed: {name}")


def call(out, key, stage, prompt, maximum, model):
    config = read(out / "config.json")
    ledger_path = out / "run/calls.json"
    ledger = read(ledger_path) if ledger_path.exists() else []
    if any(entry["status"] != "OK" for entry in ledger):
        raise RuntimeError("STOP_AFTER_TRANSPORT_FAILURE")
    totals = [(entry.get("usage") or {}).get("total_tokens") for entry in ledger]
    if any(n is None for n in totals):
        raise RuntimeError("Cannot audit token budget without provider usage")
    # Reserve a conservative UTF-8 byte bound plus output allowance and framing.
    if (
        sum(totals) + len(prompt.encode("utf-8")) + maximum + 1024
        > config["budget"]["max_total_tokens"]
    ):
        raise RuntimeError("TOKEN_BUDGET_EXHAUSTED_BEFORE_TRANSPORT")
    raw, _ = shared._call_model(
        package_root=out,
        run_dir=out / "run",
        protocol=read(out / "protocol.json"),
        ledger=ledger,
        task_key=key,
        stage=stage,
        model=model,
        prompt=prompt,
        images=[],
        max_tokens=maximum,
        system_prompt=(
            "Use only supplied source evidence. Return JSON; "
            "never invent human review or source support."
        ),
    )
    if raw is None:
        raise RuntimeError("STOP_AFTER_TRANSPORT_FAILURE")
    return raw


def predict(out):
    verify_inputs(out)
    run = out / "run"
    if run.exists():
        raise FileExistsError("Prediction attempts cannot be repeated or resumed")
    run.mkdir()
    config = read(out / "config.json")
    original = visual_decision.chat_with_system
    visual_decision.chat_with_system = lambda prompt, **kwargs: call(
        out,
        "visual-decision",
        "visual_decision",
        prompt,
        config["budget"]["decision_max_tokens"],
        config["models"]["method"],
    )
    try:
        visual_decision.decide_visual_support(
            proposition_graph_path=out / "graph.json",
            source_evidence_path=out / "source_evidence.json",
            retrieval_catalog_path=out / "catalog.json",
            output_path=run / "visual_decisions.json",
            model=config["models"]["method"],
            research_condition="proposed",
        )
    except Exception as exc:
        write(
            run / "visual_decision_failure.json",
            {"status": "FAILED", "error": shared.client.redact_response_text(str(exc))},
        )
        ledger = read(run / "calls.json")
        if any(x["status"] != "OK" for x in ledger):
            raise
    finally:
        visual_decision.chat_with_system = original
    predictions = []
    for prop in read(out / "graph.json")["narration_propositions"]:
        try:
            result = binding.bind_source_conditioned(
                prop,
                read(out / "candidates.json"),
                threshold=config["threshold"],
                allow_decision_bridge=False,
                context_model_fn=lambda prompt: call(
                    out,
                    f"binding-{prop['id']}",
                    "binding",
                    prompt,
                    config["budget"]["binding_max_tokens"],
                    config["models"]["method"],
                ),
            )
        except Exception as exc:
            result = {
                "proposition_id": prop["id"],
                "segment_id": "auto",
                "status": "INVALID_RESPONSE",
                "selected_candidate_id": None,
                "error": shared.client.redact_response_text(str(exc)),
            }
            if any(x["status"] != "OK" for x in read(run / "calls.json")):
                write(run / f"prediction-{prop['id']}.json", result)
                raise
        write(run / f"prediction-{prop['id']}.json", result)
        predictions.append(result)
    write(run / "predictions.json", predictions)
    write(
        run / "prediction_manifest.json",
        {
            p.name: sha(p)
            for p in run.glob("prediction*.json")
            if p.name != "prediction_manifest.json"
        },
    )


def review_predictions(out):
    verify_predictions(out)
    run = out / "run"
    before = sha(run / "predictions.json")
    config = read(out / "config.json")
    schema = {
        "type": "object",
        "required": ["assessments"],
        "additionalProperties": False,
        "properties": {
            "assessments": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["proposition_id", "verdict", "source_quote", "reason"],
                    "properties": {
                        "proposition_id": {"enum": ["n1", "n2", "n3", "n4"]},
                        "verdict": {
                            "enum": [
                                "SUPPORTED",
                                "WRONG",
                                "ABSTAIN_REASONABLE",
                                "ABSTAIN_MISSED",
                                "UNCERTAIN",
                            ]
                        },
                        "source_quote": {"type": "string", "minLength": 1},
                        "reason": {"type": "string", "minLength": 1},
                    },
                },
            }
        },
    }
    prompt = json.dumps(
        {
            "task": (
                "Review automatic narrated-role bindings, not mere shared-topic relevance. "
                "For each bound prediction decide whether its object performs the narrated role. "
                "A refused/invalid prediction is not a successful binding. "
                "Source quote must be literal; assess every proposition exactly once. "
                "Do not produce replacement binding IDs. Proxy evaluation, not gold."
            ),
            "source": read(out / "source.json")["normalized_section"],
            "propositions": [
                {"id": p["id"], "text": p["text"]}
                for p in read(out / "graph.json")["narration_propositions"]
            ],
            "candidates": [
                {"id": c["id"], "label": c["label"], "text": c["text"]}
                for c in read(out / "candidates.json")
            ],
            "predictions": [
                {key: p.get(key) for key in ("proposition_id", "status", "selected_candidate_id")}
                for p in read(run / "predictions.json")
            ],
            "output_json_schema": schema,
        },
        ensure_ascii=False,
    )
    try:
        raw = call(
            out,
            "semantic-review",
            "semantic_review",
            prompt,
            config["budget"]["review_max_tokens"],
            config["models"]["review"],
        )
        value = binding._parse_model_json(raw)
        from jsonschema import Draft202012Validator

        Draft202012Validator(schema).validate(value)
        by_id = {p["proposition_id"]: p for p in read(run / "predictions.json")}
        if len({a["proposition_id"] for a in value["assessments"]}) != 4:
            raise ValueError("Review duplicates proposition IDs")
        for item in value["assessments"]:
            bound = by_id[item["proposition_id"]].get("status") == "BOUND"
            if (item["verdict"] == "SUPPORTED" and not bound) or (
                item["verdict"].startswith("ABSTAIN_") and bound
            ):
                raise ValueError("Review verdict incompatible with prediction state")
            if item["verdict"] == "WRONG" and not bound:
                raise ValueError("A refused or invalid prediction is not a wrong bound object")
            if item["verdict"].startswith("ABSTAIN_") and not str(
                by_id[item["proposition_id"]]["status"]
            ).startswith("ABSTAINED"):
                raise ValueError("Invalid output must not be relabelled as model abstention")
            if not binding._quote_anchors(
                read(out / "source.json")["normalized_section"], item["source_quote"]
            ):
                raise ValueError("Review quote not anchored in source")
        write(run / "semantic_review.json", {"status": "VALID_PROXY_NOT_GOLD", **value})
    except Exception as exc:
        write(
            run / "semantic_review.json",
            {
                "status": "INVALID_OR_UNAVAILABLE",
                "error": shared.client.redact_response_text(str(exc)),
            },
        )
    if sha(run / "predictions.json") != before:
        raise ValueError("Evaluation changed predictions")


def materialize(out, reuse_audio=None):
    from textbook2video.pipeline.narrator import generate_sentence_audio
    from textbook2video.research.dynamic_planner import plan_dynamic_events
    from textbook2video.research.p0_integration import P0IntegrationPaths, apply_p0_event_schedule

    verify_inputs(out)
    verify_predictions(out)
    if (out / "audio").exists() or (out / "auto").exists():
        raise FileExistsError("Media preparation already attempted")
    props = copy.deepcopy(read(out / "graph.json")["narration_propositions"])
    predictions = read(out / "run/predictions.json")
    if {p["proposition_id"] for p in predictions} != {p["id"] for p in props}:
        raise ValueError("Prediction coverage incomplete; cannot discard difficult sentences")
    config = read(out / "config.json")
    if reuse_audio is None:
        audio = generate_sentence_audio(
            [[p["text"] for p in props]],
            output_dir=out / "audio",
            backend="sapi",
            segment_ids=["auto"],
            voice=config["audio"]["voice"],
            rate=config["audio"]["rate"],
        )
    else:
        saved = read(reuse_audio / "sentence_cues.json")
        if [c["text"] for c in saved["segments"][0]["cues"]] != [p["text"] for p in props]:
            raise ValueError("Replay audio does not match frozen narration")
        shutil.copytree(reuse_audio, out / "audio")
        audio = {"segments": saved["segments"]}
    group = audio["segments"][0]
    for prop, cue in zip(props, group["cues"], strict=True):
        if cue["text"] != prop["text"]:
            raise ValueError("Measured audio sentence mismatch")
        prop.update(start_sec=cue["start_sec"], end_sec=cue["end_sec"])
    duration = round(group["duration_sec"] + 1, 3)
    selected = {p["selected_candidate_id"] for p in predictions if p.get("status") == "BOUND"}
    selected_order = list(
        dict.fromkeys(p["selected_candidate_id"] for p in predictions if p.get("status") == "BOUND")
    )
    candidates = read(out / "candidates.json")
    if selected - {c["id"] for c in candidates}:
        raise ValueError("Unknown predicted object")
    elements = [
        {
            "id": "heading",
            "type": "heading",
            "text": "Traditional video coding: reconstruction and coding",
        }
    ]
    by_id = {c["id"]: c for c in candidates}
    elements += [
        {"id": c["id"], "type": c["type"], "text": c["text"], "source_refs": c["source_refs"]}
        for c in (by_id[key] for key in selected_order)
    ]
    board = {
        "lesson_title": "RQ2 automatic binding end-to-end development",
        "segments": [
            {
                "id": "auto",
                "narration": " ".join(p["text"] for p in props),
                "audio_duration_sec": duration,
                "visual_type": "process",
                "elements": elements,
                "animations": [
                    {
                        "target": "heading",
                        "action": "show",
                        "effect": "fadeInUp",
                        "trigger_at_sec": 0,
                    }
                ],
            }
        ],
        "metadata": {
            "total_slides": 1,
            "binding_predictions_sha256": sha(out / "run/predictions.json"),
            "unselected_candidates": [
                {
                    "id": c["id"],
                    "reason": "not selected by actual predictions; no inferred fallback object",
                }
                for c in candidates
                if c["id"] not in selected
            ],
        },
    }
    plan = plan_dynamic_events(
        propositions=props, bindings=predictions, segment_durations={"auto": duration}
    )
    write(out / "measured_propositions.json", props)
    write(out / "dynamic_plan.json", plan)
    path = out / "auto/storyboard.json"
    write(path, board)
    sidecar = out / "auto/p0_sidecar.json"
    write(
        sidecar,
        {
            "schema_version": "p0-production-sidecar-v0.1",
            "propositions": props,
            "events": [{**e, "effect": e.get("effect", "fadeIn")} for e in plan["events"]],
        },
    )
    apply_p0_event_schedule(
        P0IntegrationPaths(path, path, sidecar),
        sentence_cues=read(out / "audio/sentence_cues.json"),
    )
    board = read(path)
    for collection in ("animations", "timeline"):
        for i, event in enumerate(board["segments"][0].get(collection, [])):
            event["event_id"] = (
                event.get("research_p0", {}).get("event_id") or f"auto-{event['target']}-{i}"
            )
    write(path, board)
    frozen = [p for p in out.rglob("*") if p.is_file()]
    write(
        out / "inputs.json",
        {
            "duration_sec": duration,
            "files": {p.relative_to(out).as_posix(): sha(p) for p in frozen},
            "prediction_sha256": sha(out / "run/predictions.json"),
            "claim": "Automatic predictions drive all pedagogical events; no evaluator replacement",
        },
    )


def render(out):
    media.verify(out)
    media.offline()
    from textbook2video.animation_gen import build_slide_timelines, generate

    directory = out / "auto"
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
            "events": build_slide_timelines(read(directory / "storyboard.json")["segments"])[0],
            "html": str(html.resolve()),
            "html_sha256": sha(html),
        },
    )


def replay(source, out):
    verify_inputs(source)
    media.verify(source)
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    for name in [*read(source / "input_manifest.json"), "input_manifest.json"]:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copytree(source / "run", out / "run", dirs_exist_ok=True)
    shutil.copy2(__file__, out / "replay_runner_snapshot.py")
    before = sha(out / "run/calls.json")
    media.offline()
    materialize(out, reuse_audio=source / "audio")
    render(out)
    original = read(source / "auto/compiled.json")
    repeated = read(out / "auto/compiled.json")
    if original["events"] != repeated["events"] or read(source / "dynamic_plan.json") != read(
        out / "dynamic_plan.json"
    ):
        raise ValueError("Offline replay changed predicted event semantics")
    if sha(out / "run/calls.json") != before:
        raise ValueError("Offline replay modified request ledger")
    write(
        out / "replay.json",
        {
            "new_model_calls": 0,
            "new_tts_calls": 0,
            "predictions_identical": sha(source / "run/predictions.json")
            == sha(out / "run/predictions.json"),
            "plan_and_compiled_events_identical": True,
            "html_identical": original["html_sha256"] == repeated["html_sha256"],
        },
    )


def revalidate(source, out):
    """Reparse saved model replies with a repaired validator, never new targets."""
    verify_inputs(source)
    verify_predictions(source)
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    for name in read(source / "input_manifest.json"):
        target = out / name
        if name.startswith("code_snapshot/"):
            target = out / "original_code_snapshot" / name.removeprefix("code_snapshot/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    shutil.copytree(source / "run", out / "run")
    shutil.copy2(source / "run/predictions.json", out / "run/original_predictions.json")
    calls = read(out / "run/calls.json")
    before = sha(out / "run/calls.json")
    config = read(out / "config.json")
    results = []
    for prop in read(out / "graph.json")["narration_propositions"]:
        entries = [
            c for c in calls if c["task_key"] == f"binding-{prop['id']}" and c["status"] == "OK"
        ]
        if len(entries) != 1:
            raise ValueError("Exactly one original successful transport reply required")
        raw = entries[0]["raw_response"]
        try:
            result = binding.bind_source_conditioned(
                prop,
                read(out / "candidates.json"),
                threshold=config["threshold"],
                allow_decision_bridge=False,
                context_model_fn=lambda _prompt: raw,
            )
        except ValueError as exc:
            result = {
                "proposition_id": prop["id"],
                "segment_id": "auto",
                "status": "INVALID_RESPONSE",
                "selected_candidate_id": None,
                "error": str(exc),
            }
        write(out / "run" / f"prediction-{prop['id']}.json", result)
        results.append(result)
    write(out / "run/predictions.json", results)
    write(
        out / "run/prediction_manifest.json",
        {
            p.name: sha(p)
            for p in (out / "run").glob("prediction*.json")
            if p.name != "prediction_manifest.json"
        },
    )
    write(
        out / "validation_revision.json",
        {
            "original_run": str(source.resolve()),
            "original_predictions_sha256": sha(source / "run/predictions.json"),
            "original_calls_sha256": before,
            "new_model_calls": 0,
            "repair": (
                "Latin presentation ligature anchoring only; original model assessments retained"
            ),
            "original_review_scope": (
                "Original predictions before validation repair; not a review of the revised n3 "
                "binding. n3 invalid vs abstention and n4 WRONG-on-abstention are taxonomy "
                "inconsistencies, not trusted correctness labels."
            ),
        },
    )
    for rel in (
        "src/textbook2video/research/binding_methods.py",
        "scripts/run_rq2_auto_binding_video.py",
    ):
        target = out / "code_snapshot" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    if sha(out / "run/calls.json") != before:
        raise ValueError("Validation replay changed original request ledger")
    write(
        out / "input_manifest.json",
        {p.relative_to(out).as_posix(): sha(p) for p in out.rglob("*") if p.is_file()},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "predict",
            "materialize",
            "render",
            "record",
            "run",
            "replay",
            "revalidate",
        ],
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--from-run", type=Path)
    parser.add_argument(
        "--source-pdf",
        type=Path,
        default=Path("D:/Code/vibe coding/datasets/Doc2Present") / read(CONFIG)["source_filename"],
    )
    args = parser.parse_args()
    out = args.output.resolve()
    if args.command == "replay":
        if args.from_run is None:
            parser.error("replay requires --from-run")
        replay(args.from_run.resolve(), out)
    if args.command == "revalidate":
        if args.from_run is None:
            parser.error("revalidate requires --from-run")
        media.offline()
        revalidate(args.from_run.resolve(), out)
    if args.command in {"prepare", "run"}:
        prepare(out, args.source_pdf)
    if args.command in {"predict", "run"}:
        predict(out)
        review_predictions(out)
    if args.command in {"materialize", "run"}:
        media.offline()
        materialize(out)
    if args.command in {"render", "run"}:
        render(out)
    if args.command in {"record", "run"}:
        media.offline()
        media.record(out, "auto")
