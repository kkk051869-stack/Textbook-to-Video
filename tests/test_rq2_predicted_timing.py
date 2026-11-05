import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_rq2_predicted_timing as paired


def source_case(tmp_path):
    m = paired.media
    root = tmp_path / "source"
    props = [{"id": "n1", "text": "First."}, {"id": "n2", "text": "Last."}]
    predictions = [
        {"proposition_id": "n1", "status": "BOUND", "selected_candidate_id": "x"},
        {"proposition_id": "n2", "status": "INVALID_RESPONSE", "selected_candidate_id": None},
    ]
    m.write(root / "graph.json", {"narration_propositions": props})
    m.write(root / "run/predictions.json", predictions)
    m.write(
        root / "run/prediction_manifest.json",
        {
            "predictions.json": m.sha(root / "run/predictions.json"),
        },
    )
    m.write(
        root / "auto/storyboard.json",
        {
            "segments": [
                {
                    "id": "s",
                    "narration": "First. Last.",
                    "audio_duration_sec": 9,
                    "elements": [
                        {"id": "heading", "type": "heading", "text": "Title"},
                        {"id": "x", "type": "highlight_box", "text": "First"},
                    ],
                    "timeline": [{"target": "x", "action": "show", "trigger_at_sec": 1}],
                }
            ]
        },
    )
    m.write(
        root / "audio/sentence_cues.json",
        {
            "segments": [
                {
                    "duration_sec": 8,
                    "cues": [{"text": p["text"]} for p in props],
                }
            ]
        },
    )
    for name in ("candidates.json", "dynamic_plan.json", "measured_propositions.json"):
        m.write(root / name, [])
    m.write(root / "input_manifest.json", {})
    m.write(
        root / "inputs.json",
        {
            "files": {
                p.relative_to(root).as_posix(): m.sha(p) for p in root.rglob("*") if p.is_file()
            },
        },
    )
    return root


def test_pair_preserves_narration_predictions_and_failure_denominator(tmp_path):
    root = source_case(tmp_path)
    out = tmp_path / "paired"
    paired.prepare(root, out)
    assert paired.media.sha(out / "predictions.json") == paired.media.sha(
        root / "run/predictions.json"
    )
    contract = paired.media.read(out / "comparison_contract.json")
    assert contract["proposition_denominator"] == 2
    assert contract["unbound"][0]["status"] == "INVALID_RESPONSE"
    for mode in ("legacy", "simple_rule", "proposition_aware"):
        board = paired.media.read(out / mode / "storyboard.json")["segments"][0]
        assert board["narration"] == "First. Last."
        assert {e["id"] for e in board["elements"]} == {"heading", "x"}
        if mode != "proposition_aware":
            assert "timeline" not in board
    paired.media.verify(out)


def test_corrupt_source_stops_before_creating_comparison(tmp_path):
    root = source_case(tmp_path)
    paired.media.write(root / "audio/sentence_cues.json", {})
    with pytest.raises(ValueError, match="Frozen input changed"):
        paired.prepare(root, tmp_path / "paired")
    assert not (tmp_path / "paired").exists()
