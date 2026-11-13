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


def _object_evidence(asset, element, directory, browser, segment=None):
    from playwright.sync_api import sync_playwright

    directory.mkdir(parents=True)
    full = directory / "figure.png"
    candidates = []
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True, channel=browser or None)
        try:
            page = instance.new_page(viewport={"width": 1600, "height": 900})
            page.route("**/*", lambda route: route.abort())
            if asset is not None:
                import base64
                payload = asset.read_bytes()
                expected = element.get("visual_asset_sha256")
                if not expected:
                    raise ValueError("visual has no verified asset hash")
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise ValueError("composed visual hash drift")
                if asset.suffix.lower() == ".svg":
                    page.set_content(payload.decode("utf-8"))
                    figure = page.locator("svg")
                else:
                    import mimetypes
                    mime = mimetypes.guess_type(asset.name)[0] or "image/png"
                    encoded = base64.b64encode(payload).decode("ascii")
                    page.set_content(f'<img src="data:{mime};base64,{encoded}">')
                    figure = page.locator("img")
                    figure.evaluate("e => e.decode()")
            else:
                from textbook2video.template_renderer import render_slide
                html = render_slide(segment)
                if html is None:
                    raise ValueError("native component is not supported by template renderer")
                css = (Path(__file__).parents[1] / "templates/base.css").read_text(encoding="utf-8")
                page.set_content(f"<style>{css} .slide{{display:flex;opacity:1}} "
                                 f".anim{{opacity:1!important}}</style>{html}")
                page.locator(".slide").evaluate("e => e.classList.add('active')")
                page.locator(".anim").evaluate_all("es => es.forEach(e => e.classList.add('show'))")
                figure = page.locator(f'[data-anim-id={json.dumps(element["id"])}]')
            figure.screenshot(path=str(full), timeout=5000)
            candidates.append({"id": element["id"],
                               "text": element.get("description") or json.dumps(
                                   element, ensure_ascii=False),
                               **_image_evidence(full)})
            for index, (target, obj) in enumerate(element.get("visual_object_targets", {}).items()):
                node = figure.locator(f'[data-node-id={json.dumps(obj["node_id"])}]')
                path = directory / f"object-{index}.png"
                node.screenshot(path=str(path), timeout=5000)
                candidates.append({"id": target, "text": obj.get("description", obj["node_id"]),
                                   **_image_evidence(path)})
        finally:
            instance.close()
    return candidates, _image_evidence(full)


def _eligible_elements(board):
    """Eligibility follows actual visuals, independently of acquisition action."""
    for segment in board["segments"]:
        for element in segment["elements"]:
            if (element.get("type") == "image" or element.get("visual_object_targets")
                    or element.get("type") in {
                        "flow_step", "table", "comparison_panel", "formula"}):
                yield segment, element


def _propositions_for_element(segment, element, propositions):
    explicit = element.get("proposition_ids")
    if explicit:
        return [propositions[pid] for pid in explicit]
    # Same-page source-supported propositions are candidates, not accepted bindings.
    return [prop for prop in propositions.values()
            if str(prop.get("segment_id")) == str(segment["id"]) and prop.get("source_refs")]


def bind_course_visuals(board, graph_path, image_dir, output_dir, *, review_model, browser):
    """Bind actual composed SVG objects before production timing."""
    pages = list(_eligible_elements(board))
    output_dir.mkdir(parents=True)
    report = {"method": CONTEXT_SEMANTIC_VERSION, "results": [], "skipped": [
        {"segment_id": seg["id"], "reason": "NO_ADDRESSABLE_VISUAL_OBJECT"}
        for seg in board["segments"] if not any(s is seg for s, _ in pages)]}
    if pages and not graph_path:
        report["results"] = [
            {"segment_id": segment["id"], "element_id": element["id"],
             "status": "MISSING_PROPOSITION_GRAPH"}
            for segment, element in pages
        ]
    if pages and graph_path:
        graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
        evidence = json.loads(Path(graph["source_evidence_path"]).read_text(encoding="utf-8"))
        units = {unit["id"]: unit["text"] for unit in evidence["source_units"]}
        propositions = {prop["id"]: prop for prop in graph["narration_propositions"]}
        for index, (segment, element) in enumerate(pages):
            try:
                related = _propositions_for_element(segment, element, propositions)
            except KeyError as exc:
                report["skipped"].append({"segment_id": segment["id"], "element_id": element["id"],
                                          "reason": "UNKNOWN_PROPOSITION_ID", "detail": str(exc)})
                continue
            if not related:
                report["skipped"].append({"segment_id": segment["id"], "element_id": element["id"],
                                          "reason": "NO_SOURCE_SUPPORTED_PAGE_PROPOSITION"})
            for prop in related:
                pid = prop["id"]
                row = {"proposition_id": pid, "segment_id": segment["id"],
                       "element_id": element["id"]}
                report["results"].append(row)
                try:
                    prop = propositions[pid]
                    row.update(text=prop["text"], span=prop["span"])
                    context = "\n\n".join(units[ref] for ref in prop["source_refs"])
                    candidates, figure = _object_evidence(
                        (image_dir / element["src"] if element.get("src") else None), element,
                        output_dir / f"figure-{index}-{len(report['results'])}", browser, segment,
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
        else "NO_ELIGIBLE_VISUAL_OBJECTS"
    )
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return report


def apply_course_bindings(board, report):
    """Adapt accepted selections to existing dynamic-planner targets, fail closed."""
    segments = {str(segment["id"]): segment for segment in board["segments"]}
    for row in report["results"]:
        segment = segments[str(row["segment_id"])]
        segment.setdefault("course_binding_attempts", []).append(row)
        result = row.get("result", {})
        if (result.get("status") not in {"BOUND", "BOUND_MULTIPLE"}
                or result.get("semantic_check", {}).get("verdict") != "SUFFICIENT"):
            continue
        element = next(e for e in segment["elements"] if e["id"] == row["element_id"])
        targets = result.get("selected_candidate_ids") or [result.get("selected_candidate_id")]
        allowed = {element["id"], *element.get("visual_object_targets", {})}
        if not targets or any(target not in allowed for target in targets):
            row["adapter_status"] = "UNMAPPED_TARGET"
            continue
        span = row.get("span", {})
        if segment["narration"][span.get("start", 0):span.get("end", 0)] != row.get("text"):
            row["adapter_status"] = "NARRATION_SPAN_MISMATCH"
            continue
        segment.setdefault("course_visual_bindings", []).append({
            "proposition_id": row["proposition_id"], "parent_id": element["id"],
            "text": row["text"], "span": span, "targets": list(dict.fromkeys(targets)),
            "method": report["method"],
        })
        row["adapter_status"] = "CONNECTED_TO_DYNAMIC_PLANNER"
