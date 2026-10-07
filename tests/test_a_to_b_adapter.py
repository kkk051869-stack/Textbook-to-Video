from pathlib import Path

from textbook2video.research.a_to_b_adapter import (
    build_full_segment_handoff_candidate,
    build_handoff_candidate,
    copy_handoff_asset,
)


def test_build_candidate_uses_explicit_bridge_without_lexical_matching(tmp_path: Path) -> None:
    asset = tmp_path / "visual.png"
    asset.write_bytes(b"png")
    bridge = {
        "case_id": "lesson_011",
        "knowledge_proposition_id": "lesson-011-kprop-005",
        "segment_id": "5",
        "narration_proposition_id": "lesson-011-nprop-s005-p002",
        "trigger_at_sec": 3.698495,
        "visual_element_id": "lesson-011-seg-005-el-a-generated-001",
        "asset_caption": "generated explanation",
        "source_evidence_ids": ["lesson-011-src-p0014"],
    }
    candidate = build_handoff_candidate(
        bridge=bridge,
        legacy_storyboard={
            "segments": [
                {
                    "id": 5,
                    "narration": "segment narration",
                    "audio_duration_sec": 10,
                    "elements": [{"type": "heading", "text": "A heading"}],
                }
            ]
        },
        asset_path=asset,
    )

    segment = candidate["renderer_segments"][0]
    assert candidate["baseline_mutated"] is False
    assert segment["id"] == "lesson-011-seg-005"
    assert segment["elements"][1]["narration_proposition_ids"] == ["lesson-011-nprop-s005-p002"]
    assert segment["animations"][0]["trigger_at_sec"] == 3.698495


def test_copy_handoff_asset_keeps_original_untouched(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")

    copied = copy_handoff_asset(source, tmp_path / "destination")

    assert copied.read_bytes() == b"source"
    assert source.read_bytes() == b"source"
    assert copied != source


def test_full_segment_preserves_context_and_replaces_primary_visual(tmp_path: Path) -> None:
    asset = tmp_path / "visual.png"
    asset.write_bytes(b"png")
    bridge = {
        "case_id": "lesson_002",
        "segment_id": "3",
        "narration_proposition_id": "lesson-002-nprop-s003-p002",
        "trigger_at_sec": 3.533333,
        "visual_element_id": "lesson-002-seg-003-el-a-reuse-001",
        "asset_caption": "source diagram",
        "source_evidence_ids": ["lesson-002-src-p0003"],
    }
    candidate = build_full_segment_handoff_candidate(
        bridge=bridge,
        legacy_storyboard={
            "segments": [
                {
                    "id": 3,
                    "narration": "full narration",
                    "audio_duration_sec": 12,
                    "elements": [
                        {"id": "e1", "type": "heading", "text": "heading"},
                        {"id": "e2", "type": "image", "src": "old.png"},
                        {"id": "e3", "type": "callout", "target": "e2", "label": "callout"},
                    ],
                    "animations": [
                        {"target": "e1", "trigger_at_sec": 0.0},
                        {"target": "e2", "trigger_at_sec": 2.0},
                        {"target": "e3", "trigger_at_sec": 3.0},
                    ],
                }
            ]
        },
        asset_path=asset,
    )

    segment = candidate["renderer_segments"][0]
    assert len(segment["elements"]) == 3
    assert segment["elements"][1]["id"] == bridge["visual_element_id"]
    assert segment["elements"][2]["target"] == bridge["visual_element_id"]
    assert segment["animations"][1]["trigger_at_sec"] == bridge["trigger_at_sec"]
    assert candidate["baseline_mutated"] is False
