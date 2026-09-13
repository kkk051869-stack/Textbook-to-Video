import json
from pathlib import Path

from textbook2video.eval.evaluators.visual_vlm import (
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
