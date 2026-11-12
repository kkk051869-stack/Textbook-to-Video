"""Adapt composed course visuals to the existing source-conditioned binder."""

import hashlib
import json
from pathlib import Path

from textbook2video.llm.client import chat_with_images, redact_response_text
from textbook2video.research.binding_methods import (
    CONTEXT_SEMANTIC_VERSION,
    bind_source_conditioned,
)


def _image_evidence(path: Path) -> dict:
    return {"local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _object_evidence(asset, element, directory, browser):
    from playwright.sync_api import sync_playwright

    svg = asset.read_bytes()
    if hashlib.sha256(svg).hexdigest() != element["visual_asset_sha256"]:
        raise ValueError("composed visual hash drift")
    directory.mkdir(parents=True)
    full = directory / "figure.png"
    candidates = []
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True, channel=browser or None)
        try:
            page = instance.new_page(viewport={"width": 1600, "height": 900})
            page.route("**/*", lambda route: route.abort())
            page.set_content(svg.decode("utf-8"))
            figure = page.locator("svg")
            figure.screenshot(path=str(full), timeout=5000)
            candidates.append({
                "id": element["id"], "text": element["description"], **_image_evidence(full),
            })
            for index, (target, obj) in enumerate(element["visual_object_targets"].items()):
                node = figure.locator(f'[data-node-id={json.dumps(obj["node_id"])}]')
                path = directory / f"object-{index}.png"
                node.screenshot(path=str(path), timeout=5000)
                candidates.append({
                    "id": target, "text": obj["description"], **_image_evidence(path),
                })
        finally:
            instance.close()
    return candidates, _image_evidence(full)


def bind_course_visuals(board, graph_path, image_dir, output_dir, *, review_model, browser):
    """Audit actual composed SVG objects and record v1.3 results."""
    pages = [
        (segment, element)
        for segment in board["segments"]
        for element in segment["elements"]
        if element.get("visual_acquisition_action") == "generate"
        and element.get("visual_object_targets")
    ]
    output_dir.mkdir()
    report = {"method": CONTEXT_SEMANTIC_VERSION, "results": []}
    if pages and graph_path:
        graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
        evidence = json.loads(Path(graph["source_evidence_path"]).read_text(encoding="utf-8"))
        units = {unit["id"]: unit["text"] for unit in evidence["source_units"]}
        propositions = {prop["id"]: prop for prop in graph["narration_propositions"]}
        for index, (segment, element) in enumerate(pages):
            for pid in element["proposition_ids"]:
                row = {"proposition_id": pid, "segment_id": segment["id"],
                       "element_id": element["id"]}
                report["results"].append(row)
                try:
                    prop = propositions[pid]
                    context = "\n\n".join(units[ref] for ref in prop["source_refs"])
                    candidates, figure = _object_evidence(
                        image_dir / element["src"], element,
                        output_dir / f"figure-{index}-{len(report['results'])}", browser,
                    )
                    candidate_images = [item["local_path"] for item in candidates]
                    result = bind_source_conditioned(
                        {**prop, "source_context": context}, candidates,
                        context_method_version=CONTEXT_SEMANTIC_VERSION,
                        source_evidence=evidence, semantic_full_figure=figure,
                        context_model_fn=lambda prompt: chat_with_images(
                            prompt, candidate_images, model=review_model, timeout=90,
                        ),
                        semantic_model_fn=lambda prompt, paths: chat_with_images(
                            prompt, paths, model=review_model, timeout=90,
                        ),
                        max_repair_rounds=1, repair_deadline_sec=180,
                        use_evidence_ids=True,
                    )
                    row.update(result=result, candidates=candidates)
                except Exception as exc:
                    row.update(status="BINDING_FAILED",
                               error=redact_response_text(str(exc)))
    report["status"] = (
        "BINDING_ATTEMPTED" if report["results"]
        else "MISSING_PROPOSITION_GRAPH" if pages
        else "NO_COMPOSED_GENERATED_OBJECTS"
    )
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
