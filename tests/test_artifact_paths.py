from pathlib import Path

import pytest

from textbook2video.artifact_paths import artifact_stem, unique_artifact_stem
from textbook2video.research.visual_synthesis import compile_visuals


def test_long_visual_id_uses_short_filename_without_changing_spec(tmp_path):
    ident = "block-structure-" + "x" * 64
    spec = {"id": ident, "kind": "none", "teaching_goal": "fixture", "evidence": "原文"}
    # Test actual SVG output too, keeping IDs and endpoint relationships intact.
    spec.update(
        kind="flow",
        schema_version="teaching-visual-v2",
        title="流程",
        nodes=[
            {"id": "a", "label": "输入", "evidence": "原文"},
            {"id": "b", "label": "输出", "evidence": "原文"},
        ],
        edges=[{"source": "a", "target": "b", "evidence": "原文"}],
    )
    import json

    directory = tmp_path
    while len(str(directory)) + 41 < 212:
        directory /= "x" * 40
    remaining = 212 - len(str(directory)) - 1
    if remaining > 0:
        directory /= "y" * remaining
    output = compile_visuals([spec], directory)
    asset = json.loads(output.read_text(encoding="utf-8"))["assets"][0]
    assert asset["id"] == ident and asset["spec"] == spec
    assert len(asset["filename"]) <= 24
    assert (output.parent / "assets" / asset["filename"]).is_file()
    assert len(str(output.parent / "assets" / asset["filename"])) < 260


def test_short_ids_stay_readable_and_long_names_are_distinct():
    assert artifact_stem("main") == "main"
    assert artifact_stem("x" * 80) != artifact_stem("y" * 80)
    root = (
        Path("D:/text python/Textbook-to-Video-master")
        / "Textbook-to-Video-worktrees/organize-local-workspace"
    )
    path = (
        root
        / ".local/ordinary-course/20261025-strict-course-r38/v-12345678"
        / "course-pages-12345678/page-003/agent/revision-03/compiled/assets"
        / (artifact_stem("x" * 80) + ".svg")
    )
    assert len(str(path)) < 260


@pytest.mark.parametrize("unsafe", ["../outside", "a/b", "a\\b", "", None])
def test_unsafe_identifiers_are_not_sanitized_into_valid_assets(unsafe):
    with pytest.raises(ValueError):
        artifact_stem(unsafe)


def test_literal_hash_name_and_case_variants_cannot_overwrite_assets():
    used = set()
    long_id = "x" * 80
    names = [unique_artifact_stem(i, used) for i in (long_id, artifact_stem(long_id), "A", "a")]
    assert len({name.casefold() for name in names}) == 4
    assert all(len(name) <= 24 for name in names)


@pytest.mark.parametrize("reserved", ["CON", "nul", "COM1", "lpt9", "PRN", "AUX"])
def test_windows_device_names_use_safe_physical_names(reserved):
    assert artifact_stem(reserved).startswith("v-")


def test_long_readable_case_collision_still_respects_name_budget():
    used = set()
    assert len(unique_artifact_stem("A" * 24, used)) <= 24
    assert len(unique_artifact_stem("a" * 24, used)) <= 24


def test_actual_multi_asset_compile_and_preview_names_are_unique(tmp_path):
    import json

    from playwright.sync_api import Error, sync_playwright

    from textbook2video.research.visual_tools import dispatch, verify_revision

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge", headless=True)
        except Error:
            pytest.skip("Edge unavailable for real filename and screenshot test")
        browser.close()
    long_id = "x" * 80
    identifiers = [long_id, artifact_stem(long_id), "A", "a", "CON"]
    source = "输入经过处理，输出显示结果。"
    specs = [
        {
            "id": ident,
            "kind": "flow",
            "title": f"流程{index}",
            "teaching_goal": "理解处理",
            "nodes": [
                {"id": "a", "label": "输入", "evidence": source},
                {"id": "b", "label": "输出", "evidence": source},
            ],
            "edges": [{"source": "a", "target": "b", "evidence": source}],
        }
        for index, ident in enumerate(identifiers)
    ]
    path = dispatch(
        "create", {"visuals": specs}, source=source, output_dir=tmp_path / "multi", browser="msedge"
    )
    verify_revision(path.parent)
    manifest = json.loads((path.parent / "compiled/visual_assets.json").read_text(encoding="utf-8"))
    assert [a["id"] for a in manifest["assets"]] == identifiers
    filenames = [a["filename"] for a in manifest["assets"]]
    assert len({name.casefold() for name in filenames}) == len(identifiers)
    geometry = json.loads((path.parent / "geometry.json").read_text(encoding="utf-8"))
    assert len({r["screenshot"].casefold() for r in geometry}) == 2 * len(identifiers)
    assert {r["visual_id"] for r in geometry} == set(identifiers)
