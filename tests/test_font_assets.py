import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.font_assets import (
    CANONICAL_FONT_NAME,
    CANONICAL_FONT_SHA256,
    CJK_FONT_FAMILY,
    CJK_FONT_RELATIVE_PATH,
    CJK_FONT_STACK,
    PROJECT_FONT_RELATIVE_PATH,
    CJKFontError,
    cjk_font_face_css,
    package_cjk_font,
)
from textbook2video.pipeline.artifact_integrity import verify_render_bundle
from textbook2video.themes import load_theme, theme_to_css_vars


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FONT = REPO_ROOT / PROJECT_FONT_RELATIVE_PATH


def test_font_face_and_theme_css_use_the_canonical_family():
    css = cjk_font_face_css()
    assert f'font-family: "{CJK_FONT_FAMILY}"' in css
    assert 'url("./fonts/t2v-cjk.otf") format("opentype")' in css
    assert "font-weight: 400" in css
    assert "font-display: block" in css

    base_css = (REPO_ROOT / "src/textbook2video/templates/base.css").read_text(encoding="utf-8")
    assert css.strip() in base_css
    assert "@media (min-width: 1451px)" in base_css
    assert ".slide .anim-left > span" in base_css
    assert "line-height: 1.3 !important" in base_css
    assert ".slide .slide-title" in base_css
    assert "line-height: 1.4 !important" in base_css
    assert ".deterministic-icon-group > div" in base_css
    assert "padding-block: 9px !important" in base_css
    for theme_id in ("bright", "dark-blue-academic", "3b1b-math"):
        theme_css = theme_to_css_vars(load_theme(theme_id))
        assert f"--font-body: {CJK_FONT_STACK};" in theme_css
        assert f"--font-heading: {CJK_FONT_STACK};" in theme_css
        assert "Microsoft YaHei" not in theme_css


def test_project_canonical_font_has_expected_identity():
    assert PROJECT_FONT.is_file()
    assert hashlib.sha256(PROJECT_FONT.read_bytes()).hexdigest() == CANONICAL_FONT_SHA256
    assert CANONICAL_FONT_NAME == "Noto Sans CJK SC"


def test_package_cjk_font_uses_project_asset_by_default(tmp_path):
    info = package_cjk_font(tmp_path / "candidate")
    packaged = tmp_path / "candidate" / CJK_FONT_RELATIVE_PATH
    assert packaged.read_bytes() == PROJECT_FONT.read_bytes()
    assert info["font_family"] == CJK_FONT_FAMILY
    assert info["canonical_font_name"] == CANONICAL_FONT_NAME
    assert info["font_asset_relative_path"] == "fonts/t2v-cjk.otf"
    assert info["font_source_type"] == "canonical_asset"
    assert info["font_sha256"] == CANONICAL_FONT_SHA256
    assert info["expected_font_sha256"] == CANONICAL_FONT_SHA256
    assert info["font_sha256_matches"] is True
    assert info["font_asset_exists"] is True


def test_package_cjk_font_accepts_configured_external_copy(tmp_path):
    source = tmp_path / "configured" / "noto-sc.otf"
    source.parent.mkdir()
    source.write_bytes(PROJECT_FONT.read_bytes())
    artifact_root = tmp_path / "candidate"

    info = package_cjk_font(artifact_root, source=source)

    packaged = artifact_root / CJK_FONT_RELATIVE_PATH
    assert packaged.read_bytes() == source.read_bytes()
    assert info["font_asset_source"] == str(source.resolve())
    assert info["font_source_path"] == str(source.resolve())
    assert info["font_source_type"] == "configured_external"
    assert info["font_sha256"] == CANONICAL_FONT_SHA256
    assert info["font_asset_exists"] is True


def test_configured_font_path_takes_priority_over_project_and_system(monkeypatch, tmp_path):
    source = tmp_path / "configured" / "noto-sc.otf"
    source.parent.mkdir()
    source.write_bytes(PROJECT_FONT.read_bytes())
    monkeypatch.setenv("T2V_CJK_FONT_PATH", str(source))

    info = package_cjk_font(tmp_path / "candidate")

    assert info["font_source_type"] == "configured_external"
    assert info["font_source_path"] == str(source.resolve())
    assert info["font_sha256_matches"] is True


def test_package_cjk_font_fails_for_missing_configured_path(tmp_path):
    with pytest.raises(CJKFontError, match="T2V canonical CJK font unavailable"):
        package_cjk_font(tmp_path / "candidate", source=tmp_path / "missing.otf")


def test_package_cjk_font_fails_for_hash_mismatch(tmp_path):
    source = tmp_path / "wrong.otf"
    source.write_bytes(b"not-the-canonical-font")
    with pytest.raises(CJKFontError, match="T2V canonical CJK font unavailable"):
        package_cjk_font(tmp_path / "candidate", source=source)


def test_render_manifest_exposes_canonical_font_provenance(tmp_path):
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
    package_cjk_font(tmp_path, source=PROJECT_FONT)

    report = verify_render_bundle(storyboard, html)

    assert report["font_family"] == CJK_FONT_FAMILY
    assert report["canonical_font_name"] == CANONICAL_FONT_NAME
    assert report["font_asset_relative_path"] == "fonts/t2v-cjk.otf"
    assert report["font_sha256"] == CANONICAL_FONT_SHA256
    assert report["expected_font_sha256"] == CANONICAL_FONT_SHA256
    assert report["font_sha256_matches"] is True
    assert report["font_license"] == "SIL Open Font License 1.1"
    assert report["explicit_font_face"] is True
    assert report["font_gate_status"] == "pending_browser_probe"
