"""Engineering fixtures: no model, TTS service or recording requests."""

import copy
import json
import wave
from pathlib import Path

import pytest

from textbook2video.animation_gen import build_slide_timelines
from textbook2video.pipeline import joint_planning as joint
from textbook2video.pipeline import orchestrator
from textbook2video.pipeline.timing import apply_timing

SOURCE = "Branch A retains input. Branch B transforms input."


def response():
    return {
        "segments": [
            {
                "visual_type": "comparison",
                "elements": [
                    {
                        "id": "branches",
                        "type": "comparison_panel",
                        "items": [
                            {"title": "A", "content": "Retains input"},
                            {"title": "B", "content": "Transforms input"},
                        ],
                    },
                ],
                "visual_relations": [
                    {
                        "id": "contrast",
                        "kind": "contrast",
                        "from": [{"element_id": "branches", "index": 0}],
                        "to": [{"element_id": "branches", "index": 1}],
                        "source_refs": ["raw-unit-0001"],
                        "display_explanation": "Two alternative branch descriptions are compared.",
                    }
                ],
                "teaching_actions": [
                    {
                        "teaching_goal": "Explain A",
                        "narration": "Branch A retains input. It stays as input.",
                        "source_refs": ["raw-unit-0001"],
                        "focus": [{"element_id": "branches", "index": 0}],
                        "background": [{"element_id": "branches", "index": 1}],
                        "focus_reason": "A is being explained",
                        "relation_refs": ["contrast"],
                    },
                    {
                        "teaching_goal": "Explain B",
                        "narration": "Branch B transforms input.",
                        "source_refs": ["raw-unit-0001"],
                        "focus": [{"element_id": "branches", "index": 1}],
                        "background": [{"element_id": "branches", "index": 0}],
                        "focus_reason": "B is being explained",
                        "relation_refs": ["contrast"],
                    },
                ],
            }
        ]
    }


def generate(tmp_path, monkeypatch, payload=None):
    monkeypatch.setattr(
        "textbook2video.llm.client.chat", lambda *a, **k: json.dumps(payload or response())
    )
    return joint.generate_joint_storyboard(
        SOURCE,
        lesson_title="Branches",
        model="test",
        output_dir=tmp_path,
        stem="fixture",
        lesson_plan={},
    )


def cues(segment):
    return [
        {"sentence_id": f"a-{i}", "text": a["narration"], "start_sec": start, "end_sec": end}
        for i, (a, start, end) in enumerate(zip(segment["teaching_actions"], [0, 3], [3, 11]))
    ]


def test_joint_plan_roundtrip_compiles_distinct_children_full_action_holds(tmp_path, monkeypatch):
    board = generate(tmp_path, monkeypatch)
    segment = board["segments"][0]
    segment["audio_duration_sec"] = 11
    segment["timeline"] = [{"target": "branches", "action": "focus", "at_sec": 1}]
    segment["course_visual_bindings"] = [{"targets": ["branches"]}]
    original = copy.deepcopy(board)
    timed = apply_timing(board, cues(segment), timing_mode="semantic")
    assert board == original
    assert apply_timing(timed, cues(segment), timing_mode="semantic") == timed
    reloaded = json.loads(json.dumps(timed))
    events = build_slide_timelines(reloaded["segments"])[0]
    focused = [e for e in events if e["action"] == "focus"]
    assert [e["target"] for e in focused] == ["branches--item-0", "branches--item-1"]
    assert [e["hold_ms"] for e in focused] == [2880, 7880]
    assert [e["start_ms"] for e in focused] == [120, 3120]
    shown = [e for e in events if e["action"] == "show"]
    assert len(shown) == 1
    assert shown[0]["effect"] == "fadeInUp"


@pytest.mark.parametrize("bad", ["source_refs", "target", "background", "image"])
def test_invalid_plans_preserve_response_and_reject(tmp_path, monkeypatch, bad):
    payload = response()
    page = payload["segments"][0]
    if bad == "source_refs":
        page["teaching_actions"][0]["source_refs"] = ["raw-unit-9999"]
    elif bad == "target":
        page["teaching_actions"][0]["focus"][0]["index"] = 9
    elif bad == "background":
        page["teaching_actions"][0]["background"] = page["teaching_actions"][0]["focus"]
    else:
        page["elements"].append({"id": "unknown", "type": "image", "source_image_id": "made-up"})
    with pytest.raises(ValueError, match="rejected"):
        generate(tmp_path, monkeypatch, payload)
    assert (
        json.loads((tmp_path / "fixture_joint_planning/chunk-001.response.txt").read_text())
        == payload
    )
    assert (tmp_path / "fixture_joint_planning/chunk-001.failure.json").exists()


def test_wrong_audio_cues_cannot_be_used_for_actions(tmp_path, monkeypatch):
    board = generate(tmp_path, monkeypatch)
    segment = board["segments"][0]
    segment["audio_duration_sec"] = 11
    wrong = cues(segment)
    wrong[0]["text"] = "another narration"
    with pytest.raises(ValueError, match="do not match"):
        apply_timing(board, wrong)
    with pytest.raises(ValueError, match="measured audio cues"):
        apply_timing(board)


def test_no_signal_and_invalid_cue_coverage(tmp_path, monkeypatch):
    board = generate(tmp_path, monkeypatch)
    page = board["segments"][0]
    page["audio_duration_sec"] = 11
    page["teaching_actions"][1]["focus"] = []
    timed = apply_timing(board, cues(page))
    assert len([e for e in timed["segments"][0]["timeline"] if e["action"] == "focus"]) == 1
    bad = cues(page)
    bad[1]["start_sec"] = 4
    with pytest.raises(ValueError, match="noncontiguous"):
        apply_timing(board, bad)
    page["audio_duration_sec"] = 12
    with pytest.raises(ValueError, match="do not cover"):
        apply_timing(board, cues(page))


def test_source_chunking_does_not_drop_or_duplicate_text():
    source = "First relation. Second relation.\n并列关系。条件关系。\n" * 80
    chunks = joint._source_chunks(source)
    assert len(chunks) > 1
    assert "".join(chunks) == source


def test_initial_root_focus_does_not_overlap_a_show_on_same_object(tmp_path, monkeypatch):
    payload = response()
    page = payload["segments"][0]
    page["elements"].append({"id": "intro", "type": "text", "text": "Input"})
    page["teaching_actions"][0]["focus"] = [{"element_id": "intro", "index": None}]
    board = generate(tmp_path, monkeypatch, payload)
    segment = board["segments"][0]
    segment["audio_duration_sec"] = 11
    timed = apply_timing(board, cues(segment))
    events = build_slide_timelines(timed["segments"])[0]
    assert [(e["action"], e["start_ms"]) for e in events if e["target"] == "intro"] == [
        ("focus", 120)
    ]


def test_joint_renderer_keeps_text_when_image_is_rejected_and_renders_single_panel_item():
    from textbook2video.template_renderer import render_slide

    segment = {
        "id": "joint-example",
        "visual_type": "comparison",
        "joint_planning": {"producer": joint.VERSION},
        "visual_timing_rebuild": {"page_strategy": "preserve-components-with-acquisition"},
        "elements": [
            {"id": "title", "type": "heading", "text": "Two supported concepts"},
            {"id": "blocked-image", "type": "image", "src": "missing.png", "_render_blocked": True},
            {"id": "explanation", "type": "text", "text": "The sourced explanation remains visible."},
            {
                "id": "concept-card",
                "type": "comparison_panel",
                "items": [{"title": "Concept", "content": "Supported detail"}],
            },
        ],
    }

    html = render_slide(segment, 0, set())

    assert html is not None
    assert 'data-anim-id="title"' in html
    assert 'data-anim-id="explanation"' in html
    assert 'data-anim-id="concept-card"' in html
    assert 'data-anim-id="concept-card--item-0"' in html
    assert 'data-anim-id="blocked-image"' not in html
    assert "Supported detail" in html


@pytest.mark.parametrize("extension", ["pdf", "docx"])
def test_ordinary_produce_uses_joint_planning_and_measured_actions(
    tmp_path, monkeypatch, extension
):
    from textbook2video.pipeline.sentence_audio import build_sentence_cues, write_sentence_cues
    from textbook2video.pipeline.visual_page_render import course_page_html

    monkeypatch.setenv("T2V_TTS_BACKEND", "sapi")
    for key in ("T2V_RESEARCH_GENERATION_V2", "T2V_TIMING_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "textbook2video.pipeline.parser.extract_pdf_pages_info",
        lambda *a: {"text": SOURCE, "pages": (1, 1), "title": "Branches"},
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.parser.extract_section_from_docx",
        lambda *a, **k: {"text": SOURCE, "images": []},
    )
    monkeypatch.setattr(
        "textbook2video.pipeline.lesson_plan.generate_lesson_plan", lambda *a, **k: {}
    )
    calls = []
    monkeypatch.setattr(
        "textbook2video.llm.client.chat",
        lambda *a, **k: calls.append("joint") or json.dumps(response()),
    )

    def old_path(*a, **k):
        pytest.fail("fresh ordinary produce used separate script/storyboard generation")

    monkeypatch.setattr("textbook2video.pipeline.scriptwriter.generate_script", old_path)
    monkeypatch.setattr("textbook2video.pipeline.storyboard.generate_storyboard", old_path)

    def preserve(path, **kwargs):
        assert kwargs["preserve_existing_pages"] is True
        assert kwargs["rebuild_page_from_source"] is False
        return Path(path)

    monkeypatch.setattr(
        "textbook2video.pipeline.course_visuals.prepare_course_storyboard", preserve
    )

    def audio(groups, *, output_dir, segment_ids, **kwargs):
        # The first action contains two sentences: it must remain ONE cue.
        assert groups[0] == [a["narration"] for a in response()["segments"][0]["teaching_actions"]]
        folder = Path(output_dir)
        folder.mkdir(exist_ok=True)
        wav = folder / "s1.wav"
        with wave.open(str(wav), "wb") as f:
            f.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
            f.writeframes(b"\x01\x00" * 11000)
        sidecar = write_sentence_cues(
            folder / "sentence_cues.json",
            [
                {
                    "segment_id": segment_ids[0],
                    "duration_sec": 11,
                    "cues": [
                        c.__dict__ for c in build_sentence_cues(segment_ids[0], groups[0], [3, 8])
                    ],
                }
            ],
        )
        return {"audio_files": [wav], "sentence_cues_path": sidecar}

    monkeypatch.setattr("textbook2video.pipeline.narrator.generate_sentence_audio", audio)
    monkeypatch.setattr("textbook2video.pipeline.narrator.get_audio_duration", lambda p: 11.0)

    def render(path, **kwargs):
        board = json.loads(Path(path).read_text(encoding="utf-8"))
        events = build_slide_timelines(board["segments"])[0]
        assert [e["target"] for e in events if e["action"] == "focus"] == [
            "branches--item-0",
            "branches--item-1",
        ]
        html = tmp_path / "page.html"
        html.write_text(
            course_page_html(board["segments"][0], {}, theme="bright"), encoding="utf-8"
        )
        return html

    monkeypatch.setattr("textbook2video.animation_gen.generate", render)
    monkeypatch.setattr(
        "textbook2video.pipeline.artifact_integrity.write_render_manifest",
        lambda *a, **k: tmp_path / "manifest.json",
    )

    def record(html, output, **kwargs):
        calls.append("record_stub")
        Path(output).write_bytes(b"engineering fixture video")

    def compose(video, audio_dir, output, **kwargs):
        calls.append("compose_stub")
        Path(output).write_bytes(b"engineering fixture mux")

    monkeypatch.setattr("textbook2video.pipeline.recorder.record_html_to_video", record)
    monkeypatch.setattr("textbook2video.pipeline.compose.compose_video", compose)
    options = {"pdf_page_range": (1, 1)} if extension == "pdf" else {"chapter": 0, "section": 0}
    result = orchestrator.produce(
        f"book.{extension}", output_dir=tmp_path, quality_report=False, **options
    )
    assert result.exists()
    assert calls == ["joint", "record_stub", "compose_stub"]
