import json
from pathlib import Path

import pytest

from textbook2video.research.annotation_agreement import evaluate_agreement
from textbook2video.research.pilot_export import build_pilot_tasks, export_case, validate_empty_gold
from textbook2video.research.snapshot import freeze_case


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    source_case = tmp_path / "source_case"
    artifact = tmp_path / "artifact"
    execution = tmp_path / "execution"
    workspace.mkdir()
    source_case.mkdir()
    artifact.mkdir()
    execution.mkdir()

    _write_json(source_case / "source" / "source.json", {
        "title": "Test",
        "source_locator": "test:1",
        "source_document": {"path": "source.pdf", "sha256": "source-hash"},
        "normalized_text_sha256": "text-hash",
        "paragraphs": [{"id": "p001", "text": "甲乙丙", "source_locator": "test:p1"}],
        "images": [],
    })
    (source_case / "source" / "source.pdf").write_bytes(b"pdf")
    _write_json(source_case / "case_manifest.json", {"case_id": "case_1"})
    _write_json(source_case / "private" / "annotation.json", {
        "core_concepts": [{"id": "c001", "statement": "甲乙", "evidence_paragraphs": ["p001"]}]
    })
    storyboard = {
        "lesson_title": "Test",
        "segments": [{
            "id": 1,
            "narration": "甲乙。丙丁。",
            "audio_duration_sec": 4.0,
            "knowledge_point_ids": ["kp1"],
            "render_mode": "template",
            "visual_type": "definition",
            "elements": [{"id": "e1", "type": "text", "text": "甲乙"}],
            "animations": [{"target": "e1", "effect": "fadeIn", "trigger_at_sec": 0.0}],
            "timeline": [{"target": "e1", "action": "show", "at_sec": 0.0}],
        }],
    }
    _write_json(artifact / "storyboard.json", storyboard)
    _write_json(artifact / "storyboard_timed.json", storyboard)
    _write_json(artifact / "lesson_plan.json", {"status": "disabled"})
    (artifact / "script.txt").write_text("甲乙。丙丁。", encoding="utf-8")
    _write_json(artifact / "animation.manifest.json", {"status": "ok"})
    _write_json(artifact / "quality_report.json", {"status": "ok"})

    _write_json(execution / "run_config.json", {
        "commit": "generation", "candidate_commit": "candidate", "model": "model",
        "tts_backend": "test", "tts_voice": "voice", "tts_rate": 0,
        "timed_reveal": True, "theme": "theme", "browser": "browser", "fps": 30,
    })
    _write_json(execution / "candidate_manifest.json", {
        "candidate_system_id": "candidate", "candidate_commit": "candidate",
        "deterministic_renderer": True, "llm_fallback_used": False,
    })
    _write_json(execution / "audio_provenance.json", {"backend": "test"})
    (execution / "audio" / "s1.wav").parent.mkdir(parents=True, exist_ok=True)
    (execution / "audio" / "s1.wav").write_bytes(b"wav")
    (execution / "animation.html").write_text("<html></html>", encoding="utf-8")
    (execution / "final.mp4").write_bytes(b"mp4")
    (execution / "video_silent.mp4").write_bytes(b"mp4")
    (execution / "subtitles.srt").write_text("", encoding="utf-8")
    _write_json(execution / "storyboard.layout.json", {})
    _write_json(execution / "storyboard.layout-1366x768.json", {})
    _write_json(execution / "video_probe.json", {})
    _write_json(execution / "animation_trace.json", {
        "events": [{
            "event_id": "1-a01", "slide": 1, "target": "e1", "target_resolved": True,
            "status": "executed", "error_code": None,
            "planned": {"trigger": "show", "effect": "fadeIn", "start_ms": 0, "duration_ms": 600},
            "actual": {"trigger": "show", "effect": "fadeIn", "start_ms": 50, "duration_ms": 600},
        }]
    })
    _write_json(execution / "animation_trace.raw.json", [])
    _write_json(execution / "browser_runtime.json", {})
    return workspace, source_case, artifact, execution


def test_snapshot_is_immutable_and_records_missing_before_timing(tmp_path: Path) -> None:
    workspace, source_case, artifact, execution = _fixture_tree(tmp_path)
    output = tmp_path / "baseline"
    manifest_path = freeze_case(
        case_id="case_1",
        workspace=workspace,
        source_case_dir=source_case,
        artifact_dir=artifact,
        execution_dir=execution,
        output_root=output,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    before = next(item for item in manifest["artifacts"] if item["role"] == "storyboard_before_timing")
    assert before["status"] == "MISSING"
    assert "storyboard_before_timing" in manifest["missing_artifacts"]
    with pytest.raises(FileExistsError):
        freeze_case(
            case_id="case_1",
            workspace=workspace,
            source_case_dir=source_case,
            artifact_dir=artifact,
            execution_dir=execution,
            output_root=output,
        )


def test_export_keeps_candidates_separate_from_empty_gold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, source_case, artifact, execution = _fixture_tree(tmp_path)
    baseline = tmp_path / "baseline"
    freeze_case(
        case_id="case_1",
        workspace=workspace,
        source_case_dir=source_case,
        artifact_dir=artifact,
        execution_dir=execution,
        output_root=baseline,
    )
    monkeypatch.setattr(
        "textbook2video.research.pilot_export._extract_frames",
        lambda _video, _destination, events: [
            {"event_id": event["event_id"], "status": "MISSING", "frames": []}
            for event in events
        ],
    )
    package = tmp_path / "pilot"
    cases_root = package / "cases"
    manifest = export_case(baseline / "case_1", cases_root)
    assert manifest["counts"]["proposition_candidates"] == 2
    assert manifest["gold_validation"]["status"] == "EMPTY"
    annotation = json.loads((cases_root / "case_1" / "annotations" / "annotator_A.json").read_text(encoding="utf-8"))
    assert validate_empty_gold(annotation) == []
    row = annotation["segments"][0]["propositions"][0]
    assert row["candidate_boundary"]["candidate_text"]
    assert row["proposition_text"] is None
    assert row["visual_applicability"] is None
    assert row["temporal_label"] is None
    assert row["signal_label"] is None

    observations = json.loads(
        (cases_root / "case_1" / "machine_observations.json").read_text(encoding="utf-8")
    )
    richness = observations["segments"][0]["richness_observation"]
    assert richness["element_count"] == 1
    assert richness["animation_count"] == 1
    assert richness["timeline_event_count"] == 1
    assert richness["events_per_10_sec"] == 2.5
    assert richness["signaling_event_count"] == 0

    build_pilot_tasks(package, source_task_count=1)
    panel = json.loads(
        (package / "tasks" / "three_layer" / "annotator_A" / "A_plan_only.json").read_text(
            encoding="utf-8"
        )
    )
    task = panel["tasks"][0]
    assert task["segment_id"] == "1"
    assert task["narration_context"] == "甲乙。丙丁。"
    assert task["proposition_candidates"]
    assert task["target_element"]["id"] == "e1"


def test_agreement_reports_not_ready_for_empty_templates() -> None:
    annotation = {
        "annotation_status": "NOT_STARTED",
        "segments": [{"segment_id": "1", "propositions": [{"proposition_id": None}]}],
    }
    result = evaluate_agreement(annotation, annotation)
    assert result["status"] == "NOT_READY"
    assert result["metrics"] is None
