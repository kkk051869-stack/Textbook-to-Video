import array
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_rq2_native_timing as control
from review_rq2_native_timing import waveform_checks


def test_changed_frozen_audio_is_rejected_before_rendering(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"original measured audio")
    control.write(tmp_path / "inputs.json", {"files": {"audio.wav": control.sha(audio)}})
    control.verify(tmp_path)
    audio.write_bytes(b"substituted different utterance")
    with pytest.raises(ValueError, match="Frozen input changed"):
        control.verify(tmp_path)


def test_decode_alignment_detects_known_ten_millisecond_lag():
    rng = random.Random(42)
    original = array.array("h", [rng.randrange(-10000, 10001) for _ in range(24000)])
    delayed = array.array("h", [0] * 80) + original
    result = waveform_checks(original, delayed, [0])[0]
    assert result["final_audio_lag_sec"] == pytest.approx(0.01)
    assert result["best_correlation"] == pytest.approx(1)


def test_silent_audio_does_not_pass_waveform_agreement():
    original = array.array("h", [1000] * 24000)
    silent = array.array("h", [0] * 24000)
    result = waveform_checks(original, silent, [0])[0]
    assert result["best_correlation"] < 0.1
