from textbook2video.animation_gen import build_slide_timelines
from textbook2video.pipeline.timing import (
    _apply_course_binding_timing,
    _visual_label_mentioned,
    apply_timing,
)


def test_joint_focus_keeps_parent_reveal_and_uses_measured_sentence():
    segment = {
        "id": "s1",
        "narration": "Overview. Both inputs feed the operation.",
        "audio_duration_sec": 7.0,
        "elements": [{"id": "figure", "type": "image"}],
        "animations": [],
        "timeline": [{"target": "figure", "action": "show", "at_sec": 0.0}],
        "course_visual_bindings": [{
            "proposition_id": "p1", "parent_id": "figure",
            "text": "Both inputs feed the operation.",
            "span": {"start": 10, "end": 41},
            "targets": ["input-a", "input-b"],
        }],
    }
    _apply_course_binding_timing(segment, [
        {"text": "Overview.", "start_sec": 0.0, "end_sec": 3.0},
        {"text": "Both inputs feed the operation.", "start_sec": 3.0, "end_sec": 7.0},
    ])
    timeline = segment["timeline"]
    assert timeline[0]["action"] == "show"
    assert [(event["target"], event["at_sec"], event["action"]) for event in timeline[1:]] == [
        ("input-a", 3.0, "focus"), ("input-b", 3.0, "focus"),
    ]


def test_narration_focuses_all_mentioned_objects_with_incomplete_review():
    sentences = ["先看这张图。", "SPLIT 后使用 mAR Prior。", "再看 mAR Prior。"]
    segment = {
        "id": "s1",
        "narration": "".join(sentences),
        "audio_duration_sec": 9.0,
        "elements": [{
            "id": "figure", "type": "image",
            "visual_object_targets": {
                "split": {"label": "SPLIT 操作"},
                "mar": {"label": "多尺度自回归模型 (mAR Prior)"},
                "gaussian": {"label": "简单高斯分布"},
            },
        }],
        "visual_review": {"asset_reviews": [{"checks": {"completeness": False}}]},
        "timeline": [{"target": "figure", "action": "show", "at_sec": 0.0}],
    }
    cues = [
        {"text": sentence, "start_sec": index * 3, "end_sec": (index + 1) * 3}
        for index, sentence in enumerate(sentences)
    ]
    timed = apply_timing({"segments": [segment]}, cues, timing_mode="semantic")
    events = build_slide_timelines(timed["segments"])[0]
    focused = [(e["target"], e["start_ms"]) for e in events if e["action"] == "focus"]
    assert focused == [
        ("split", 3000), ("mar", 3000), ("mar", 6000),
    ]
    assert timed["segments"][0]["visual_review"] == segment["visual_review"]
    assert apply_timing(timed, cues, timing_mode="semantic")["segments"] == timed["segments"]


def test_visual_label_matches_spoken_phrase_without_losing_negation():
    assert _visual_label_mentioned("保持不变路径", "另一半保持不变。")
    assert not _visual_label_mentioned("无顺序依赖", "维度间存在顺序依赖。")


def test_accepted_joint_binding_drives_compiled_events_instead_of_label_matching():
    from textbook2video.pipeline.course_binding import apply_course_bindings

    text = "The two inputs are combined."
    element = {"id": "figure", "type": "image", "visual_object_targets": {
        "a": {"label": "unspoken A"}, "b": {"label": "unspoken B"},
        "other": {"label": "inputs"},
    }}
    board = {"segments": [{"id": "s1", "narration": text, "audio_duration_sec": 6,
                           "elements": [element], "timeline": [
                               {"target": "figure", "action": "show", "at_sec": 0}]}]}
    row = {"segment_id": "s1", "element_id": "figure", "proposition_id": "p1",
           "text": text, "span": {"start": 0, "end": len(text)},
           "result": {"status": "BOUND_MULTIPLE", "selected_candidate_ids": ["a", "b"],
                      "semantic_check": {"verdict": "SUFFICIENT"}}}
    apply_course_bindings(board, {"method": "v1.3", "results": [row]})
    timed = apply_timing(board, [{"text": text, "start_sec": 2, "end_sec": 6}],
                         timing_mode="semantic")
    events = build_slide_timelines(timed["segments"])[0]
    signals = [e for e in events if e["action"] == "focus"]
    assert {e["target"] for e in signals} == {"a", "b"}
    assert {e["start_ms"] for e in signals} == {2000}
    assert row["adapter_status"] == "CONNECTED_TO_DYNAMIC_PLANNER"
    assert timed["segments"][0]["elements"] == board["segments"][0]["elements"]


def test_unresolved_binding_does_not_silently_become_lexical_focus():
    from textbook2video.pipeline.course_binding import apply_course_bindings

    for status, ids in [("SEMANTIC_UNCERTAIN", ["node"]), ("BOUND", ["unknown"])]:
        board = {"segments": [{"id": "s1", "narration": "Node.", "audio_duration_sec": 4,
                               "elements": [{"id": "figure", "type": "image",
                                             "visual_object_targets": {
                                                 "node": {"label": "Node"}}}]}]}
        row = {"segment_id": "s1", "element_id": "figure", "proposition_id": "p1",
               "text": "Node.", "span": {"start": 0, "end": 5},
               "result": {"status": status, "selected_candidate_ids": ids,
                          "semantic_check": {"verdict": "SUFFICIENT"}}}
        apply_course_bindings(board, {"method": "v1.3", "results": [row]})
        timed = apply_timing(board, [{"text": "Node.", "start_sec": 1, "end_sec": 4}],
                             timing_mode="semantic")
        events = build_slide_timelines(timed["segments"])[0]
        assert not any(e["action"] == "focus" for e in events)


def test_production_preparation_binds_before_measured_timing(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from textbook2video.pipeline import course_binding, course_visuals, orchestrator

    path = tmp_path / "storyboard.json"
    text = "Explain this relation."
    board = {"segments": [{"id": "s1", "narration": text, "elements": [
        {"id": "figure", "type": "image", "visual_object_targets": {"node": {}}}
    ]}], "metadata": {"course_visuals": {"asset_selection_path": str(tmp_path / "selection.json")}}}
    (tmp_path / "selection.json").write_text(json.dumps({"graph": "graph.json"}))
    path.write_text(json.dumps(board), encoding="utf-8")
    monkeypatch.setattr(course_visuals, "prepare_course_storyboard", lambda *a, **kw: path)
    def bind(*args, **kwargs):
        return {"method": "v1.3", "results": [{
            "segment_id": "s1", "element_id": "figure", "proposition_id": "p1",
            "text": text, "span": {"start": 0, "end": len(text)},
            "result": {"status": "BOUND", "selected_candidate_ids": ["figure"],
                       "semantic_check": {"verdict": "SUFFICIENT"}},
        }]}
    monkeypatch.setattr(course_binding, "bind_course_visuals", bind)
    def measure(planned, *args, **kwargs):
        assert kwargs["timing_mode"] == "semantic"
        assert planned["segments"][0]["course_visual_bindings"][0]["targets"] == ["figure"]
        return [4]
    monkeypatch.setattr(orchestrator, "run_tts", measure)
    (tmp_path / "demo_rq2_audit").mkdir()
    arts = SimpleNamespace(storyboard_path=path, output_dir=tmp_path, stem="demo",
                           raw_path=tmp_path / "source.txt", lesson_plan_path=None)
    orchestrator._prepare_default_course_visuals(
        arts, model=None, theme=None, browser="msedge", voice=None, rate=None,
        reuse_audio=False, frozen_audio_dir=None, timing_mode=None, rq2_audit=True,
    )
    assert arts.durations == [4]


def test_candidate_scope_is_independent_of_rq1_action():
    from textbook2video.pipeline.course_binding import _eligible_elements, _propositions_for_element
    elements = [{"id": action, "type": "image", "visual_acquisition_action": action}
                for action in ("reuse", "retrieve", "generate")]
    elements.extend([{"id": "native", "type": "flow_step"}, {"id": "body", "type": "text"}])
    segment = {"id": "s", "elements": elements}
    assert [e["id"] for _, e in _eligible_elements({"segments": [segment]})] == [
        "reuse", "retrieve", "generate", "native"]
    props = {"p": {"id": "p", "segment_id": "s", "source_refs": ["source"]},
             "other": {"id": "other", "segment_id": "other", "source_refs": ["source"]},
             "no-source": {"id": "no-source", "segment_id": "s", "source_refs": []}}
    assert _propositions_for_element(segment, elements[0], props) == [props["p"]]


def test_binding_advances_late_parent_reveal_and_preserves_other_targets():
    text = "The process has three stages."
    board = {"segments": [{"id": "s", "narration": text, "audio_duration_sec": 12,
        "elements": [{"id": "flow", "type": "flow_step", "steps": ["A", "B", "C"]},
                     {"id": "other", "type": "text", "text": "Context"}],
        "timeline": [{"target": "flow,other", "action": "show", "at_sec": 9}],
        "course_visual_bindings": [{"proposition_id": "p", "parent_id": "flow",
            "text": text, "span": {"start": 0, "end": len(text)}, "targets": ["flow"]}]}]}
    board["segments"][0]["timeline"].append({
        "event_id": "stale", "target": "flow", "action": "focus", "at_sec": 8,
        "research_p0": {"action_source": "course_binding_dynamic_plan"}})
    from textbook2video.pipeline.timing import _apply_course_binding_timing

    _apply_course_binding_timing(board["segments"][0],
                                 [{"text": text, "start_sec": 1, "end_sec": 4}])
    events = build_slide_timelines(board["segments"])[0]
    assert all(e.get("event_id") != "stale" for e in events)
    assert any(e["action"] == "focus" and e["target"] == "flow"
               and e["start_ms"] == 1000 for e in events)
    assert any(e["action"] == "show" and e["target"] == "other"
               and e["start_ms"] == 9000 for e in events)


def test_local_focus_units_preserve_narration_spans_and_source_refs():
    from textbook2video.pipeline.course_binding import _propositions_for_element
    text = ("The inputs are combined in the reconstruction. x = a + b. "
            "The result supplies the next prediction.")
    prop = {"id": "p", "segment_id": "s", "text": text,
            "span": {"start": 0, "end": len(text)}, "source_refs": ["source"]}
    units = _propositions_for_element({"id": "s", "narration": text},
                                     {"visual_object_targets": {"node": {}}}, {"p": prop})
    assert len(units) == 3
    for unit in units:
        assert text[unit["span"]["start"]:unit["span"]["end"]] == unit["text"]
        assert unit["source_refs"] == ["source"]
        assert unit["parent_proposition_id"] == "p"
        assert unit["focus_scope"] == "local"


def test_inline_relation_target_resolves_existing_svg_path(tmp_path):
    import hashlib

    from textbook2video.animation_gen import _inline_reviewed_visual_objects
    from textbook2video.animation_ids import visual_node_animation_id
    data = b'<svg xmlns="http://www.w3.org/2000/svg"><path data-edge="a:b" d="M0 0L10 10"/></svg>'
    path = tmp_path / "relation.svg"
    path.write_bytes(data)
    target = visual_node_animation_id("figure", "edge:a:b")
    html = _inline_reviewed_visual_objects(path, {"id": "figure",
        "visual_asset_sha256": hashlib.sha256(data).hexdigest(),
        "visual_object_targets": {target: {"edge_id": "a:b", "description": "relation"}}})
    assert target in html
    assert 'data-visual-object="edge"' in html


def test_local_units_inside_one_audio_cue_use_explicit_approximate_windows():
    from textbook2video.pipeline.timing import _apply_course_binding_timing

    text = "Read the input. Return the output."
    cut = text.index("Return")
    segment = {"id": "s", "narration": text, "audio_duration_sec": 10,
        "elements": [{"id": "figure", "type": "image"}],
        "timeline": [{"target": "figure", "action": "show", "at_sec": 0}],
        "course_visual_bindings": [
            {"proposition_id": "a", "parent_id": "figure", "text": text[:cut],
             "span": {"start": 0, "end": cut}, "targets": ["input"], "focus_scope": "local"},
            {"proposition_id": "b", "parent_id": "figure", "text": text[cut:],
             "span": {"start": cut, "end": len(text)}, "targets": ["output"],
             "focus_scope": "local"}]}
    _apply_course_binding_timing(segment, [{"text": text, "start_sec": 0, "end_sec": 10}])
    events = segment["course_dynamic_plan"]["events"]
    assert {e["target_element_id"] for e in events} == {"input", "output"}
    assert len({e["at_sec"] for e in events}) == 2
    assert segment["course_dynamic_plan"]["approximate_proposition_ids"] == ["a", "b"]
    assert "not forced alignment" in segment["course_dynamic_plan"]["claim"]
