import json
from pathlib import Path

from textbook2video.eval.evaluators.video_qa_final import (
    FinalVideoQAAdapter,
    FinalVideoError,
    FfmpegFinalMediaAdapter,
    PreparedFinalMedia,
    audit_audience_input_manifest,
    normalize_audience_response,
    normalize_reference_response,
)
from textbook2video.eval.runner import EvalContext, run_case
from textbook2video.eval.dataset import CaseManifest


class FakeClient:
    model = "fake-vlm"

    def __init__(self, replies):
        self.replies = list(replies) if isinstance(replies, list) else replies
        self.messages = []

    def chat(self, messages, *, max_tokens):
        self.messages.append(messages)
        reply = self.replies.pop(0) if isinstance(self.replies, list) else self.replies
        return reply, json.dumps(reply, ensure_ascii=False)


class FakeMediaAdapter:
    def __init__(self, tmp_path):
        video = tmp_path / "final.mp4"
        video.write_bytes(b"mp4")
        frames = []
        for index in range(2):
            frame = tmp_path / f"frame_{index}.png"
            frame.write_bytes(f"frame-{index}".encode())
            frames.append(frame)
        subtitle = tmp_path / "embedded_subtitle.srt"
        subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nvisible\n", encoding="utf-8")
        manifest = {
            "schema_version": "textbookeval-final-media-v0.1",
            "input_mode": "final_media_extracted",
            "final_video": {"path": str(video), "sha256": "video-sha"},
            "derived_frames": [
                {"path": frame.name, "sha256": f"frame-sha-{i}", "timestamp_sec": float(i)}
                for i, frame in enumerate(frames)
            ],
            "derived_subtitle": {
                "path": subtitle.name,
                "sha256": "subtitle-sha",
                "source": "embedded_mp4",
            },
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.media = PreparedFinalMedia(video, {"duration_sec": 2}, frames, subtitle, manifest_path, manifest)

    def prepare(self, video_path, output_root):
        return self.media


def _case(tmp_path, questions):
    questions_path = tmp_path / "heldout_questions.json"
    questions_path.write_text(json.dumps({"questions": questions}, ensure_ascii=False), encoding="utf-8")
    return CaseManifest(
        manifest_path=tmp_path / "case_manifest.json",
        raw={
            "case_id": "case-1",
            "lesson_id": "lesson_001",
            "dataset_version": "dataset-v1",
            "status": "frozen",
            "source": {"files": []},
            "heldout_questions": {
                "role": "heldout_questions",
                "path": questions_path.name,
                "sha256": "not-verified-in-unit-test",
                "review_status": "frozen",
            },
            "review": {"reviewer": "test", "reviewed_at": "2026-01-01", "annotation_status": "frozen"},
        },
    )


def _context(tmp_path, case, adapter=None):
    return EvalContext(
        case=case,
        run_id="run-1",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
        final_video_qa=adapter,
    )


def test_audience_normalization_is_fail_closed():
    value, errors = normalize_audience_response(
        {
            "question_id": "q1",
            "answer": "visible answer",
            "explanation": "shown in the video",
            "confidence": "high",
            "evidence_from_video": [{"timestamp_or_frame": "frame_0001", "observation": "visible"}],
        },
        question_id="q1",
    )
    assert value["answer"] == "visible answer"
    assert errors == []

    cannot, errors = normalize_audience_response("cannot_determine", question_id="q1")
    assert cannot["answer"] == "cannot_determine"
    assert errors == []

    malformed, errors = normalize_audience_response({"answer": "guess"}, question_id="q1")
    assert malformed["answer"] == "cannot_determine"
    assert "missing_evidence" in errors


def test_reference_normalization_supports_all_statuses_and_explanation():
    value, errors = normalize_reference_response(
        {
            "question_id": "q1",
            "status": "partial",
            "reason": "one point is missing",
            "matched_gold_points": ["point 1"],
            "missing_gold_points": ["point 2"],
            "contradictions": [],
            "explanation_status": "supported",
        },
        question_id="q1",
    )
    assert value["status"] == "partial"
    assert value["explanation_status"] == "supported"
    assert errors == []

    uncertain, errors = normalize_reference_response({"question_id": "q1"}, question_id="q1")
    assert uncertain["status"] == "uncertain"
    assert "invalid_status" in errors


def test_leakage_audit_fails_only_for_actual_forbidden_inputs():
    assert audit_audience_input_manifest(
        {
            "actual_audience_inputs": [
                {"kind": "final_video"},
                {"kind": "derived_frames"},
                {"kind": "derived_subtitle"},
            ],
            "audience_payload": {"input_kinds": ["final_video", "question_text"]},
        }
    )["passed"]
    audit = audit_audience_input_manifest(
        {"actual_audience_inputs": [{"kind": "gold_answer"}]}
    )
    assert audit["status"] == "fail"
    assert "gold_answer" in audit["forbidden_inputs_found"]


def test_ffmpeg_media_probe_rejects_missing_subtitle_stream(tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"mp4")

    def command_runner(command, *, timeout):
        assert command[0] == "ffprobe"
        return type("Completed", (), {"returncode": 0, "stdout": json.dumps({"streams": [{"codec_type": "video"}, {"codec_type": "audio"}], "format": {"duration": "1"}}), "stderr": ""})()

    adapter = FfmpegFinalMediaAdapter(command_runner=command_runner)
    try:
        adapter.prepare(video, tmp_path / "out")
    except FinalVideoError as exc:
        assert exc.code == "FINAL_VIDEO_UNAVAILABLE"
        assert "subtitle" in str(exc)
    else:
        raise AssertionError("missing embedded subtitle must fail closed")


def test_final_video_qa_separates_audience_and_reference_and_writes_raw_evidence(tmp_path):
    questions = [
        {"id": "q1", "type": "short_answer", "question": "What is visible?", "answer": "gold secret", "scoring": "mention visible"},
        {"id": "q2", "type": "short_answer", "question": "What else?", "answer": "another secret", "scoring": "mention text"},
    ]
    case = _case(tmp_path, questions)
    candidate = tmp_path / "final.mp4"
    candidate.write_bytes(b"candidate")
    audience = FakeClient(
        [
            {"question_id": "q1", "answer": "visible", "explanation": "shown", "confidence": "high", "evidence_from_video": [{"timestamp_or_frame": "frame_0001", "observation": "visible"}]},
            {"question_id": "q2", "answer": "cannot_determine", "explanation": "not shown", "confidence": "low", "evidence_from_video": []},
        ]
    )
    reference = FakeClient(
        [
            {"question_id": "q1", "status": "correct", "reason": "supported", "matched_gold_points": ["visible"], "missing_gold_points": [], "contradictions": [], "explanation_status": "supported"},
            {"question_id": "q2", "status": "uncertain", "reason": "not enough", "matched_gold_points": [], "missing_gold_points": ["gold"], "contradictions": [], "explanation_status": "unverified"},
        ]
    )
    adapter = FinalVideoQAAdapter(audience, reference, media_adapter=FakeMediaAdapter(tmp_path))
    context = _context(tmp_path, case, adapter)
    result = adapter.evaluate_case(context)
    assert result["status"] == "ok"
    assert result["metrics"]["question_count"] == 2
    assert result["metrics"]["answered_count"] == 1
    assert result["metrics"]["correct_count"] == 1
    assert result["metrics"]["uncertain_count"] == 1
    assert result["metrics"]["strict_accuracy"] == 0.5
    assert result["metrics"]["information_recoverability"]["answer_rate"] == 0.5
    assert result["metrics"]["quiz_accuracy"]["partial_credit_accuracy"] == 0.5
    assert result["details"]["video_qa"]["input_mode"] == "final_media_extracted"
    audience_prompt = audience.messages[0][0]["content"][0]["text"]
    reference_prompt = reference.messages[0][0]["content"]
    assert "gold secret" not in audience_prompt
    assert "gold secret" in reference_prompt
    assert (tmp_path / "out" / "video_qa" / "audience" / "q1.json").is_file()
    assert (tmp_path / "out" / "video_qa" / "reference_judge" / "q1.json").is_file()
    assert (tmp_path / "out" / "video_qa" / "audience_input_manifest.json").is_file()
    assert (tmp_path / "out" / "video_qa" / "video_qa_calibration.md").is_file()


def test_runner_publishes_final_video_qa_in_existing_video_qa_field(tmp_path):
    questions = [{"id": "q1", "type": "short_answer", "question": "What?", "answer": "gold", "scoring": "answer"}]
    case = _case(tmp_path, questions)
    (tmp_path / "final.mp4").write_bytes(b"candidate")
    adapter = FinalVideoQAAdapter(
        FakeClient({"question_id": "q1", "answer": "visible", "explanation": "shown", "confidence": "high", "evidence_from_video": [{"timestamp_or_frame": "f", "observation": "shown"}]}),
        FakeClient({"question_id": "q1", "status": "correct", "reason": "ok", "matched_gold_points": ["answer"], "missing_gold_points": [], "contradictions": [], "explanation_status": "supported"}),
        media_adapter=FakeMediaAdapter(tmp_path),
    )
    report = run_case(
        case,
        run_id="run-1",
        artifacts_root=tmp_path,
        output_root=tmp_path / "runner-out",
        evaluators=[],
        repo_root=Path(__file__).resolve().parents[1],
        final_video_qa=adapter,
    )
    assert report["video_qa"]["metrics"]["correct_count"] == 1
    assert "videoqa_final" in report["evaluators"]
    assert (tmp_path / "runner-out" / "eval_report.json").is_file()
