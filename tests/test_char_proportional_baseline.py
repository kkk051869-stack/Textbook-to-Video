import copy

from textbook2video.eval.char_proportional_baseline import (
    aggregate_baseline_rows,
    build_baseline_report,
    build_char_proportional_cues,
    build_char_proportional_timing,
    evaluate_char_proportional_baseline,
)


def _segment():
    return {
        "id": "s1",
        "narration": "开场介绍。芯片制造工艺需要突破。最后总结。",
        "audio_duration_sec": 10.0,
        "elements": [
            {"id": "e1", "type": "heading", "text": "本节内容"},
            {"id": "e2", "type": "text", "text": "芯片制造工艺"},
            {"id": "e3", "type": "text", "text": "最后总结"},
        ],
        "animations": [
            {"target": "e1", "trigger_at_sec": 8.0},
            {"target": "e2", "trigger_at_sec": 8.0},
            {"target": "e3", "trigger_at_sec": 8.0},
        ],
    }


def test_historical_char_proportional_cues_reproduce_visible_length_allocation():
    cues = build_char_proportional_cues(_segment())
    assert [cue["text"] for cue in cues] == ["开场介绍。", "芯片制造工艺需要突破。", "最后总结。"]
    assert cues[0]["start"] == 0.0
    assert round(cues[0]["end"], 6) == round(10 * 4 / 18, 6)
    assert round(cues[1]["end"] - cues[1]["start"], 6) == round(10 * 10 / 18, 6)
    assert cues[-1]["end"] == 10.0
    assert cues[1]["start"] > cues[0]["end"] - 1e-9
    assert cues[1]["end"] < cues[2]["end"]


def test_baseline_replays_old_element_order_clamp_and_fallback():
    timings = build_char_proportional_timing(_segment())
    assert [item["target"] for item in timings] == ["e1", "e2", "e3"]
    assert timings[0]["trigger_at_sec"] == 0.0
    assert all(0.0 <= item["trigger_at_sec"] <= 8.0 for item in timings)
    assert timings[1]["baseline_method"] in {"legacy_fuzzy_cue_start", "legacy_even_time_fallback"}


def test_baseline_does_not_mutate_production_trigger_at_sec():
    storyboard = {"segments": [_segment()]}
    production = copy.deepcopy(storyboard)
    production["segments"][0]["animations"] = [
        {
            "target": "e1",
            "trigger_at_sec": 0.0,
            "trigger_source": "text_match",
            "matched_sentence_id": "sentence_1",
            "matched_sentence_text": "开场介绍。",
            "lead_sec": 1.0,
            "match_method": "substring",
            "match_score": 0.96,
        },
        {
            "target": "e2",
            "trigger_at_sec": 2.0,
            "trigger_source": "primary_visual_fallback",
        },
    ]
    before = copy.deepcopy(production)
    report = evaluate_char_proportional_baseline(storyboard, timed_storyboard=production)
    assert production == before
    assert report["metrics"]["char_evaluated_element_count"] == 1


def test_semantic_rows_filter_fallback_and_resolve_sentence_start():
    storyboard = {"metadata": {"lesson_id": "lesson_test"}, "segments": [_segment()]}
    production = copy.deepcopy(storyboard)
    production["segments"][0]["animations"] = [
        {
            "target": "e1",
            "trigger_at_sec": 0.0,
            "trigger_source": "text_match",
            "matched_sentence_id": "sentence_1",
            "matched_sentence_text": "开场介绍。",
            "lead_sec": 1.0,
            "match_method": "substring",
            "match_score": 0.96,
        },
        {"target": "e2", "trigger_at_sec": 0.5, "trigger_source": "primary_visual_fallback"},
    ]
    report = build_baseline_report(storyboard, production, case_id="case", lesson_id="lesson_test")
    assert report["metrics"]["char_evaluated_element_count"] == 1
    assert len(report["excluded_elements"]) == 1
    assert report["evaluated_elements"][0]["sentence_start_sec"] == 0.0
    assert report["evaluated_elements"][0]["target_trigger_sec"] == 0.0


def test_char_error_and_aggregate_metrics_are_deterministic():
    rows = [
        {"char_error_sec": 0.0, "semantic_plan_error_sec": 0.1},
        {"char_error_sec": 1.0, "semantic_plan_error_sec": 0.2},
        {"char_error_sec": 2.0, "semantic_plan_error_sec": 0.3},
        {"char_error_sec": 3.0, "semantic_plan_error_sec": 0.4},
    ]
    metrics = aggregate_baseline_rows(rows)
    assert metrics["char_evaluated_element_count"] == 4
    assert metrics["char_mae_sec"] == 1.5
    assert metrics["char_median_error_sec"] == 1.5
    assert metrics["char_p95_error_sec"] == 2.85
    assert metrics["char_max_error_sec"] == 3.0
    assert metrics["char_error_le_0_5_ratio"] == 0.25
    assert metrics["char_error_le_1_0_ratio"] == 0.5
    assert metrics["char_error_le_2_0_ratio"] == 0.75


def test_non_default_lead_and_same_sentence_elements_are_compared_independently():
    segment = {
        "id": "s1",
        "narration": "展示芯片和传感器。",
        "audio_duration_sec": 4.0,
        "elements": [
            {"id": "e1", "type": "heading", "text": "标题"},
            {"id": "e2", "type": "text", "text": "芯片"},
            {"id": "e3", "type": "text", "text": "传感器"},
        ],
    }
    storyboard = {"segments": [segment]}
    production = copy.deepcopy(storyboard)
    production["segments"][0]["animations"] = [
        {
            "target": target,
            "trigger_at_sec": 1.0,
            "trigger_source": "text_match",
            "matched_sentence_id": "sentence_1",
            "matched_sentence_text": "展示芯片和传感器。",
            "lead_sec": 0.25,
            "match_method": "token_overlap",
            "match_score": 0.9,
        }
        for target in ("e2", "e3")
    ]
    report = build_baseline_report(storyboard, production, case_id="case", lesson_id="lesson")
    rows = report["evaluated_elements"]
    assert len(rows) == 2
    assert all(row["sentence_start_sec"] == 0.0 for row in rows)
    assert all(row["target_trigger_sec"] == 0.0 for row in rows)
    assert all(row["lead_sec"] == 0.25 for row in rows)
    assert {row["element_id"] for row in rows} == {"e2", "e3"}
