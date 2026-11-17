import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_rq3_event_fault_dev as dev


def board():
    return {
        "segments": [
            {
                "animations": [
                    {"event_id": "p0-dynamic-n2-show", "target": "v08", "trigger_at_sec": 8.701},
                    {"event_id": "other", "target": "v17", "trigger_at_sec": 19.942},
                ]
            }
        ]
    }


@pytest.mark.parametrize("fault", ["early", "late", "wrong_target", "missing"])
def test_injection_keeps_reference_and_unrelated_events_immutable(fault):
    source = board()
    before = copy.deepcopy(source)
    changed = dev.perturb(source, fault)
    assert source == before
    assert changed["segments"][0]["animations"][1] == before["segments"][0]["animations"][1]
    assert len(changed["segments"][0]["animations"]) == 2
    if fault == "missing":
        assert changed["segments"] == before["segments"]
    assert changed["metadata"]["development_fault_injection"] == fault


@pytest.mark.parametrize("value", [None, "false", 0])
def test_unknown_pixel_observation_cannot_turn_into_visible_or_absent(value):
    observations = {
        t: {"entropy": False, "reconstruction": False} for t in ("6.5", "9.5", "12.5", "18.0")
    }
    observations["9.5"]["entropy"] = value
    assert dev.classify(observations) == "unobservable"


def test_classifier_uses_pixel_observations_and_not_injection_or_runtime():
    observations = {
        t: {"entropy": False, "reconstruction": False} for t in ("6.5", "9.5", "12.5", "18.0")
    }
    assert dev.classify(observations) == "missing_in_sampled_window"
    observations["12.5"]["entropy"] = True
    assert dev.classify(observations) == "late"
    observations["9.5"]["reconstruction"] = True
    assert dev.classify(observations) == "wrong_target"


def test_changed_reference_timing_is_not_silently_accepted():
    source = board()
    source["segments"][0]["animations"][0]["trigger_at_sec"] = 9
    with pytest.raises(ValueError, match="timing changed"):
        dev.perturb(source, "early")
