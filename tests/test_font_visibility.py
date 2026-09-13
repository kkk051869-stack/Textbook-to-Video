import json
import os
from pathlib import Path

import pytest

from textbook2video.eval.evaluators.font_visibility import (
    _font_asset_info,
    _font_faces_from_css,
    evaluate_font_visibility,
)
from textbook2video.font_assets import PROJECT_FONT_RELATIVE_PATH
from textbook2video.eval.runner import EvalContext, run_case


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_REPO_ROOT = Path(os.environ.get("T2V_TEST_REPO_ROOT", REPO_ROOT))


class _FontCase:
    case_id = "font-case"
    lesson_id = "font-lesson"
    dataset_version = "font-test"

    def __init__(self, root: Path, expected_family: str, font_path: Path):
        self.manifest_path = root / "case_manifest.json"
        self.raw = {
            "candidate_artifacts": {"html": "fixture.html"},
            "metadata": {
                "font_visibility": {
                    "expected_family": expected_family,
                    "font_asset_path": str(font_path),
                }
            },
        }

    def assets(self):
        return []

    def resolve_asset(self, asset):
        raise AssertionError(f"unexpected asset: {asset}")


def _font_path() -> Path:
    configured = os.environ.get("T2V_TEST_CJK_FONT")
    if configured:
        return Path(configured)
    return REPO_ROOT / PROJECT_FONT_RELATIVE_PATH


def _browser_available() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with sync_playwright() as playwright:
        executable = os.environ.get("T2V_PLAYWRIGHT_EXECUTABLE")
        if executable and Path(executable).is_file():
            return executable
        default = Path(playwright.chromium.executable_path)
        return str(default) if default.is_file() else None


def _context(tmp_path: Path, html: str, *, expected_family: str, font_path: Path) -> EvalContext:
    (tmp_path / "fixture.html").write_text(html, encoding="utf-8")
    case = _FontCase(tmp_path, expected_family, font_path)
    return EvalContext(
        case=case,
        run_id="font-test-run",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
    )


def test_font_asset_missing_is_explicitly_reported(tmp_path):
    info = _font_asset_info(tmp_path / "missing.ttc")
    assert info["exists"] is False
    assert info["sha256"] is None


def test_font_face_css_parser_extracts_family_and_sources():
    css = '@font-face { font-family: "T2V-CJK"; src: url("./fonts/msyh.ttc") format("truetype"); }'
    assert _font_faces_from_css(css) == [
        {"family": "T2V-CJK", "sources": ["./fonts/msyh.ttc"]}
    ]


@pytest.fixture(scope="module")
def browser_executable():
    executable = _browser_available()
    if not executable:
        pytest.skip("No Playwright Chromium executable is available")
    return executable


def test_bad_fixture_fails_without_explicit_font_face(tmp_path, browser_executable, monkeypatch):
    monkeypatch.setenv("T2V_PLAYWRIGHT_EXECUTABLE", browser_executable)
    font_path = _font_path()
    if not font_path.is_file():
        pytest.skip("No existing CJK font asset is available for the fixture")
    context = _context(
        tmp_path,
        '<!doctype html><meta charset="utf-8"><style>body { font-family: "__T2V_MISSING__", monospace; }</style>'
        "<h1>互联网 数字化转型 中国制造</h1>",
        expected_family="T2V-CJK",
        font_path=font_path,
    )

    result = evaluate_font_visibility(context)

    assert result["status"] == "failed"
    assert result["passed"] is False
    assert any(issue["type"] == "FONT_FACE_NOT_BOUND" for issue in result["issues"])
    assert (tmp_path / "out" / "browser_runtime.json").is_file()


def test_good_fixture_passes_with_explicit_font_face(tmp_path, browser_executable, monkeypatch):
    monkeypatch.setenv("T2V_PLAYWRIGHT_EXECUTABLE", browser_executable)
    font_path = _font_path()
    if not font_path.is_file():
        pytest.skip("No existing CJK font asset is available for the fixture")
    font_url = font_path.resolve().as_uri()
    html = (
        '<!doctype html><meta charset="utf-8"><style>'
        f'@font-face {{ font-family: "T2V-CJK"; src: url("{font_url}") format("opentype"); }}'
        'body { font-family: "T2V-CJK"; font-size: 48px; }'
        '</style><h1>互联网 数字化转型 中国制造 教育 数据</h1>'
    )
    context = _context(tmp_path, html, expected_family="T2V-CJK", font_path=font_path)

    result = evaluate_font_visibility(context)

    assert result["status"] == "ok"
    assert result["passed"] is True
    assert result["metrics"]["explicit_font_face"] is True
    assert result["metrics"]["font_loaded"] is True
    assert result["metrics"]["cjk_glyph_visibility"] is True
    assert result["details"]["actual_cjk_nodes"]["checked"] >= 1


def test_font_gate_is_present_in_eval_report_and_run_manifest(tmp_path, browser_executable, monkeypatch):
    monkeypatch.setenv("T2V_PLAYWRIGHT_EXECUTABLE", browser_executable)
    font_path = _font_path()
    if not font_path.is_file():
        pytest.skip("No existing CJK font asset is available for the fixture")
    font_url = font_path.resolve().as_uri()
    html = (
        '<!doctype html><meta charset="utf-8"><style>'
        f'@font-face {{ font-family: "T2V-CJK"; src: url("{font_url}") format("opentype"); }}'
        'body { font-family: "T2V-CJK"; }'
        '</style><p>中文字体验证</p>'
    )
    context = _context(tmp_path, html, expected_family="T2V-CJK", font_path=font_path)
    report = run_case(
        context.case,
        run_id=context.run_id,
        artifacts_root=context.artifacts_root,
        output_root=context.output_root,
        evaluators=[evaluate_font_visibility],
        repo_root=TEST_REPO_ROOT,
    )

    assert report["font_visibility"]["status"] == "ok"
    saved_report = json.loads((tmp_path / "out" / "eval_report.json").read_text(encoding="utf-8"))
    saved_manifest = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert saved_report["font_visibility"]["metrics"]["font_loaded"] is True
    assert saved_manifest["metadata"]["font_visibility"]["font_loaded"] is True
