from __future__ import annotations

import hashlib
import json
import re
import wave
from pathlib import Path

import pytest

from scripts.replay_course_dev_bundle import (
    BundleValidationError,
    _apply_palette_surface_contrast,
    _inline_reviewed_svg_nodes,
    replay_course_dev_bundle,
    validate_course_dev_bundle,
)
from textbook2video.animation_ids import visual_node_animation_id


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_bundle(root: Path) -> Path:
    (root / "audio").mkdir(parents=True)
    (root / "images").mkdir()
    (root / "reviews").mkdir()
    audio = root / "audio" / "s1.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(22050)
        target.writeframes(b"\x00\x00" * 22050)

    narration = "测试课程页面。"
    storyboard = {
        "title": "bundle validation fixture",
        "segments": [
            {
                "id": "s1",
                "visual_type": "image",
                "narration": narration,
                "audio_duration_sec": 1.0,
                "elements": [{"id": "e1", "type": "text", "text": "测试内容"}],
            }
        ],
    }
    _write_json(root / "storyboard.json", storyboard)
    _write_json(root / "asset-review-records.json", {"records": []})
    _write_json(
        root / "execution-map.json",
        {
            "audio": [
                {
                    "source_page_id": 1,
                    "derived_segment_id": "s1",
                    "path": "audio/s1.wav",
                    "sha256": _sha(audio),
                    "narration_sha256": hashlib.sha256(narration.encode("utf-8")).hexdigest(),
                    "duration_sec": 1.0,
                }
            ],
            "assets": [],
        },
    )
    files = [
        {"path": name, "sha256": _sha(root / name)}
        for name in (
            "storyboard.json",
            "execution-map.json",
            "asset-review-records.json",
            "audio/s1.wav",
        )
    ]
    _write_json(
        root / "manifest.json",
        {
            "schema": "course-dev-bundle-v1",
            "storyboard": "storyboard.json",
            "execution_map": "execution-map.json",
            "asset_reviews": "asset-review-records.json",
            "files": files,
            "offline_only": True,
            "theme_id": "bright",
            "browser_channel": "msedge",
            "render_adjustments": [],
        },
    )
    return root


def test_validates_hash_bound_audio_and_storyboard(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle")

    result = validate_course_dev_bundle(bundle)

    assert len(result.storyboard["segments"]) == 1
    assert result.execution_map["audio"][0]["derived_segment_id"] == "s1"


def test_rejects_changed_audio_even_when_manifest_is_refreshed(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    audio = bundle / "audio" / "s1.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(22050)
        target.writeframes(b"\x01\x00" * 22050)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "audio/s1.wav":
            entry["sha256"] = _sha(audio)
    _write_json(bundle / "manifest.json", manifest)

    with pytest.raises(BundleValidationError, match="audio hash mismatch"):
        validate_course_dev_bundle(bundle)


def test_failed_bundle_validation_does_not_create_run_directory(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    (bundle / "storyboard.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "run"

    with pytest.raises(BundleValidationError, match="hash mismatch"):
        replay_course_dev_bundle(bundle, output)

    assert not output.exists()


def test_refuses_to_overwrite_a_run_directory(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "bundle")
    output = tmp_path / "existing-run"
    output.mkdir()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        replay_course_dev_bundle(bundle, output)


def test_inlines_hash_bound_svg_nodes_for_repeat_visuals(tmp_path: Path) -> None:
    svg_path = tmp_path / "asset.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<g data-node-id="part"><rect id="shape" width="10" height="10"/></g></svg>',
        encoding="utf-8",
    )
    element_id = "local-visual-repeat"
    node_target = visual_node_animation_id(element_id, "part")
    elements = [
        {
            "id": element_id,
            "type": "image",
            "src": "asset.svg",
            "visual_asset_sha256": _sha(svg_path),
            "visual_object_targets": {node_target: {"node_id": "part", "description": "fixture"}},
        }
    ]
    storyboard = {
        "segments": [
            {"id": "s1", "elements": elements},
            {"id": "s2", "elements": elements},
            {"id": "s3", "elements": elements},
        ]
    }
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / svg_path.name).write_bytes(svg_path.read_bytes())
    html_path = tmp_path / "render.html"
    container = (
        f'<div class="anim" data-anim-id="{element_id}">'
        '<div><img src="../input/images/asset.svg" alt="fixture"></div></div>'
    )
    html_path.write_text(container * 3, encoding="utf-8")

    count = _inline_reviewed_svg_nodes(html_path, storyboard, image_dir)

    rendered = html_path.read_text(encoding="utf-8")
    assert count == 3
    assert "<img" not in rendered
    assert rendered.count(f'data-anim-id="{node_target}"') == 3
    svg_fragments = re.findall(r"<svg\b.*?</svg>", rendered)
    assert len(svg_fragments) == 3
    assert all(not re.search(r'class="[^"]*\banim\b', fragment) for fragment in svg_fragments)
    assert len(set(re.findall(r'id="([^"]+--svg-[^"]+)"', rendered))) == 3
    assert _inline_reviewed_svg_nodes(html_path, storyboard, image_dir) == 3


def test_dark_palette_svg_surface_overlay_is_render_only_and_idempotent(tmp_path: Path) -> None:
    html = tmp_path / "render.html"
    html.write_text(
        "<html><head></head><body>"
        '<div class="t2v-image-surface"><svg data-theme="dark-blue-academic"></svg></div>'
        "</body></html>",
        encoding="utf-8",
    )

    assert _apply_palette_surface_contrast(html) == 1
    rendered = html.read_text(encoding="utf-8")
    assert ':has(> svg[data-theme="dark-blue-academic"])' in rendered
    assert "background:#10243a!important" in rendered
    assert _apply_palette_surface_contrast(html) == 1
    assert rendered == html.read_text(encoding="utf-8")
