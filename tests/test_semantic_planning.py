from textbook2video.eval.semantic_planning import evaluate_semantic_planning


def _animation(target, trigger, sentence_id="sentence_2", source="text_match"):
    item = {
        "target": target,
        "trigger_at_sec": trigger,
        "trigger_source": source,
    }
    if source == "text_match":
        item.update({"matched_sentence_id": sentence_id, "lead_sec": 1.0})
    return item


def test_planning_gate_accepts_non_adjacent_same_sentence_anchor():
    storyboard = {
        "segments": [{
            "id": 2,
            "audio_duration_sec": 40.0,
            "animations": [
                _animation("e1", 9.0),
                _animation("e2", 9.0),
                _animation("e3", 19.0, "sentence_3"),
                _animation("e4", 19.0, "sentence_3"),
                _animation("e5", 19.0, "sentence_3"),
                _animation("e6", 9.0),
            ],
        }]
    }
    cues = [{
        "segment_id": 2,
        "cues": [
            {"sentence_id": "sentence_2", "start_sec": 10.0},
            {"sentence_id": "sentence_3", "start_sec": 20.0},
        ],
    }]

    report = evaluate_semantic_planning(storyboard, cues)

    assert report["passed"] is True
    assert report["metrics"]["semantic_anchor_violation_count"] == 0
    assert report["metrics"]["same_sentence_sync_violation_count"] == 0


def test_planning_gate_reports_anchor_delta_and_sentence_spread():
    storyboard = {
        "segments": [{
            "id": 2,
            "audio_duration_sec": 40.0,
            "animations": [
                _animation("e1", 9.0),
                _animation("e2", 9.3),
            ],
        }]
    }
    cues = [{
        "segment_id": 2,
        "cues": [{"sentence_id": "sentence_2", "start_sec": 10.0}],
    }]

    report = evaluate_semantic_planning(storyboard, cues)

    assert report["passed"] is False
    assert report["metrics"]["semantic_anchor_violation_count"] == 1
    assert report["metrics"]["same_sentence_sync_violation_count"] == 1
    assert report["metrics"]["max_same_sentence_spread_sec"] == 0.3


def test_planning_gate_checks_trigger_bounds():
    storyboard = {
        "segments": [{
            "id": 1,
            "audio_duration_sec": 2.0,
            "animations": [_animation("e1", 2.1, "sentence_1")],
        }]
    }
    cues = [{
        "segment_id": 1,
        "cues": [{"sentence_id": "sentence_1", "start_sec": 1.0}],
    }]

    report = evaluate_semantic_planning(storyboard, cues)

    assert report["passed"] is False
    assert report["metrics"]["trigger_bounds_violation_count"] == 1
