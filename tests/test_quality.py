import json

from textbook2video.pipeline.quality import build_quality_report, write_quality_report


def test_build_quality_report_summarizes_core_artifacts(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "fig1.png").write_bytes(b"PNG")
    audio = tmp_path / "lesson_audio"
    audio.mkdir()
    (audio / "s1.mp3").write_bytes(b"A")
    (audio / "s2.mp3").write_bytes(b"B")

    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "第一段。",
                "audio_duration_sec": 2.0,
                "elements": [
                    {"id": "e1", "type": "heading", "text": "标题"},
                    {"id": "e2", "type": "image", "src": "fig1.png"},
                ],
            },
            {
                "id": 2,
                "narration": "第二段。",
                "audio_duration_sec": 3.0,
                "elements": [{"id": "e1", "type": "text", "text": "文字"}],
            },
        ]
    }
    sb_path = tmp_path / "lesson_storyboard.json"
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")
    srt = tmp_path / "lesson.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n第一段。\n\n"
        "2\n00:00:02,000 --> 00:00:05,000\n第二段。\n",
        encoding="utf-8",
    )

    report = build_quality_report(sb_path, audio_dir=audio, subtitle_path=srt)

    assert report["summary"]["segments"] == 2
    assert report["summary"]["duration_sec"] == 5.0
    assert report["checks"]["audio_files"]["count"] == 2
    assert report["checks"]["subtitles"]["cue_count"] == 2
    assert report["checks"]["subtitles"]["coverage_ratio"] == 1.0
    assert report["checks"]["textbook_images"]["ratio"] == 1.0
    assert report["warnings"] == []


def test_quality_report_warns_for_missing_audio_and_short_timing(tmp_path):
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "短。",
                "audio_duration_sec": 1.0,
                "animations": [{"target": "e2", "effect": "fadeIn", "trigger_at_sec": 1.0}],
            }
        ]
    }
    sb_path = tmp_path / "lesson_storyboard.json"
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")

    report = build_quality_report(sb_path, audio_dir=tmp_path / "missing")

    assert any("audio segment files 0/1" in w for w in report["warnings"])
    assert any("shorter than last trigger" in w for w in report["warnings"])


def test_write_quality_report_writes_json(tmp_path):
    sb_path = tmp_path / "lesson_storyboard.json"
    sb_path.write_text(
        json.dumps({"segments": [{"id": 1, "narration": "x", "audio_duration_sec": 1.0}]}),
        encoding="utf-8",
    )

    out = write_quality_report(sb_path, tmp_path / "lesson_quality.json")

    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["segments"] == 1
