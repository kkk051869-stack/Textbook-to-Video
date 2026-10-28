"""Verified cross-run reuse; indexes reference retained, immutable run evidence."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_binding(
    source,
    goal,
    *,
    model,
    review_model=None,
    theme,
    browser,
    allow_images,
    page_context,
    narration_text,
    review_policy,
    **unused,
):
    from textbook2video.llm import client, image_gen
    from textbook2video.research import visual_synthesis

    package = Path(__file__).resolve().parents[1]
    code = {
        str(p.relative_to(package)): file_hash(p)
        for p in sorted(package.rglob("*"))
        if p.is_file() and p.suffix in {".py", ".json", ".md", ".js", ".css"}
    }
    context = deepcopy(page_context)
    for element in context or []:
        if element.get("source_image_path"):
            element["source_image_sha256"] = file_hash(element["source_image_path"])
    return {
        "version": 1,
        "source": digest(source),
        "goal": digest(goal),
        "narration": digest(narration_text if narration_text is not None else source),
        "context": digest(context),
        "model": model,
        "review_model": review_model or model,
        "theme": theme,
        "browser": browser,
        "allow_images": allow_images,
        "review_policy": review_policy,
        "endpoint": digest(client.LLM_BASE_URL),
        "image_endpoint": digest(image_gen.LLM_BASE_URL),
        "image_model": visual_synthesis.compile_visuals.__kwdefaults__["image_model"],
        "image_size": image_gen.generate_image.__kwdefaults__["size"],
        "code": digest(code),
        "cache_context": digest(unused.get("cache_context")),
        "runtime": {
            name: importlib.metadata.version(name)
            for name in ("playwright", "jsonschema", "litellm")
        },
    }


def artifact_hashes(directory):
    return {
        p.relative_to(directory).as_posix(): file_hash(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p != directory / "run.json"
    }


def read_run(path, binding, seen=None):
    from textbook2video.research.visual_tools import (
        RevisionIntegrityError,
        verify_failure,
        verify_revision,
    )

    path = Path(path)
    seen = set() if seen is None else seen
    identity = str(path.resolve()).casefold()
    if identity in seen:
        raise RevisionIntegrityError("cyclic resumed run chain")
    seen.add(identity)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("input_binding") != binding:
        raise RevisionIntegrityError("run input/code/policy binding changed; cannot resume")
    if state.get("artifact_hashes") != artifact_hashes(path.parent):
        raise RevisionIntegrityError("run artifacts changed; cannot reuse or resume")
    if state.get("resumed_from"):
        previous = Path(state["resumed_from"])
        if file_hash(previous) != state.get("resumed_run_sha256"):
            raise RevisionIntegrityError("resumed parent run manifest changed")
        read_run(previous, binding, seen)
    for entry in state["history"]:
        directory = Path(entry["revision"])
        if (directory / "revision.json").exists():
            verify_revision(directory)
        else:
            verify_failure(directory)
    return state


def usable_run(state):
    from textbook2video.research.visual_review_policy import review_disposition

    draft = state["status"] == "DRAFT_WITH_WARNINGS_PENDING_HUMAN"
    selected = state.get("usable_revision") if draft else state.get("accepted_revision")
    if not selected or state["status"] not in {
        "MODEL_REVIEWED_PENDING_HUMAN",
        "DRAFT_WITH_WARNINGS_PENDING_HUMAN",
    }:
        return False
    directory = Path(selected)
    review = json.loads((directory / "review.json").read_text(encoding="utf-8"))
    record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    matches = [e for e in state["history"] if Path(e["revision"]).resolve() == directory.resolve()]
    disposition = review_disposition(review, record.get("geometry", []), record.get("page_plan"))
    return (
        len(matches) == 1
        and review.get("model") == state.get("review_model")
        and matches[0].get("review_sha256") == digest(review)
        and disposition["draft_usable" if draft else "strict_approved"]
        and (not draft or state.get("review_policy") == "development")
    )


def run_cached(agent, source, goal, output_dir, *, cache_dir=None, before_run=None, **kwargs):
    if cache_dir is None:
        if before_run:
            before_run()
        return agent(source, goal, output_dir, **kwargs)
    from textbook2video.research.visual_tools import RevisionIntegrityError

    binding = input_binding(source, goal, **kwargs)
    directory = Path(cache_dir).resolve() / digest(binding)
    directory.mkdir(parents=True, exist_ok=True)
    resume = None
    missing = []
    for entry in sorted(directory.glob("*.json"), reverse=True):
        index = json.loads(entry.read_text(encoding="utf-8"))
        if index.get("binding") != binding:
            raise RevisionIntegrityError("cache index binding drift")
        path = Path(index["run"])
        if not path.is_file():
            missing.append(str(path))
            continue
        if file_hash(path) != index["run_sha256"]:
            raise RevisionIntegrityError("cache run manifest hash drift")
        state = read_run(path, binding)
        if usable_run(state):
            _event(output_dir, {"status": "HIT_VERIFIED", "run": str(path), "missing": missing})
            return path
        if resume is None:
            resume = path
    _event(
        output_dir,
        {
            "status": "RESUME" if resume else "MISS",
            "from": str(resume) if resume else None,
            "missing": missing,
        },
    )
    if before_run:
        before_run()
    try:
        return agent(source, goal, output_dir, resume_from=resume, **kwargs)
    finally:
        path = Path(output_dir) / "run.json"
        if path.exists():
            read_run(path, binding)
            payload = {
                "binding": binding,
                "run": str(path.resolve()),
                "run_sha256": file_hash(path),
            }
            name = f"{time.time_ns()}-{uuid4().hex}"
            temporary = directory / (name + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(directory / (name + ".json"))


def _event(output_dir, value):
    path = Path(output_dir).with_name(Path(output_dir).name + "-cache.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def recover_candidate(parent, destination, *, browser):
    """Reuse sealed pixels, or compiled assets whose previous render failed."""
    from textbook2video.research import visual_tools as tools
    from textbook2video.research.visual_draft_graph import read_draft, save_draft_result

    parent, destination = Path(parent), Path(destination)
    sealed = (parent / "revision.json").exists()
    if sealed:
        tools.verify_revision(parent)
        record = json.loads((parent / "revision.json").read_text(encoding="utf-8"))
        parent_record = deepcopy(record)
    else:
        parent_record = tools.verify_failure(parent)
        record = json.loads((parent / "render-pending.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=False)
    for name in (
        "source.json",
        "request.json",
        "raw_tool_request.json",
        "specs.json",
        "edit_base.json",
        "composition_assets.json",
        "draft-graph.json",
    ):
        if (parent / name).exists():
            shutil.copy2(parent / name, destination / name)
    draft = read_draft(destination) if (destination / "draft-graph.json").exists() else None
    if draft:
        record["draft_sha256"] = draft["sha256"]
        record["reused_draft_from"] = str(parent.resolve())
        if sealed:
            shutil.copy2(parent / "draft-result.json", destination / "draft-result.json")
    shutil.copytree(parent / "compiled", destination / "compiled")
    record.update(
        parent=str(parent.resolve()),
        parent_sha256=tools.digest(parent_record),
        manifest=str((destination / "compiled/visual_assets.json").resolve()),
        recovery_stage="review" if sealed else "render",
    )
    record.pop("execution_sha256", None)
    findings = []
    for name in (
        "prior-review-findings.json",
        "review-response.txt",
        "review-response-retry-1.txt",
    ):
        if (parent / name).exists():
            try:
                findings.append(tools._json((parent / name).read_text(encoding="utf-8")))
            except ValueError:
                pass
    carried = merge_findings(findings)
    if carried:
        tools._save(destination / "prior-review-findings.json", carried)
    if sealed:
        geometry = deepcopy(record.get("geometry", []))
        for index, capture in enumerate(geometry):
            path = destination / f"recovered-{index}.png"
            shutil.copy2(capture["screenshot"], path)
            capture["screenshot"] = str(path.resolve())
        record["geometry"] = geometry
        tools._save(destination / "geometry.json", geometry)
    else:
        tools._save(destination / "render-pending.json", record)
        try:
            record["geometry"] = tools.preview_revision(destination, browser=browser)
        except Exception as error:
            draft_binding = ({"draft_sha256": draft["sha256"], "draft_result_sha256":
                              save_draft_result(destination, draft, error)} if draft else {})
            tools._save(
                destination / "failure.json",
                {
                    "status": "FAILED_PRESERVED",
                    "error_type": type(error).__name__,
                    "parent": str(parent.resolve()),
                    "parent_sha256": tools.digest(parent_record),
                    "edit_base_sha256": record.get("edit_base_sha256"),
                    **draft_binding,
                },
            )
            raise
        if draft:
            record["draft_result_sha256"] = save_draft_result(destination, draft)
    record["integrity_version"] = "visual-revision-v2"
    record["execution_sha256"] = tools.digest(record)
    tools._save(destination / "revision.json", record)
    tools.verify_revision(destination)
    return destination


def merge_findings(reports):
    """A protocol/transport retry of identical pixels cannot erase negative findings."""
    from textbook2video.research.visual_fact_audit import fact_audit_findings
    from textbook2video.research.visual_relation_semantics import relation_findings

    reports = [r for r in reports if isinstance(r, dict)]
    if not reports:
        return None
    result = {"verdict": "ACCEPT", "checks": {}, "scores": {}, "issues": [], "coverage": []}
    for report in reports:
        semantic = relation_findings(report) + fact_audit_findings(report)
        if semantic:
            if result["verdict"] != "REJECT":
                result["verdict"] = "REVISE"
            for finding in semantic:
                if finding not in result["issues"]:
                    result["issues"].append(finding)
                key = "accuracy" if finding["category"] == "factual_error" else "completeness"
                result["checks"][key] = False
        if report.get("verdict") == "REJECT":
            result["verdict"] = "REJECT"
        elif report.get("verdict") == "REVISE" and result["verdict"] != "REJECT":
            result["verdict"] = "REVISE"
        for field in ("issues", "coverage"):
            for item in report.get(field, []) if isinstance(report.get(field, []), list) else []:
                if item not in result[field]:
                    result[field].append(item)
        for key, value in (
            (report.get("checks") or {}).items() if isinstance(report.get("checks"), dict) else []
        ):
            if value is False:
                result["checks"][key] = False
        for key, value in (
            (report.get("scores") or {}).items() if isinstance(report.get("scores"), dict) else []
        ):
            if type(value) is int and 0 <= value <= 4:
                result["scores"][key] = min(value, result["scores"].get(key, value))
    return result
