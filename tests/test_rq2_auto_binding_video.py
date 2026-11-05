import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_rq2_auto_binding_video as auto


def case(tmp_path):
    props = [
        {"id": f"n{i}", "segment_id": "auto", "text": f"Source sentence {i}."} for i in range(1, 5)
    ]
    candidates = [
        {"id": k, "label": k, "type": "highlight_box", "text": k, "source_refs": [k]}
        for k in "ABCD"
    ]
    results = [
        {
            "proposition_id": "n1",
            "segment_id": "auto",
            "status": "BOUND",
            "selected_candidate_id": "C",
        },
        {
            "proposition_id": "n2",
            "segment_id": "auto",
            "status": "ABSTAINED_NO_SUPPORT",
            "selected_candidate_id": None,
        },
        {
            "proposition_id": "n3",
            "segment_id": "auto",
            "status": "INVALID_RESPONSE",
            "selected_candidate_id": None,
        },
        {
            "proposition_id": "n4",
            "segment_id": "auto",
            "status": "BOUND",
            "selected_candidate_id": "A",
        },
    ]
    auto.write(tmp_path / "graph.json", {"narration_propositions": props})
    auto.write(tmp_path / "candidates.json", candidates)
    auto.write(tmp_path / "config.json", {"audio": {"voice": "en-US", "rate": "+0%"}})
    auto.write(tmp_path / "input_manifest.json", {})
    auto.write(tmp_path / "run/predictions.json", results)
    auto.write(
        tmp_path / "run/prediction_manifest.json",
        {"predictions.json": auto.sha(tmp_path / "run/predictions.json")},
    )
    return props, results


def test_predictions_not_text_order_or_corrected_targets_drive_events(tmp_path, monkeypatch):
    from textbook2video.pipeline import narrator

    props, original = case(tmp_path)

    def audio(groups, **kwargs):
        assert groups == [[p["text"] for p in props]]
        result = {
            "segments": [
                {
                    "segment_id": "auto",
                    "duration_sec": 8,
                    "cues": [
                        {"text": p["text"], "start_sec": i * 2, "end_sec": i * 2 + 2}
                        for i, p in enumerate(props)
                    ],
                }
            ]
        }
        auto.write(kwargs["output_dir"] / "sentence_cues.json", result)
        return result

    monkeypatch.setattr(narrator, "generate_sentence_audio", audio)
    auto.materialize(tmp_path)
    plan = auto.read(tmp_path / "dynamic_plan.json")
    assert set(plan["unbound_propositions"]) == {"n2", "n3"}
    shows = {
        e["proposition_id"]: e["target_element_id"] for e in plan["events"] if e["action"] == "show"
    }
    assert shows == {"n1": "C", "n4": "A"}
    board = auto.read(tmp_path / "auto/storyboard.json")
    assert board["segments"][0]["narration"] == " ".join(p["text"] for p in props)
    assert [e["id"] for e in board["segments"][0]["elements"]] == ["heading", "C", "A"]
    assert auto.read(tmp_path / "run/predictions.json") == original


def test_changed_prediction_fails_before_audio_or_page_creation(tmp_path):
    case(tmp_path)
    auto.write(tmp_path / "run/predictions.json", [])
    with pytest.raises(ValueError, match="Original prediction changed"):
        auto.materialize(tmp_path)
    assert not (tmp_path / "audio").exists()
    assert not (tmp_path / "auto").exists()


def test_budget_refuses_transport_before_spending(tmp_path, monkeypatch):
    auto.write(tmp_path / "config.json", {"budget": {"max_total_tokens": 1}})

    def forbidden(**kwargs):
        raise AssertionError("transport must not be reached")

    monkeypatch.setattr(auto.shared, "_call_model", forbidden)
    with pytest.raises(RuntimeError, match="TOKEN_BUDGET"):
        auto.call(tmp_path, "x", "binding", "source", 100, "model")


def test_nonempty_run_never_repeats_model_calls(tmp_path):
    case(tmp_path)
    with pytest.raises(FileExistsError):
        auto.predict(tmp_path)


@pytest.mark.parametrize("index,verdict", [(1, "WRONG"), (2, "ABSTAIN_MISSED")])
def test_review_cannot_confuse_invalid_refusal_and_wrong_object(
    tmp_path, monkeypatch, index, verdict
):
    props, _ = case(tmp_path)
    auto.write(
        tmp_path / "config.json",
        {"budget": {"review_max_tokens": 100}, "models": {"review": "fixture"}},
    )
    auto.write(tmp_path / "source.json", {"normalized_section": " ".join(p["text"] for p in props)})
    items = [
        {
            "proposition_id": p["id"],
            "verdict": "UNCERTAIN",
            "source_quote": p["text"],
            "reason": "Engineering fixture",
        }
        for p in props
    ]
    items[index]["verdict"] = verdict
    monkeypatch.setattr(auto, "call", lambda *args: auto.json.dumps({"assessments": items}))
    auto.review_predictions(tmp_path)
    review = auto.read(tmp_path / "run/semantic_review.json")
    assert review["status"] == "INVALID_OR_UNAVAILABLE"
    assert auto.read(tmp_path / "run/predictions.json")[index]["selected_candidate_id"] is None
