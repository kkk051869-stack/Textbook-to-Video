import io
import wave
from pathlib import Path

import pytest

from textbook2video.pipeline import narrator
from textbook2video.pipeline.sentence_audio import (
    build_sentence_cues,
    concat_wav_bytes,
    sentence_cache_key,
    wav_duration,
)
from textbook2video.pipeline.subtitles import SentenceSplitter, build_subtitle_cues
from textbook2video.pipeline.timing import build_segment_timing
from textbook2video.pipeline.timing import apply_timing


def _wav(seconds: float, rate: int = 1000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\0\0" * int(seconds * rate))
    return out.getvalue()


def test_sentence_splitter_keeps_sentence_boundaries():
    assert SentenceSplitter().split("第一句。第二句！第三句？") == [
        "第一句。",
        "第二句！",
        "第三句？",
    ]


def test_concat_wav_bytes_is_in_memory_and_preserves_duration():
    merged = concat_wav_bytes([_wav(1.0), _wav(2.0)])
    assert abs(wav_duration(merged) - 3.0) < 0.01


def test_concat_wav_rejects_mismatched_format():
    with pytest.raises(ValueError, match="parameters"):
        concat_wav_bytes([_wav(1.0, 1000), _wav(1.0, 2000)])


def test_sentence_cue_audio_hash_is_optional_but_stable():
    cues = build_sentence_cues(1, ["one"], [1.0], audio_hashes=["a" * 64])
    assert cues[0].audio_sha256 == "a" * 64


def test_build_sentence_cues_are_contiguous():
    cues = build_sentence_cues(4, ["一。", "二。"], [1.25, 2.5])
    assert cues[0].start_sec == 0.0
    assert cues[0].end_sec == cues[1].start_sec
    assert cues[-1].end_sec == 3.75


def test_sentence_cache_key_includes_config():
    a = sentence_cache_key("你好", backend="megatts3", config={"t": 24})
    b = sentence_cache_key("你好", backend="megatts3", config={"t": 25})
    assert a != b


def test_real_sentence_cues_drive_subtitles_and_animation_timing():
    sidecar = {
        "segments": [{
            "segment_id": 1,
            "cues": [
                {"text": "第一句。", "start_sec": 0.0, "end_sec": 1.2},
                {"text": "关键概念。", "start_sec": 1.2, "end_sec": 2.8},
            ],
        }]
    }
    storyboard = {
        "segments": [{
            "id": 1,
            "narration": "第一句。关键概念。",
            "audio_duration_sec": 2.8,
            "elements": [
                {"id": "h", "type": "heading", "text": "标题"},
                {"id": "k", "type": "text", "text": "关键概念"},
            ],
        }]
    }
    cues = build_subtitle_cues(storyboard, sentence_cues=sidecar)
    assert [(cue.start_sec, cue.end_sec) for cue in cues] == [(0.0, 1.2), (1.2, 2.8)]
    animations = build_segment_timing(storyboard["segments"][0], sidecar["segments"][0]["cues"])
    # A reliable semantic anchor is exactly sentence_start - lead.
    assert animations[1]["trigger_at_sec"] == 0.2
    assert animations[1]["trigger_source"] == "text_match"
    assert animations[1]["matched_sentence_id"] == "sentence_2"
    assert animations[1]["lead_sec"] == 1.0
    assert apply_timing(storyboard, sidecar)["metadata"]["timing_source"] == "sentence_cues"


def test_real_sentence_cues_are_offset_per_segment_for_srt_clock():
    storyboard = {
        "segments": [
            {"id": 1, "narration": "first", "audio_duration_sec": 2.0},
            {"id": 2, "narration": "second", "audio_duration_sec": 3.0},
        ]
    }
    sidecar = {
        "segments": [
            {
                "segment_id": 1,
                "cues": [{"sentence_id": "s1", "text": "first", "start_sec": 0.0, "end_sec": 2.0}],
            },
            {
                "segment_id": 2,
                "cues": [{"sentence_id": "s2", "text": "second", "start_sec": 0.0, "end_sec": 3.0}],
            },
        ]
    }

    cues = build_subtitle_cues(storyboard, sentence_cues=sidecar)

    assert [(cue.sentence_id, cue.start_sec, cue.end_sec) for cue in cues] == [
        ("s1", 0.0, 2.0),
        ("s2", 2.0, 5.0),
    ]


def test_unmentioned_elements_use_typed_fallbacks():
    segment = {
        "id": 1,
        "audio_duration_sec": 8.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "diagram", "type": "diagram"},
            {"id": "badge", "type": "badge"},
        ],
    }
    animations = build_segment_timing(segment, [{"text": "完全无关", "start": 4.0}])
    assert [a["trigger_source"] for a in animations] == [
        "structural_fallback", "primary_visual_fallback", "decorative_fallback"
    ]
    assert [a["trigger_at_sec"] for a in animations] == [0.0, 0.5, 0.8]


def test_same_sentence_semantic_elements_are_not_staggered():
    segment = {
        "id": 1,
        "audio_duration_sec": 20.0,
        "elements": [
            {"id": "a", "type": "text", "text": "关键概念"},
            {"id": "b", "type": "text", "text": "关键概念"},
            {"id": "c", "type": "text", "text": "关键概念"},
        ],
    }
    animations = build_segment_timing(
        segment,
        [{"text": "这里介绍关键概念", "start_sec": 10.0, "end_sec": 12.0}],
    )
    assert [a["trigger_at_sec"] for a in animations] == [9.0, 9.0, 9.0]


def test_non_adjacent_same_sentence_semantic_elements_keep_one_anchor():
    segment = {
        "id": 2,
        "audio_duration_sec": 40.0,
        "elements": [
            {"id": "e1", "type": "text", "text": "第二概念"},
            {"id": "e2", "type": "text", "text": "第二概念"},
            {"id": "e3", "type": "text", "text": "第三概念"},
            {"id": "e4", "type": "text", "text": "第三概念"},
            {"id": "e5", "type": "text", "text": "第三概念"},
            {"id": "e6", "type": "text", "text": "第二概念"},
        ],
    }
    cues = [
        {"sentence_id": "sentence_2", "text": "第二概念", "start_sec": 10.0, "end_sec": 12.0},
        {"sentence_id": "sentence_3", "text": "第三概念", "start_sec": 20.0, "end_sec": 22.0},
    ]

    animations = build_segment_timing(segment, cues)

    assert [a["trigger_at_sec"] for a in animations] == [9.0, 9.0, 19.0, 19.0, 19.0, 9.0]
    assert [a["matched_sentence_id"] for a in animations] == [
        "sentence_2", "sentence_2", "sentence_3", "sentence_3", "sentence_3", "sentence_2"
    ]


def test_fallback_before_semantic_anchor_cannot_push_anchor():
    segment = {
        "id": 3,
        "audio_duration_sec": 20.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "visual", "type": "image", "description": "辅助图片"},
            {"id": "concept", "type": "text", "text": "关键概念"},
        ],
    }
    cues = [{"sentence_id": "sentence_1", "text": "关键概念", "start_sec": 1.0, "end_sec": 3.0}]

    animations = build_segment_timing(segment, cues)

    assert animations[2]["trigger_source"] == "text_match"
    assert animations[2]["trigger_at_sec"] == 0.0
    assert animations[1]["trigger_at_sec"] <= animations[2]["trigger_at_sec"]


def test_semantic_triggers_stay_within_audio_duration():
    segment = {
        "id": 4,
        "audio_duration_sec": 2.0,
        "elements": [
            {"id": "a", "type": "text", "text": "早期概念"},
            {"id": "b", "type": "text", "text": "晚期概念"},
        ],
    }
    cues = [
        {"sentence_id": "s1", "text": "早期概念", "start_sec": 0.1, "end_sec": 0.5},
        {"sentence_id": "s2", "text": "晚期概念", "start_sec": 1.9, "end_sec": 2.0},
    ]

    animations = build_segment_timing(segment, cues)

    assert all(0.0 <= a["trigger_at_sec"] <= 2.0 for a in animations)


def test_different_sentence_semantic_elements_keep_sentence_lead():
    segment = {
        "id": 1,
        "audio_duration_sec": 40.0,
        "elements": [
            {"id": "a", "type": "text", "text": "第一概念"},
            {"id": "b", "type": "text", "text": "第二概念"},
            {"id": "c", "type": "text", "text": "第三概念"},
        ],
    }
    cues = [
        {"text": "第一概念", "start_sec": 10.0, "end_sec": 12.0},
        {"text": "第二概念", "start_sec": 20.0, "end_sec": 22.0},
        {"text": "第三概念", "start_sec": 30.0, "end_sec": 32.0},
    ]
    animations = build_segment_timing(segment, cues)
    assert [a["trigger_at_sec"] for a in animations] == [9.0, 19.0, 29.0]
    assert all(0.0 <= a["trigger_at_sec"] <= 40.0 for a in animations)


def test_generate_sentence_audio_keeps_only_segment_outputs(tmp_path, monkeypatch):
    def fake_batch(texts, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, _ in enumerate(texts, start=1):
            path = output_dir / f"s{index}.wav"
            path.write_bytes(_wav(0.5))
            paths.append(path)
        return paths

    monkeypatch.setattr(narrator, "_generate_megatts3", fake_batch)
    result = narrator.generate_sentence_audio(
        [["一。", "二。"], ["三。"]], output_dir=tmp_path
    )
    assert [p.name for p in result["audio_files"]] == ["s1.wav", "s2.wav"]
    assert (tmp_path / "sentence_cues.json").exists()
    assert not list(tmp_path.glob(".sentence_tts_*"))


def test_sentence_provenance_keeps_stable_id_and_text():
    segment = {
        "id": 1,
        "audio_duration_sec": 5.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "concept", "type": "text", "text": "关键概念"},
        ],
    }
    cues = [{
        "sentence_id": "segment-1-sentence-2",
        "index": 2,
        "text": "这里介绍关键概念。",
        "start_sec": 2.0,
        "end_sec": 5.0,
    }]
    animations = build_segment_timing(segment, cues)
    assert animations[1]["sentence_start_sec"] == 2.0
    assert animations[1]["matched_sentence_id"] == "segment-1-sentence-2"
    assert animations[1]["matched_sentence_index"] == 2
    assert animations[1]["matched_sentence_text"] == "这里介绍关键概念。"
    assert animations[1]["match_score"] >= 0.08
    assert animations[1]["match_method"] in {"substring", "token_overlap", "exact"}


def test_dict_sentence_sidecar_is_filtered_to_segment_and_keeps_id():
    storyboard = {
        "segments": [{
            "id": 2,
            "narration": "第二段关键概念。",
            "audio_duration_sec": 4.0,
            "elements": [
                {"id": "title", "type": "heading", "text": "标题"},
                {"id": "concept", "type": "text", "text": "关键概念"},
            ],
        }],
    }
    sidecar = {
        "segments": [
            {"segment_id": 1, "cues": [{"sentence_id": "wrong-segment", "text": "关键概念", "start_sec": 0.0, "end_sec": 1.0}]},
            {"segment_id": 2, "cues": [{"sentence_id": "segment-2-sentence-1", "text": "第二段关键概念。", "start_sec": 0.0, "end_sec": 4.0}]},
        ]
    }
    animation = apply_timing(storyboard, sidecar)["segments"][0]["animations"][1]
    assert animation["matched_sentence_id"] == "segment-2-sentence-1"


def test_deterministic_containment_matches_short_domain_labels():
    segment = {
        "id": 1,
        "audio_duration_sec": 12.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "pillar", "type": "text", "text": "支柱"},
            {"id": "network", "type": "text", "text": "5G网络"},
        ],
    }
    cues = [
        {"sentence_id": "s-pillar", "text": "数字经济已经成为重要支柱。", "start_sec": 2.0, "end_sec": 4.0},
        {"sentence_id": "s-5g", "text": "我国已经建成大量5G基站。", "start_sec": 6.0, "end_sec": 8.0},
    ]
    animations = build_segment_timing(segment, cues)
    assert animations[1]["matched_sentence_id"] == "s-pillar"
    assert animations[2]["matched_sentence_id"] == "s-5g"
    assert animations[1]["match_method"] in {"substring", "token_overlap"}
    assert animations[2]["match_method"] in {"substring", "token_overlap"}


def test_numeric_and_technical_tokens_are_not_diluted():
    segment = {
        "id": 1,
        "audio_duration_sec": 8.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "交易"},
            {"id": "amount", "type": "icon_group", "items": ["0.5 BTC", "0.3 BTC"]},
        ],
    }
    cues = [{
        "sentence_id": "s-utxo",
        "text": "用户拥有0.5和0.3比特币的UTXO。",
        "start_sec": 1.5,
        "end_sec": 5.0,
    }]
    animation = build_segment_timing(segment, cues)[1]
    assert animation["trigger_source"] == "text_match"
    assert animation["matched_sentence_id"] == "s-utxo"
    assert animation["match_method"] == "token_overlap"


def test_ai_alias_normalization_matches_artificial_intelligence():
    segment = {
        "id": 1,
        "audio_duration_sec": 8.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "callout", "type": "callout", "label": "AI 驱动"},
        ],
    }
    cues = [{
        "sentence_id": "s-ai",
        "text": "我们再来看人工智能+。",
        "start_sec": 2.0,
        "end_sec": 4.0,
    }]
    animation = build_segment_timing(segment, cues)[1]
    assert animation["trigger_source"] == "text_match"
    assert animation["matched_sentence_id"] == "s-ai"
    assert animation["match_method"] == "alias_overlap"


def test_explicit_target_uses_limited_parent_context():
    segment = {
        "id": 1,
        "audio_duration_sec": 8.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "image", "type": "image", "description": "紫色结构图"},
            {"id": "callout", "type": "callout", "target": "image", "label": "关键区域标注"},
        ],
    }
    cues = [{
        "sentence_id": "s-purple",
        "text": "紫色结构图表示核心区域。",
        "start_sec": 2.0,
        "end_sec": 4.0,
    }]
    animation = build_segment_timing(segment, cues)[2]
    assert animation["trigger_source"] == "text_match"
    assert animation["matched_sentence_id"] == "s-purple"
    assert animation["match_method"] == "parent_context"


def test_child_does_not_inherit_unrelated_slide_text():
    segment = {
        "id": 1,
        "audio_duration_sec": 8.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "芯片技术"},
            {"id": "image", "type": "image", "description": "芯片结构图"},
            {"id": "badge", "type": "callout", "target": "image", "label": "装饰"},
        ],
    }
    cues = [{"sentence_id": "s-chip", "text": "介绍芯片结构。", "start_sec": 2.0, "end_sec": 4.0}]
    animation = build_segment_timing(segment, cues)[2]
    assert animation["trigger_source"] == "decorative_fallback"


def test_subheading_is_structural_fallback():
    segment = {
        "id": 1,
        "audio_duration_sec": 5.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "标题"},
            {"id": "sub", "type": "subheading", "text": "通识课 第三讲"},
        ],
    }
    animations = build_segment_timing(segment, [{"text": "完全无关", "start_sec": 2.0, "end_sec": 5.0}])
    assert animations[1]["trigger_source"] == "structural_fallback"
    assert animations[1]["trigger_at_sec"] == 0.0


def test_symbol_only_visual_remains_fallback_without_semantic_context():
    segment = {
        "id": 1,
        "audio_duration_sec": 5.0,
        "elements": [
            {"id": "title", "type": "heading", "text": "哈希"},
            {"id": "symbol", "type": "icon_group", "items": ["A → B", "B ← ❌"]},
        ],
    }
    animations = build_segment_timing(
        segment,
        [{"text": "哈希不可逆，无法从哈希值反推原始数据。", "start_sec": 1.0, "end_sec": 5.0}],
    )
    assert animations[1]["trigger_source"] == "decorative_fallback"


def test_ambiguous_chip_process_callout_stays_fallback():
    segment = {
        "id": 4,
        "audio_duration_sec": 20.8,
        "elements": [
            {"id": "title", "type": "heading", "text": "补齐短板：核心技术能力提升"},
            {"id": "image", "type": "image", "description": "芯片的微观结构"},
            {"id": "callout", "type": "callout", "target": "image", "label": "芯片制造工艺"},
        ],
    }
    cues = [{
        "sentence_id": "segment-4-sentence-3",
        "text": "芯片、高端传感器、工业软件等卡脖子技术，是我国数字化转型的瓶颈。",
        "start_sec": 7.6,
        "end_sec": 14.4,
    }]
    animations = build_segment_timing(segment, cues)
    assert animations[1]["trigger_source"] == "text_match"
    assert animations[2]["trigger_source"] == "decorative_fallback"
