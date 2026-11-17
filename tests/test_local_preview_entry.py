"""Exercise the explicit CLI with offline source bundles and the real renderer."""
import hashlib
import json
import sys
from pathlib import Path

import pytest
from test_local_visual_composition import compose, page

from textbook2video.cli import main
from textbook2video.pipeline.orchestrator import preview_local_page

pytest_plugins = ("test_local_visual_composition",)


def test_explicit_cli_preserves_page_and_runs_controller(tmp_path, fixture_bundle, monkeypatch):
    segment = page()
    result = compose(segment, fixture_bundle, tmp_path / "bundle")
    source = Path(result["storyboard"])
    before = source.read_bytes()
    output = tmp_path / "preview"
    monkeypatch.setattr(sys, "argv", ["t2v", "preview-local", str(source),
                                    "--segment", segment["id"], "--output", str(output)])
    main()
    report = json.loads((output / "preview-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "DEVELOPMENT_PREVIEW_PENDING_REVIEW"
    assert report["human_review"] == "NOT_REVIEWED"
    assert report["new_visual_alignment"] == "NOT_VERIFIED"
    runtime = json.loads((output / "runtime-checks.json").read_text(encoding="utf-8"))
    assert runtime["passed"] and len(runtime["viewports"]) == 2
    assert all(len(v["trace"]) == 2 for v in runtime["viewports"])
    assert source.read_bytes() == before
    assert report["input_sha256"] == hashlib.sha256(before).hexdigest()
    html = (output / "runtime.html").read_text(encoding="utf-8")
    assert "data:image/svg+xml;base64," in html
    assert "opacity:1!important;transform:none!important;animation:none!important" not in html
    with pytest.raises(FileExistsError):
        preview_local_page(source, segment["id"], output)


def test_strict_semantic_gate_and_hash_gate_remain_closed(tmp_path, fixture_bundle):
    segment = page()
    result = compose(segment, fixture_bundle, tmp_path / "bundle")
    source = Path(result["storyboard"])
    with pytest.raises(ValueError, match="semantic review"):
        preview_local_page(source, segment["id"], tmp_path / "strict", policy="strict")
    assert not (tmp_path / "strict").exists()
    unchanged = source.read_bytes()
    wrong_binding = json.loads(unchanged)
    wrong_binding["segments"][0]["local_visual_operations"][0]["asset_sha256"] = "0" * 64
    source.write_text(json.dumps(wrong_binding), encoding="utf-8")
    with pytest.raises(ValueError, match="local operation asset"):
        preview_local_page(source, segment["id"], tmp_path / "wrong-binding")
    assert not (tmp_path / "wrong-binding").exists()
    source.write_bytes(unchanged)
    board = json.loads(source.read_text(encoding="utf-8"))
    element = board["segments"][0]["elements"][-1]
    element["source_image_id"] = "book"
    board["metadata"]["available_images"] = [{"id": "book", "filename": element["src"],
                                              "semantic_status": "REQUIRES_VLM"}]
    source.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="ACCEPT"):
        preview_local_page(source, segment["id"], tmp_path / "strict-book", policy="strict")
    image = next((source.parent / "images").iterdir())
    image.write_bytes(image.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hash drift"):
        preview_local_page(source, segment["id"], tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()


def test_dangling_event_is_not_silently_dropped_by_compiler(tmp_path, fixture_bundle):
    segment = page()
    result = compose(segment, fixture_bundle, tmp_path / "bundle")
    source = Path(result["storyboard"])
    board = json.loads(source.read_text(encoding="utf-8"))
    board["segments"][0]["timeline"][0]["target"] = "missing-object"
    source.write_text(json.dumps(board), encoding="utf-8")
    with pytest.raises(ValueError, match="event target"):
        preview_local_page(source, segment["id"], tmp_path / "bad-event")
    assert not (tmp_path / "bad-event").exists()
