from __future__ import annotations

import json
from copy import deepcopy

import pytest

from textbook2video.pipeline import course_visuals, orchestrator
from textbook2video.research import visual_tools as tools

SOURCE = "采集数据。处理数据。"


def approved_panels(tmp_path, *, spans=("采集数据。", "处理数据。")):
    specs = [
        {
            "id": f"panel-{i}",
            "schema_version": "teaching-visual-v2",
            "kind": "flow",
            "title": f"阶段{i}",
            "teaching_goal": "理解数据处理",
            "narration_span": span,
            "nodes": [
                {"id": "a", "label": "输入", "evidence": SOURCE},
                {"id": "b", "label": "输出", "evidence": SOURCE},
            ],
            "edges": [{"source": "a", "target": "b", "evidence": SOURCE}],
        }
        for i, span in enumerate(spans, 1)
    ]
    directory = tmp_path / "approved"
    tools.dispatch("create", {"visuals": specs}, source=SOURCE, output_dir=directory, render=False)
    report = tools._save_review(
        directory,
        json.dumps(
            {
                "verdict": "ACCEPT",
                "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
                "issues": [],
                "reason": "fixture review",
            }
        ),
        [],
        model="test",
        has_images=True,
    )
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "status": "MODEL_REVIEWED_PENDING_HUMAN",
                "accepted_revision": str(directory),
                "history": [{"revision": str(directory), "review_sha256": tools.digest(report)}],
            }
        ),
        encoding="utf-8",
    )
    return run_path


def board():
    return {
        "total_slides": 1,
        "segments": [
            {
                "id": "lesson-part",
                "narration": SOURCE,
                "audio_duration_sec": 10,
                "visual_type": "process",
                "elements": [{"id": "h", "type": "heading", "text": "数据处理"}],
                "timeline": [{"target": "h", "at_sec": 2}],
            }
        ],
    }


def test_split_panels_are_actual_pages_before_tts_and_preserve_every_word(monkeypatch, tmp_path):
    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    segments = board()["segments"]
    original = deepcopy(segments)
    images = course_visuals.generate_course_visuals(
        segments, output_dir=tmp_path, model="test", theme="bright", rebuild_timing_before_tts=True
    )
    assert len(segments) == 2 and len(images) == 2
    assert "".join(s["narration"] for s in segments) == SOURCE
    assert len({s["id"] for s in segments}) == 2
    for child in segments:
        assert child["timeline"] == [] and child["animations"] == []
        assert child["visual_timing_rebuild"]["original_timeline"] == original[0]["timeline"]
        assert child["visual_origin_segment_id"] == "lesson-part"


def test_a_split_cannot_omit_or_rewrite_narration(monkeypatch, tmp_path):
    run = approved_panels(tmp_path, spans=("采集数据。", "处理。"))
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    with pytest.raises(ValueError, match="partition narration verbatim"):
        course_visuals.generate_course_visuals(
            board()["segments"],
            output_dir=tmp_path,
            model="test",
            theme="bright",
            rebuild_timing_before_tts=True,
        )


def test_prepared_storyboard_and_images_are_new_artifacts_not_overwritten_input(
    monkeypatch, tmp_path
):
    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board(), ensure_ascii=False), encoding="utf-8")
    original = source.read_bytes()
    raw = tmp_path / "textbook.txt"
    raw.write_text(SOURCE, encoding="utf-8")
    output = course_visuals.prepare_course_storyboard(
        source,
        output_dir=tmp_path,
        model="test",
        theme="bright",
        browser="msedge",
        source_path=raw,
        source_scope="textbook",
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert source.read_bytes() == original and output != source
    assert result["total_slides"] == 2
    assert result["metadata"]["course_visuals"]["source_scope"] == "textbook"
    review_report = json.loads(
        (output.parent / "visual-review-report.json").read_text(encoding="utf-8")
    )
    assert review_report == result["metadata"]["course_visuals"]
    assert review_report["review_policy"] == "strict"
    assert review_report["human_review"] == "NOT_REVIEWED"
    for segment in result["segments"]:
        picture = next(e for e in segment["elements"] if e["type"] == "image")
        assert (output.parent / "images" / picture["src"]).is_file()


def test_production_prepares_visuals_before_measured_audio_alignment(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board()), encoding="utf-8")
    planned = tmp_path / "planned.json"
    planned.write_text(json.dumps(board()), encoding="utf-8")
    calls = []

    def prepare(*args, **kwargs):
        assert kwargs["review_policy"] == "development"
        calls.append("visuals")
        return planned

    def tts(data, path, audio_dir, **kwargs):
        assert calls == ["visuals"] and path == planned
        assert data["segments"][0]["narration"] == SOURCE
        calls.append("measured_tts")
        return [7.125]

    monkeypatch.setattr(course_visuals, "prepare_course_storyboard", prepare)
    monkeypatch.setattr(orchestrator, "run_tts", tts)
    arts = orchestrator.Artifacts(
        stem="lesson",
        title="数据处理",
        raw_path=tmp_path / "raw.txt",
        script_path=tmp_path / "script.txt",
        storyboard_path=source,
        output_dir=tmp_path,
    )
    orchestrator._prepare_default_course_visuals(
        arts,
        model="test",
        theme="bright",
        browser="msedge",
        voice=None,
        rate=None,
        reuse_audio=False,
        frozen_audio_dir=None,
        timing_mode="semantic",
    )
    assert calls == ["visuals", "measured_tts"] and arts.durations == [7.125]
    assert arts.storyboard_path == planned


def test_split_cannot_reuse_ordinary_old_audio_cache(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board()), encoding="utf-8")
    split = board()
    split["segments"] = [
        dict(split["segments"][0], narration="采集数据。"),
        dict(split["segments"][0], id="second", narration="处理数据。"),
    ]
    planned = tmp_path / "planned.json"
    planned.write_text(json.dumps(split), encoding="utf-8")
    monkeypatch.setattr(course_visuals, "prepare_course_storyboard", lambda *a, **kw: planned)
    monkeypatch.setattr(
        orchestrator, "run_tts", lambda *a, **kw: pytest.fail("old audio must not be reused")
    )
    arts = orchestrator.Artifacts(
        stem="lesson",
        title="data",
        raw_path=tmp_path / "raw.txt",
        script_path=tmp_path / "script.txt",
        storyboard_path=source,
        output_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="cached/frozen"):
        orchestrator._prepare_default_course_visuals(
            arts,
            model="test",
            theme="bright",
            browser="msedge",
            voice=None,
            rate=None,
            reuse_audio=True,
            frozen_audio_dir=None,
            timing_mode="legacy",
        )


def test_copied_cover_and_distinct_panels_cannot_overwrite_each_other(monkeypatch, tmp_path):
    import hashlib

    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    source = tmp_path / "source.json"
    source_images = tmp_path / "images"
    source_images.mkdir()
    name = "generated-page-002.svg"
    cover_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><title>original-cover</title></svg>'
    (source_images / name).write_bytes(cover_bytes)
    data = board()
    data["segments"].insert(
        0,
        {
            "id": "cover",
            "narration": "开场。",
            "visual_type": "title",
            "elements": [{"id": "cover-picture", "type": "image", "src": name}],
        },
    )
    source.write_text(json.dumps(data), encoding="utf-8")
    destination = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge"
    )
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert (destination.parent / "images" / name).read_bytes() == cover_bytes
    records = result["metadata"]["course_visuals"]["assets"]
    assert len(records) == 2 and records[0]["filename"] != records[1]["filename"]
    for record in records:
        actual = (destination.parent / "images" / record["filename"]).read_bytes()
        assert hashlib.sha256(actual).hexdigest() == record["sha256"]
    assert len(list((destination.parent / "images").iterdir())) == 3


def test_copied_asset_hash_is_checked_again_at_render_time(monkeypatch, tmp_path):
    from textbook2video.animation_gen import load_textbook_images

    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board()), encoding="utf-8")
    path = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    record = data["metadata"]["course_visuals"]["assets"][0]
    (path.parent / "images" / record["filename"]).write_bytes(b"changed after review")
    with pytest.raises(ValueError, match="hash drift"):
        load_textbook_images(data["segments"], path.parent / "images")


def test_textbook_asset_is_not_retained_on_two_course_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(
        course_visuals, "run_visual_agent", lambda *a, **kw: pytest.fail("cover skipped")
    )
    images = tmp_path / "images"
    images.mkdir()
    (images / "same.svg").write_bytes(b"original")
    source = tmp_path / "source.json"
    data = {
        "segments": [
            {
                "id": str(i),
                "narration": "cover",
                "visual_type": "title",
                "elements": [{"id": "pic", "type": "image", "src": "same.svg"}],
            }
            for i in range(2)
        ]
    }
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="at most one"):
        course_visuals.prepare_course_storyboard(
            source, output_dir=tmp_path, model="test", theme="bright", browser="msedge"
        )
