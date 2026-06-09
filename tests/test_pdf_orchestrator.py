import json

from textbook2video.pipeline.orchestrator import build_storyboard_pdf_general


def test_build_storyboard_pdf_general_wires_extract_script_and_storyboard(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    bundle = {
        "structure_path": tmp_path / "demo_structure.json",
        "raw_path": tmp_path / "demo_raw.txt",
        "images_path": tmp_path / "demo_images.json",
    }
    bundle["raw_path"].write_text("raw pdf text", encoding="utf-8")
    bundle["images_path"].write_text(
        json.dumps([{"id": "img1", "filename": "images/a.png", "description": "desc"}]),
        encoding="utf-8",
    )

    calls = {}

    def fake_bundle(*args, **kwargs):
        calls["bundle"] = kwargs
        return bundle

    def fake_script(raw_text_path, **kwargs):
        calls["script"] = (raw_text_path, kwargs)
        script_path = tmp_path / "demo_script.txt"
        script_path.write_text("Segment 1:\nhello\n", encoding="utf-8")
        return {
            "stem": "demo",
            "raw_path": bundle["raw_path"],
            "script_path": script_path,
            "segments": ["hello"],
            "text": "raw pdf text",
        }

    class FakeArts:
        def __init__(self, storyboard_path):
            self.storyboard_path = storyboard_path

    def fake_storyboard(script_path, **kwargs):
        calls["storyboard"] = (script_path, kwargs)
        return FakeArts(tmp_path / "demo_storyboard.json")

    monkeypatch.setattr(
        "textbook2video.pipeline.pdf_layout.write_pdf_extract_bundle",
        fake_bundle,
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.orchestrator.build_script_from_text",
        fake_script,
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.orchestrator.build_storyboard_from_script",
        fake_storyboard,
    )

    arts = build_storyboard_pdf_general(
        "book.pdf",
        output_dir=tmp_path,
        start_page=21,
        max_pages=8,
        stem="demo",
        profile=profile,
        model="test-model",
        skip_tts=True,
    )

    assert arts.storyboard_path == tmp_path / "demo_storyboard.json"
    assert calls["bundle"]["start_page"] == 21
    assert calls["bundle"]["max_pages"] == 8
    assert calls["script"][0] == bundle["raw_path"]
    assert calls["storyboard"][1]["images"] == bundle["images_path"]
    assert calls["storyboard"][1]["model"] == "test-model"
