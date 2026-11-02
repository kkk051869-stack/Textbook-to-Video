"""Replay a saved, hash-verified offline course bundle through the existing renderer.

This is a recovery entry point for reviewed development inputs. It does not run
produce, request models, generate images, synthesize speech, or overwrite a run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# This repository has several concurrent worktrees. Prefer the source beside
# this script over an editable .venv install that may point at another tree.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOCAL_SRC = _REPO_ROOT / "src"
if str(_LOCAL_SRC) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SRC))


class BundleValidationError(ValueError):
    """The saved bundle is incomplete, inconsistent, or has a hash mismatch."""


@dataclass(frozen=True)
class ValidatedBundle:
    root: Path
    manifest: dict[str, Any]
    storyboard: dict[str, Any]
    execution_map: dict[str, Any]
    asset_reviews: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(root: Path, value: str, *, label: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise BundleValidationError(f"{label} escapes bundle root: {value}") from exc
    if not candidate.is_file():
        raise BundleValidationError(f"{label} is missing: {value}")
    return candidate


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleValidationError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise BundleValidationError(f"{label} must be a JSON object")
    return value


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as source:
            rate = source.getframerate()
            if rate <= 0:
                raise BundleValidationError(f"invalid WAV sample rate: {path}")
            return source.getnframes() / rate
    except (wave.Error, OSError) as exc:
        raise BundleValidationError(f"audio must be a readable PCM WAV: {path}") from exc


def validate_course_dev_bundle(bundle_dir: str | Path) -> ValidatedBundle:
    """Validate immutable bundle files, image provenance, and audio mapping."""
    root = Path(bundle_dir).resolve()
    if not root.is_dir():
        raise BundleValidationError(f"bundle directory does not exist: {root}")

    manifest = _read_json(root / "manifest.json", label="manifest")
    if manifest.get("schema") != "course-dev-bundle-v1":
        raise BundleValidationError("unsupported course development bundle schema")
    for key in ("storyboard", "execution_map", "asset_reviews"):
        if not isinstance(manifest.get(key), str):
            raise BundleValidationError(f"manifest.{key} must be a relative file path")

    declared_files = manifest.get("files")
    if not isinstance(declared_files, list) or not declared_files:
        raise BundleValidationError("manifest.files must list hashed bundle inputs")
    listed: set[str] = set()
    for record in declared_files:
        if not isinstance(record, dict):
            raise BundleValidationError("manifest.files entries must be objects")
        relative = record.get("path")
        expected = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise BundleValidationError("manifest file entries require path and sha256")
        if relative in listed:
            raise BundleValidationError(f"duplicate manifest file entry: {relative}")
        listed.add(relative)
        path = _relative_file(root, relative, label="manifest file")
        actual = sha256_file(path)
        if actual != expected:
            raise BundleValidationError(
                f"hash mismatch for {relative}: expected {expected}, got {actual}"
            )

    required = {manifest["storyboard"], manifest["execution_map"], manifest["asset_reviews"]}
    if not required.issubset(listed):
        raise BundleValidationError(
            "manifest must hash storyboard, execution map, and review records"
        )

    storyboard_path = _relative_file(root, manifest["storyboard"], label="storyboard")
    map_path = _relative_file(root, manifest["execution_map"], label="execution map")
    reviews_path = _relative_file(root, manifest["asset_reviews"], label="asset review records")
    storyboard = _read_json(storyboard_path, label="storyboard")
    execution_map = _read_json(map_path, label="execution map")
    asset_reviews = _read_json(reviews_path, label="asset review records")

    segments = storyboard.get("segments")
    audio_entries = execution_map.get("audio")
    if not isinstance(segments, list) or not segments:
        raise BundleValidationError("storyboard must contain segments")
    if not isinstance(audio_entries, list) or len(audio_entries) != len(segments):
        raise BundleValidationError("audio map must contain exactly one entry per segment")

    segments_by_id: dict[str, dict[str, Any]] = {}
    for segment in segments:
        if not isinstance(segment, dict) or segment.get("id") is None:
            raise BundleValidationError("every storyboard segment needs an id")
        segment_id = str(segment["id"])
        if segment_id in segments_by_id:
            raise BundleValidationError(f"duplicate segment id: {segment_id}")
        segments_by_id[segment_id] = segment

    audio_ids: set[str] = set()
    for entry in audio_entries:
        if not isinstance(entry, dict):
            raise BundleValidationError("audio map entries must be objects")
        segment_id = str(entry.get("derived_segment_id", ""))
        if segment_id not in segments_by_id or segment_id in audio_ids:
            raise BundleValidationError(
                f"audio map has a missing or duplicate segment: {segment_id}"
            )
        audio_ids.add(segment_id)
        segment = segments_by_id[segment_id]
        relative_audio = entry.get("path")
        if not isinstance(relative_audio, str):
            raise BundleValidationError(f"audio path is missing for segment {segment_id}")
        audio_path = _relative_file(root, relative_audio, label=f"audio for {segment_id}")
        if sha256_file(audio_path) != entry.get("sha256"):
            raise BundleValidationError(f"audio hash mismatch for segment {segment_id}")
        narration = str(segment.get("narration") or "")
        actual_narration_hash = hashlib.sha256(narration.encode("utf-8")).hexdigest()
        if actual_narration_hash != entry.get("narration_sha256"):
            raise BundleValidationError(f"narration hash mismatch for segment {segment_id}")
        measured_duration = _wav_duration(audio_path)
        declared_duration = float(entry.get("duration_sec", -1))
        storyboard_duration = float(segment.get("audio_duration_sec", -1))
        if abs(measured_duration - declared_duration) > 0.03:
            raise BundleValidationError(f"audio duration differs from map for segment {segment_id}")
        if abs(measured_duration - storyboard_duration) > 0.03:
            raise BundleValidationError(
                f"audio duration differs from storyboard for segment {segment_id}"
            )

    if audio_ids != set(segments_by_id):
        raise BundleValidationError("audio mapping does not cover every storyboard segment")

    assets: dict[str, dict[str, Any]] = {}
    for asset in execution_map.get("assets", []):
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            raise BundleValidationError("execution map asset entries require relative paths")
        relative = asset["path"]
        path = _relative_file(root, relative, label="visual asset")
        actual = sha256_file(path)
        if actual != asset.get("sha256"):
            raise BundleValidationError(f"visual asset hash mismatch: {relative}")
        assets[Path(relative).as_posix()] = asset

    for segment in segments:
        segment_id = str(segment["id"])
        for element in segment.get("elements", []) or []:
            if not isinstance(element, dict) or element.get("type") != "image":
                continue
            source = element.get("src")
            if not isinstance(source, str):
                continue  # Existing source admission will reject incomplete image references.
            relative = (Path("images") / source).as_posix()
            path = _relative_file(root, relative, label=f"image for segment {segment_id}")
            asset = assets.get(relative)
            if asset is None:
                raise BundleValidationError(f"image is not catalogued in execution map: {relative}")
            actual = sha256_file(path)
            if actual != asset.get("sha256"):
                raise BundleValidationError(
                    f"image hash mismatch in segment {segment_id}: {source}"
                )
            expected_inline_hash = element.get("visual_asset_sha256")
            if expected_inline_hash and expected_inline_hash != actual:
                raise BundleValidationError(
                    f"inline SVG hash mismatch in segment {segment_id}: {source}"
                )

    if not isinstance(asset_reviews.get("records"), list):
        raise BundleValidationError("asset review records must contain a records list")
    for review in asset_reviews["records"]:
        if not isinstance(review, dict):
            raise BundleValidationError("asset review record must be an object")
        evidence = review.get("evidence_files", [])
        if not isinstance(evidence, list):
            raise BundleValidationError("review evidence_files must be a list")
        for item in evidence:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise BundleValidationError("review evidence entries need relative path and sha256")
            path = _relative_file(root, item["path"], label="review evidence")
            if sha256_file(path) != item.get("sha256"):
                raise BundleValidationError(f"review evidence hash mismatch: {item['path']}")

    if manifest.get("offline_only") is not True:
        raise BundleValidationError("bundle must explicitly declare offline_only=true")
    return ValidatedBundle(root, manifest, storyboard, execution_map, asset_reviews)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_bundle_inputs(bundle: ValidatedBundle, output: Path) -> tuple[Path, Path, Path]:
    input_dir = output / "input"
    input_dir.mkdir(parents=True)
    storyboard_path = input_dir / "storyboard.json"
    map_path = input_dir / "execution-map.json"
    reviews_path = input_dir / "asset-review-records.json"
    _write_json(storyboard_path, bundle.storyboard)
    _write_json(map_path, bundle.execution_map)
    _write_json(reviews_path, bundle.asset_reviews)
    shutil.copytree(bundle.root / "images", input_dir / "images")
    shutil.copytree(bundle.root / "reviews", input_dir / "reviews")
    shutil.copytree(bundle.root / "audio", output / "audio")
    shutil.copy2(bundle.root / "manifest.json", input_dir / "bundle-manifest.json")
    return storyboard_path, map_path, reviews_path


def _capture_static_screenshots(
    html: Path, output: Path, *, browser_channel: str
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    captures = output / "qa" / "static-pages"
    captures.mkdir(parents=True, exist_ok=False)
    viewports = ((1600, 900), (1366, 768))
    page_count = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=browser_channel, headless=True)
        try:
            for width, height in viewports:
                page = browser.new_page(
                    viewport={"width": width, "height": height}, device_scale_factor=1
                )
                page.goto(html.resolve().as_uri(), wait_until="load")
                page.evaluate("async () => { await document.fonts.ready; return true; }")
                count = page.locator(".slide").count()
                if count == 0:
                    raise RuntimeError("rendered HTML has no .slide elements")
                for index in range(count):
                    page.evaluate(
                        """index => {
                          const slides = [...document.querySelectorAll('.slide')];
                          slides.forEach((slide, i) => {
                            slide.classList.toggle('active', i === index);
                            // The deck controller fades active slides over 700ms.
                            // Disable that transition so static QA captures a settled page.
                            slide.style.setProperty('transition', 'none', 'important');
                            slide.style.setProperty(
                              'opacity', i === index ? '1' : '0', 'important'
                            );
                            slide.querySelectorAll('.anim').forEach(el => {
                              el.classList.add('show');
                              // Inline !important overrides higher-specificity
                              // entry keyframes so this is a true full-state
                              // layout capture, not an animation's first frame.
                              el.style.setProperty('opacity', '1', 'important');
                              el.style.setProperty('visibility', 'visible', 'important');
                              el.style.setProperty('transform', 'none', 'important');
                              el.style.setProperty('filter', 'none', 'important');
                              el.style.setProperty('animation', 'none', 'important');
                            });
                          });
                        }""",
                        index,
                    )
                    page.wait_for_timeout(120)
                    name = f"page-{index + 1:02d}-{width}x{height}.png"
                    page.screenshot(path=str(captures / name), full_page=True)
                page.close()
                page_count = count
        finally:
            browser.close()

    contacts: dict[str, str] = {}
    for width, height in viewports:
        contact_html = captures / f"contact-{width}x{height}.html"
        cards = []
        for index in range(page_count):
            name = f"page-{index + 1:02d}-{width}x{height}.png"
            cards.append(
                f"<figure><figcaption>第{index + 1}页</figcaption>"
                f'<img src="{name}" alt="第{index + 1}页"></figure>'
            )
        contact_html.write_text(
            "<!doctype html><meta charset='utf-8'><style>"
            "body{margin:0;background:#ececec;font:16px sans-serif}"
            "main{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:8px}"
            "figure{margin:0;background:white}figcaption{padding:4px 8px;font-weight:600}"
            "img{display:block;width:100%;height:auto}"
            "</style><main>" + "".join(cards) + "</main>",
            encoding="utf-8",
        )
        contacts[str(width)] = str(contact_html.with_suffix(".png"))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=browser_channel, headless=True)
            try:
                page = browser.new_page(
                    viewport={"width": width, "height": height}, device_scale_factor=1
                )
                page.goto(contact_html.resolve().as_uri(), wait_until="load")
                page.screenshot(path=contacts[str(width)], full_page=True)
            finally:
                browser.close()
    return {
        "page_count": page_count,
        "viewports": [list(v) for v in viewports],
        "contactsheets": contacts,
    }


def _inline_reviewed_svg_nodes(html_path: Path, storyboard: dict[str, Any], image_dir: Path) -> int:
    """Inline hash-bound SVGs whose declared child nodes are timeline targets.

    The template renderer normally emits image assets as <img>. SVG child
    selectors do not cross that document boundary, so the recovery path uses
    the renderer's existing strict SVG inliner for explicitly declared nodes.
    """
    from textbook2video import animation_gen

    document = html_path.read_text(encoding="utf-8")
    entries: list[tuple[str, dict[str, Any]]] = []
    for segment in storyboard.get("segments", []):
        segment_id = str(segment.get("id", ""))
        for element in segment.get("elements", []) or []:
            if element.get("visual_object_targets"):
                entries.append((segment_id, element))
    if not entries:
        return 0

    grouped: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    for segment_id, element in entries:
        if element.get("type") != "image" or not isinstance(element.get("src"), str):
            raise BundleValidationError(
                "visual_object_targets must belong to a saved image element"
            )
        grouped.setdefault((str(element["id"]), str(element["src"])), []).append(
            (segment_id, element)
        )

    changed = False
    verified_visuals = 0
    for (stable_id, source), group in grouped.items():
        image_path = (image_dir / source).resolve()
        try:
            image_path.relative_to(image_dir.resolve())
        except ValueError as exc:
            raise BundleValidationError(
                f"visual object asset escapes bundle images: {source}"
            ) from exc
        if not image_path.is_file():
            raise BundleValidationError(f"visual object asset is missing: {source}")
        target_map = group[0][1]["visual_object_targets"]
        target_ids = list(target_map)
        if any(set(element["visual_object_targets"]) != set(target_ids) for _, element in group):
            raise BundleValidationError(
                f"repeated visual {stable_id} has inconsistent node bindings"
            )

        expected = len(group)
        svg_fragments = re.findall(r"<svg\b.*?</svg>", document, re.IGNORECASE | re.DOTALL)
        child_counts = {
            target: sum(
                len(re.findall(r'data-anim-id=["\']' + re.escape(target) + r'["\']', svg))
                for svg in svg_fragments
            )
            for target in target_ids
        }
        if all(count == expected for count in child_counts.values()):
            # The repository renderer already used its strict SVG inliner.
            verified_visuals += expected
            continue
        if any(child_counts.values()):
            raise BundleValidationError(f"partially inlined SVG node set for {stable_id}")

        # Fallback for renderer builds that left this saved SVG as <img>.
        # The exact hash is checked by the existing strict renderer helper.
        src_name = re.escape(Path(source).name)
        element_id = re.escape(stable_id)
        pattern = re.compile(
            r'(<div\b(?=[^>]*\bdata-anim-id=["\']'
            + element_id
            + r'["\'])[^>]*>)(?:(?!</div>).)*?(<img\b(?=[^>]*\bsrc=["\'][^"\']*/'
            + src_name
            + r'["\'])[^>]*>)',
            re.IGNORECASE | re.DOTALL,
        )
        if len(list(pattern.finditer(document))) != expected:
            raise BundleValidationError(
                f"expected {expected} rendered SVG containers for {stable_id} ({source})"
            )
        for segment_id, element in group:
            match = next(pattern.finditer(document), None)
            if match is None:
                raise BundleValidationError(
                    f"missing remaining SVG container for segment {segment_id}"
                )
            inline = animation_gen._inline_reviewed_visual_objects(
                image_path, element, scope=segment_id
            )
            document = document[: match.start(2)] + inline + document[match.end(2) :]
            changed = True

        svg_fragments = re.findall(r"<svg\b.*?</svg>", document, re.IGNORECASE | re.DOTALL)
        child_counts = {
            target: sum(
                len(re.findall(r'data-anim-id=["\']' + re.escape(target) + r'["\']', svg))
                for svg in svg_fragments
            )
            for target in target_ids
        }
        if any(count != expected for count in child_counts.values()):
            raise BundleValidationError(
                f"SVG node selectors were not fully inlined for {stable_id}"
            )
        verified_visuals += expected
    if changed:
        html_path.write_text(document, encoding="utf-8")
    return verified_visuals


def _apply_palette_surface_contrast(html_path: Path) -> int:
    """Give transparent dark-palette SVGs the dark surface their light text needs.

    This only changes the generated HTML presentation wrapper. The reviewed
    SVG file and its bundle hash remain untouched.
    """
    document = html_path.read_text(encoding="utf-8")
    occurrences = len(
        re.findall(
            r"<svg\b[^>]*\bdata-theme=[\"']dark-blue-academic[\"']",
            document,
            re.IGNORECASE | re.DOTALL,
        )
    )
    if not occurrences:
        return 0
    if 'id="course-dev-dark-svg-surface-contrast"' in document:
        return occurrences
    if "</head>" not in document:
        raise RuntimeError("rendered HTML has no </head>; refusing a visual contrast patch")
    css = (
        '<style id="course-dev-dark-svg-surface-contrast">'
        '.slide .t2v-image-surface:has(> svg[data-theme="dark-blue-academic"]) {'
        "background:#10243a!important;border:1px solid #425b72;border-radius:14px;"
        "overflow:hidden;box-shadow:0 10px 28px rgba(7,19,34,.32);"
        "}</style>"
    )
    html_path.write_text(document.replace("</head>", css + "</head>", 1), encoding="utf-8")
    return occurrences


def _validate_rendered_animation_targets(
    html_path: Path,
    storyboard: dict[str, Any],
    *,
    browser_channel: str,
) -> dict[str, Any]:
    """Check every compiled timeline selector resolves once in its slide."""
    from playwright.sync_api import sync_playwright

    from textbook2video.animation_gen import build_slide_timelines

    timelines = build_slide_timelines(storyboard.get("segments", []))
    checks = 0
    missing: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=browser_channel, headless=True)
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            slide_count = page.locator(".slide").count()
            if slide_count != len(timelines):
                raise RuntimeError(
                    "rendered slide count "
                    f"{slide_count} differs from timeline count {len(timelines)}"
                )
            for slide_index, timeline in enumerate(timelines):
                slide = page.locator(".slide").nth(slide_index)
                for event in timeline:
                    selector = str(event["selector"])
                    count = slide.locator(selector).count()
                    checks += 1
                    if count != 1:
                        missing.append(
                            {
                                "slide_index": slide_index + 1,
                                "slide_id": str(storyboard["segments"][slide_index].get("id")),
                                "event_id": event["event_id"],
                                "selector": selector,
                                "count": count,
                            }
                        )
            page.close()
        finally:
            browser.close()
    return {"checked_selectors": checks, "missing_or_ambiguous": missing, "passed": not missing}


def replay_course_dev_bundle(
    bundle_dir: str | Path,
    output_dir: str | Path,
    *,
    render_only: bool = False,
) -> dict[str, Any]:
    """Render, record, subtitle, and mux a fresh offline course run."""
    bundle = validate_course_dev_bundle(bundle_dir)
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite an existing run: {output}")
    try:
        output.relative_to(bundle.root)
    except ValueError:
        pass
    else:
        raise ValueError("output directory must be outside the immutable bundle")

    output.mkdir(parents=True, exist_ok=False)
    for name in ("render", "video", "qa"):
        (output / name).mkdir()
    storyboard_path, _, _ = _copy_bundle_inputs(bundle, output)
    audio_dir = output / "audio"

    from textbook2video import animation_gen
    from textbook2video.pipeline.artifact_integrity import verify_render_bundle
    from textbook2video.pipeline.compose import compose_video
    from textbook2video.pipeline.recorder import record_html_to_video
    from textbook2video.pipeline.subtitles import generate_srt

    def forbidden_fallback(**_: Any) -> None:
        raise RuntimeError("OFFLINE_GUARD: renderer attempted an LLM fallback")

    prior_fallback = animation_gen.generate_batch_slides
    prior_skip_svg = os.environ.get("T2V_SKIP_SVG")
    animation_gen.generate_batch_slides = forbidden_fallback
    os.environ["T2V_SKIP_SVG"] = "1"
    try:
        html = animation_gen.generate(
            str(storyboard_path),
            output_dir=output / "render",
            theme_id=str(bundle.manifest.get("theme_id", "bright")),
            skip_image_gen=True,
            visual_tools_enabled=False,
            layout_repair_attempts=0,
            layout_browser_channel=str(bundle.manifest.get("browser_channel", "msedge")),
        )
    finally:
        animation_gen.generate_batch_slides = prior_fallback
        if prior_skip_svg is None:
            os.environ.pop("T2V_SKIP_SVG", None)
        else:
            os.environ["T2V_SKIP_SVG"] = prior_skip_svg

    inlined_visual_nodes = _inline_reviewed_svg_nodes(
        html, bundle.storyboard, output / "input" / "images"
    )
    contrast_surfaces = _apply_palette_surface_contrast(html)

    for adjustment in bundle.manifest.get("render_adjustments", []):
        slide_number = int(adjustment["slide_number"])
        max_width = int(adjustment["max_width_px"])
        scale = float(adjustment["scale"])
        css = (
            f'<style id="course-dev-slide-{slide_number}-fit">'
            f"@media screen and (max-width:{max_width}px) {{"
            f".slide:nth-child({slide_number}) .fit-scale {{"
            f"transform:scale({scale})!important;transform-origin:center top!important;"
            "}}</style>"
        )
        document = html.read_text(encoding="utf-8")
        if "</head>" not in document:
            raise RuntimeError("rendered HTML has no </head>; refusing a layout patch")
        html.write_text(document.replace("</head>", css + "</head>", 1), encoding="utf-8")

    browser_channel = str(bundle.manifest.get("browser_channel", "msedge"))
    passed, layout_report = animation_gen.run_layout_qa(
        html,
        output / "render" / "final-layout.json",
        browser_channel=browser_channel,
    )
    if not passed:
        raise RuntimeError("multi-viewport layout QA failed; see render/final-layout.json")
    target_validation = _validate_rendered_animation_targets(
        html, bundle.storyboard, browser_channel=browser_channel
    )
    _write_json(output / "qa" / "rendered-animation-targets.json", target_validation)
    if not target_validation["passed"]:
        raise RuntimeError("one or more storyboard animation targets did not render")
    screenshots = _capture_static_screenshots(html, output, browser_channel=browser_channel)

    render_manifest = verify_render_bundle(storyboard_path, html, audio_dir=audio_dir)
    _write_json(html.with_name(f"{html.stem}.manifest.json"), render_manifest)
    _write_json(output / "qa" / "layout-qa-summary.json", layout_report)
    _write_json(output / "qa" / "screenshots.json", screenshots)

    if render_only:
        summary = {
            "bundle": str(bundle.root),
            "output": str(output),
            "html": str(html.resolve()),
            "segments": len(bundle.storyboard["segments"]),
            "inlined_reviewed_svg_visuals": inlined_visual_nodes,
            "dark_palette_svg_surfaces": contrast_surfaces,
            "render_overlay": (
                "dark-blue-academic SVGs receive a dark presentation surface; "
                "source assets and hashes unchanged"
            ),
            "rendered_animation_targets": target_validation,
            "screenshots": screenshots,
            "external_calls": {
                "llm": 0,
                "vlm": 0,
                "image_generation": 0,
                "health_check": 0,
                "tts_api": 0,
            },
            "layout_qa_passed": bool(passed),
            "media_recorded": False,
        }
        _write_json(output / "render-only-summary.json", summary)
        return summary

    silent = output / "video" / "lesson_002-full-course-dev-silent.mp4"
    final = output / "video" / "lesson_002-full-course-dev.mp4"
    trace = output / "video" / "runtime-trace.json"
    srt = output / "video" / "lesson_002-full-course-dev.srt"
    seconds = math.ceil(float(render_manifest["audio_total_duration_sec"])) + 1
    record_html_to_video(
        str(html),
        str(silent),
        duration=seconds,
        fps=30,
        browser_channel=browser_channel,
        viewport_width=1600,
        viewport_height=900,
        trace_path=str(trace),
    )
    generate_srt(storyboard_path, srt)
    compose_video(silent, audio_dir, final, subtitle_path=srt)

    trace_data = _read_json(trace, label="runtime trace")
    statuses: dict[str, int] = {}
    for event in trace_data.get("events", []):
        status = str(event.get("status", "missing_status"))
        statuses[status] = statuses.get(status, 0) + 1
    non_executed = {status: count for status, count in statuses.items() if status != "executed"}
    if non_executed:
        raise RuntimeError(f"runtime trace contains non-executed events: {non_executed}")
    summary = {
        "bundle": str(bundle.root),
        "output": str(output),
        "html": str(html.resolve()),
        "mp4": str(final.resolve()),
        "srt": str(srt.resolve()),
        "runtime_trace": str(trace.resolve()),
        "segments": len(bundle.storyboard["segments"]),
        "inlined_reviewed_svg_visuals": inlined_visual_nodes,
        "dark_palette_svg_surfaces": contrast_surfaces,
        "render_overlay": (
            "dark-blue-academic SVGs receive a dark presentation surface; "
            "source assets and hashes unchanged"
        ),
        "audio_total_duration_sec": render_manifest["audio_total_duration_sec"],
        "runtime_event_statuses": statuses,
        "runtime_event_count": sum(statuses.values()),
        "mp4_sha256": sha256_file(final),
        "mp4_bytes": final.stat().st_size,
        "screenshots": screenshots,
        "external_calls": {
            "llm": 0,
            "vlm": 0,
            "image_generation": 0,
            "health_check": 0,
            "tts_api": 0,
        },
        "layout_qa_passed": bool(passed),
        "human_full_listen_review": "pending",
    }
    _write_json(output / "run-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="immutable saved course bundle directory")
    parser.add_argument("--output", required=True, help="new, non-existing run output directory")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate hashes and mappings without rendering",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help=(
            "compile offline HTML, check layout/targets, and capture screenshots "
            "without media recording"
        ),
    )
    args = parser.parse_args()
    if args.validate_only:
        bundle = validate_course_dev_bundle(args.bundle)
        print(
            json.dumps(
                {
                    "valid": True,
                    "segments": len(bundle.storyboard["segments"]),
                    "audio_entries": len(bundle.execution_map.get("audio", [])),
                    "assets": len(bundle.execution_map.get("assets", [])),
                    "bundle": str(bundle.root),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            replay_course_dev_bundle(args.bundle, args.output, render_only=args.render_only),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
