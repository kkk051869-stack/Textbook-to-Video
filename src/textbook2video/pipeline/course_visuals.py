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
from textbook2video.research.visual_review_policy import POLICIES, review_disposition
from textbook2video.research.visual_tools import digest, run_visual_agent, verify_revision

NON_CONTENT_TYPES = {"title", "cover", "section", "divider", "ending"}


class EnhancementUnavailable(ValueError):
    """An enhancement could not be produced, not an integrity-check bypass."""


def generate_course_visuals(
    segments: list[dict], *, output_dir: Path, model: str, theme: str,
    browser: str = "msedge", allow_images: bool = True,
    source_text: str | None = None, rebuild_timing_before_tts: bool = False,
    source_image_dir: Path | None = None, max_iterations: int = 5,
    review_policy: str = "strict", rebuild_page_from_source: bool = False,
    failure_policy: str = "stop",
) -> dict[str, str]:
    """Commit each page only after enhancement succeeds; isolate generation failures.

    Fallback is for ordinary development production only. Verification failures
    deliberately remain fatal, as do invalid configuration and source binding.
    """
    if review_policy not in POLICIES:
        raise ValueError("review_policy must be strict or development")
    if failure_policy not in {"stop", "fallback"}:
        raise ValueError("failure_policy must be stop or fallback")
    if failure_policy == "fallback" and review_policy != "development":
        raise ValueError("fallback requires development review policy")
    if rebuild_page_from_source and any(
        s.get("visual_type") not in NON_CONTENT_TYPES for s in segments
    ) and (not rebuild_timing_before_tts or not source_text):
        raise ValueError("source-first page rebuild requires textbook text and planning before TTS")
    checkpoint = output_dir / f"course-pages-{uuid4().hex[:12]}"
    checkpoint.mkdir(parents=True, exist_ok=False)
    results, planned, journal = {}, [], []
    for index, original in enumerate(segments):
        candidate = [deepcopy(original)]
        page_dir = checkpoint / f"page-{index + 1:03}"
        page_dir.mkdir()
        try:
            images = _generate_course_visuals_strict(
                candidate, output_dir=page_dir, model=model, theme=theme,
                browser=browser, allow_images=allow_images, source_text=source_text,
                rebuild_timing_before_tts=rebuild_timing_before_tts,
                source_image_dir=source_image_dir, max_iterations=max_iterations,
                review_policy=review_policy, rebuild_page_from_source=rebuild_page_from_source,
                page_index_offset=index, run_root=page_dir,
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
    segments[:] = planned
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
    review_policy: str = "strict",
    rebuild_page_from_source: bool = True,
    failure_policy: str | None = None,
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
        review_policy=review_policy,
        rebuild_page_from_source=rebuild_page_from_source,
        failure_policy=failure_policy or ("fallback" if review_policy == "development" else "stop"),
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
        "page_strategy": (
            "mixed-with-original-fallbacks"
            if any(r["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED" for r in page_reviews)
            else requested_strategy if page_reviews else "no-content-pages"
        ),
        "requested_page_strategy": requested_strategy,
        "status": (
            "NOT_REVIEWED_NO_CONTENT_PAGES" if not page_reviews
            else "COMPLETED_WITH_ENHANCEMENT_FALLBACKS_PENDING_HUMAN"
            if any(r["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED" for r in page_reviews)
            else "DRAFT_WITH_WARNINGS_PENDING_HUMAN"
            if any(review.get("warnings") for review in page_reviews)
            else "MODEL_REVIEWED_PENDING_HUMAN"
        ),
        "page_reviews": page_reviews,
        "reviewed_page_count": sum(
            r["status"] != "FALLBACK_ORIGINAL_NOT_REVIEWED" for r in page_reviews
        ),
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
