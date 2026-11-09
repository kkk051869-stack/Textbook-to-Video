"""Bounded Doc2Present binding comparison; existing methods, development only."""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
shared = importlib.import_module("run_rq1_doc2present_v2")
binding = importlib.import_module("textbook2video.research.binding_methods")

CONFIG = Path("configs/research/rq2_doc2present_binding_dev_v1.json")
write, sha = shared._write, shared._sha


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def valid_results(results: dict) -> dict:
    """Invalid predictions are failures, not abstention proposals."""
    return {method: result for method, result in results.items()
            if result.get("status") == "BOUND"
            or str(result.get("status", "")).startswith("ABSTAINED")}


def groups_for(results: dict) -> tuple[list[dict], dict]:
    """Group exact outcomes only; scores, method IDs and rationales stay private."""
    options, mapping, seen = [], {}, {}
    for method, result in results.items():
        target = result.get("selected_candidate_id")
        if target not in seen:
            seen[target] = f"o{len(options) + 1}"
            options.append({"option_id": seen[target], "selected_candidate_id": target})
        mapping[method] = seen[target]
    return options, mapping


def validate_judgment(
    value: dict,
    option_ids: list[str],
    context: str,
    verdicts: list[str],
    options: list[dict] | None = None,
) -> dict:
    assessments = value.get("assessment_by_option")
    if not isinstance(assessments, dict) or set(assessments) != set(option_ids):
        raise ValueError("Judge must assess every option exactly once")
    targets = {item["option_id"]: item["selected_candidate_id"] for item in options or []}
    for option_id, item in assessments.items():
        if not isinstance(item, dict) or set(item) != {
            "verdict",
            "source_quote",
            "visible_evidence",
        }:
            raise ValueError("Judge assessment fields invalid")
        if item["verdict"] not in verdicts or not str(item["visible_evidence"] or "").strip():
            raise ValueError("Judge verdict/evidence invalid")
        if option_id in targets:
            allowed = (
                {"BOUND_SUPPORTED", "PARTIAL", "WRONG", "UNCERTAIN"}
                if targets[option_id] is not None
                else {"ABSTAIN_REASONABLE", "ABSTAIN_MISSED", "UNCERTAIN"}
            )
            if item["verdict"] not in allowed:
                raise ValueError("Judge verdict conflicts with bound/abstain outcome")
        quote = item["source_quote"]
        if quote is not None and (
            not isinstance(quote, str) or not quote.strip() or quote not in context
        ):
            raise ValueError("Judge source quote is not literal supplied evidence")
    return value


def prepare(package: Path, config_path: Path = CONFIG) -> None:
    import pymupdf

    if package.exists():
        raise FileExistsError(package)
    config = read(ROOT / config_path)
    if config.get("required_target_role") not in {None, "actor"}:
        raise ValueError("unsupported binding target role")
    package.mkdir(parents=True)
    tasks = []
    for spec in config["documents"]:
        source = ROOT / config["source_root"] / spec["filename"]
        if sha(source) != spec["sha256"]:
            raise ValueError("source PDF hash mismatch")
        raw = package / "inputs" / f"{spec['id']}.pdf"
        raw.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, raw)
        with pymupdf.open(raw) as pdf:
            page = pdf[spec["page"] - 1]
            claim_page = int(spec.get("claim_page", spec["page"]))
            raw_text = pdf[claim_page - 1].get_text()
            text = shared._norm_source(raw_text)
            write(
                package / "inputs" / f"{spec['id']}-page.json",
                {"page_number": claim_page, "raw_text": raw_text, "normalized_text": text},
            )
            figure = package / "inputs" / f"{spec['id']}-fig2.png"
            page.get_pixmap(
                matrix=pymupdf.Matrix(3, 3), clip=pymupdf.Rect(spec["figure_rect"]), alpha=False
            ).save(figure)
            candidates = []
            for obj in spec["objects"]:
                crop = package / "inputs" / f"{obj['id']}.png"
                page.get_pixmap(
                    matrix=pymupdf.Matrix(4, 4), clip=pymupdf.Rect(obj["rect"]), alpha=False
                ).save(crop)
                candidates.append(
                    {
                        "id": obj["id"],
                        "segment_id": spec["id"],
                        "text": obj["label"],
                        "nearby_text": obj["label"],
                        "source_refs": [f"{obj['id']}-visible-label"],
                        "source_locator": f"{spec['id']} PDF page {spec['page']} Figure 2, rectangle {obj['rect']}",
                        "local_path": crop.relative_to(package).as_posix(),
                        "sha256": sha(crop),
                        "provenance_status": "ENGINEERING_OBJECT_LOCALIZATION_NOT_BINDING_GOLD",
                    }
                )
            for i, claim in enumerate(spec["claims"], 1):
                if text.count(claim) != 1:
                    raise ValueError("claim must occur exactly once in normalized source")
                start = text.index(claim)
                context = text[max(0, start - 650) : start + len(claim) + 650]
                prop_id = f"{spec['id']}-{config.get('proposition_id_prefix', 'method')}-s{i}"
                tasks.append(
                    {
                        "id": prop_id,
                        "document_id": spec["id"],
                        "proposition": {
                            "id": prop_id,
                            "segment_id": spec["id"],
                            "text": claim,
                            "source_refs": [f"{prop_id}-sentence"],
                            "source_context": context,
                        },
                        "source_context": context,
                        "source_span": [start, start + len(claim)],
                        "source_page_number": claim_page,
                        "candidates": candidates,
                        "figure_path": figure.relative_to(package).as_posix(),
                    }
                )
    write(package / "inputs/config.json", config)
    write(package / "inputs/tasks.json", tasks)
    for relative in [
        "scripts/run_rq2_binding_dev.py",
        "scripts/run_rq1_doc2present_v2.py",
        "scripts/run_rq1_new_corpus.py",
        "src/textbook2video/research/binding_methods.py",
        "src/textbook2video/research/source_evidence.py",
        "src/textbook2video/llm/client.py",
    ]:
        target = package / "code_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    import subprocess

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    )
    files = {p.relative_to(package).as_posix(): sha(p) for p in package.rglob("*") if p.is_file()}
    write(
        package / "protocol.json",
        {
            "scope": config["scope"],
            "run_id": config["run_id"],
            "git_head": head,
            "dirty": dirty,
            "source_files": files,
            "budget": config["budget"],
            "models": config["models"],
            "methods": config["methods"],
            "planned_propositions": len(tasks),
        },
    )
    write(package / "run-01/protocol.json", read(package / "protocol.json"))
    write(package / "run-01/calls.json", [])


def verify(package: Path) -> dict:
    protocol = read(package / "protocol.json")
    if sha(package / "protocol.json") != sha(package / "run-01/protocol.json"):
        raise ValueError("protocol changed after preparation")
    for rel, digest in protocol["source_files"].items():
        path = shared._package_path(package, rel)
        if sha(path) != digest:
            raise ValueError(f"frozen input changed: {rel}")
    for task in read(package / "inputs/tasks.json"):
        page = read(package / "inputs" / f"{task['document_id']}-page.json")
        start, end = task["source_span"]
        if page["normalized_text"][start:end] != task["proposition"]["text"]:
            raise ValueError("source span mismatch")
        ids = [c["id"] for c in task["candidates"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate IDs")
        for candidate in task["candidates"]:
            if sha(shared._package_path(package, candidate["local_path"])) != candidate["sha256"]:
                raise ValueError("candidate pixel hash differs from declared object")
    run = package / "run-01"
    calls = read(run / "calls.json")
    if [c["call_id"] for c in calls] != list(range(1, len(calls) + 1)):
        raise ValueError("call IDs must be continuous")
    if len(calls) > protocol["budget"]["max_transport_calls"] or len(
        {c["task_key"] for c in calls}
    ) != len(calls):
        raise ValueError("call budget or task uniqueness violated")
    for call in calls:
        if sha(shared._package_path(run, call["prompt_path"])) != call["prompt_sha256"]:
            raise ValueError("saved request hash mismatch")
    manifest = run / "output_manifest.json"
    if manifest.exists():
        for rel, digest in read(manifest).items():
            if sha(shared._package_path(run, rel)) != digest:
                raise ValueError(f"saved output changed: {rel}")
    return {
        "status": "PASS",
        "inputs": len(protocol["source_files"]),
        "calls": len(calls),
        "outputs": len(read(manifest)) if manifest.exists() else 0,
        "new_model_calls": 0,
    }


def embedding_batch(
    package: Path, run: Path, protocol: dict, ledger: list, texts: list[str]
) -> list:
    import requests

    if ledger or protocol["budget"]["max_transport_calls"] < 1:
        raise ValueError("embedding batch must reserve the first and only embedding request")
    prompt_path = "prompts/001-embedding.json"
    payload = {"model": protocol["models"]["embedding_model"], "input": texts}
    write(run / prompt_path, payload)
    entry = {
        "call_id": 1,
        "task_key": "embedding:one-batch",
        "stage": "embedding_batch",
        "model_alias": payload["model"],
        "status": "STARTED",
        "prompt_path": prompt_path,
        "prompt_sha256": sha(run / prompt_path),
        "usage": None,
        "cost_usd": None,
    }
    ledger.append(entry)
    write(run / "calls.json", ledger)
    started = time.monotonic()
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.post(
            shared.legacy.LLM_BASE_URL.rstrip("/") + "/embeddings",
            headers={"Authorization": "Bearer " + shared.legacy.LLM_API_KEY},
            json=payload,
            timeout=protocol["models"]["timeout_sec"],
        )
        response.raise_for_status()
        value = response.json()
        entry.update(status="OK", usage=value.get("usage"))
        write(run / "embedding-response.json", value)
        rows = sorted(value["data"], key=lambda x: x["index"])
        vectors = [item["embedding"] for item in rows]
        if [x["index"] for x in rows] != list(range(len(texts))) or not vectors or not vectors[0]:
            raise ValueError("embedding response indices/dimensions invalid")
        if any(
            len(v) != len(vectors[0]) or any(not math.isfinite(float(x)) for x in v)
            for v in vectors
        ):
            raise ValueError("embedding response is not finite fixed-dimensional vectors")
        return vectors
    except Exception as exc:
        entry.update(
            status="FAILED", error_message=shared.client.redact_response_text(str(exc))[:600]
        )
        raise
    finally:
        entry["elapsed_sec"] = round(time.monotonic() - started, 3)
        write(run / "calls.json", ledger)


def judge_prompt(
    task: dict, options: list, verdicts: list, required_target_role: str | None = None
) -> str:
    if required_target_role not in {None, "actor"}:
        raise ValueError("unsupported binding target role")
    ids = sorted(o["option_id"] for o in options)
    assessment = {
        "type": "object",
        "properties": {
            "verdict": {"enum": verdicts},
            "source_quote": {"type": ["string", "null"]},
            "visible_evidence": {"type": "string", "minLength": 1},
        },
        "required": ["verdict", "source_quote", "visible_evidence"],
        "additionalProperties": False,
    }
    return json.dumps(
        {
            "task": "Assess each anonymous proposition-to-object binding using supplied source and actual pixels. Null means abstain. Proxy only, not gold.",
            "proposition": task["proposition"]["text"],
            "source_context": task["source_context"],
            "images": [{"index": 1, "role": "source diagram region (cropped panel)"}]
            + [
                {"index": i + 2, "candidate_id": c["id"], "visible_label": c["text"]}
                for i, c in enumerate(task["candidates"])
            ],
            "options_in_display_order": options,
            "rubric": {
                "BOUND_SUPPORTED": "Selected block performs the narrated role, with correct actor/action/object and context.",
                "PARTIAL": "Related block but role/process explanation incomplete or ambiguous.",
                "WRONG": "Wrong object or semantic role; vocabulary/page proximity alone is insufficient.",
                "ABSTAIN_REASONABLE": "Null and evidence does not support one explanatory block.",
                "ABSTAIN_MISSED": "Null despite evidence supporting an explanatory block.",
                "UNCERTAIN": "Cannot determine; preserve disagreement, never force a winner.",
            },
            "rules": [
                "Do not infer method identity or reward confident prose. Identical outcomes share one option.",
                "Assess all options independently; no forced ranking. For a bound object use a bound verdict; for null use an abstention verdict or UNCERTAIN.",
                "source_quote must be a literal nonempty substring of supplied source_context or null; visible_evidence must describe the actual pixels and role. Never invent evidence.",
                "Return a JSON instance, not the schema.",
            ] + (list(binding.ACTOR_BINDING_RULES) + [
                "Under this actor contract, a selected candidate that only denotes the patient "
                "is WRONG, not BOUND_SUPPORTED or PARTIAL. Null is reasonable if no actor "
                "candidate is supported; use UNCERTAIN when identity cannot be resolved."
            ] if required_target_role == "actor" else []),
            "output_json_schema": {
                "type": "object",
                "properties": {
                    "assessment_by_option": {
                        "type": "object",
                        "properties": {key: assessment for key in ids},
                        "required": ids,
                        "additionalProperties": False,
                    }
                },
                "required": ["assessment_by_option"],
                "additionalProperties": False,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def summarize(package: Path) -> dict:
    from collections import Counter

    protocol = read(package / "protocol.json")
    tasks = read(package / "inputs/tasks.json")
    run = package / "run-01"
    per_method = {
        m: {"planned": len(tasks), "valid": 0, "bound": 0, "verdicts": Counter()}
        for m in protocol["methods"]
    }
    pairs, valid_judges, planned_judges = [], 0, len(tasks) * 4
    for task in tasks:
        outputs = run / "bindings" / f"{task['id']}.json"
        results = read(outputs) if outputs.exists() else {}
        for method, result in results.items():
            if result.get("status") == "BOUND" or str(result.get("status", "")).startswith(
                "ABSTAINED"
            ):
                per_method[method]["valid"] += 1
                per_method[method]["bound"] += bool(result.get("selected_candidate_id"))
        options, mapping = groups_for(
            {
                m: v
                for m, v in results.items()
                if v.get("status") == "BOUND" or str(v.get("status", "")).startswith("ABSTAINED")
            }
        )
        for alias in protocol["models"]["judge_models"]:
            judged = []
            for order in ("forward", "reverse"):
                path = run / "judges" / f"{task['id']}-{alias}-{order}.json"
                row = read(path) if path.exists() else {}
                if row.get("status") == "OK":
                    valid_judges += 1
                    judged.append(row["judgment"])
                    for method, option in mapping.items():
                        per_method[method]["verdicts"][
                            row["judgment"]["assessment_by_option"][option]["verdict"]
                        ] += 1
            if len(judged) == 2:
                verdict_maps = [
                    {key: item["verdict"] for key, item in j["assessment_by_option"].items()}
                    for j in judged
                ]
                pairs.append(
                    {
                        "proposition_id": task["id"],
                        "judge_alias": alias,
                        "verdict_map_changed": verdict_maps[0] != verdict_maps[1],
                    }
                )
    return {
        "scope": protocol["scope"],
        "run_id": protocol["run_id"],
        "code_commit": protocol["git_head"],
        "per_method": per_method,
        "valid_judge_slots": valid_judges,
        "planned_judge_slots": planned_judges,
        "order_pairs": pairs,
        "changed_verdict_pairs": sum(p["verdict_map_changed"] for p in pairs),
        "calls": shared._call_summary(
            read(run / "calls.json"), budget_limit=protocol["budget"]["max_transport_calls"]
        ),
        "claim_boundary": "Development proxy judgments, not binding truth, method superiority, timing, visibility, or learning effect.",
    }


def execute(package: Path) -> None:
    verify(package)
    config = read(package / "inputs/config.json")
    protocol = read(package / "protocol.json")
    tasks = read(package / "inputs/tasks.json")
    run = package / "run-01"
    ledger = read(run / "calls.json")
    for rel, digest in protocol["source_files"].items():
        if (
            rel.startswith("code_snapshot/")
            and sha(ROOT / rel.removeprefix("code_snapshot/")) != digest
        ):
            raise ValueError("execution code differs from prepared snapshot")
    if ledger or (run / "output_manifest.json").exists():
        raise ValueError("nonempty execution cannot be repeated or resumed in this bounded run")
    lock = run / "run.lock"
    with lock.open("x") as handle:
        handle.write(str(os.getpid()))
    started = time.monotonic()
    try:
        texts = list(
            dict.fromkeys(
                [t["proposition"]["text"] for t in tasks]
                + [binding._candidate_text(c) for t in tasks for c in t["candidates"]]
            )
        )
        vectors = embedding_batch(package, run, protocol, ledger, texts)
        lookup = dict(zip(texts, vectors, strict=True))
        for task in tasks:
            candidates = copy.deepcopy(task["candidates"])
            for c in candidates:
                c["local_path"] = str(shared._package_path(package, c["local_path"]))
            prop = task["proposition"]
            images = [str(shared._package_path(package, task["figure_path"]))] + [
                c["local_path"] for c in candidates
            ]

            def direct(prompt: str) -> str:
                labelled = {
                    "image_order": ["Source Figure 2 diagram region"]
                    + [c["id"] for c in candidates],
                    "request": json.loads(prompt),
                }
                raw, entry = shared._call_model(
                    package_root=package,
                    run_dir=run,
                    protocol=protocol,
                    ledger=ledger,
                    task_key=f"direct:{task['id']}",
                    stage="direct_binding",
                    model=config["models"]["method_model"],
                    prompt=json.dumps(labelled, ensure_ascii=False),
                    images=images,
                    max_tokens=config["models"]["max_tokens"],
                    system_prompt="Bind the narrated role to an object using source evidence and images. Return JSON only.",
                )
                if raw is None:
                    raise RuntimeError("STOPPED_AFTER_TRANSPORT_FAILURE")
                return raw

            results = {
                "lexical": binding.bind_lexical(
                    prop, candidates, threshold=config["thresholds"]["lexical"]
                ),
                "embedding": binding.bind_embedding(
                    prop,
                    candidates,
                    embed_fn=lambda text: lookup[text],
                    threshold=config["thresholds"]["embedding"],
                ),
                "source_conditioned": binding.bind_source_conditioned(
                    prop,
                    candidates,
                    threshold=config["thresholds"]["source_conditioned"],
                    allow_decision_bridge=False,
                ),
                "source_conditioned_no_source": binding.bind_source_conditioned(
                    {**prop, "source_refs": []},
                    candidates,
                    threshold=config["thresholds"]["source_conditioned"],
                    allow_decision_bridge=False,
                ),
            }
            results["embedding"]["embedding_backend"] = config["models"]["embedding_model"]
            try:
                results["direct_llm_vlm"] = binding.bind_direct_llm_vlm(
                    prop, candidates, model_fn=direct, model=config["models"]["method_model"],
                    required_target_role=config.get("required_target_role"),
                )
                results["direct_llm_vlm"]["comparator_mode"] = "VLM_PIXELS_VIA_LOGGED_MODEL_FN"
            except Exception as exc:
                results["direct_llm_vlm"] = {
                    "status": "INVALID_RESPONSE",
                    "selected_candidate_id": None,
                    "error": shared.client.redact_response_text(str(exc))[:500],
                }
            if any(c["status"] != "OK" for c in ledger):
                if config.get("context_relation_mode"):
                    results["source_conditioned_legacy"] = results.pop("source_conditioned")
                    results["source_conditioned_context_no_source"] = results.pop(
                        "source_conditioned_no_source"
                    )
                    results["source_conditioned_context"] = {
                        "status": "NOT_RUN_AFTER_TRANSPORT_FAILURE",
                        "selected_candidate_id": None,
                    }
                write(run / "bindings" / f"{task['id']}.json", results)
                raise RuntimeError("STOPPED_AFTER_TRANSPORT_FAILURE")
            if config.get("context_relation_mode"):
                results["source_conditioned_legacy"] = results.pop("source_conditioned")
                results.pop("source_conditioned_no_source")

                def context_model(prompt: str) -> str:
                    labelled = {
                        "image_order": ["Source Figure 2 diagram region"]
                        + [c["id"] for c in candidates],
                        "request": json.loads(prompt),
                    }
                    raw, entry = shared._call_model(
                        package_root=package,
                        run_dir=run,
                        protocol=protocol,
                        ledger=ledger,
                        task_key=f"context:{task['id']}",
                        stage="context_binding",
                        model=config["models"]["method_model"],
                        prompt=json.dumps(labelled, ensure_ascii=False),
                        images=images,
                        max_tokens=config["models"].get(
                            "context_max_tokens", config["models"]["max_tokens"]
                        ),
                        system_prompt="Assess source-supported object roles, preserve negation and ambiguity. Return only JSON with literal source evidence.",
                    )
                    if raw is None:
                        raise RuntimeError("STOPPED_AFTER_TRANSPORT_FAILURE")
                    return raw

                try:
                    results["source_conditioned_context"] = binding.bind_source_conditioned(
                        prop,
                        candidates,
                        threshold=config["thresholds"]["source_conditioned"],
                        allow_decision_bridge=False,
                        context_model_fn=context_model,
                    )
                except Exception as exc:
                    results["source_conditioned_context"] = {
                        "status": "INVALID_RESPONSE",
                        "selected_candidate_id": None,
                        "error": shared.client.redact_response_text(str(exc))[:500],
                    }
                results["source_conditioned_context_no_source"] = binding.bind_source_conditioned(
                    {**prop, "source_refs": [], "source_context": ""},
                    candidates,
                    threshold=config["thresholds"]["source_conditioned"],
                    context_model_fn=context_model,
                )
            write(run / "bindings" / f"{task['id']}.json", results)
            if any(c["status"] != "OK" for c in ledger):
                raise RuntimeError("STOPPED_AFTER_TRANSPORT_FAILURE")
            write(run / "report.json", summarize(package))
        for task in tasks:
            results = read(run / "bindings" / f"{task['id']}.json")
            eligible = valid_results(results)
            options, mapping = groups_for(eligible)
            images = [str(shared._package_path(package, task["figure_path"]))] + [
                str(shared._package_path(package, c["local_path"])) for c in task["candidates"]
            ]
            for alias in config["models"]["judge_models"]:
                for order in config["orders"]:
                    target = run / "judges" / f"{task['id']}-{alias}-{order}.json"
                    if not eligible:
                        write(target, {"status": "SKIPPED_NO_VALID_METHOD_OUTPUT",
                                       "excluded_methods": sorted(results)})
                        continue
                    prompt = judge_prompt(
                        task,
                        options if order == "forward" else list(reversed(options)),
                        config["judge_verdicts"],
                        required_target_role=config.get("required_target_role"),
                    )
                    raw, entry = shared._call_model(
                        package_root=package,
                        run_dir=run,
                        protocol=protocol,
                        ledger=ledger,
                        task_key=f"judge:{task['id']}:{alias}:{order}",
                        stage="binding_judge",
                        model=alias,
                        prompt=prompt,
                        images=images,
                        max_tokens=config["models"]["max_tokens"],
                        system_prompt="Independent instructional object-binding evaluator. Output JSON only; preserve uncertainty.",
                    )
                    row = {
                        "status": "INVALID_RESPONSE",
                        "mapping": mapping,
                        "excluded_methods": sorted(set(results) - set(eligible)),
                        "call_id": entry["call_id"],
                    }
                    if raw is not None:
                        try:
                            value = shared._parse_json_response(raw)
                            from jsonschema import Draft202012Validator

                            Draft202012Validator(json.loads(prompt)["output_json_schema"]).validate(
                                value
                            )
                            validate_judgment(
                                value,
                                [o["option_id"] for o in options],
                                task["source_context"],
                                config["judge_verdicts"],
                                options,
                            )
                            row.update(status="OK", judgment=value)
                        except Exception as exc:
                            row["parse_error"] = str(exc)[:500]
                    write(target, row)
                    write(run / "report.json", summarize(package))
                    if raw is None:
                        raise RuntimeError("STOPPED_AFTER_TRANSPORT_FAILURE")
        write(
            run / "execution.json",
            {"elapsed_sec": round(time.monotonic() - started, 3), "status": "COMPLETE"},
        )
        write(run / "report.json", summarize(package))
        manifest = {
            p.relative_to(run).as_posix(): sha(p)
            for p in run.rglob("*")
            if p.is_file() and p.name not in {"run.lock", "output_manifest.json"}
        }
        write(run / "output_manifest.json", manifest)
    finally:
        lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "verify", "execute", "analyze-only"])
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config-path", type=Path, default=CONFIG)
    args = parser.parse_args()
    package = args.package_root.resolve()
    if args.command == "prepare":
        prepare(package, args.config_path)
    elif args.command == "execute":
        execute(package)
    elif args.command == "verify":
        print(json.dumps(verify(package), ensure_ascii=False))
    else:
        verify(package)
        if not (package / "run-01/output_manifest.json").exists():
            raise ValueError("analyze-only requires a completed immutable run")
        if not args.output or args.output.exists():
            raise ValueError("analyze-only requires a fresh output path")
        before = sha(package / "run-01/calls.json")
        report = summarize(package)
        if sha(package / "run-01/calls.json") != before:
            raise ValueError("analysis altered the call ledger")
        write(args.output, {"report": report, "new_model_calls": 0, "calls_unchanged": True})


if __name__ == "__main__":
    main()
