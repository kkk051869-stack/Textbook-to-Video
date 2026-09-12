import hashlib
import json
from pathlib import Path

from textbook2video.font_assets import (
    CJK_FONT_FAMILY,
    CJK_FONT_RELATIVE_PATH,
    CJK_FONT_STACK,
    cjk_font_face_css,
    package_cjk_font,
)
from textbook2video.pipeline.artifact_integrity import verify_render_bundle
from textbook2video.themes import load_theme, theme_to_css_vars


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_font_face_and_theme_css_use_the_internal_family():
    css = cjk_font_face_css()
    assert f'font-family: "{CJK_FONT_FAMILY}"' in css
    assert 'url("./fonts/msyh.ttc") format("truetype")' in css
    assert "font-display: block" in css

    base_css = (REPO_ROOT / "src/textbook2video/templates/base.css").read_text(encoding="utf-8")
    assert css.strip() in base_css
    assert "@media (min-width: 1451px)" in base_css
    assert ".deterministic-icon-group > div" in base_css
    assert "padding-block: 16px !important" in base_css
    for theme_id in ("bright", "dark-blue-academic", "3b1b-math"):
        theme_css = theme_to_css_vars(load_theme(theme_id))
        assert f"--font-body: {CJK_FONT_STACK};" in theme_css
        assert f"--font-heading: {CJK_FONT_STACK};" in theme_css
        assert "Microsoft YaHei" not in theme_css


def test_package_cjk_font_copies_existing_source_and_records_provenance(tmp_path):
    source = tmp_path / "source-msyh.ttc"
    source.write_bytes(b"existing-font-bytes")
    artifact_root = tmp_path / "candidate"

    info = package_cjk_font(artifact_root, source=source)

    packaged = artifact_root / CJK_FONT_RELATIVE_PATH
    assert packaged.read_bytes() == source.read_bytes()
    assert info["font_family"] == CJK_FONT_FAMILY
    assert info["font_asset_relative_path"] == "fonts/msyh.ttc"
    assert info["font_asset_source"] == str(source.resolve())
    assert info["font_asset_source_kind"] == "configured"
    assert info["font_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert info["font_asset_exists"] is True


def test_render_manifest_exposes_packaged_font_provenance(tmp_path):
    storyboard = tmp_path / "storyboard.json"
    html = tmp_path / "animation.html"
    storyboard.write_text(
        json.dumps({"segments": [{"id": 1, "audio_duration_sec": 1.0}]}),
        encoding="utf-8",
    )
    html.write_text(
        '<style>@font-face { font-family: "T2V-CJK"; }</style>'
        "<script>var slideDurations = [1000];</script>",
        encoding="utf-8",
    )
    source = tmp_path / "font-source.ttc"
    source.write_bytes(b"existing-font-bytes")
    package_cjk_font(tmp_path, source=source)

    report = verify_render_bundle(storyboard, html)

    assert report["font_family"] == "T2V-CJK"
    assert report["font_asset_relative_path"] == "fonts/msyh.ttc"
    assert report["font_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["explicit_font_face"] is True
    assert report["font_gate_status"] == "pending_browser_probe"
