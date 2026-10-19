from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from textbook2video.research.visual_synthesis import compile_visuals, render_svg, route_visual


@pytest.mark.parametrize(
    "kind",
    [
        "flow",
        "hierarchy",
        "network",
        "timeline",
        "cycle",
        "comparison",
        "causal",
        "part_whole",
        "proportion",
        "table",
        "chart",
        "formula",
        "code",
    ],
)
def test_every_deterministic_visual_kind_renders_svg(kind: str) -> None:
    spec = {"id": kind, "kind": kind, "title": "教学图", "items": ["A", "B", "C"]}
    if kind == "comparison":
        spec["items"] = ["A", "B"]
    elif kind in {"proportion", "chart"}:
        spec.update({"items": [1, 2, 3], "values": [1, 2, 3]})
    elif kind == "table":
        spec.update({"items": [["甲", "乙"], ["1", "2"]], "rows": [["甲", "乙"], ["1", "2"]]})
    assert route_visual(spec) == "svg"
    assert "<svg" in render_svg(spec)


def test_compile_visuals_records_svg_and_ecnu_image_provenance(tmp_path: Path) -> None:
    def fake_image(prompt: str, *, model: str) -> str:
        assert model == "ecnu-image"
        assert prompt == "一间实验室"
        return base64.b64encode(b"png-bytes").decode("ascii")

    manifest_path = compile_visuals(
        [
            {"id": "flow-1", "kind": "flow", "title": "步骤", "items": ["输入", "处理", "输出"]},
            {"id": "scene-1", "kind": "scene", "description": "一间实验室"},
            {"id": "skip", "kind": "none"},
        ],
        tmp_path,
        image_generator=fake_image,
        image_model="ecnu-image",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [asset["status"] for asset in manifest["assets"]] == [
        "DETERMINISTIC_SVG",
        "GENERATED_PENDING_REVIEW",
        "NO_VISUAL",
    ]
    assert (tmp_path / "assets" / "flow-1.svg").is_file()
    assert (tmp_path / "assets" / "scene-1.png").read_bytes() == b"png-bytes"


def test_unknown_visual_kind_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported teaching visual kind"):
        route_visual({"kind": "mystery"})


def test_revision_requires_new_directory_and_keeps_prior_asset(tmp_path: Path) -> None:
    original = compile_visuals(
        [{"id": "flow", "kind": "flow", "title": "v1", "items": ["A", "B"]}], tmp_path / "v1"
    )
    original_svg = (tmp_path / "v1" / "assets" / "flow.svg").read_bytes()
    with pytest.raises(FileExistsError, match="new output directory"):
        compile_visuals(
            [{"id": "flow", "kind": "flow", "title": "changed", "items": ["A", "B"]}],
            tmp_path / "v1",
        )

    revision = compile_visuals(
        [{"id": "flow", "kind": "flow", "title": "v2", "items": ["A", "B"]}],
        tmp_path / "v2",
        revision_of=original,
    )
    revision_manifest = json.loads(revision.read_text(encoding="utf-8"))
    assert revision_manifest["revision_of"] == str(original.resolve())
    assert (tmp_path / "v1" / "assets" / "flow.svg").read_bytes() == original_svg


def test_command_interface_returns_machine_readable_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from textbook2video.research.visual_synthesis import main

    spec_path = tmp_path / "specs.json"
    spec_path.write_text(
        json.dumps({"visuals": [{"id": "causal", "kind": "causal", "items": ["因", "果"]}]}),
        encoding="utf-8",
    )
    assert main(["--specs", str(spec_path), "--output-dir", str(tmp_path / "result")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["assets"] == [
        {"id": "causal", "route": "svg", "status": "DETERMINISTIC_SVG", "filename": "causal.svg"}
    ]
