import json
from pathlib import Path

from textbook2video.eval.evaluators.visual_vlm import (
    DIMENSION_ISSUE_TYPES,
    VisualVLMAdapter,
    evaluate_visual_vlm,
    normalize_visual_response,
)
from textbook2video.eval.runner import EvalContext, run_case


class _Case:
    case_id = "case_visual"
    lesson_id = "lesson_visual"
    dataset_version = "dataset-test"

    def __init__(self, root: Path):
        self.root = root
        self.manifest_path = root / "case_manifest.json"
        self.raw = {"case_id": self.case_id, "lesson_id": self.lesson_id}

    def assets(self):
        return []

    def resolve_asset(self, asset):
        return self.root / asset.path


class _FakeClient:
    model = "vision-test"

    def __init__(self, response):
        self.response = response
        self.messages = []

    def chat(self, messages, *, max_tokens):
        self.messages.append((messages, max_tokens))
        return self.response, json.dumps(self.response, ensure_ascii=False)


def _response():
    evidence = [{"region": "center", "observation": "visible teaching content"}]
    return {
        "visual_hierarchy": {"status": "clear", "confidence": "high", "reason": "title leads", "evidence": evidence},
        "readability": {"status": "good", "confidence": "high", "reason": "text is legible", "evidence": evidence},
        "visual_relevance": {"status": "relevant", "confidence": "medium", "reason": "visual supports topic", "evidence": evidence},
        "composition_coherence": {"status": "coherent", "confidence": "medium", "reason": "groups align", "evidence": evidence},
        "pedagogical_visual_value": {"status": "strong", "confidence": "medium", "reason": "comparison is useful", "evidence": evidence},
        "image_grounding": {"status": "not_applicable", "confidence": "high", "reason": "no image is present", "evidence": evidence},
        "issues": [],
    }


def test_visual_response_is_strict_and_fails_closed():
    normalized, errors = normalize_visual_response(_response())
    assert not errors
    assert normalized["visual_hierarchy"]["status"] == "clear"

    normalized, errors = normalize_visual_response("not-json")
    assert errors == ["response_not_object"]
    assert all(normalized[name]["status"] == "uncertain" for name in normalized if name != "issues")

    invalid = _response()
    invalid["readability"] = {"status": "good", "confidence": "high", "reason": ""}
    _, errors = normalize_visual_response(invalid)
    assert "invalid_readability" in errors

    no_image = _response()
    no_image["image_grounding"] = {
        "status": "not_applicable",
        "confidence": "high",
        "reason": "no image is present",
        "evidence": [],
    }
    normalized, errors = normalize_visual_response(no_image)
    assert not errors
    assert normalized["image_grounding"]["status"] == "not_applicable"

    missing_evidence = _response()
    missing_evidence["visual_relevance"]["evidence"] = []
    normalized, errors = normalize_visual_response(missing_evidence)
    assert normalized["visual_relevance"]["status"] == "uncertain"
    assert "invalid_visual_relevance" in errors


def test_visual_issue_taxonomy_uses_formal_names():
    assert DIMENSION_ISSUE_TYPES == {
        "visual_hierarchy": "VISUAL_HIERARCHY",
        "readability": "VISUAL_READABILITY",
        "visual_relevance": "VISUAL_SEMANTIC",
        "composition_coherence": "VISUAL_COMPOSITION",
        "pedagogical_visual_value": "VISUAL_PEDAGOGICAL_VALUE",
        "image_grounding": "IMAGE_GROUNDING",
    }


def test_visual_adapter_saves_screenshot_raw_response_and_provenance(tmp_path):
    html = tmp_path / "animation.html"
    html.write_text('<div class="slide"></div>', encoding="utf-8")
    storyboard = tmp_path / "storyboard.json"
    storyboard.write_text(
        json.dumps({"segments": [{"id": 1, "narration": "Explain the idea.", "elements": []}]}),
        encoding="utf-8",
    )

    def render(_html_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = output_dir / "slide_001.png"
        screenshot.write_bytes(b"png-test")
        return [screenshot], {"ok": True, "viewport": {"width": 1920, "height": 1080}}

    adapter = VisualVLMAdapter(_FakeClient(_response()), render_screenshots=render)
    context = EvalContext(
        case=_Case(tmp_path),
        run_id="visual-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
        candidate_commit="commit-test",
    )
    adapter.set_output_root(context.output_root)
    result = adapter.evaluate_case(context)

    assert result["status"] == "ok"
    assert result["metrics"]["judged_slide_count"] == 1
    assert result["details"]["slides"][0]["render_commit"] == "commit-test"
    assert (tmp_path / "out" / "rendered_visual" / "slide_001.png").is_file()
    raw = tmp_path / "out" / "rendered_visual" / "judge" / "slide_001.json"
    assert raw.is_file()
    raw_value = json.loads(raw.read_text(encoding="utf-8"))
    assert raw_value["image_sha256"]
    assert raw_value["context_sha256"]
    assert raw_value["parsed_response"]["readability"]["status"] == "good"
    calibration = tmp_path / "out" / "visual_vlm_calibration.md"
    assert calibration.is_file()
    calibration_text = calibration.read_text(encoding="utf-8")
    assert "| Slide | Dimension | VLM result | Confidence | Evidence | Human label | Notes |" in calibration_text
    assert calibration_text.count("| pending |") == 6
    assert result["details"]["calibration_path"] == "visual_vlm_calibration.md"


def test_visual_adapter_fails_closed_for_missing_screenshot(tmp_path):
    html = tmp_path / "animation.html"
    html.write_text('<div class="slide"></div>', encoding="utf-8")
    (tmp_path / "storyboard.json").write_text(
        json.dumps({"segments": [{"id": 1}, {"id": 2}]}), encoding="utf-8"
    )

    def render(_html_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = output_dir / "slide_001.png"
        screenshot.write_bytes(b"png-test")
        return [screenshot], {"ok": True}

    adapter = VisualVLMAdapter(_FakeClient(_response()), render_screenshots=render)
    context = EvalContext(
        case=_Case(tmp_path),
        run_id="visual-missing-screenshot",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
    )
    result = adapter.evaluate_case(context)
    assert result["status"] == "unavailable"
    assert "screenshot" in result["details"]["reason"]


def test_visual_adapter_fails_closed_for_invalid_slide_segment(tmp_path):
    html = tmp_path / "animation.html"
    html.write_text('<div class="slide"></div>', encoding="utf-8")
    (tmp_path / "storyboard.json").write_text(
        json.dumps({"segments": [{"id": None}]}), encoding="utf-8"
    )

    def render(_html_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = output_dir / "slide_001.png"
        screenshot.write_bytes(b"png-test")
        return [screenshot], {"ok": True}

    adapter = VisualVLMAdapter(_FakeClient(_response()), render_screenshots=render)
    context = EvalContext(
        case=_Case(tmp_path),
        run_id="visual-invalid-slide",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
    )
    result = adapter.evaluate_case(context)
    assert result["status"] == "unavailable"
    assert "invalid slide" in result["details"]["reason"]


def test_visual_adapter_marks_provider_error_uncertain(tmp_path):
    html = tmp_path / "animation.html"
    html.write_text('<div class="slide"></div>', encoding="utf-8")
    (tmp_path / "storyboard.json").write_text(
        json.dumps({"segments": [{"id": 1}]}), encoding="utf-8"
    )

    def render(_html_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = output_dir / "slide_001.png"
        screenshot.write_bytes(b"png-test")
        return [screenshot], {"ok": True}

    class FailingClient(_FakeClient):
        def chat(self, messages, *, max_tokens):
            raise RuntimeError("provider unavailable")

    adapter = VisualVLMAdapter(FailingClient(_response()), render_screenshots=render, max_retries=0)
    context = EvalContext(
        case=_Case(tmp_path),
        run_id="visual-provider-error",
        artifacts_root=tmp_path,
        output_root=tmp_path / "out",
    )
    result = adapter.evaluate_case(context)
    assert result["status"] == "ok"
    assert result["metrics"]["uncertain_slide_count"] == 1
    assert result["issues"][0]["type"] == "EVAL_UNCERTAIN"


def test_runner_can_enable_visual_evaluator_without_changing_default_evaluators(tmp_path):
    html = tmp_path / "animation.html"
    html.write_text('<div class="slide"></div>', encoding="utf-8")
    (tmp_path / "storyboard.json").write_text(
        json.dumps({"segments": [{"id": 1, "narration": "Explain.", "elements": []}]}),
        encoding="utf-8",
    )

    def render(_html_path, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "slide_001.png"
        path.write_bytes(b"png-test")
        return [path], {"ok": True}

    adapter = VisualVLMAdapter(_FakeClient(_response()), render_screenshots=render)
    report = run_case(
        _Case(tmp_path),
        run_id="visual-runner-test",
        artifacts_root=tmp_path,
        output_root=tmp_path / "eval",
        evaluators=[evaluate_visual_vlm],
        visual_vlm=adapter,
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert report["evaluators"]["visual_vlm"]["status"] == "ok"
    assert report["evaluators"]["visual_vlm"]["details"]["model"] == "vision-test"
    assert json.loads((tmp_path / "eval" / "run_manifest.json").read_text(encoding="utf-8"))["models"]["visual_vlm"] == "vision-test"
