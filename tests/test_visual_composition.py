"""Composition produces actual assets, not a trusted model layout declaration."""

import hashlib
import json
import struct
import zlib
from functools import partial

import pytest

from textbook2video.research.visual_composition import execution_assets, render_composition
from textbook2video.research.visual_tools import compose, dispatch, verify_revision


def fixture_assets(tmp_path, *, font_size=52):
    assets_dir = tmp_path / "compiled/assets"
    assets_dir.mkdir(parents=True)
    assets = []
    for ident in ("a", "b"):
        data = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 680">'
            f'<text x="20" y="100" font-size="{font_size}">{ident}</text></svg>'
        ).encode()
        (assets_dir / f"{ident}.svg").write_bytes(data)
        assets.append({
            "id": ident, "filename": f"{ident}.svg",
            "sha256": hashlib.sha256(data).hexdigest(),
            "spec": {"id": ident, "title": ident, "narration_span": ident},
        })
    (tmp_path / "compiled/visual_assets.json").write_text(json.dumps({"assets": assets}))
    return assets


def test_pair_produces_self_contained_asset_with_provenance(tmp_path):
    original = fixture_assets(tmp_path)
    rendered = render_composition(
        tmp_path, compose(["b", "a"], axis="horizontal", horizontal_free=True), page_plan=None
    )
    assert execution_assets(tmp_path) == rendered
    assert rendered[0]["members"] == [
        {"id": a["id"], "sha256": a["sha256"]} for a in reversed(original)
    ]
    assert rendered[0]["spec"]["narration_span"] == "ba"
    svg = (tmp_path / "compiled/assets" / rendered[0]["filename"]).read_text(encoding="utf-8")
    assert svg.count("data:image/svg+xml;base64,") == 2
    assert 'data-visual-id="b"' in svg
    assert 'x="812.0"' in svg
    assert execution_assets(tmp_path)[0]["spec"]["kind"] == "composition"
    assert json.loads((tmp_path / "compiled/visual_assets.json").read_text())["assets"] == original


def test_model_free_space_flag_does_not_override_body_supports(tmp_path):
    fixture_assets(tmp_path)
    with pytest.raises(ValueError, match="empty body axis"):
        render_composition(
            tmp_path, compose(["a", "b"], axis="vertical", vertical_free=True),
            page_plan={"support_element_ids": ["text"]},
        )
    assert not (tmp_path / "composition_assets.json").exists()


def test_small_paired_labels_fail_instead_of_shrinking(tmp_path):
    fixture_assets(tmp_path, font_size=18)
    with pytest.raises(ValueError, match="too small"):
        render_composition(
            tmp_path, compose(["a", "b"], axis="horizontal", horizontal_free=True),
            page_plan=None,
        )


def test_single_page_sequence_executes_declared_order(tmp_path):
    original = fixture_assets(tmp_path)
    rendered = render_composition(tmp_path, compose(["b", "a"]), page_plan=None)
    assert rendered == original[::-1]
    assert execution_assets(tmp_path) == original[::-1]


def test_raster_composition_uses_declared_pymupdf_dependency(tmp_path):
    assets = fixture_assets(tmp_path)

    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack(
            "!I", zlib.crc32(kind + data)
        )

    data = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack("!2I5B", 600, 680, 8, 2, 0, 0, 0)
    ) + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x40\x80\xc0" * 600) * 680)) + chunk(
        b"IEND", b""
    )
    for asset in assets:
        filename = f"{asset['id']}.png"
        (tmp_path / "compiled/assets" / filename).write_bytes(data)
        asset.update(filename=filename, sha256=hashlib.sha256(data).hexdigest())
    (tmp_path / "compiled/visual_assets.json").write_text(json.dumps({"assets": assets}))
    rendered = render_composition(
        tmp_path, compose(["a", "b"], axis="horizontal", horizontal_free=True), page_plan=None
    )
    svg = (tmp_path / "compiled/assets" / rendered[0]["filename"]).read_text(encoding="utf-8")
    assert svg.count("data:image/png;base64,") == 2


def test_composition_cannot_reorder_spoken_panels(tmp_path):
    source = "甲。乙。"
    specs = [
        {"id": ident, "schema_version": "teaching-visual-v2", "kind": "code",
         "title": ident, "teaching_goal": "按顺序说明", "content": ident,
         "evidence": source, "narration_span": span}
        for ident, span in (("a", "甲。"), ("b", "乙。"))
    ]
    with pytest.raises(ValueError, match="composition order must preserve"):
        dispatch(
            "create", {"visuals": specs, "composition": {"visual_ids": ["b", "a"]}},
            source=source, output_dir=tmp_path / "bad-order", render=False,
            narration_text=source,
        )
    assert (tmp_path / "bad-order/failure.json").exists()


@pytest.mark.parametrize("responses", [("YWJj", ""), ("", "")])
def test_failed_image_panel_is_not_silently_removed(monkeypatch, tmp_path, responses):
    from textbook2video.research import visual_tools

    generated = iter(responses)
    compiler = partial(
        visual_tools.compile_visuals, image_generator=lambda *a, **kw: next(generated)
    )
    monkeypatch.setattr(visual_tools, "compile_visuals", compiler)
    source = "甲。乙。"
    specs = [
        {"id": ident, "kind": "scene", "title": ident, "prompt": ident,
         "teaching_goal": "观察两个例子", "evidence": source, "narration_span": span}
        for ident, span in (("a", "甲。"), ("b", "乙。"))
    ]
    with pytest.raises(ValueError, match="cannot omit planned panels"):
        dispatch("create", {"visuals": specs}, source=source,
                 output_dir=tmp_path / "failed", render=False, narration_text=source)
    assert (tmp_path / "failed/failure.json").exists()
    assert not (tmp_path / "failed/revision.json").exists()


def test_compose_dispatch_compiles_renders_and_seals(monkeypatch, tmp_path):
    from textbook2video.research import visual_tools

    source = "甲和乙是两个独立的例子。"
    specs = [
        {"id": ident, "kind": "scene", "prompt": ident,
         "teaching_goal": "观察不同例子", "evidence": source, "title": ident}
        for ident in ("a", "b")
    ]

    def compile_fixture(specs, output_dir, **kwargs):
        fixture_assets(output_dir.parent)
        path = output_dir / "visual_assets.json"
        manifest = json.loads(path.read_text())
        for asset, spec in zip(manifest["assets"], specs, strict=True):
            asset["spec"] = spec
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    monkeypatch.setattr(visual_tools, "compile_visuals", compile_fixture)
    revision_path = dispatch(
        "compose", {"visuals": specs, "visual_ids": ["a", "b"],
                    "axis": "horizontal", "horizontal_free": True},
        source=source, output_dir=tmp_path / "revision",
    )
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    assert revision["composition"]["pages"] == [["a", "b"]]
    assert len(revision["geometry"]) == 2
    assert all(not capture["issues"] for capture in revision["geometry"])
    verify_revision(revision_path.parent)
    legacy = dict(revision)
    legacy.pop("execution_assets_sha256")
    legacy.pop("execution_sha256")
    legacy["execution_sha256"] = visual_tools.digest(legacy)
    revision_path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(ValueError, match="require an execution seal"):
        verify_revision(revision_path.parent)
    revision_path.write_text(json.dumps(revision), encoding="utf-8")
    rendered = execution_assets(revision_path.parent)[0]
    asset = revision_path.parent / "compiled/assets" / rendered["filename"]
    asset.write_text("changed")
    with pytest.raises(ValueError, match="composition asset hash drift"):
        verify_revision(revision_path.parent)
