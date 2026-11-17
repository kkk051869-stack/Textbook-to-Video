"""produce 端到端编排接线测试（不依赖 LLM/浏览器/网络，全部 mock 重步骤）。"""

import json
import math
import sys
import types
from pathlib import Path

import pytest

from textbook2video.pipeline import orchestrator
from textbook2video.pipeline.orchestrator import Artifacts, produce


def test_from_storyboard_uses_isolated_working_copy_and_preserves_images(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    (source / "images").mkdir(parents=True)
    (source / "images" / "figure.png").write_bytes(b"figure")
    source_storyboard = source / "lesson_storyboard.json"
    original = {
        "metadata": {"available_images": [{
            "id": "source-figure",
            "filename": "figure.png",
            "figure_id": "Figure 4",
            "caption": "Figure 4: Original source caption.",
        }]},
        "segments": [{
            "id": "1", "narration": "hello",
            "elements": [{"id": "fig", "type": "image", "src": "figure.png"}],
        }],
    }
    source_storyboard.write_text(json.dumps(original), encoding="utf-8")

    arts = orchestrator._artifacts_from_storyboard(
        source_storyboard, output_dir=output, skip_tts=True,
    )

    assert arts.storyboard_path == output / "lesson_storyboard.json"
    assert json.loads(source_storyboard.read_text(encoding="utf-8")) == original
    assert (output / "images" / "figure.png").read_bytes() == b"figure"
    working = json.loads(arts.storyboard_path.read_text(encoding="utf-8"))
    figure = working["segments"][0]["elements"][0]
    assert figure["source_image_id"] == "source-figure"
    assert figure["figure_id"] == "Figure 4"
    assert figure["source_caption"] == "Figure 4: Original source caption."


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """把 produce 依赖的重步骤替换为轻量桩，返回记录调用参数的字典。"""
    calls = {}

    audio_dir = tmp_path / "ch3_s0_audio"
    audio_dir.mkdir()
    sb_path = tmp_path / "ch3_s0_storyboard.json"
    sb_path.write_text("{}", encoding="utf-8")

    fake_arts = Artifacts(
        stem="ch3_s0", title="第4章", raw_path=tmp_path / "r.txt",
        script_path=tmp_path / "s.txt", storyboard_path=sb_path,
        output_dir=tmp_path, audio_dir=audio_dir, durations=[3.0, 4.5, 2.5],
    )

    def fake_build_docx(*a, **k):
        calls["build"] = k
        return fake_arts

    def fake_animate(sb, **k):
        calls["animate"] = (sb, k)
        html = tmp_path / "anim.html"
        html.write_text("<html></html>", encoding="utf-8")
        return html

    def fake_record(html, out, **k):
        calls["record"] = (html, out, k)
        Path(out).write_bytes(b"VIDEO")   # 造出无声中间视频

    def fake_compose(video, adir, out, **k):
        calls["compose"] = (video, adir, out, k)
        Path(out).write_bytes(b"FINAL")

    def fake_srt(storyboard, out, **k):
        calls["srt"] = (storyboard, out, k)
        Path(out).write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
        return Path(out)

    def fake_quality(storyboard, out, **k):
        calls["quality"] = (storyboard, out, k)
        Path(out).write_text("{}", encoding="utf-8")
        return Path(out)

    def fake_manifest(storyboard, html, **k):
        calls["manifest"] = (storyboard, html, k)
        path = tmp_path / "anim.manifest.json"
        path.write_text("{}", encoding="utf-8")
        return path

    monkeypatch.setattr(orchestrator, "build_storyboard_docx", fake_build_docx)
    # This fixture isolates production wiring. RQ1/RQ2/TTS-adapter behavior is
    # exercised with complete storyboards in test_recent_orchestrator.py.
    monkeypatch.setattr(orchestrator, "_prepare_default_course_visuals", lambda *a, **k: None)
    monkeypatch.setitem(
        sys.modules,
        "textbook2video.animation_gen",
        types.SimpleNamespace(generate=fake_animate),
    )
    monkeypatch.setitem(
        sys.modules,
        "textbook2video.pipeline.recorder",
        types.SimpleNamespace(record_html_to_video=fake_record),
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.compose.compose_video", fake_compose
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.subtitles.generate_srt", fake_srt
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.quality.write_quality_report", fake_quality
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.artifact_integrity.write_render_manifest", fake_manifest
    )
    return calls, fake_arts, tmp_path


def test_produce_wires_full_chain(wired):
    calls, arts, tmp_path = wired
    final = produce(
        "book.docx", chapter=3, section=0, output_dir=tmp_path,
        theme="dark-blue-academic", model="ecnu-plus",
    )
    # 最终成片路径 = <stem>.mp4
    assert final == tmp_path / "ch3_s0.mp4"
    assert final.read_bytes() == b"FINAL"

    # 录制时长 = ceil(总时长) + 1 余量
    total = sum(arts.durations)            # 10.0
    _, _, rec_kw = calls["record"]
    assert rec_kw["duration"] == math.ceil(total) + 1

    # compose 收到 (无声视频, 音频目录, 成片)
    video, adir, out, compose_kw = calls["compose"]
    assert Path(adir) == arts.audio_dir
    assert Path(out) == final
    assert Path(compose_kw["subtitle_path"]) == tmp_path / "ch3_s0.srt"

    # animate 收到 storyboard 路径 + 主题透传
    sb, anim_kw = calls["animate"]
    assert Path(sb) == arts.storyboard_path
    assert anim_kw["theme_id"] == "dark-blue-academic"
    assert Path(calls["quality"][1]) == tmp_path / "ch3_s0_quality.json"


@pytest.mark.parametrize("mode", [
    "phase2", "legacy", "supplied", "restore", "missing_cues", "bad_cues", "missing_review",
    "frozen_inputs", "missing_graph", "missing_decisions", "invalid_plan",
])
def test_produce_p0_mode_uses_production_animation_chain(wired, monkeypatch, mode):
    calls, arts, tmp_path = wired
    monkeypatch.delenv("T2V_RESEARCH_GENERATION_V2", raising=False)
    baseline_path = arts.storyboard_path
    order = []
    baseline = {
        "lesson_title": "第4章",
        "segments": [{
            "id": "seg-01",
            "narration": "先介绍概念。再解释关键机制。",
            "elements": [{
                "id": "existing-diagram", "type": "text", "text": "机制",
                "source_image_id": "fig-mechanism",
            }],
            "animations": [],
        }],
    }
    arts.storyboard_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    arts.raw_path.write_text("关键机制来自教材。", encoding="utf-8")
    arts.lesson_plan_path = tmp_path / "ch3_s0_lesson_plan.json"
    arts.lesson_plan_path.write_text(json.dumps({"knowledge_points": [{"id": "kp1", "name": "关键机制"}]}, ensure_ascii=False), encoding="utf-8")

    def fake_graph(**kwargs):
        order.append("graph")
        destination = Path(kwargs["output_path"])
        destination.write_text(json.dumps({
            "narration_propositions": [{
                "id": "test-seg-seg-01-nprop-001", "segment_id": "seg-01",
                "text": "再解释关键机制。", "span": {"start": 6, "end": 13},
                "knowledge_proposition_ids": ["test-kprop-001"], "source_refs": ["raw-unit-0001"],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        return destination

    monkeypatch.setattr("textbook2video.research.proposition_graph.build_proposition_graph", fake_graph)

    def fake_decision(**kwargs):
        order.append("decision")
        destination = Path(kwargs["output_path"])
        destination.write_text(json.dumps({"decisions": [{
            "narration_proposition_id": "test-seg-seg-01-nprop-001", "action": "reuse",
            "source_image_id": "fig-mechanism",
        }]}, ensure_ascii=False), encoding="utf-8")
        return destination

    def fake_acquisition(**kwargs):
        order.append("acquisition")
        destination = Path(kwargs["output_dir"]) / "visual_acquisition.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}", encoding="utf-8")
        return destination

    monkeypatch.setattr("textbook2video.research.visual_decision.decide_visual_support", fake_decision)
    monkeypatch.setattr("textbook2video.research.visual_acquisition.execute_visual_acquisition", fake_acquisition)
    def fake_tts(storyboard, storyboard_path, audio_dir, **_kwargs):
        order.append("tts")
        calls["p0_tts"] = storyboard_path
        calls["p0_tts_kwargs"] = _kwargs
        storyboard["segments"][0]["audio_duration_sec"] = 8.0
        Path(audio_dir).mkdir(parents=True, exist_ok=True)
        (Path(audio_dir) / "sentence_cues.json").write_text(json.dumps({
            "schema_version": "sentence-cues-v1",
            "segments": [{
                "segment_id": "seg-01",
                "duration_sec": 8.0,
                "cues": [
                    {"sentence_id": "seg-01-sent-01", "index": 1, "text": "先介绍概念。", "start_sec": 0.0, "end_sec": 3.0},
                    {"sentence_id": "seg-01-sent-02", "index": 2, "text": "再解释关键机制。", "start_sec": 3.0, "end_sec": 8.0},
                ],
            }],
        }, ensure_ascii=False), encoding="utf-8")
        Path(storyboard_path).write_text(
            json.dumps(storyboard, ensure_ascii=False), encoding="utf-8"
        )
        if mode == "missing_cues":
            (Path(audio_dir) / "sentence_cues.json").unlink()
        elif mode == "bad_cues":
            (Path(audio_dir) / "sentence_cues.json").write_text("{", encoding="utf-8")
        return [8.0]

    monkeypatch.setattr(orchestrator, "run_tts", fake_tts)
    import importlib
    for module_name, function_name, event in [
        ("candidate_pool", "build_frozen_candidate_pool", "pool"),
        ("p0_method_runner", "run_p0_method_suite", "methods"),
        ("p0_method_runner", "build_executable_p0_plan", "compile"),
    ]:
        module = importlib.import_module(f"textbook2video.research.{module_name}")
        original_fn = getattr(module, function_name)

        def tracked(*args, _fn=original_fn, _event=event, **kwargs):
            order.append(_event)
            return _fn(*args, **kwargs)

        monkeypatch.setattr(module, function_name, tracked)

    options = {}
    if mode == "frozen_inputs":
        graph_path = fake_graph(output_path=tmp_path / "frozen_graph.json")
        decision_path = fake_decision(output_path=tmp_path / "frozen_decisions.json")
        order.clear()
        options.update(p0_proposition_graph=graph_path, p0_visual_decisions=decision_path)
    elif mode == "missing_graph":
        options["p0_proposition_graph"] = tmp_path / "missing-graph.json"
    elif mode == "missing_decisions":
        options["p0_visual_decisions"] = tmp_path / "missing-decisions.json"
    elif mode == "invalid_plan":
        plan = tmp_path / "invalid-plan.json"
        plan.write_text('{"schema_version": "invalid", "events": []}', encoding="utf-8")
        options["p0_plan"] = plan
    elif mode == "legacy":
        options["p0_method_mode"] = "legacy"
    elif mode == "supplied":
        plan = tmp_path / "provided_plan.json"
        plan.write_text(json.dumps({"schema_version": "p0-event-plan-v0.1", "events": []}),
                        encoding="utf-8")
        options["p0_plan"] = plan
    elif mode == "restore":
        # Real restoration discovers source sidecars; TTS is stubbed below its boundary.
        (tmp_path / "ch3_s0_raw.txt").write_bytes(arts.raw_path.read_bytes())
        options.update(from_storyboard=baseline_path, reuse_audio=True,
                       frozen_audio_dir=tmp_path / "frozen_audio")
    elif mode == "missing_review":
        options["p0_vlm_review"] = tmp_path / "missing-review.json"

    error = {
        "missing_cues": (ValueError, "formal P0 generation requires measured"),
        "bad_cues": (ValueError, "P0 sentence cues could not be read"),
        "missing_review": (FileNotFoundError, "P0 VLM review does not exist"),
        "missing_graph": (FileNotFoundError, "missing-graph.json"),
        "missing_decisions": (FileNotFoundError, "P0 visual decision file does not exist"),
        "invalid_plan": (ValueError, "unsupported P0 plan schema"),
    }.get(mode)
    if error:
        with pytest.raises(error[0], match=error[1]):
            produce("book.docx", chapter=3, section=0, output_dir=tmp_path,
                    p0_research=True, **options)
        expected_order = {
            "missing_graph": [], "missing_decisions": ["graph"],
            "invalid_plan": ["graph", "decision", "acquisition"],
            "missing_review": ["graph", "decision", "acquisition"],
        }.get(mode, ["graph", "decision", "acquisition", "tts"])
        assert order == expected_order
        assert "animate" not in calls
        return
    final = produce("book.docx", chapter=3, section=0, output_dir=tmp_path,
                    p0_research=True, **options)
    expected_order = (["acquisition", "tts"] if mode == "frozen_inputs"
                      else ["graph", "decision", "acquisition", "tts"])
    if mode not in {"legacy", "supplied"}:
        expected_order += ["pool", "methods", "compile"]
    assert order == expected_order
    assert calls["p0_tts_kwargs"]["timing_mode"] == "semantic"
    assert calls["p0_tts_kwargs"]["reuse_existing_audio"] == (mode == "restore")
    assert calls["p0_tts_kwargs"]["frozen_audio_dir"] == options.get("frozen_audio_dir")
    if mode != "restore":
        assert calls["build"]["skip_tts"] is True

    assert final == tmp_path / "ch3_s0_p0.mp4"
    assert Path(calls["p0_tts"]).name == "ch3_s0_p0_storyboard.json"
    assert Path(calls["animate"][0]).name == "ch3_s0_p0_storyboard.json"
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == baseline
    sidecar = tmp_path / "ch3_s0_p0_research_p0.json"
    assert sidecar.is_file()
    events = json.loads(sidecar.read_text(encoding="utf-8"))["events"]
    if mode == "supplied":
        assert events == []
        assert not (tmp_path / "ch3_s0_p0_p0_phase2").exists()
    else:
        assert events[0]["status"] == "SCHEDULED_ON_PRODUCTION_ANIMATION"
        assert (tmp_path / "ch3_s0_p0_plan.json").is_file()



def test_produce_wires_agent_review_options(wired):
    calls, arts, tmp_path = wired
    produce(
        "book.docx",
        chapter=3,
        section=0,
        output_dir=tmp_path,
        agent_review=True,
        agent_review_rounds=3,
        agent_review_strict=True,
    )

    assert calls["build"]["agent_review"] is True
    assert calls["build"]["agent_review_rounds"] == 3
    assert calls["build"]["agent_review_strict"] is True


def test_produce_removes_silent_intermediate_by_default(wired):
    calls, arts, tmp_path = wired
    produce("book.docx", chapter=3, section=0, output_dir=tmp_path)
    assert not (tmp_path / "ch3_s0_silent.mp4").exists()


def test_produce_keeps_intermediate_when_requested(wired):
    calls, arts, tmp_path = wired
    produce("book.docx", chapter=3, section=0, output_dir=tmp_path,
            keep_intermediate=True)
    assert (tmp_path / "ch3_s0_silent.mp4").exists()


def test_produce_requires_lesson_or_chapter(tmp_path):
    with pytest.raises(ValueError):
        produce("book.pdf", output_dir=tmp_path)


def test_produce_from_storyboard_skips_content_generation(wired, monkeypatch):
    calls, arts, tmp_path = wired

    def fake_from_storyboard(*a, **k):
        calls["from_storyboard"] = (a, k)
        return arts

    monkeypatch.setattr(orchestrator, "_artifacts_from_storyboard", fake_from_storyboard)

    final = produce(
        "book.docx",
        output_dir=tmp_path,
        from_storyboard=tmp_path / "ch3_s0_storyboard.json",
    )

    assert final == tmp_path / "ch3_s0.mp4"
    assert "from_storyboard" in calls
    assert "build" not in calls


def test_produce_require_review_rejects_unapproved_storyboard(wired):
    calls, arts, tmp_path = wired
    arts.storyboard_path.write_text(
        json.dumps({"segments": [], "metadata": {}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="human-approved"):
        produce(
            "book.docx",
            chapter=3,
            section=0,
            output_dir=tmp_path,
            require_review=True,
        )

    assert "animate" not in calls


def test_produce_require_review_allows_approved_storyboard(wired):
    calls, arts, tmp_path = wired
    arts.storyboard_path.write_text(
        json.dumps({
            "segments": [],
            "metadata": {"human_review": {"status": "approved"}},
        }),
        encoding="utf-8",
    )

    final = produce(
        "book.docx",
        chapter=3,
        section=0,
        output_dir=tmp_path,
        require_review=True,
    )

    assert final == tmp_path / "ch3_s0.mp4"
    assert "animate" in calls


def test_produce_from_html_requires_storyboard(tmp_path):
    with pytest.raises(ValueError):
        produce("book.docx", output_dir=tmp_path, from_html=tmp_path / "x.html")
