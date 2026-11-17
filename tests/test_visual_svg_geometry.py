import base64
import hashlib
import json

import pytest
from playwright.sync_api import Error, sync_playwright

from textbook2video.research import visual_grammar, visual_tools


@pytest.fixture(scope="module")
def browser_channel():
    with sync_playwright() as pw:
        for channel in ("msedge", None):
            try:
                browser = pw.chromium.launch(channel=channel)
                browser.close()
                return channel
            except Error:
                continue
    pytest.skip("No Chromium browser for SVG glyph geometry")


@pytest.mark.parametrize("overflow", [False, True])
@pytest.mark.parametrize("paired", [False, True])
@pytest.mark.parametrize("long_path", [False, True])
def test_external_course_svg_image_still_has_real_glyph_containment_checks(
    tmp_path, monkeypatch, browser_channel, overflow, paired, long_path
):
    if long_path:
        while len(str(tmp_path)) < 290:
            tmp_path /= "deep preview path 教学"
    y = 200 if overflow else 90
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="680" '
        'viewBox="0 0 1600 680"><g data-node-id="a">'
        '<rect x="20" y="30" width="300" height="100"/>'
        f'<text x="40" y="{y}" font-size="52">Input</text></g>'
        '<g data-node-id="b"><rect x="400" y="30" width="300" height="100"/>'
        '<text x="420" y="90" font-size="52">Output</text></g></svg>'
    )
    monkeypatch.setattr(visual_grammar, "render_visual", lambda *a, **k: svg)
    source = "Input data. Output result."
    spec = {
        "id": "main",
        "kind": "flow",
        "title": "Input and output",
        "teaching_goal": "Explain the relationship",
        "nodes": [
            {"id": "a", "label": "Input", "evidence": source},
            {"id": "b", "label": "Output", "evidence": source},
        ],
        "edges": [{"source": "a", "target": "b", "evidence": source}],
    }
    arguments = {"visuals": [spec]}
    if paired:
        arguments["visuals"].append({**spec, "id": "second"})
        arguments["composition"] = {
            "visual_ids": ["main", "second"],
            "axis": "horizontal",
            "horizontal_free": True,
        }
    revision = visual_tools.dispatch(
        "create",
        arguments,
        source=source,
        output_dir=tmp_path / "preview",
        page_context=[],
        browser=browser_channel,
    )
    visual_tools.verify_revision(revision.parent)
    geometry = json.loads((revision.parent / "geometry.json").read_text(encoding="utf-8"))
    assert len(geometry) == 2
    for capture in geometry:
        check = capture["source_svg_glyph_checks"]
        assert check["text_nodes"] == (4 if paired else 2)
        if paired:
            assert check["direct_text_nodes"] == 0
            assert len(check["members"]) == 2
            assert all(m["text_nodes"] == 2 for m in check["members"])
        assert any(i["type"] == "node_text_overflow" for i in capture["issues"]) is overflow


@pytest.mark.parametrize("corrupt", [False, True])
def test_raster_preview_embeds_bytes_from_long_path(tmp_path, browser_channel, corrupt):
    while len(str(tmp_path)) < 290:
        tmp_path /= "deep preview path 教学"
    assets = tmp_path / "compiled/assets"
    assets.mkdir(parents=True)
    # Engineering fixture: a one-pixel image tests decoding, not visual quality.
    data = (b"not an image" if corrupt else base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF1cAAAAASUVORK5CYII="
    ))
    path = assets / "fixture.png"
    path.write_bytes(data)
    (tmp_path / "compiled/visual_assets.json").write_text(json.dumps({"assets": [{
        "id": "fixture", "filename": path.name, "sha256": hashlib.sha256(data).hexdigest(),
        "spec": {"title": "Raster fixture"},
    }]}), encoding="utf-8")
    (tmp_path / "request.json").write_text(json.dumps({"theme": "dark-blue-academic"}), encoding="utf-8")
    if corrupt:
        with pytest.raises(Error, match="decode|decoded|EncodingError"):
            visual_tools.preview_revision(tmp_path, browser=browser_channel)
    else:
        captures = visual_tools.preview_revision(tmp_path, browser=browser_channel)
        assert len(captures) == 2
        assert all(c["sha256"] for c in captures)
        markup = (tmp_path / "fixture.html").read_text(encoding="utf-8")
        assert 'src="data:image/png;base64,' in markup
        assert "file:///" not in markup
    assert path.read_bytes() == data


def test_missing_preview_asset_still_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        visual_tools._preview_asset_uri(tmp_path / "missing.svg")


def test_unregistered_nested_svg_is_not_a_zero_text_pass(tmp_path, browser_channel):
    inner = base64.b64encode(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        b'<text x="5" y="30" font-size="24">Nested</text></svg>'
    ).decode()
    data = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="680" '
        'viewBox="0 0 1600 680">'
        f'<image width="1600" height="680" href="data:image/svg+xml;base64,{inner}"/></svg>'
    ).encode()
    path = tmp_path / "compiled/assets/nested.svg"
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    asset = {"id": "nested", "filename": path.name, "sha256": hashlib.sha256(data).hexdigest()}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=browser_channel)
        try:
            page = browser.new_page()
            result = visual_tools._asset_svg_glyph_checks(page, tmp_path, asset, [asset])
            assert result["text_nodes"] == 0 and result["nested_images"] == 1
            assert result["issues"] == [{"type": "unmeasured_nested_svg_content"}]
            with pytest.raises(ValueError, match="asset hash drift"):
                visual_tools._asset_svg_glyph_checks(
                    page, tmp_path, {**asset, "sha256": "0" * 64}, [asset]
                )
        finally:
            browser.close()
