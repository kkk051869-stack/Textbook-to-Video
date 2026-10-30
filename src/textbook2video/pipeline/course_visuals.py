"""Default course adapter for source-grounded visual tools.

Never silently return to freehand SVG after a rejected structured visual.
Measured narration/timings stay unchanged. Replaced targets are explicitly logged.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from textbook2video.animation_ids import normalize_element_ids
from textbook2video.pipeline.review_health import check_review_health
from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
from textbook2video.research.visual_composition import execution_assets
from textbook2video.research.visual_review_policy import POLICIES, review_disposition
from textbook2video.research.visual_tools import digest, run_visual_agent, verify_revision

NON_CONTENT_TYPES = {"title", "cover", "section", "divider", "ending"}


class EnhancementUnavailable(ValueError):
    """An enhancement could not be produced, not an integrity-check bypass."""


def prepare_course_asset_selection(
    storyboard_path: Path, source_path: Path, catalog_path: Path, output_dir: Path,
    *, model: str, review_model: str, lesson_plan_path: Path | None = None,
) -> dict:
    """Run the existing proposition/decision/acquisition chain for ordinary courses.

    Missing or rejected candidates request the existing visual agent; they never
    become accepted assets. This adapter defines no new model-facing protocol.
    """
    from textbook2video.research.proposition_graph import build_proposition_graph
    from textbook2video.research.source_evidence import build_source_evidence
    from textbook2video.research.visual_acquisition import execute_visual_acquisition
    from textbook2video.research.visual_decision import decide_visual_support

    output_dir.mkdir(parents=True, exist_ok=False)
    board = json.loads(storyboard_path.read_text(encoding="utf-8"))
    evidence_path = build_source_evidence(
        raw_path=source_path,
        available_images=board.get("metadata", {}).get("available_images", []),
        output_path=output_dir / "source_evidence.json",
    )
    graph_path = build_proposition_graph(
        raw_path=source_path, source_evidence_path=evidence_path,
        storyboard_path=storyboard_path, lesson_plan_path=lesson_plan_path,
        output_path=output_dir / "proposition_graph.json", model=model,
    )
    decisions_path = decide_visual_support(
        proposition_graph_path=graph_path, source_evidence_path=evidence_path,
        output_path=output_dir / "visual_decisions.json", model=model,
        retrieval_catalog_path=catalog_path, storyboard_path=storyboard_path,
    )
    acquired_path = execute_visual_acquisition(
        decision_path=decisions_path, output_dir=output_dir / "acquisition",
        retrieval_catalog_path=catalog_path, source_evidence_path=evidence_path,
        enable_generation=False, content_addressed_assets=True,
    )
    return _review_course_asset_selection(
        storyboard_path, source_path, output_dir, graph_path, decisions_path, acquired_path,
        review_model=review_model)


def _review_course_asset_selection(
    storyboard_path: Path, source_path: Path, output_dir: Path,
    graph_path: Path, decisions_path: Path, acquired_path: Path, *, review_model: str,
) -> dict:
    """Finish the existing acquisition stage, including from explicit saved inputs."""
    from textbook2video.llm.client import chat_with_images
    from textbook2video.research.visual_briefs import build_vlm_review_context
    from textbook2video.research.visual_tools import _json

    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / 'selection.json').exists():
        raise FileExistsError('course asset selection already exists')
    board = json.loads(storyboard_path.read_text(encoding='utf-8'))
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if graph.get('raw_sha256') != hashlib.sha256(source_path.read_bytes()).hexdigest():
        raise ValueError('saved acquisition source hash mismatch')
    decision_document = json.loads(decisions_path.read_text(encoding='utf-8'))
    acquired_document = json.loads(acquired_path.read_text(encoding='utf-8'))
    for value, key, expected in (
        (graph, 'storyboard_path', storyboard_path),
        (decision_document, 'storyboard_path', storyboard_path),
        (decision_document, 'proposition_graph_path', graph_path),
        (acquired_document, 'decision_path', decisions_path),
    ):
        if not isinstance(value.get(key), str) or Path(value[key]).resolve() != expected.resolve():
            raise ValueError('saved acquisition input chain mismatch')
    evidence_file = graph.get('source_evidence_path')
    if (not isinstance(evidence_file, str)
            or decision_document.get('source_evidence_path') != evidence_file
            or acquired_document.get('source_evidence_path') != evidence_file):
        raise ValueError('saved acquisition source evidence chain mismatch')
    evidence = json.loads(Path(evidence_file).read_text(encoding='utf-8'))
    if evidence.get('document', {}).get('sha256') != hashlib.sha256(
            source_path.read_text(encoding='utf-8').encode()).hexdigest():
        raise ValueError('saved acquisition source evidence hash mismatch')
    propositions = {p['id']: p for p in graph['narration_propositions']}
    decisions = decision_document['decisions']
    acquired = acquired_document['assets']
    by_prop = {a['proposition_id']: a for a in acquired}
    rows = {}
    source = source_path.read_text(encoding="utf-8")
    for segment in board['segments']:
        if segment.get('visual_type') in NON_CONTENT_TYPES:
            continue
        sid = str(segment['id'])
        local = [d for d in decisions if str(propositions[d['narration_proposition_id']]['segment_id']) == sid]
        row = {'decisions': local, 'assets': [], 'requires_generation': not bool(local)}
        row['propositions'] = [propositions[d['narration_proposition_id']] for d in local]
        for prop in row['propositions']:
            span = prop.get('span', {})
            start, end = span.get('start'), span.get('end')
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(segment['narration'])
                    or segment['narration'][start:end] != prop['text']):
                raise ValueError('course acquisition proposition span does not match narration')
        candidates = {}
        for decision in local:
            if decision.get('abstain') or decision.get('uncertain'):
                row['requires_generation'] = True
                continue
            if decision['action'] == 'none':
                continue
            asset = by_prop[decision['narration_proposition_id']]
            if asset['status'] not in {'SOURCE_REUSED_PENDING_VLM_REVIEW', 'RETRIEVED_LOCAL_RAG'}:
                row['requires_generation'] = True
                continue
            key = (asset['asset_id'], asset['sha256'])
            entry = candidates.setdefault(key, {'asset': asset, 'propositions': [], 'proposition_ids': []})
            entry['propositions'].append(propositions[decision['narration_proposition_id']]['text'])
            entry['proposition_ids'].append(decision['narration_proposition_id'])
        for index, candidate in enumerate(candidates.values()):
            asset = candidate['asset']
            proposition = '\n'.join(candidate['propositions'])
            context = build_vlm_review_context(
                {'id': asset['asset_id'], 'filename': asset['filename'],
                 'caption': asset.get('caption')}, segment_id=sid, proposition=proposition)
            request = {**context, 'source_text': source,
                       'response': {'verdict': 'ACCEPT|REJECT', 'visual_summary': 'visible content',
                                    'reason': 'source fidelity and relevance to ALL supplied propositions'}}
            prefix = output_dir / f"asset-review-{sid}-{index:03}"
            if prefix.with_suffix('.request.json').exists():
                raise FileExistsError('course asset review attempt already exists')
            prefix.with_suffix('.request.json').write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
            raw = chat_with_images(json.dumps(request, ensure_ascii=False), [asset['local_path']],
                                   model=review_model, temperature=0, max_tokens=1500, timeout=120,
                                   extra_body={'response_format': {'type': 'json_object'}})
            from textbook2video.llm.client import redact_response_text
            prefix.with_suffix('.response.txt').write_text(redact_response_text(raw), encoding='utf-8')
            report = _json(raw)
            if (report.get('verdict') not in {'ACCEPT', 'REJECT'}
                    or not isinstance(report.get('reason'), str) or not report['reason'].strip()
                    or not isinstance(report.get('visual_summary'), str) or not report['visual_summary'].strip()):
                raise ValueError('asset review requires verdict, reason and visual_summary')
            prefix.with_suffix('.review.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            if report['verdict'] == 'ACCEPT':
                row['assets'].append({**asset, 'review': report,
                                      'proposition_ids': candidate['proposition_ids'],
                                      'review_path': str(prefix.with_suffix('.review.json'))})
            else:
                row['requires_generation'] = True
        rows[sid] = row
    result = {'producer': 'ordinary-course-existing-acquisition-adapter-v1',
              'source_storyboard_sha256': hashlib.sha256(storyboard_path.read_bytes()).hexdigest(),
              'graph': str(graph_path), 'decisions': str(decisions_path),
              'acquisition': str(acquired_path), 'pages': rows, 'human_review': 'NOT_REVIEWED'}
    (output_dir / 'selection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def _split_mixed_acquisition_pages(segments: list[dict], selection: dict) -> tuple[list[dict], dict]:
    """Separate covered/missing spans using the existing exact proposition partition."""
    selection = deepcopy(selection)
    expanded = []
    reserved = {str(s['id']) for s in segments}
    for original in segments:
        row = selection['pages'].get(str(original['id']))
        if not row or not row['requires_generation'] or not row['assets']:
            expanded.append(original)
            continue
        props = sorted(row.get('propositions', []), key=lambda p: p['span']['start'])
        narration = original['narration']
        cursor = 0
        for prop in props:
            start, end = prop['span']['start'], prop['span']['end']
            if start != cursor or narration[start:end] != prop['text']:
                break
            cursor = end
        else:
            if cursor == len(narration) and props:
                covered = {p for a in row['assets'] for p in a['proposition_ids']}
                covered.update(d['narration_proposition_id'] for d in row['decisions']
                               if d['action'] == 'none' and not d.get('abstain') and not d.get('uncertain'))
                groups = []
                for prop in props:
                    ready = prop['id'] in covered
                    if not groups or groups[-1]['ready'] != ready:
                        groups.append({'ready': ready, 'props': []})
                    groups[-1]['props'].append(prop)
                if len(groups) > 1:
                    if any(e.get('type') != 'heading' for e in original['elements']):
                        raise ValueError(
                            'mixed acquisition split needs explicit component/event assignment; '
                            'refusing to discard original teaching content')
                    for index, group in enumerate(groups, 1):
                        ident = f"{original['id']}-visual-part-{index}"
                        if ident in reserved:
                            raise ValueError('mixed acquisition page ID collision')
                        reserved.add(ident)
                        part = deepcopy(original)
                        start, end = group['props'][0]['span']['start'], group['props'][-1]['span']['end']
                        part.update(id=ident, narration=narration[start:end],
                                    visual_origin_segment_id=original['id'],
                                    visual_origin_narration_span={'start': start, 'end': end})
                        part['elements'] = [e for e in part['elements'] if e.get('type') == 'heading']
                        part['elements'].append({'id': 'acquisition-narration', 'type': 'text',
                                                 'text': part['narration']})
                        prop_ids = {p['id'] for p in group['props']}
                        selection['pages'][ident] = {
                            'requires_generation': not group['ready'], 'propositions': group['props'],
                            'decisions': [d for d in row['decisions'] if d['narration_proposition_id'] in prop_ids],
                            'assets': [{**a, 'proposition_ids': [p for p in a['proposition_ids'] if p in prop_ids]}
                                       for a in row['assets'] if prop_ids.intersection(a['proposition_ids'])],
                        }
                        expanded.append(part)
                    continue
        row['mixed_split_abstain'] = 'No complete contiguous mixed narration partition'
        expanded.append(original)
    if ''.join(s['narration'] for s in expanded) != ''.join(s['narration'] for s in segments):
        raise ValueError('mixed acquisition changed narration')
    return expanded, selection


def compose_local_visual(
    segment: dict, *, revision: Path, asset_id: str, output_dir: Path,
    images: dict[str, str] | None = None, element_id: str | None = None,
    replace_element_id: str | None = None, coverage: dict | None = None,
    theme: str = "dark-blue-academic", browser: str = "msedge",
    engineering_fixture: bool = False, storyboard_path: Path | None = None,
) -> dict:
    """Explicit, offline-only local SVG admission; commit only after dual-viewport QA.

    Consume an existing sealed visual-tools revision, never run an agent/health
    check. Unreviewed revisions require the explicit engineering-fixture flag.
    Output must be a new directory; failures preserve diagnostics, not page edits.
    """
    from xml.etree import ElementTree as ET

    from textbook2video.pipeline.visual_page_plan import apply_local_visual_plan
    from textbook2video.pipeline.visual_page_render import course_page_html, validate_local_page

    revision = Path(revision).resolve()
    verify_revision(revision)
    source = json.loads((revision / "source.json").read_text(encoding="utf-8"))["source_text"]
    if not engineering_fixture:
        review_path = revision / "review.json"
        if not review_path.is_file():
            raise ValueError("unreviewed asset requires explicit engineering_fixture=True")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        revision_record = json.loads((revision / "revision.json").read_text(encoding="utf-8"))
        if not review_disposition(review, revision_record.get("geometry", []),
                                  revision_record.get("page_plan"))["strict_approved"]:
            raise ValueError("local asset has not passed the existing strict review gate")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"local composition output already exists: {output_dir}")
    if storyboard_path is not None:
        storyboard_path = Path(storyboard_path).resolve()
        source_storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        matches = [s for s in source_storyboard.get("segments", [])
                   if str(s.get("id")) == str(segment.get("id"))]
        if len(matches) != 1 or digest(matches[0]) != digest(segment):
            raise ValueError("segment must exactly match one page in storyboard_path")
        candidate_storyboard = deepcopy(source_storyboard)
    else:
        candidate_storyboard = {
            "lesson_title": "本地视觉合成预览",
            "segments": [deepcopy(segment)],
            "metadata": {},
        }
        storyboard_path = None
    assets = [a for a in execution_assets(revision) if a.get("id") == asset_id]
    if len(assets) != 1 or not assets[0].get("filename"):
        raise ValueError("local asset ID must identify exactly one compiled asset")
    asset = assets[0]
    path = revision / "compiled/assets" / asset["filename"]
    if path.suffix.lower() != ".svg":
        raise ValueError("local composition currently admits SVG assets only")
    svg = ET.fromstring(path.read_bytes())
    view_box = [float(v) for v in svg.attrib.get("viewBox", "").replace(",", " ").split()]
    if len(view_box) != 4 or not all(0 < v < 100000 for v in view_box[2:]):
        raise ValueError("local SVG requires a finite positive viewBox")
    # The ID depends on operation identity, never the element array position.
    ident = element_id or "local-visual-" + digest(
        [segment["id"], asset_id, asset["sha256"], replace_element_id]
    )[:16]
    candidate = deepcopy(segment)
    bundle_name = _unique_local_asset_name(asset["sha256"], candidate_storyboard)
    element = {"id": ident, "type": "image", "src": bundle_name,
               "description": asset["spec"]["title"], "visual_asset_sha256": asset["sha256"],
               "visual_brief_role": "EXPLANATORY_DIAGRAM",
               "local_visual_size": view_box[2:]}
    record = apply_local_visual_plan(
        candidate, element, replace_element_id=replace_element_id, coverage=coverage,
        visual_spec=asset["spec"], source_text=source,
    )
    record.update({"producer": "local-visual-composition-v1", "revision": str(revision),
                   "asset_id": asset_id, "asset_sha256": asset["sha256"],
                   "source_sha256": digest(source), "source_path": str(revision / "source.json"),
                   "semantic_review": "ENGINEERING_FIXTURE_NOT_REVIEWED" if engineering_fixture
                   else "EXISTING_MODEL_REVIEW_PENDING_HUMAN"})
    page_key = str(segment["id"])
    image_paths = dict(images or {})
    new_key = f"{page_key}:{ident}"
    image_paths[new_key] = str(path)
    for original in candidate["elements"]:
        if original.get("type") != "image":
            continue
        key = f"{page_key}:{original['id']}"
        image_path = image_paths.get(key)
        if image_path is None and storyboard_path is not None:
            image_path = str(storyboard_path.parent / "images" / original.get("src", ""))
            image_paths[key] = image_path
        if original.get("_render_blocked") or image_path is None:
            raise ValueError("local composition requires pixels for every retained image")
        actual_hash = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
        expected_hash = _expected_element_hash(candidate_storyboard, candidate, original)
        if expected_hash and actual_hash != expected_hash:
            raise ValueError(f"retained image hash drift: {key}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
        raise ValueError("local asset hash drift")
    record["input_segment_sha256"] = digest(segment)
    target_page = next(s for s in candidate_storyboard["segments"]
                       if str(s.get("id")) == page_key)
    target_page.clear()
    target_page.update(candidate)
    candidate_storyboard["metadata"] = candidate_storyboard.get("metadata") or {}
    if storyboard_path is None:
        candidate_storyboard["metadata"].setdefault("available_images", [])

    output_dir.mkdir(parents=True, exist_ok=False)
    image_paths = _copy_storyboard_images(
        candidate_storyboard, output_dir, supplied_images=images or {},
        storyboard_path=storyboard_path, new_asset_key=new_key, new_asset_path=path,
    )
    record["asset_inventory"] = [
        {"key": key, "path": Path(image_paths[key]).relative_to(output_dir).as_posix(),
         "sha256": hashlib.sha256(Path(image_paths[key]).read_bytes()).hexdigest()}
        for key in image_paths if key.split(":", 1)[0] == page_key
    ]
    _record_course_visual_asset(candidate_storyboard, candidate, element, asset)
    pending_storyboard = output_dir / ".storyboard.pending.json"
    pending_storyboard.write_text(
        json.dumps(candidate_storyboard, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        reloaded_segment, reloaded_images = load_local_storyboard_page(
            pending_storyboard, segment["id"]
        )
        static_html = course_page_html(reloaded_segment, reloaded_images, theme=theme)
        runtime_html = course_page_html(
            reloaded_segment, reloaded_images, theme=theme, static=False
        )
        (output_dir / "static.html").write_text(static_html, encoding="utf-8")
        (output_dir / "runtime.html").write_text(runtime_html, encoding="utf-8")
        report = validate_local_page(
            reloaded_segment, reloaded_images, output_dir=output_dir, browser=browser
        )
        if not report["passed"]:
            raise ValueError(
                f"local composition needs layout adjustment or page split; see {output_dir}"
            )
        verify_revision(revision)
        # Re-read the saved board and manifest after browser validation so the
        # commit depends only on the persisted bundle, not transient mappings.
        reloaded_segment, reloaded_images = load_local_storyboard_page(
            pending_storyboard, segment["id"]
        )
        persisted_page = next(
            s for s in candidate_storyboard["segments"] if str(s.get("id")) == page_key
        )
        persisted_page["local_visual_operations"][-1]["layout_report"] = str(
            output_dir / "layout.json"
        )
        report["save_reload_render"] = {
            "passed": True, "storyboard": "storyboard.json",
            "images_dir": "images", "source": "reloaded_storyboard_and_asset_inventory",
        }
        (output_dir / "layout.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        pending_storyboard.write_text(
            json.dumps(candidate_storyboard, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reloaded_segment, reloaded_images = load_local_storyboard_page(
            pending_storyboard, segment["id"]
        )
        final_storyboard = output_dir / "storyboard.json"
        pending_storyboard.replace(final_storyboard)
    except BaseException:
        pending_storyboard.unlink(missing_ok=True)
        raise
    # No earlier step is allowed to mutate the caller's page.
    segment.clear()
    segment.update(reloaded_segment)
    return {"images": reloaded_images, "storyboard": str(final_storyboard),
            "html": str(output_dir / "runtime.html"),
            "static_html": str(output_dir / "static.html"), "layout": report}


def load_local_storyboard_page(
    storyboard_path: Path, segment_id: str | int,
) -> tuple[dict, dict[str, str]]:
    """Reload a locally composed storyboard page and verify its copied images."""
    storyboard_path = Path(storyboard_path).resolve()
    board = json.loads(storyboard_path.read_text(encoding="utf-8"))
    matches = [s for s in board.get("segments", [])
               if str(s.get("id")) == str(segment_id)]
    if len(matches) != 1:
        raise ValueError("local storyboard page ID must resolve exactly once")
    segment = matches[0]
    operations = segment.get("local_visual_operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("storyboard page has no local visual asset inventory")
    inventory = {}
    for item in operations[-1].get("asset_inventory", []):
        key = item.get("key")
        if not isinstance(key, str) or key in inventory:
            raise ValueError("local visual image inventory has a duplicate or invalid key")
        relative = Path(str(item.get("path", "")))
        root = (storyboard_path.parent / "images").resolve()
        asset_path = (storyboard_path.parent / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not asset_path.is_relative_to(root):
            raise ValueError("local visual image inventory path escapes storyboard images/")
        if not asset_path.is_file():
            raise ValueError(f"local visual image is missing: {key}")
        actual_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        if actual_hash != item.get("sha256"):
            raise ValueError(f"local visual image hash drift: {key}")
        inventory[key] = str(asset_path)
    images = {}
    for element in segment.get("elements", []):
        if element.get("type") != "image":
            continue
        key = f"{segment['id']}:{element['id']}"
        if key not in inventory:
            raise ValueError(f"local storyboard image is absent from inventory: {key}")
        expected_hash = _expected_element_hash(board, segment, element)
        actual_hash = hashlib.sha256(Path(inventory[key]).read_bytes()).hexdigest()
        if expected_hash and actual_hash != expected_hash:
            raise ValueError(f"storyboard expected image hash drift: {key}")
        images[key] = inventory[key]
    return segment, images


def _expected_element_hash(storyboard: dict, segment: dict, element: dict) -> str | None:
    expected = set()
    value = element.get("visual_asset_sha256")
    if value:
        expected.add(str(value).lower())
    segment_id, element_id, src = str(segment.get("id")), str(element.get("id")), element.get("src")
    metadata = storyboard.get("metadata") or {}
    course_assets = (metadata.get("course_visuals") or {}).get("assets", [])
    for item in course_assets if isinstance(course_assets, list) else []:
        if not isinstance(item, dict):
            continue
        page_element_match = (
            str(item.get("segment_id")) == segment_id
            and str(item.get("element_id")) == element_id
        )
        if page_element_match or (src and item.get("filename") == src):
            for field in ("sha256", "asset_sha256", "visual_asset_sha256"):
                if item.get(field):
                    expected.add(str(item[field]).lower())
    source_id = element.get("source_image_id")
    available = metadata.get("available_images", [])
    for item in available if isinstance(available, list) else []:
        if not isinstance(item, dict):
            continue
        if ((source_id and str(item.get("id")) == str(source_id))
                or (src and item.get("filename") == src)):
            for field in ("sha256", "asset_sha256", "visual_asset_sha256"):
                if item.get(field):
                    expected.add(str(item[field]).lower())
    for operation in segment.get("local_visual_operations", []):
        for item in operation.get("asset_inventory", []):
            if not isinstance(item, dict):
                continue
            if item.get("key") == f"{segment_id}:{element_id}" and item.get("sha256"):
                expected.add(str(item["sha256"]).lower())
    if len(expected) > 1:
        raise ValueError(
            f"conflicting expected hashes for retained image {segment_id}:{element_id}"
        )
    if expected:
        value = next(iter(expected))
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"invalid expected image hash for {segment_id}:{element_id}")
        return value
    return None


def _unique_local_asset_name(sha256: str, storyboard: dict) -> str:
    metadata = storyboard.get("metadata") or {}
    reserved = {
        str(element.get("src")).casefold()
        for segment in storyboard.get("segments", [])
        for element in segment.get("elements", [])
        if element.get("src")
    }
    for items in (metadata.get("available_images", []),
                  (metadata.get("course_visuals") or {}).get("assets", [])):
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            filename = item.get("filename")
            if filename:
                reserved.add(str(filename).casefold())
    base = f"local-visual-{sha256[:16]}"
    name = f"{base}.svg"
    suffix = 1
    while name.casefold() in reserved:
        suffix += 1
        name = f"{base}-{suffix}.svg"
    return name


def _copy_storyboard_images(
    storyboard: dict, output_dir: Path, *, supplied_images: dict[str, str],
    storyboard_path: Path | None, new_asset_key: str, new_asset_path: Path,
) -> dict[str, str]:
    image_dir = output_dir / "images"
    image_dir.mkdir()
    names: dict[str, tuple[str, str]] = {}
    paths: dict[str, str] = {}
    target_ids = {
        f"{segment['id']}:{element['id']}"
        for segment in storyboard["segments"]
        for element in segment.get("elements", [])
        if element.get("type") == "image"
    }
    for segment in storyboard["segments"]:
        for element in segment.get("elements", []):
            if element.get("type") != "image":
                continue
            key = f"{segment['id']}:{element['id']}"
            src = str(element.get("src", ""))
            if not src or Path(src).name != src or "/" in src or "\\" in src or src in {".", ".."}:
                raise ValueError(f"storyboard image src must be a filename: {src!r}")
            if key == new_asset_key:
                source_path = new_asset_path
            else:
                source_path_value = supplied_images.get(key)
                if source_path_value is None and storyboard_path is not None:
                    source_path_value = str(storyboard_path.parent / "images" / src)
                if source_path_value is None:
                    raise ValueError(f"local storyboard bundle has no image pixels for {key}")
                source_path = Path(source_path_value)
            if not source_path.is_file():
                raise ValueError(f"local storyboard image is missing: {key}")
            data = source_path.read_bytes()
            actual_hash = hashlib.sha256(data).hexdigest()
            expected_hash = _expected_element_hash(storyboard, segment, element)
            if expected_hash and actual_hash != expected_hash:
                raise ValueError(f"retained image hash drift: {key}")
            if key == new_asset_key and actual_hash != element.get("visual_asset_sha256"):
                raise ValueError("local visual hash drift during bundle copy")
            if src.casefold() in names:
                existing_name, existing_hash = names[src.casefold()]
                if existing_hash == actual_hash:
                    name = existing_name
                else:
                    name = _collision_filename(src, actual_hash, names)
            elif any(name.casefold() == src.casefold() for name, _ in names.values()):
                name = _collision_filename(src, actual_hash, names)
            else:
                name = src
            collision = names.get(name.casefold())
            if collision and collision[1] != actual_hash:
                name = _collision_filename(src, actual_hash, names)
            destination = image_dir / name
            if not destination.exists():
                with destination.open("xb") as stream:
                    stream.write(data)
            elif hashlib.sha256(destination.read_bytes()).hexdigest() != actual_hash:
                raise ValueError(f"image filename collision could not be resolved: {name}")
            names[name.casefold()] = (name, actual_hash)
            if name != src:
                element["src"] = name
            paths[key] = str(destination.resolve())
            _record_copied_image_hash(storyboard, element, actual_hash, src, name)
    missing = target_ids.difference(paths)
    if missing:
        raise ValueError(f"local storyboard images were not copied: {sorted(missing)}")
    return paths


def _collision_filename(src: str, sha256: str, names: dict[str, tuple[str, str]]) -> str:
    path = Path(src)
    base = f"{path.stem}-{sha256[:12]}"
    suffix = path.suffix
    name = f"{base}{suffix}"
    index = 1
    while name.casefold() in names:
        old = names[name.casefold()]
        if old[1] == sha256:
            return old[0]
        index += 1
        name = f"{base}-{index}{suffix}"
    return name


def _record_copied_image_hash(storyboard: dict, element: dict, sha256: str,
                              source_name: str, output_name: str) -> None:
    metadata = storyboard.setdefault("metadata", {})
    available = metadata.get("available_images", [])
    source_id = element.get("source_image_id")
    for item in available if isinstance(available, list) else []:
        if not isinstance(item, dict):
            continue
        if ((source_id and str(item.get("id")) == str(source_id))
                or item.get("filename") in {source_name, output_name}):
            existing = item.get("sha256")
            if existing and str(existing).lower() != sha256:
                raise ValueError(f"available image manifest hash drift: {source_name}")
            item["sha256"] = sha256


def _record_course_visual_asset(storyboard: dict, segment: dict,
                                element: dict, asset: dict) -> None:
    metadata = storyboard.setdefault("metadata", {})
    course_visuals = metadata.setdefault("course_visuals", {})
    inventory = course_visuals.setdefault("assets", [])
    if not isinstance(inventory, list):
        raise ValueError("storyboard course_visuals.assets must be a list")
    inventory.append({
        "segment_id": segment["id"], "element_id": element["id"],
        "filename": element["src"], "sha256": asset["sha256"],
        "visual_tools_run": True, "producer": "local-visual-composition-v1",
        "asset_id": asset["id"],
    })


def generate_course_visuals(
    segments: list[dict], *, output_dir: Path, model: str, theme: str,
    browser: str = "msedge", allow_images: bool = True,
    source_text: str | None = None, rebuild_timing_before_tts: bool = False,
    source_image_dir: Path | None = None, max_iterations: int = 5,
    review_policy: str = "strict", rebuild_page_from_source: bool = False,
    failure_policy: str = "stop",
    review_model: str | None = None,
    cache_dir: Path | None = None,
    asset_selection: dict | None = None,
) -> dict[str, str]:
    """Commit each page only after enhancement succeeds; isolate generation failures.

    Fallback is for ordinary development production only. Verification failures
    deliberately remain fatal, as do invalid configuration and source binding.
    """
    if review_policy not in POLICIES:
        raise ValueError("review_policy must be strict or development")
    if asset_selection is not None and review_policy != 'development':
        raise ValueError('asset selection pending page review requires development policy')
    if failure_policy not in {"stop", "fallback"}:
        raise ValueError("failure_policy must be stop or fallback")
    if failure_policy == "fallback" and review_policy != "development":
        raise ValueError("fallback requires development review policy")
    if rebuild_page_from_source and any(
        s.get("visual_type") not in NON_CONTENT_TYPES for s in segments
    ) and (not rebuild_timing_before_tts or not source_text):
        raise ValueError("source-first page rebuild requires textbook text and planning before TTS")
    checkpoint = output_dir / f"course-pages-{uuid4().hex[:8]}"
    checkpoint.mkdir(parents=True, exist_ok=False)
    input_segments = segments
    if asset_selection is not None:
        segments, asset_selection = _split_mixed_acquisition_pages(segments, asset_selection)
        if len(segments) != len(input_segments) and not rebuild_timing_before_tts:
            raise ValueError('mixed acquisition page splitting requires planning before TTS')
    health_checked = False

    def ensure_review_health():
        nonlocal health_checked
        if not health_checked:
            check_review_health(checkpoint / "review-health", model=review_model or model)
            health_checked = True

    results, planned, journal = {}, [], []
    for index, original in enumerate(segments):
        candidate = [deepcopy(original)]
        page_dir = checkpoint / f"page-{index + 1:03}"
        page_dir.mkdir()
        selection = (asset_selection or {}).get('pages', {}).get(str(original['id']))
        if selection is not None and not selection['requires_generation']:
            selected = deepcopy(original)
            selected['visual_timing_rebuild'] = {
                'original_timeline': deepcopy(original.get('timeline', [])),
                'original_animations': deepcopy(original.get('animations', [])),
                'original_audio_duration_sec': original.get('audio_duration_sec'),
                'status': 'PRESERVED_EVENTS_PENDING_ALIGNMENT_REVIEW',
                'page_strategy': 'preserve-components-with-acquisition',
                'reason': 'Selected assets fill visual gaps; no component replacement authorized',
                'original_elements': deepcopy(original['elements']),
                'requested_rebuild_page_from_source': rebuild_page_from_source,
            }
            for asset in selection['assets']:
                path = Path(asset['local_path'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
                    raise ValueError('selected course visual hash drift')
                persisted = json.loads(Path(asset['review_path']).read_text(encoding='utf-8'))
                if persisted != asset['review'] or persisted.get('verdict') != 'ACCEPT':
                    raise ValueError('selected course visual review changed')
                matching = []
                for existing in selected['elements']:
                    if existing.get('type') != 'image' or not existing.get('src'):
                        continue
                    src = Path(existing['src'])
                    if src.name != str(src) or source_image_dir is None:
                        raise ValueError('retained acquisition image requires a local source directory')
                    original_path = source_image_dir / src
                    actual = hashlib.sha256(original_path.read_bytes()).hexdigest()
                    if existing.get('visual_asset_sha256', actual) != actual:
                        raise ValueError('retained acquisition image hash drift')
                    if actual == asset['sha256']:
                        matching.append(existing)
                if len(matching) > 1:
                    raise ValueError('selected asset matches multiple original image objects')
                if matching:
                    existing = matching[0]
                    existing.update(
                        visual_asset_sha256=asset['sha256'],
                        proposition_ids=asset['proposition_ids'],
                        visual_brief_proposition=next(
                            p['text'] for p in selection['propositions']
                            if p['id'] in asset['proposition_ids']),
                        acquisition_review_path=asset['review_path'],
                        visual_relevance_verdict=persisted['verdict'],
                    )
                    results[f"{original['id']}:{existing['id']}"] = str(path)
                    continue
                ident = f"acquired-{asset['sha256'][:16]}"
                if any(e['id'] == ident for e in selected['elements']):
                    raise ValueError('acquired visual element ID collision')
                selected['elements'].append({
                    'id': ident, 'type': 'image', 'description': persisted['visual_summary'],
                    'visual_asset_sha256': asset['sha256'],
                    'proposition_ids': asset['proposition_ids'],
                    'visual_brief_proposition': next(
                        p['text'] for p in selection['propositions'] if p['id'] in asset['proposition_ids']),
                    'acquisition_review_path': asset['review_path'],
                })
                results[f"{original['id']}:{ident}"] = str(path)
            selected['visual_review'] = {
                'policy': review_policy, 'status': 'ASSET_SELECTION_PENDING_PAGE_REVIEW',
                'model_verdict': 'NOT_REVIEWED', 'human_review': 'NOT_REVIEWED',
                'warnings': [], 'acquisition_decisions': selection['decisions'],
            }
            planned.append(selected)
            (page_dir / 'asset-selection.json').write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf-8')
            continue
        try:
            if cache_dir is None and original.get('visual_type') not in NON_CONTENT_TYPES:
                ensure_review_health()
            images = _generate_course_visuals_strict(
                candidate, output_dir=page_dir, model=model, theme=theme,
                review_model=review_model,
                browser=browser, allow_images=allow_images, source_text=source_text,
                rebuild_timing_before_tts=rebuild_timing_before_tts,
                source_image_dir=source_image_dir, max_iterations=max_iterations,
                review_policy=review_policy, rebuild_page_from_source=rebuild_page_from_source,
                page_index_offset=index, run_root=page_dir,
                cache_dir=cache_dir,
                ensure_review_health=ensure_review_health if cache_dir else None,
            )
        except EnhancementUnavailable as error:
            if failure_policy == "stop":
                raise
            restored = deepcopy(original)
            omitted = []
            for element in restored.get("elements", []):
                if element.get("type") == "image" and not element.get("src"):
                    element["_render_blocked"] = True
                    omitted.append(deepcopy(element))
            if rebuild_timing_before_tts:
                restored["visual_timing_rebuild"] = {
                    "original_timeline": deepcopy(original.get("timeline", [])),
                    "original_animations": deepcopy(original.get("animations", [])),
                    "original_audio_duration_sec": original.get("audio_duration_sec"),
                    "status": "AWAITING_MEASURED_TTS_ALIGNMENT",
                    "page_strategy": "fallback-original",
                }
                restored["timeline"], restored["animations"] = [], []
                restored.pop("audio_duration_sec", None)
            restored["visual_review"] = {
                "policy": review_policy, "status": "FALLBACK_ORIGINAL_NOT_REVIEWED",
                "model_verdict": "NOT_REVIEWED", "human_review": "NOT_REVIEWED",
                "warnings": [str(error)], "failure_type": type(error).__name__,
                "evidence_dir": str(page_dir.resolve()), "omitted_image_intents": omitted,
            }
            candidate, images = [restored], {}
            print(f"  ⚠️ Page {original['id']}: enhancement unavailable; using original storyboard")
        if "".join(s["narration"] for s in candidate) != original["narration"]:
            raise ValueError("course planning changed narration")
        if len(candidate) == 1:
            original.clear()
            original.update(candidate[0])
            candidate = [original]
        planned.extend(candidate)
        results.update(images)
        journal.append({"original_segment_id": original["id"], "segments": candidate,
                        "images": images})
        # Separate immutable checkpoints survive a later page/process failure.
        with (page_dir / "checkpoint.json").open("x", encoding="utf-8") as stream:
            json.dump(journal[-1], stream, ensure_ascii=False, indent=2)
    input_segments[:] = planned
    with (checkpoint / "completed.json").open("x", encoding="utf-8") as stream:
        json.dump(journal, stream, ensure_ascii=False, indent=2)
    return results


def _generate_course_visuals_strict(
    segments: list[dict],
    *,
    output_dir: Path,
    model: str,
    theme: str,
    browser: str = "msedge",
    allow_images: bool = True,
    source_text: str | None = None,
    rebuild_timing_before_tts: bool = False,
    source_image_dir: Path | None = None,
    max_iterations: int = 5,
    review_policy: str = "strict",
    rebuild_page_from_source: bool = False,
    page_index_offset: int = 0,
    run_root: Path | None = None,
    review_model: str | None = None,
    cache_dir: Path | None = None,
    ensure_review_health=None,
) -> dict[str, str]:
    if review_policy not in POLICIES:
        raise ValueError("review_policy must be strict or development")
    results = {}
    root = run_root if run_root is not None else output_dir / f"visual-tools-{uuid4().hex[:12]}"
    planned_segments = []
    for index, segment in enumerate(list(segments)):
        index += page_index_offset
        if segment.get("visual_type") in NON_CONTENT_TYPES:
            planned_segments.append(segment)
            continue
        if rebuild_page_from_source and (not rebuild_timing_before_tts or not source_text):
            raise ValueError(
                "source-first page rebuild requires textbook text and planning before TTS"
            )
        if rebuild_timing_before_tts:
            segment["visual_timing_rebuild"] = {
                "original_timeline": deepcopy(segment.get("timeline", [])),
                "original_animations": deepcopy(segment.get("animations", [])),
                "original_audio_duration_sec": segment.get("audio_duration_sec"),
                "status": "AWAITING_MEASURED_TTS_ALIGNMENT",
            }
            segment["timeline"], segment["animations"] = [], []
            segment.pop("audio_duration_sec", None)
        if rebuild_page_from_source:
            segment["visual_timing_rebuild"].update({
                "original_elements": deepcopy(segment.get("elements", [])),
                "page_strategy": "source-narration-rebuild",
                "scope": (
                    "Full original narration and textbook source; legacy visuals are audit only"
                ),
            })
            segment["elements"] = [
                element for element in segment.get("elements", [])
                if element.get("type") == "heading"
            ]
        segment["elements"] = normalize_element_ids(segment.get("elements", []))
        for element in segment["elements"]:
            if element.get("type") == "image" and element.get("src") and source_image_dir:
                path = (source_image_dir / element["src"]).resolve()
                if not path.is_relative_to(source_image_dir.resolve()):
                    raise ValueError("source image must stay inside its declared image directory")
                if path.is_file():
                    element["source_image_path"] = str(path)
        targets = [e for e in segment.get("elements", []) if e.get("type") == "image"]
        primary_id = f"visual-primary-{index + 1}"
        existing_ids = {str(e["id"]) for e in segment["elements"]}
        while primary_id in existing_ids:
            primary_id += "-new"
        context = [
            e for e in segment.get("elements", []) if e.get("type") not in {"heading", "subheading"}
        ]
        source = (
            source_text if source_text is not None else str(segment.get("narration") or "").strip()
        )
        if not source:
            raise ValueError(
                "visual tools require actual segment narration, not image instructions"
            )
        goal = next(
            (
                str(e.get("text"))
                for e in segment.get("elements", [])
                if e.get("type") == "heading" and e.get("text")
            ),
            source[:120],
        )
        from litellm.exceptions import (
            APIConnectionError,
            APIError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )
        from playwright.sync_api import Error as BrowserError

        try:
            from textbook2video.research.visual_cache import file_hash, run_cached

            cache_options = {}
            if cache_dir is not None:
                inventory = ({p.relative_to(source_image_dir).as_posix(): file_hash(p)
                              for p in sorted(source_image_dir.rglob('*')) if p.is_file()}
                             if source_image_dir and source_image_dir.is_dir() else {})
                cache_options['cache_context'] = {
                    'source_images': inventory, 'rebuild_page': rebuild_page_from_source,
                    'before_tts': rebuild_timing_before_tts,
                }
            run_path = run_cached(
                run_visual_agent,
                source,
                goal,
                root / "agent",
                cache_dir=cache_dir, before_run=ensure_review_health, **cache_options,
                model=model,
                review_model=review_model,
                theme=theme,
                browser=browser,
                allow_images=allow_images,
                page_context=context,
                narration_text=segment["narration"],
                max_iterations=max_iterations,
                review_policy=review_policy,
            )
        except (
            APIError, APIConnectionError, InternalServerError, RateLimitError,
            ServiceUnavailableError, Timeout, BrowserError, TimeoutError, ConnectionError,
        ) as error:
            raise EnhancementUnavailable(
                f"visual generation transport/render failure ({type(error).__name__}); see {root}"
            ) from error
        run = json.loads(run_path.read_text(encoding="utf-8"))
        draft = run.get("status") == "DRAFT_WITH_WARNINGS_PENDING_HUMAN"
        selected_revision = run.get("usable_revision") if draft else run.get("accepted_revision")
        if (
            run.get("status") not in {
                "MODEL_REVIEWED_PENDING_HUMAN", "DRAFT_WITH_WARNINGS_PENDING_HUMAN"
            }
            or not selected_revision
            or (
                draft and (
                    review_policy != "development" or run.get("review_policy") != "development"
                )
            )
        ):
            raise EnhancementUnavailable(f"visual tool review did not pass; see {run_path}")
        revision = Path(selected_revision)
        verify_revision(revision)
        approved_review = json.loads((revision / "review.json").read_text(encoding="utf-8"))
        record = json.loads((revision / "revision.json").read_text(encoding="utf-8"))
        disposition = review_disposition(
            approved_review, record.get("geometry", []), record.get("page_plan")
        )
        approved_entries = [
            entry
            for entry in run["history"]
            if Path(entry["revision"]).resolve() == revision.resolve()
        ]
        if (
            not disposition["draft_usable" if draft else "strict_approved"]
            or len(approved_entries) != 1
            or approved_entries[0].get("review_sha256") != digest(approved_review)
        ):
            raise ValueError("course asset review does not match the accepted revision")
        segment["visual_review"] = {
            "policy": review_policy, "status": run["status"],
            "model_verdict": approved_review["verdict"],
            "warnings": disposition["warnings"], "human_review": "NOT_REVIEWED",
            "run_path": str(run_path),
        }
        manifest = json.loads(
            (revision / "compiled/visual_assets.json").read_text(encoding="utf-8")
        )
        original_assets = manifest["assets"]
        if any(
            not asset.get("filename") and asset["spec"]["kind"] != "none"
            for asset in original_assets
        ):
            raise ValueError(
                "course visual sequence contains failed generation; cannot omit panels"
            )
        assets = [a for a in execution_assets(revision) if a.get("filename")]
        if len(assets) > 1:
            if not rebuild_timing_before_tts:
                raise ValueError(
                    f"visual panels need a course page split before TTS; see {run_path}"
                )
            spans = [asset["spec"].get("narration_span") for asset in assets]
            if (
                any(not isinstance(span, str) or not span for span in spans)
                or "".join(spans) != segment["narration"]
            ):
                raise ValueError("split panels must partition narration verbatim without gaps")
            for panel_index, (asset, span) in enumerate(zip(assets, spans, strict=True), 1):
                child = deepcopy(segment)
                child["id"] = f"{segment['id']}-panel-{panel_index}"
                child["narration"] = span
                child["visual_origin_segment_id"] = segment["id"]
                for heading in child["elements"]:
                    if heading.get("type") == "heading":
                        heading["text"] = asset["spec"]["title"]
                materialize_visual(
                    child, asset, original_assets, primary_id, revision, run_path, source,
                    audit_dir=root,
                )
                planned_segments.append(child)
                results[f"{child['id']}:{primary_id}"] = str(
                    revision / "compiled/assets" / asset["filename"]
                )
            continue
        if assets:
            asset = assets[0]
            results[f"{segment['id']}:{primary_id}"] = str(
                revision / "compiled/assets" / asset["filename"]
            )
            materialize_visual(
                segment, asset, original_assets, primary_id, revision, run_path, source,
                audit_dir=root,
            )
        else:
            for target in targets:
                target["_render_blocked"] = True
                target["visual_tools_run"] = str(run_path)
        planned_segments.append(segment)
    segments[:] = planned_segments
    if root.exists():
        with (root / "effective_segments.json").open("x", encoding="utf-8") as stream:
            json.dump(segments, stream, ensure_ascii=False, indent=2)
    return results


def compiled_visual_object_targets(asset: dict, element_id: str, revision: Path) -> dict:
    """Bind only physically present nodes of this exact compiled asset."""
    from textbook2video.animation_ids import visual_node_animation_id

    graph = asset['spec'].get('diagram', asset['spec'])
    physical_ids = set()
    if asset.get('filename', '').endswith('.svg'):
        from xml.etree import ElementTree as ET
        path = revision / 'compiled/assets' / asset['filename']
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
            raise ValueError('compiled visual object asset hash drift')
        physical_ids = {obj.get('data-node-id') for obj in ET.parse(path).getroot().iter()}
    return {visual_node_animation_id(element_id, node['id']): {
        'node_id': node['id'],
        'description': ' '.join(str(node.get(k) or '') for k in ('label', 'detail')).strip()}
        for node in graph.get('nodes', []) if node.get('id') in physical_ids}


def materialize_visual(
    segment, asset, all_assets, primary_id, revision, run_path, source, *, audit_dir=None
):
    objects = compiled_visual_object_targets(asset, primary_id, revision)
    segment["elements"].append(
        {
            "id": primary_id,
            "type": "image",
            "description": asset["spec"]["title"],
            "visual_brief_role": "EXPLANATORY_DIAGRAM",
            "visual_tools_run": str(run_path),
            "visual_asset_sha256": asset["sha256"],
            "visual_object_targets": objects,
        }
    )
    record = json.loads((revision / "revision.json").read_text(encoding="utf-8"))
    page_plan = record.get("page_plan") or {
        "support_element_ids": [],
        "replaces_element_ids": [],
        "reason": "No competing body elements",
        "coverage": [],
    }
    applied = apply_visual_page_plan(
        segment,
        primary_id,
        page_plan,
        visual_specs=[a["spec"] for a in all_assets],
        source_text=source,
    )
    applied["coverage_scope"] = "panel_sequence" if len(all_assets) > 1 else "single_panel"
    record_path = (audit_dir or run_path.parent.parent) / f"course-page-plan-{segment['id']}.json"
    with record_path.open("x", encoding="utf-8") as stream:
        json.dump(applied, stream, ensure_ascii=False, indent=2)


def prepare_course_storyboard(
    storyboard_path: Path,
    *,
    output_dir: Path,
    model: str,
    theme: str,
    browser: str,
    source_path: Path | None = None,
    source_scope: str = "provided-raw-text",
    review_policy: str = "strict",
    rebuild_page_from_source: bool = True,
    failure_policy: str | None = None,
    review_model: str | None = None,
    cache_dir: Path | None = None,
    retrieval_catalog_path: Path | None = None,
    lesson_plan_path: Path | None = None,
    asset_selection_path: Path | None = None,
) -> Path:
    """Plan/split visuals before measured TTS creates a new page schedule."""
    if (retrieval_catalog_path is not None or asset_selection_path is not None) and review_policy != 'development':
        raise ValueError('ordinary acquisition pending page review requires development policy')
    if retrieval_catalog_path is not None and asset_selection_path is not None:
        raise ValueError('choose a catalog or an explicit saved asset selection, not both')
    board = json.loads(storyboard_path.read_text(encoding="utf-8"))
    original_narration = "".join(segment["narration"] for segment in board["segments"])
    directory = output_dir / f"v-{uuid4().hex[:8]}"
    directory.mkdir(parents=True, exist_ok=False)
    source = (
        source_path.read_text(encoding="utf-8") if source_path and source_path.is_file() else None
    )
    effective_failure_policy = failure_policy or (
        "fallback" if review_policy == "development" else "stop"
    )
    asset_selection = None
    if asset_selection_path is not None:
        asset_selection = json.loads(asset_selection_path.read_text(encoding='utf-8'))
        if asset_selection.get('source_storyboard_sha256') != hashlib.sha256(storyboard_path.read_bytes()).hexdigest():
            raise ValueError('saved asset selection storyboard hash mismatch')
        graph = json.loads(Path(asset_selection['graph']).read_text(encoding='utf-8'))
        if source_path is None or graph.get('raw_sha256') != hashlib.sha256(source_path.read_bytes()).hexdigest():
            raise ValueError('saved asset selection source hash mismatch')
    if retrieval_catalog_path is not None:
        if source_path is None or not source_path.is_file():
            raise ValueError('course asset selection requires actual textbook source')
        asset_selection = prepare_course_asset_selection(
            storyboard_path, source_path, retrieval_catalog_path, directory / 'asset-selection',
            model=model, review_model=review_model or model,
            lesson_plan_path=lesson_plan_path,
        )
    if asset_selection is not None:
        for segment in board['segments']:
            for element in segment['elements']:
                if element.get('type') == 'image' and element.get('src'):
                    src = Path(element['src'])
                    if src.name != str(src):
                        raise ValueError('retained source image filename is not local')
                    actual = hashlib.sha256(
                        (storyboard_path.parent / 'images' / src).read_bytes()).hexdigest()
                    expected = _expected_element_hash(board, segment, element)
                    if expected and actual != expected:
                        raise ValueError('retained acquisition image hash drift')
    images = generate_course_visuals(
        board["segments"],
        output_dir=directory,
        model=model,
        review_model=review_model,
        cache_dir=cache_dir,
        theme=theme,
        browser=browser,
        source_text=source,
        rebuild_timing_before_tts=True,
        source_image_dir=storyboard_path.parent / "images",
        review_policy=review_policy,
        rebuild_page_from_source=rebuild_page_from_source,
        failure_policy=effective_failure_policy,
        asset_selection=asset_selection,
    )
    if "".join(s["narration"] for s in board["segments"]) != original_narration:
        raise ValueError("course planning changed narration")
    image_dir = directory / "images"
    image_dir.mkdir()
    source_uses = set()
    omitted_images = []
    reserved_names = {
        str(e.get("src")).casefold()
        for s in board["segments"]
        for e in s["elements"]
        if e.get("src")
    }
    asset_inventory = []
    asset_index = 0
    for segment in board["segments"]:
        for element in list(segment["elements"]):
            if element.get("type") == "image" and element.get("_render_blocked"):
                omitted_images.append({"segment_id": segment["id"], "element": element})
                segment["elements"].remove(element)
        for element in list(segment["elements"]):
            key = f"{segment['id']}:{element['id']}"
            if key not in images:
                if element.get("src"):
                    original = storyboard_path.parent / "images" / element["src"]
                    if Path(element["src"]).name != element["src"] or not original.is_file():
                        raise ValueError("unresolved retained source image in planned course")
                    if not element.get("visual_tools_run"):
                        image_hash = hashlib.sha256(original.read_bytes()).hexdigest()
                        preserving = segment.get('visual_timing_rebuild', {}).get(
                            'page_strategy') == 'preserve-components-with-acquisition'
                        if image_hash in source_uses and not preserving:
                            if effective_failure_policy == "fallback":
                                omitted_images.append({
                                    "segment_id": segment["id"], "element": deepcopy(element),
                                    "reason": "duplicate-textbook-image-not-reused",
                                })
                                segment["elements"].remove(element)
                                # No stale event may refer to an omitted original image.
                                for timing_key in ("timeline", "animations"):
                                    surviving = []
                                    for event in segment.get(timing_key, []):
                                        event = deepcopy(event)
                                        target = event.get("target")
                                        if isinstance(target, str):
                                            targets = [t.strip() for t in target.split(",")]
                                            kept = [t for t in targets if t != str(element["id"])]
                                            if not kept:
                                                continue
                                            event["target"] = ",".join(kept)
                                        surviving.append(event)
                                    segment[timing_key] = surviving
                                continue
                            raise ValueError(
                                "a textbook image may be used on at most one course page"
                            )
                        source_uses.add(image_hash)
                    destination = image_dir / element["src"]
                    if not destination.exists():
                        with original.open("rb") as reader, destination.open("xb") as writer:
                            shutil.copyfileobj(reader, writer)
                    if (
                        hashlib.sha256(destination.read_bytes()).hexdigest()
                        != hashlib.sha256(original.read_bytes()).hexdigest()
                    ):
                        raise ValueError("retained source image changed during copy")
                continue
            path = Path(images[key])
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if source_hash != element.get("visual_asset_sha256"):
                raise ValueError("reviewed visual asset hash drift before course copy")
            asset_index += 1
            name = f"generated-{source_hash[:16]}-{asset_index:03}{path.suffix}"
            suffix_index = 0
            while name.casefold() in reserved_names or (image_dir / name).exists():
                suffix_index += 1
                name = f"generated-{source_hash[:16]}-{asset_index:03}-{suffix_index}{path.suffix}"
            reserved_names.add(name.casefold())
            destination = image_dir / name
            with path.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != source_hash:
                raise ValueError("reviewed visual asset changed during copy")
            element["src"] = name
            asset_inventory.append(
                {
                    "segment_id": segment["id"],
                    "element_id": element["id"],
                    "filename": name,
                    "sha256": source_hash,
                    "visual_tools_run": element.get("visual_tools_run"),
                    "acquisition_review_path": element.get("acquisition_review_path"),
                }
            )
    board["total_slides"] = len(board["segments"])
    board.setdefault('metadata', {})['total_slides'] = len(board['segments'])
    page_reviews = [
        {"segment_id": s["id"], **s["visual_review"]}
        for s in board["segments"]
        if s.get("visual_type") not in NON_CONTENT_TYPES and s.get("visual_review")
    ]
    requested_strategy = (
        "source-narration-rebuild" if rebuild_page_from_source else "preserve-legacy-elements"
    )
    board.setdefault("metadata", {})["course_visuals"] = {
        "producer": "visual-tools-before-tts",
        "source_storyboard": str(storyboard_path.resolve()),
        "source_storyboard_sha256": hashlib.sha256(storyboard_path.read_bytes()).hexdigest(),
        "source_scope": (
            (source_scope if source is not None else "narration-derived")
            if page_reviews else "not-used-no-content-pages"
        ),
        "omitted_images": omitted_images,
        "assets": asset_inventory,
        "narration_sha256": digest(original_narration),
        "human_review": "NOT_REVIEWED",
        "review_policy": review_policy,
        "review_model": review_model or model,
        "page_strategy": (
            "mixed-with-original-fallbacks"
            if any(r["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED" for r in page_reviews)
            else "visual-acquisition-before-generation" if asset_selection is not None
            else requested_strategy if page_reviews else "no-content-pages"
        ),
        "requested_page_strategy": requested_strategy,
        "status": (
            "NOT_REVIEWED_NO_CONTENT_PAGES" if not page_reviews
            else "COMPLETED_WITH_ENHANCEMENT_FALLBACKS_PENDING_HUMAN"
            if any(r["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED" for r in page_reviews)
            else "ASSET_SELECTION_PENDING_PAGE_REVIEW"
            if any(r["status"] == "ASSET_SELECTION_PENDING_PAGE_REVIEW" for r in page_reviews)
            else "DRAFT_WITH_WARNINGS_PENDING_HUMAN"
            if any(review.get("warnings") for review in page_reviews)
            else "MODEL_REVIEWED_PENDING_HUMAN"
        ),
        "page_reviews": page_reviews,
        "reviewed_page_count": sum(
            r["status"] in {"MODEL_REVIEWED_PENDING_HUMAN", "DRAFT_WITH_WARNINGS_PENDING_HUMAN"}
            for r in page_reviews
        ),
        "asset_selected_page_count": sum(
            r["status"] == "ASSET_SELECTION_PENDING_PAGE_REVIEW" for r in page_reviews),
        "asset_selection_path": str(asset_selection_path or directory / 'asset-selection/selection.json')
        if asset_selection is not None else None,
        "fallback_page_count": sum(
            r["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED" for r in page_reviews
        ),
        "skipped_pages": [
            {"segment_id": s["id"], "reason": "non-content-page-not-reviewed"}
            for s in board["segments"] if s.get("visual_type") in NON_CONTENT_TYPES
        ],
    }
    with (directory / "visual-review-report.json").open("x", encoding="utf-8") as stream:
        json.dump(board["metadata"]["course_visuals"], stream, ensure_ascii=False, indent=2)
    destination = directory / storyboard_path.name
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(board, stream, ensure_ascii=False, indent=2)
    return destination
