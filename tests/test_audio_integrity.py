import json
import shutil
import subprocess
from pathlib import Path

import pytest

from textbook2video.eval.evaluators.audio_integrity import evaluate_audio_integrity
from textbook2video.eval.runner import EvalContext


class _Case:
    case_id = "case_audio"
    lesson_id = "lesson_audio"
    raw = {}


def _context(root: Path) -> EvalContext:
    return EvalContext(
        case=_Case(),
        run_id="run-audio",
        artifacts_root=root,
        output_root=root / "eval",
    )


def _write_timed(root: Path, durations=(1.0,)) -> None:
    (root / "storyboard_timed.json").write_text(
        json.dumps({"segments": [{"audio_duration_sec": value} for value in durations]}),
        encoding="utf-8",
    )


def test_audio_gate_reports_all_missing_delivery_inputs(tmp_path):
    _write_timed(tmp_path)
    result = evaluate_audio_integrity(_context(tmp_path))
    assert result["passed"] is False
    assert {issue["type"] for issue in result["issues"]} == {
        "AUDIO_ASSET_MISSING",
        "MP4_AUDIO_STREAM_MISSING",
        "SUBTITLE_COVERAGE_INCOMPLETE",
    }


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_audio_gate_accepts_complete_audio_video_and_subtitles(tmp_path):
    _write_timed(tmp_path, (1.0,))
    audio = tmp_path / "audio"
    audio.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", "-c:a", "libmp3lame", str(audio / "s1.mp3")],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(tmp_path / "final.mp4")],
        check=True,
        capture_output=True,
    )
    (tmp_path / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n测试\n", encoding="utf-8"
    )
    result = evaluate_audio_integrity(_context(tmp_path))
    assert result["passed"] is True
    assert result["metrics"]["audio_stream_present"] is True
    assert result["metrics"]["subtitle_coverage"] == 1.0
