import json
from copy import deepcopy

import pytest

from textbook2video.pipeline import course_visuals, review_health


def test_probe_checks_image_and_records_model(tmp_path, monkeypatch):
    def reply(prompt, images, **kwargs):
        assert images[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert kwargs["model"] == "reviewer"
        assert kwargs["timeout"] == 30
        return '{"shape":"square","color":"blue"}'

    monkeypatch.setattr(review_health, "chat_with_images", reply)
    path = review_health.check_review_health(tmp_path / "health", model="reviewer")
    assert json.loads(path.read_text())["status"] == "AVAILABLE"


@pytest.mark.parametrize("response", ["not JSON", '{}', '{"shape":"circle","color":"red"}'])
def test_probe_rejects_invalid_understanding(tmp_path, monkeypatch, response):
    monkeypatch.setattr(review_health, "chat_with_images", lambda *a, **kw: response)
    with pytest.raises(review_health.ReviewServiceUnavailable):
        review_health.check_review_health(tmp_path / "health", model="reviewer")


@pytest.mark.parametrize("failure_policy", ["stop", "fallback"])
def test_common_failure_stops_before_page_mutations(tmp_path, monkeypatch, failure_policy):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(kwargs["model"])
        raise RuntimeError("secret-provider-error")

    monkeypatch.setattr(review_health, "chat_with_images", unavailable)
    monkeypatch.setattr(
        course_visuals, "run_visual_agent", lambda *a, **kw: pytest.fail("planner called")
    )
    segments = [{"id": 1, "narration": "keep", "elements": []},
                {"id": 2, "narration": "keep too", "elements": []}]
    before = deepcopy(segments)
    with pytest.raises(review_health.ReviewServiceUnavailable):
        course_visuals.generate_course_visuals(
            segments, output_dir=tmp_path, model="planner", review_model="reviewer",
            theme="bright", review_policy="development", failure_policy=failure_policy,
        )
    assert calls == ["reviewer"]
    assert segments == before
    result = next(tmp_path.rglob("result.json")).read_text()
    assert "secret-provider-error" not in result
    assert json.loads(result)["error_type"] == "RuntimeError"


def test_cover_only_needs_no_review_service(tmp_path, monkeypatch):
    monkeypatch.setattr(review_health, "chat_with_images", lambda *a, **kw: pytest.fail("network"))
    assert course_visuals.generate_course_visuals(
        [{"id": 1, "visual_type": "cover", "narration": "title", "elements": []}],
        output_dir=tmp_path, model="planner", theme="bright",
    ) == {}


def test_success_checks_once_and_preserves_separate_models(tmp_path, monkeypatch):
    probes, pages = [], []
    monkeypatch.setattr(
        course_visuals, "check_review_health", lambda path, **kw: probes.append(kw["model"])
    )

    def plan(segments, **kwargs):
        pages.append((kwargs["model"], kwargs["review_model"]))
        return {}

    monkeypatch.setattr(course_visuals, "_generate_course_visuals_strict", plan)
    course_visuals.generate_course_visuals(
        [{"id": 1, "narration": "one"}, {"id": 2, "narration": "two"}],
        output_dir=tmp_path, model="planner", review_model="reviewer", theme="bright",
    )
    assert probes == ["reviewer"]
    assert pages == [("planner", "reviewer"), ("planner", "reviewer")]


def test_mid_batch_review_failure_is_not_page_fallback(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(course_visuals, "check_review_health", lambda *a, **kw: None)

    def unavailable(*a, **kw):
        calls.append(1)
        raise review_health.ReviewServiceUnavailable("review transport failed")

    monkeypatch.setattr(course_visuals, "run_visual_agent", unavailable)
    segments = [{"id": 1, "narration": "one", "elements": []},
                {"id": 2, "narration": "two", "elements": []}]
    before = deepcopy(segments)
    with pytest.raises(review_health.ReviewServiceUnavailable):
        course_visuals.generate_course_visuals(
            segments, output_dir=tmp_path, model="planner", theme="bright",
            review_policy="development", failure_policy="fallback",
        )
    assert calls == [1]
    assert segments == before
