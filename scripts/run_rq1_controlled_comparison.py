"""Bounded, resumable RQ1 development comparison with reversed option order."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from run_rq1_preference_comparison import (  # noqa: E402
    _action_options,
    _candidate_assets,
    _method_choices,
    _sample_by_action,
    _segment_images,
)

from textbook2video.llm import client  # noqa: E402
from textbook2video.research.rq1_controlled_evaluation import summarize_controlled  # noqa: E402
from textbook2video.research.rq1_preference_judge import (  # noqa: E402
    PREFERENCE_JUDGE_VERSION,
    judge_rq1_action_preferences,
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output: Path, *, execute: bool):
    output.mkdir(parents=True, exist_ok=True)
    lock = output / "run.lock"
    # Exclusive filesystem create prevents concurrent processes sharing a budget.
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    try:
        return _run(output, execute=execute)
    finally:
        lock.unlink()


def validate_cached_row(row: dict, expected: dict):
    if any(row.get(k) != v for k, v in expected.items()):
        raise ValueError("cached row identity/protocol mismatch")


def analyze_saved(output: Path, destination: Path):
    """Recompute a bound saved report without transport or retrying judgments."""
    if destination.exists():
        raise FileExistsError(destination)
    manifest = output / "protocol.json"
    protocol = read(manifest)
    report = read(output / "report.json")
    if report["protocol_sha256"] != digest(manifest):
        raise ValueError("saved report/protocol mismatch")
    for item in protocol["inputs"].values():
        if digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("saved input drift")
    by_id = {x["proposition"]["id"]: x for x in protocol["tasks"]}
    for row in report["rows"]:
        task = by_id[row["proposition_id"]]
        options = task["options"] if row["order"] == "forward" else task["options"][::-1]
        validate_cached_row(
            row,
            {
                "method_choices": task["method_choices"],
                "option_order": [x["action"] for x in options],
            },
        )
    report["summary"] = summarize_controlled(
        report["rows"], protocol["models"], proposition_ids=list(by_id)
    )
    report["analysis_implementation_sha256"] = digest(
        ROOT / "src/textbook2video/research/rq1_controlled_evaluation.py"
    )
    report["additional_model_calls"] = 0
    write(destination, report)


def _run(output: Path, *, execute: bool):
    config_path = ROOT / "configs/research/rq1_controlled_dev_v1.json"
    config = read(config_path)
    if not (
        0 < config["max_transport_calls"] <= 16
        and 0 < config["timeout_sec"] <= 120
        and 0 < config["max_output_tokens"] <= 1800
        and config["sample_per_current_action"] == 1
        and config["models"] == ["ecnu-plus", "ecnu-max"]
    ):
        raise ValueError("configuration exceeds bounded development protocol")
    frozen = ROOT / "datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1"
    paths = {
        "graph": frozen / "inputs/track_a_r10/proposition_graph.json",
        "source": frozen / "inputs/track_a_r10/source_evidence.json",
        "decisions": frozen / "inputs/track_a_r10/visual_decisions.json",
        "storyboard": frozen / "cases/lesson_002/baseline/storyboard.json",
        "candidates": frozen / "inputs/lesson_002_candidate_universe.json",
    }
    graph, source, decisions, storyboard, candidates = [read(paths[k]) for k in paths]
    samples = _sample_by_action(
        graph["narration_propositions"],
        decisions["decisions"],
        per_action=config["sample_per_current_action"],
    )
    units = {x["id"]: x for x in source["source_units"]}
    assets = _candidate_assets(candidates)
    for c in candidates["candidates"]:
        path = ROOT / c["path"]
        if not path.is_file() or digest(path) != c["sha256"]:
            raise ValueError(f"candidate integrity failure: {c['candidate_id']}")
        paths["asset:" + c["candidate_id"]] = path
    images_by_segment = _segment_images(storyboard)
    tasks = []
    for sample in samples:
        prop = sample["proposition"]
        refs = prop.get("source_refs", [])
        if not refs or any(ref not in units for ref in refs):
            raise ValueError(f"missing source evidence: {prop['id']}")
        images = images_by_segment.get(str(prop["segment_id"]), [])
        options, pixels = _action_options(prop, images, assets)
        tasks.append(
            {
                "proposition": prop,
                "source": [units[x] for x in refs],
                "options": options,
                "images": [str(p) for p in pixels],
                "method_choices": _method_choices(sample, images),
            }
        )
    protocol = {
        "scope": "DEVELOPMENT_PREVIOUSLY_EXPOSED_LESSON_NOT_HOLDOUT",
        "sample_strategy": "first stable ID per action; not population prevalence",
        "models": ["ecnu-plus", "ecnu-max"],
        "orders": ["forward", "reverse"],
        "judge_version": PREFERENCE_JUDGE_VERSION,
        "configuration_sha256": digest(config_path),
        "conditions": config["conditions"],
        "max_transport_calls": config["max_transport_calls"],
        "timeout_sec": config["timeout_sec"],
        "max_output_tokens": config["max_output_tokens"],
        "automatic_transport_retries": 0,
        "primary": "per-model/order proxy top1 counts",
        "uncertainty": "missing/failure/abstain/order or model disagreement => UNRESOLVED",
        "human_labels_required": False,
        "asset_outcomes": "NOT_EXECUTED",
        "inputs": {k: {"path": str(p), "sha256": digest(p)} for k, p in paths.items()},
        "implementation": {
            p: digest(ROOT / p)
            for p in (
                "scripts/run_rq1_controlled_comparison.py",
                "src/textbook2video/research/rq1_controlled_evaluation.py",
                "src/textbook2video/research/rq1_preference_judge.py",
            )
        },
        "tasks": tasks,
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "protocol.json"
    if manifest.exists() and read(manifest) != protocol:
        raise ValueError("protocol/input drift; choose a new run directory")
    write(manifest, protocol)
    if not execute:
        return
    ledger_path = output / "calls.json"
    ledger = read(ledger_path) if ledger_path.exists() else []
    # Observe actual LiteLLM usage without changing the production transport.
    original = client.litellm.completion if client.litellm else None
    usage = {}
    if original:

        def observed(*args, **kwargs):
            response = original(*args, **kwargs)
            usage.update(response.usage.model_dump() if response.usage else {})
            return response

        client.litellm.completion = observed

    def transport(fn):
        def call(*args, **kwargs):
            if len(ledger) >= protocol["max_transport_calls"]:
                raise RuntimeError("RUN_TRANSPORT_BUDGET_EXHAUSTED")
            usage.clear()
            entry = {
                "number": len(ledger) + 1,
                "model": kwargs["model"],
                "prompt_sha256": hashlib.sha256(args[0].encode("utf-8")).hexdigest(),
                "status": "STARTED",
                "usage": None,
                "cost": None,
            }
            ledger.append(entry)
            write(ledger_path, ledger)  # Reserve budget even on process interruption.
            started = time.monotonic()
            try:
                kwargs["timeout"] = protocol["timeout_sec"]
                kwargs["max_tokens"] = protocol["max_output_tokens"]
                raw = fn(*args, **kwargs)
                entry.update(status="OK", raw_response=raw)
                return raw
            except Exception as exc:
                entry.update(status="FAILED", error=type(exc).__name__)
                raise
            finally:
                entry.update(
                    elapsed_sec=round(time.monotonic() - started, 3), usage=dict(usage) or None
                )
                write(ledger_path, ledger)

        return call

    rows = []
    try:
        for task in tasks:
            for model in protocol["models"]:
                for order in protocol["orders"]:
                    pid = task["proposition"]["id"]
                    destination = output / f"{pid}-{model}-{order}.json"
                    options = task["options"] if order == "forward" else task["options"][::-1]
                    expected = {
                        "proposition_id": pid,
                        "model": model,
                        "order": order,
                        "method_choices": task["method_choices"],
                        "option_order": [x["action"] for x in options],
                        "protocol_sha256": digest(manifest),
                    }
                    if destination.exists():
                        row = read(destination)
                        validate_cached_row(row, expected)
                    else:
                        row = {**expected, "status": "FAILED"}
                        try:
                            row["judgment"] = judge_rq1_action_preferences(
                                proposition=task["proposition"],
                                source_evidence=task["source"],
                                options=options,
                                candidate_images=task["images"],
                                model=model,
                                text_call=transport(client.chat_with_system),
                                image_call=transport(client.chat_with_images),
                            )
                            row["status"] = "OK"
                        except Exception as exc:
                            row["error"] = type(exc).__name__
                            if len(ledger) >= protocol["max_transport_calls"]:
                                row["status"] = "BUDGET_BLOCKED"
                        write(destination, row)
                    rows.append(row)
                    summary = summarize_controlled(
                        rows,
                        protocol["models"],
                        proposition_ids=[x["proposition"]["id"] for x in tasks],
                    )
                    write(
                        output / "report.json",
                        {
                            "protocol_sha256": digest(manifest),
                            "summary": summary,
                            "rows": rows,
                            "transport_calls": len(ledger),
                        },
                    )
                    print(pid, model, order, row["status"], flush=True)
    finally:
        if original:
            client.litellm.completion = original


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--analysis-output", type=Path)
    args = parser.parse_args()
    if args.analyze_only:
        if args.execute or not args.analysis_output:
            parser.error("--analyze-only requires --analysis-output and forbids --execute")
        analyze_saved(args.output, args.analysis_output)
    else:
        run(args.output, execute=args.execute)
