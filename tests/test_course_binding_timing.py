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
    assert [(event["target"], event["start_ms"]) for event in events if event["action"] == "focus"] == [
        ("split", 3000), ("mar", 3000), ("mar", 6000),
    ]
    assert timed["segments"][0]["visual_review"] == segment["visual_review"]
    assert apply_timing(timed, cues, timing_mode="semantic")["segments"] == timed["segments"]


def test_visual_label_matches_spoken_phrase_without_losing_negation():
    assert _visual_label_mentioned("保持不变路径", "另一半保持不变。")
    assert not _visual_label_mentioned("无顺序依赖", "维度间存在顺序依赖。")
