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
from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
from textbook2video.research.visual_composition import execution_assets
from textbook2video.research.visual_tools import digest, run_visual_agent, verify_revision


def generate_course_visuals(
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
) -> dict[str, str]:
    results = {}
    root = output_dir / f"visual-tools-{uuid4().hex[:12]}"
    planned_segments = []
    for index, segment in enumerate(list(segments)):
        if segment.get("visual_type") in {"title", "cover", "section", "divider", "ending"}:
            planned_segments.append(segment)
            continue
        if rebuild_timing_before_tts:
            segment["visual_timing_rebuild"] = {
                "original_timeline": deepcopy(segment.get("timeline", [])),
                "original_animations": deepcopy(segment.get("animations", [])),
                "original_audio_duration_sec": segment.get("audio_duration_sec"),
                "status": "AWAITING_MEASURED_TTS_ALIGNMENT",
            }
            segment["timeline"], segment["animations"] = [], []
            segment.pop("audio_duration_sec", None)
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
        run_path = run_visual_agent(
            source,
            goal,
            root / f"page-{index + 1:03}",
            model=model,
            theme=theme,
            browser=browser,
            allow_images=allow_images,
            page_context=context,
            narration_text=segment["narration"],
        )
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run.get("status") != "MODEL_REVIEWED_PENDING_HUMAN" or not run.get("accepted_revision"):
            raise ValueError(f"visual tool review did not pass; see {run_path}")
        revision = Path(run["accepted_revision"])
        verify_revision(revision)
        approved_review = json.loads((revision / "review.json").read_text(encoding="utf-8"))
        approved_entries = [
            entry
            for entry in run["history"]
            if Path(entry["revision"]).resolve() == revision.resolve()
        ]
        if (
            approved_review.get("verdict") != "ACCEPT"
            or len(approved_entries) != 1
            or approved_entries[0].get("review_sha256") != digest(approved_review)
        ):
            raise ValueError("course asset review does not match the accepted revision")
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
                    child, asset, original_assets, primary_id, revision, run_path, source
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
                segment, asset, original_assets, primary_id, revision, run_path, source
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


def materialize_visual(segment, asset, all_assets, primary_id, revision, run_path, source):
    segment["elements"].append(
        {
            "id": primary_id,
            "type": "image",
            "description": asset["spec"]["title"],
            "visual_brief_role": "EXPLANATORY_DIAGRAM",
            "visual_tools_run": str(run_path),
            "visual_asset_sha256": asset["sha256"],
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
    record_path = run_path.parent / f"course-page-plan-{segment['id']}.json"
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
) -> Path:
    """Plan/split visuals before measured TTS creates a new page schedule."""
    board = json.loads(storyboard_path.read_text(encoding="utf-8"))
    original_narration = "".join(segment["narration"] for segment in board["segments"])
    directory = output_dir / f"course-visuals-{uuid4().hex[:12]}"
    directory.mkdir(parents=True, exist_ok=False)
    source = (
        source_path.read_text(encoding="utf-8") if source_path and source_path.is_file() else None
    )
    images = generate_course_visuals(
        board["segments"],
        output_dir=directory,
        model=model,
        theme=theme,
        browser=browser,
        source_text=source,
        rebuild_timing_before_tts=True,
        source_image_dir=storyboard_path.parent / "images",
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
        for element in segment["elements"]:
            key = f"{segment['id']}:{element['id']}"
            if key not in images:
                if element.get("src"):
                    original = storyboard_path.parent / "images" / element["src"]
                    if Path(element["src"]).name != element["src"] or not original.is_file():
                        raise ValueError("unresolved retained source image in planned course")
                    if not element.get("visual_tools_run"):
                        image_hash = hashlib.sha256(original.read_bytes()).hexdigest()
                        if image_hash in source_uses:
                            raise ValueError(
                                "a textbook image may be used on at most one course page"
                            )
                        source_uses.add(image_hash)
                    destination = image_dir / element["src"]
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
                    "visual_tools_run": element["visual_tools_run"],
                }
            )
    board["total_slides"] = len(board["segments"])
    board.setdefault("metadata", {})["course_visuals"] = {
        "producer": "visual-tools-before-tts",
        "source_storyboard": str(storyboard_path.resolve()),
        "source_storyboard_sha256": hashlib.sha256(storyboard_path.read_bytes()).hexdigest(),
        "source_scope": source_scope if source is not None else "narration-derived",
        "omitted_images": omitted_images,
        "assets": asset_inventory,
        "narration_sha256": digest(original_narration),
        "human_review": "NOT_REVIEWED",
    }
    destination = directory / storyboard_path.name
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(board, stream, ensure_ascii=False, indent=2)
    return destination
