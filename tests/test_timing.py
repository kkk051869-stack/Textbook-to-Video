import json

from textbook2video.pipeline.timing import (
    apply_timing,
    build_segment_timing,
    timed_storyboard_path,
    write_timed_storyboard,
)


def test_explicit_narration_binding_anchors_an_english_captioned_image():
    sentence = '哈希函数把输入数据转换成固定长度的散列值。'
    segment = {'id': 1, 'audio_duration_sec': 12,
               'narration': '区块链把多个区块连接起来。' + sentence,
               'elements': [{'id': 'retrieved-hash', 'type': 'image',
                             'description': 'English diagram: text input and hash sums',
                             'visual_brief_proposition': sentence}]}
    cues = [{'sentence_id': 'chain', 'text': '区块链把多个区块连接起来。',
             'start_sec': 0, 'end_sec': 5},
            {'sentence_id': 'hash', 'text': sentence, 'start_sec': 5, 'end_sec': 12}]
    events = build_segment_timing(segment, cues, lead_sec=0, timing_mode='semantic')
    assert events[0]['trigger_source'] == 'text_match'
    assert events[0]['matched_sentence_id'] == 'hash'
    assert events[0]['trigger_at_sec'] == 5


def test_build_segment_timing_creates_monotonic_triggers():
    segment = {
        "id": 1,
        "narration": "算法是一组解决问题的明确步骤。它不等同于程序。",
        "audio_duration_sec": 6.0,
        "elements": [
            {"id": "e1", "type": "heading", "text": "算法"},
            {"id": "e2", "type": "text", "text": "解决问题的明确步骤"},
            {"id": "e3", "type": "comparison_panel", "items": ["算法", "程序"]},
        ],
        "animations": [{"target": "e2", "effect": "fadeIn"}],
    }

    animations = build_segment_timing(segment)

    assert [a["target"] for a in animations] == ["e1", "e2", "e3"]
    assert animations[0]["trigger_at_sec"] == 0.0
    assert animations[1]["effect"] == "fadeIn"
    triggers = [a["trigger_at_sec"] for a in animations]
    assert triggers == sorted(triggers)
    assert triggers[-1] <= 4.8


def test_apply_timing_adds_metadata_and_clamps_short_audio():
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "短句。",
                "audio_duration_sec": 0.8,
                "elements": [
                    {"id": "e1", "type": "heading", "text": "短句"},
                    {"id": "e2", "type": "text", "text": "补充"},
                ],
            }
        ]
    }

    timed = apply_timing(storyboard)

    assert timed is not storyboard
    assert timed["metadata"]["timing_source"] == "deterministic_subtitle_cues"
    triggers = [
        anim["trigger_at_sec"]
        for anim in timed["segments"][0]["animations"]
    ]
    assert triggers[-1] <= 0.48


def test_write_timed_storyboard_uses_sibling_name(tmp_path):
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "hello",
                "audio_duration_sec": 2.0,
                "elements": [{"id": "e1", "type": "heading", "text": "hello"}],
            }
        ]
    }
    sb_path = tmp_path / "lesson4_storyboard.json"
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")

    out = write_timed_storyboard(storyboard, sb_path)

    assert out == tmp_path / "lesson4_timed_storyboard.json"
    assert out == timed_storyboard_path(sb_path)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["segments"][0]["animations"][0]["trigger_at_sec"] == 0.0


def test_semantic_timing_updates_runtime_timeline_and_splits_groups():
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "区块。哈希。",
                "audio_duration_sec": 5.0,
                "elements": [
                    {"id": "e1", "type": "text", "text": "区块"},
                    {"id": "e2", "type": "text", "text": "哈希"},
                ],
                "timeline": [{"at_sec": 0.0, "action": "show", "target": "e1,e2", "stagger": True}],
            }
        ]
    }
    cues = {
        "segments": [
            {
                "segment_id": 1,
                "cues": [
                    {"sentence_id": "s1", "index": 1, "text": "区块", "start_sec": 1.0, "end_sec": 2.0},
                    {"sentence_id": "s2", "index": 2, "text": "哈希", "start_sec": 3.0, "end_sec": 4.0},
                ],
            }
        ]
    }

    timed = apply_timing(storyboard, cues, timing_mode="semantic")
    timeline = timed["segments"][0]["timeline"]

    assert [item["target"] for item in timeline] == ["e1", "e2"]
    assert [item["at_sec"] for item in timeline] == [0.0, 2.0]
    assert [item["matched_sentence_id"] for item in timeline] == ["s1", "s2"]


def test_semantic_timing_preserves_independent_p0_show_and_focus_events():
    storyboard = {
        "segments": [{
            "id": 1,
            "narration": "鍥惧舰銆?",
            "audio_duration_sec": 5.0,
            "elements": [{"id": "figure", "type": "image", "text": "鍥惧舰"}],
            "animations": [
                {
                    "target": "figure", "action": "show", "effect": "fadeInUp",
                    "trigger_at_sec": 1.0,
                    "research_p0": {"event_id": "show-1"},
                },
                {
                    "target": "figure", "action": "focus", "effect": "highlight",
                    "trigger_at_sec": 1.2,
                    "research_p0": {"event_id": "focus-1"},
                },
            ],
            "timeline": [
                {
                    "target": "figure", "action": "show", "at_sec": 1.0,
                    "research_p0": {"event_id": "show-1"},
                },
                {
                    "target": "figure", "action": "focus", "at_sec": 1.2,
                    "research_p0": {"event_id": "focus-1"},
                },
            ],
        }]
    }
    timed = apply_timing(
        storyboard,
        {
            "segments": [{"segment_id": 1, "cues": [
                {"sentence_id": "s1", "index": 1, "text": "鍥惧舰", "start_sec": 0.0, "end_sec": 2.0},
            ]}],
        },
        timing_mode="semantic",
    )
    p0_events = [
        item for item in timed["segments"][0]["timeline"]
        if isinstance(item.get("research_p0"), dict)
    ]
    assert [item["action"] for item in p0_events] == ["show", "focus"]
    assert [item["research_p0"]["event_id"] for item in p0_events] == ["show-1", "focus-1"]


def test_semantic_timing_keeps_heading_visible_and_matches_panel_content():
    segment = {
        "id": 2,
        "narration": "Introducing DVC. Compare block motion estimation with optical flow.",
        "audio_duration_sec": 8.0,
        "elements": [
            {"id": "heading", "type": "heading", "text": "DVC architecture"},
            {
                "id": "comparison",
                "type": "comparison_panel",
                "items": [{"title": "Legacy", "content": "block motion estimation"}],
            },
        ],
    }
    cues = [
        {"sentence_id": "s1", "text": "Introducing DVC.", "start_sec": 0.0, "end_sec": 2.0},
        {
            "sentence_id": "s2",
            "text": "Compare block motion estimation with optical flow.",
            "start_sec": 3.0,
            "end_sec": 6.0,
        },
    ]

    animations = build_segment_timing(segment, cues, timing_mode="semantic")

    assert animations[0]["trigger_at_sec"] == 0.0
    assert animations[0]["trigger_source"] == "structural_anchor"
    assert animations[1]["matched_sentence_id"] == "s2"
    assert animations[1]["trigger_at_sec"] == 2.0
