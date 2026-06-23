"""run_tts 回写测试（narrate 命令的核心），mock TTS 后端，不依赖网络/ffmpeg。"""

import json
import sys
import types

from textbook2video.pipeline import orchestrator
from textbook2video.pipeline.orchestrator import run_tts


def _patch_narrator(monkeypatch, generate_audio, get_audio_duration):
    monkeypatch.setitem(
        sys.modules,
        "textbook2video.pipeline.narrator",
        types.SimpleNamespace(
            generate_audio=generate_audio,
            get_audio_duration=get_audio_duration,
        ),
    )


def test_run_tts_writes_back_durations(tmp_path, monkeypatch):
    sb_path = tmp_path / "ch3_s0_storyboard.json"
    storyboard = {
        "lesson_title": "第4章",
        "segments": [
            {"id": 1, "narration": "第一段旁白"},
            {"id": 2, "narration": "第二段旁白"},
        ],
    }
    sb_path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")

    def fake_generate_audio(narrations, *, output_dir, **k):
        from pathlib import Path
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for i, _ in enumerate(narrations, 1):
            f = d / f"s{i}.mp3"
            f.write_bytes(b"")
            files.append(f)
        return files

    durations_map = {"s1.mp3": 3.0, "s2.mp3": 4.66}

    def fake_duration(path):
        from pathlib import Path
        return durations_map[Path(path).name]

    _patch_narrator(monkeypatch, fake_generate_audio, fake_duration)

    audio_dir = tmp_path / "ch3_s0_audio"
    durations = run_tts(storyboard, sb_path, audio_dir)

    assert durations == [3.0, 4.7]   # 4.66 → round(.,1)=4.7
    # 回写进内存对象
    assert storyboard["segments"][0]["audio_duration_sec"] == 3.0
    assert storyboard["segments"][1]["audio_duration_sec"] == 4.7
    # 回写进磁盘 JSON
    on_disk = json.loads(sb_path.read_text(encoding="utf-8"))
    assert on_disk["segments"][1]["audio_duration_sec"] == 4.7


def test_run_tts_handles_duration_failure_as_zero(tmp_path, monkeypatch):
    sb_path = tmp_path / "lesson4_storyboard.json"
    storyboard = {"segments": [{"id": 1, "narration": "x"}]}
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")

    def fake_generate_audio(narrations, *, output_dir, **k):
        from pathlib import Path
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        f = d / "s1.mp3"
        f.write_bytes(b"")
        return [f]

    def boom(path):
        raise ValueError("无法获取时长")

    _patch_narrator(monkeypatch, fake_generate_audio, boom)

    durations = run_tts(storyboard, sb_path, tmp_path / "a")
    assert durations == [0.0]


def test_run_tts_writes_timed_storyboard(tmp_path, monkeypatch):
    sb_path = tmp_path / "lesson4_storyboard.json"
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "Algorithm means clear steps.",
                "elements": [
                    {"id": "e1", "type": "heading", "text": "Algorithm"},
                    {"id": "e2", "type": "text", "text": "clear steps"},
                ],
            }
        ]
    }
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")

    def fake_generate_audio(narrations, *, output_dir, **k):
        from pathlib import Path

        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        f = d / "s1.mp3"
        f.write_bytes(b"")
        return [f]

    _patch_narrator(monkeypatch, fake_generate_audio, lambda _path: 5.0)

    run_tts(storyboard, sb_path, tmp_path / "audio")

    on_disk = json.loads(sb_path.read_text(encoding="utf-8"))
    assert on_disk["metadata"]["timing_source"] == "deterministic_subtitle_cues"
    assert on_disk["segments"][0]["animations"][0]["trigger_at_sec"] == 0.0

    timed_path = tmp_path / "lesson4_timed_storyboard.json"
    assert timed_path.exists()
    timed = json.loads(timed_path.read_text(encoding="utf-8"))
    assert timed["segments"][0]["animations"][1]["target"] == "e2"
