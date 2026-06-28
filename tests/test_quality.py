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
                "knowledge_point_ids": ["kp1"],
                "audio_duration_sec": 2.0,
                "elements": [
                    {"id": "e1", "type": "heading", "text": "标题"},
                    {"id": "e2", "type": "image", "src": "fig1.png"},
                ],
            },
            {
                "id": 2,
                "narration": "第二段。",
                "pedagogical_role": "lesson_summary",
                "knowledge_point_ids": ["kp2"],
                "audio_duration_sec": 3.0,
                "elements": [{"id": "e1", "type": "text", "text": "文字"}],
            },
        ]
    }
    sb_path = tmp_path / "lesson_storyboard.json"
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")
    plan_path = tmp_path / "lesson_lesson_plan.json"
    plan_path.write_text(json.dumps({
        "objectives": ["理解概念"],
        "knowledge_points": [{"id": "kp1", "name": "一"}, {"id": "kp2", "name": "二"}],
    }), encoding="utf-8")
    srt = tmp_path / "lesson.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n第一段。\n\n"
        "2\n00:00:02,000 --> 00:00:05,000\n第二段。\n",
        encoding="utf-8",
    )

    report = build_quality_report(
        sb_path, audio_dir=audio, subtitle_path=srt, lesson_plan_path=plan_path
    )

    assert report["summary"]["segments"] == 2
    assert report["summary"]["duration_sec"] == 5.0
    assert report["checks"]["audio_files"]["count"] == 2
    assert report["checks"]["subtitles"]["cue_count"] == 2
    assert report["checks"]["subtitles"]["coverage_ratio"] == 1.0
    assert report["checks"]["textbook_images"]["ratio"] == 1.0
    assert report["checks"]["lesson_plan"]["knowledge_point_coverage"] == 1.0
    assert report["checks"]["lesson_plan"]["instructional_events"]["coverage"] == 1.0
    assert report["scores"]["instructional_event_coverage"] == 1.0
    assert report["warnings"] == []


def test_quality_report_checks_lesson_plan_instructional_events(tmp_path):
    storyboard = {
        "segments": [
            {
                "id": 1,
                "narration": "讲解算法定义。",
                "knowledge_point_ids": ["kp1"],
                "audio_duration_sec": 2.0,
            }
        ]
    }
    sb_path = tmp_path / "lesson_storyboard.json"
    sb_path.write_text(json.dumps(storyboard), encoding="utf-8")
    plan_path = tmp_path / "lesson_lesson_plan.json"
    plan_path.write_text(json.dumps({
        "knowledge_points": [{"id": "kp1", "name": "算法定义"}],
        "activities": ["请举一个生活中的算法例子"],
        "assessment_questions": [{"question": "算法必须有明确步骤吗？"}],
    }), encoding="utf-8")

    report = build_quality_report(sb_path, lesson_plan_path=plan_path)

    events = report["checks"]["lesson_plan"]["instructional_events"]
    assert events["required_roles"] == [
        "reflection_activity",
        "knowledge_check",
        "lesson_summary",
    ]
    assert events["present_roles"] == []
    assert events["missing_roles"] == [
        "knowledge_check",
        "lesson_summary",
        "reflection_activity",
    ]
    assert events["coverage"] == 0.0
    assert report["scores"]["instructional_event_coverage"] == 0.0
    assert any("instructional event coverage is incomplete" in w for w in report["warnings"])


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
