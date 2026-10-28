import json
from copy import deepcopy
from pathlib import Path

import pytest
from playwright.sync_api import Error as BrowserError
from visual_plan_test_utils import model_plan_json

from textbook2video.pipeline import course_visuals
from textbook2video.pipeline.review_health import ReviewServiceUnavailable
from textbook2video.research import visual_cache as cache
from textbook2video.research import visual_tools as tools

SOURCE = "输入经过处理。输出显示结果。"
REAL_REVIEW = tools.review_revision
REAL_PREVIEW = tools.preview_revision


def arguments():
    return {
        "visuals": [
            {
                "id": "main",
                "kind": "flow",
                "title": "处理流程",
                "teaching_goal": "理解处理",
                "nodes": [
                    {"id": "a", "label": "输入", "source_ref": "source-001"},
                    {"id": "b", "label": "输出", "source_ref": "source-002"},
                ],
                "edges": [
                    {"source": "a", "target": "b", "source_ref": ["source-001", "source-002"]}
                ],
            }
        ]
    }


def fact_audit():
    return {"panels": [{
        "visual_id": "main", "units": [
            {"narration_ref": "narration-001", "status": "visible",
             "reason": "Input is shown", "visible_evidence": ["输入"]},
            {"narration_ref": "narration-002", "status": "visible",
             "reason": "Output is shown", "visible_evidence": ["输出"]},
        ], "edges": [{"source": "a", "target": "b", "status": "supported",
                      "reason": "Processing connects input and output"}],
    }]}


@pytest.fixture
def wired(monkeypatch):
    calls = {"plan": 0, "render": 0, "review": 0, "health": 0}
    modes = {}

    def planner(*args, **kwargs):
        calls["plan"] += 1
        return model_plan_json({"tool": "create", "arguments": arguments()})

    def preview(directory, **kwargs):
        calls["render"] += 1
        if modes.pop("render_fail", False):
            raise BrowserError("simulated render failure")
        tools._save(directory / "geometry.json", [])
        return []

    def review(directory, **kwargs):
        calls["review"] += 1
        if modes.pop("review_fail", False):
            raise ConnectionError("simulated provider failure")
        report = {
            "verdict": "ACCEPT",
            "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
            "issues": [],
            "reason": "fixture",
        }
        return tools._save_review(
            directory, json.dumps(report), [], model=kwargs["model"], has_images=True
        )

    def health(*args, **kwargs):
        calls["health"] += 1

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", preview)
    monkeypatch.setattr(tools, "review_revision", review)
    monkeypatch.setattr(course_visuals, "check_review_health", health)
    return calls, modes


def invoke(tmp_path, name, *, source=SOURCE, goal="理解处理", **overrides):
    kwargs = dict(
        model="planner",
        review_model="reviewer",
        theme="bright",
        browser="msedge",
        allow_images=False,
        page_context=[],
        narration_text=SOURCE,
        review_policy="strict",
    )
    kwargs.update(overrides)
    return cache.run_cached(
        tools.run_visual_agent,
        source,
        goal,
        tmp_path / name,
        cache_dir=tmp_path / "cache",
        **kwargs,
    )


def test_success_is_reused_across_runs_without_model_or_render_calls(tmp_path, wired):
    first = invoke(tmp_path, "first")
    before = deepcopy(wired[0])
    assert invoke(tmp_path, "second") == first
    assert wired[0] == before
    assert json.loads((tmp_path / "second-cache.json").read_text())["status"] == "HIT_VERIFIED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "another"),
        ("review_model", "other-reviewer"),
        ("theme", "dark-blue-academic"),
        ("review_policy", "development"),
        ("narration_text", SOURCE + "补充。"),
        ("allow_images", True),
        ("cache_context", {"source_images": {"a.png": "changed"}}),
    ],
)
def test_changed_binding_never_hits(tmp_path, wired, field, value):
    first = invoke(tmp_path, "first")
    second = invoke(tmp_path, "second", **{field: value})
    assert second != first
    assert wired[0]["plan"] == 2


def test_tampered_asset_is_a_hard_failure_not_regeneration(tmp_path, wired):
    path = invoke(tmp_path, "first")
    record = json.loads(path.read_text(encoding="utf-8"))
    asset = next((path.parent / "revision-00/compiled/assets").glob("*.svg"))
    asset.write_text("tampered", encoding="utf-8")
    before = deepcopy(wired[0])
    with pytest.raises(tools.RevisionIntegrityError):
        invoke(tmp_path, "second")
    assert wired[0] == before
    assert record["status"] == "MODEL_REVIEWED_PENDING_HUMAN"


def test_review_failure_retries_only_review_in_new_directory(tmp_path, wired):
    wired[1]["review_fail"] = True
    with pytest.raises(ReviewServiceUnavailable):
        invoke(tmp_path, "first")
    original = cache.artifact_hashes(tmp_path / "first")
    second = invoke(tmp_path, "second")
    assert wired[0] == {"plan": 1, "render": 1, "review": 2, "health": 0}
    assert cache.artifact_hashes(tmp_path / "first") == original
    state = json.loads(second.read_text(encoding="utf-8"))
    assert state["status"] == "MODEL_REVIEWED_PENDING_HUMAN"
    assert state["accepted_revision"].endswith("recovery-00")
    tools.verify_revision(second.parent / "recovery-00")


def test_render_failure_retries_render_without_replanning_or_compiling(
    tmp_path, wired, monkeypatch
):
    wired[1]["render_fail"] = True
    with pytest.raises(BrowserError):
        invoke(tmp_path, "first")
    monkeypatch.setattr(tools, "compile_visuals", lambda *a, **kw: pytest.fail("recompiled"))
    path = invoke(tmp_path, "second")
    assert wired[0]["plan"] == 1 and wired[0]["render"] == 2 and wired[0]["review"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "MODEL_REVIEWED_PENDING_HUMAN"


def test_course_reuses_pages_and_preserves_narration_without_health_api(tmp_path, wired):
    segments = [
        {
            "id": i,
            "narration": SOURCE,
            "elements": [{"id": "h", "type": "heading", "text": f"处理{i}"}],
        }
        for i in (1, 2)
    ]
    original = deepcopy(segments)
    options = dict(
        model="planner",
        review_model="reviewer",
        theme="bright",
        source_text=SOURCE,
        rebuild_timing_before_tts=True,
        rebuild_page_from_source=True,
        cache_dir=tmp_path / "cache",
    )
    first = course_visuals.generate_course_visuals(
        deepcopy(original), output_dir=tmp_path / "one", **options
    )
    before = deepcopy(wired[0])
    second = course_visuals.generate_course_visuals(
        segments, output_dir=tmp_path / "two", **options
    )
    assert first == second and wired[0] == before
    assert [s["narration"] for s in segments] == [s["narration"] for s in original]


def test_resume_rejects_changed_original_input(tmp_path, wired):
    wired[1]["review_fail"] = True
    with pytest.raises(ReviewServiceUnavailable):
        invoke(tmp_path, "first")
    with pytest.raises(tools.RevisionIntegrityError):
        tools.run_visual_agent(
            SOURCE + "不同来源。",
            "理解处理",
            tmp_path / "other",
            resume_from=tmp_path / "first/run.json",
        )


@pytest.mark.parametrize(
    "field,value", [("source", SOURCE + "新增原文。"), ("goal", "另一教学目标")]
)
def test_source_and_goal_changes_miss_cache(tmp_path, wired, field, value):
    first = invoke(tmp_path, "first")
    assert invoke(tmp_path, "second", **{field: value}) != first
    assert wired[0]["plan"] == 2


def test_repeated_render_failure_can_resume_again(tmp_path, wired):
    for name in ("first", "second"):
        wired[1]["render_fail"] = True
        with pytest.raises(BrowserError):
            invoke(tmp_path, name)
    path = invoke(tmp_path, "third")
    assert wired[0]["plan"] == 1 and wired[0]["render"] == 3
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "MODEL_REVIEWED_PENDING_HUMAN"


def test_failed_content_stage_edits_preserved_candidate_without_new_create(
    tmp_path, wired, monkeypatch
):
    def planner(prompt, **kwargs):
        wired[0]["plan"] += 1
        if wired[0]["plan"] == 1:
            args = arguments()
            args["visuals"][0]["edges"][0]["target"] = "missing"
            return model_plan_json({"tool": "create", "arguments": args})
        request = json.loads(prompt)
        assert "evidence" not in request["previous_candidate"]["visuals"][0]["nodes"][0]
        fixed = arguments()
        return model_plan_json({"tool": "revise", "arguments": fixed})

    monkeypatch.setattr(tools, "chat_with_system", planner)
    first = invoke(tmp_path, "first", max_iterations=1)
    assert not cache.usable_run(json.loads(first.read_text(encoding="utf-8")))
    second = invoke(tmp_path, "second", max_iterations=1)
    assert cache.usable_run(json.loads(second.read_text(encoding="utf-8")))
    assert wired[0]["plan"] == 2 and wired[0]["render"] == 1


@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("default_narration", [False, True])
def test_image_api_recovery_reuses_successful_asset_and_does_not_replan(
    tmp_path, wired, monkeypatch, raises, default_narration
):
    import base64

    from textbook2video.research import visual_synthesis as synthesis

    calls = []

    def image(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 2:
            if raises:
                raise ConnectionError("image endpoint unavailable")
            return None
        return base64.b64encode(b"fixture image bytes").decode()

    def planner(*args, **kwargs):
        wired[0]["plan"] += 1
        return model_plan_json(
            {
                "tool": "create",
                "arguments": {
                    "visuals": [
                        {
                            "id": ident,
                            "kind": "scene",
                            "title": ident,
                            "teaching_goal": "理解处理",
                            "prompt": ident,
                            "source_ref": f"source-00{i}",
                            "narration_refs": [f"narration-00{i}"],
                        }
                        for i, ident in enumerate(("first-picture", "second-picture"), 1)
                    ]
                },
            }
        )

    original_compile = synthesis.compile_visuals
    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(
        tools, "compile_visuals", lambda *a, **kw: original_compile(*a, image_generator=image, **kw)
    )
    options = {"max_iterations": 1, "allow_images": True}
    if default_narration:
        options["narration_text"] = None
    if raises:
        with pytest.raises(ConnectionError):
            invoke(tmp_path, "first", **options)
    else:
        invoke(tmp_path, "first", **options)
    path = invoke(tmp_path, "second", **options)
    assert calls == ["first-picture", "second-picture", "second-picture"]
    assert wired[0]["plan"] == 1
    state = json.loads(path.read_text(encoding="utf-8"))
    assert cache.usable_run(state)
    recovered_request = json.loads(
        (Path(state["usable_revision"]) / "request.json").read_text(encoding="utf-8")
    )
    assert recovered_request["layout_policy"] == "automatic"


def test_endpoint_binding_uses_effective_client_not_changed_environment(
    tmp_path, wired, monkeypatch
):
    from textbook2video.llm import client

    first = invoke(tmp_path, "first")
    monkeypatch.setenv("LLM_API_KEY", "fixture-key-never-used")
    monkeypatch.setenv("LLM_BASE_URL", "https://unused-new-environment.invalid/v1")
    assert invoke(tmp_path, "second") == first
    monkeypatch.setattr(client, "LLM_BASE_URL", "https://actual-other-endpoint.invalid/v1")
    assert invoke(tmp_path, "third") != first
    assert wired[0]["plan"] == 2


def test_two_page_retry_reuses_first_and_only_reviews_failed_second(tmp_path, wired, monkeypatch):
    original_review = tools.review_revision
    failed = []

    def review(directory, **kwargs):
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        if request["teaching_goal"] == "处理2" and not failed:
            failed.append(True)
            wired[0]["review"] += 1
            raise ConnectionError("second page review unavailable")
        return original_review(directory, **kwargs)

    monkeypatch.setattr(tools, "review_revision", review)
    original = [
        {
            "id": i,
            "narration": SOURCE,
            "elements": [{"id": "h", "type": "heading", "text": f"处理{i}"}],
        }
        for i in (1, 2)
    ]
    options = dict(
        model="planner",
        review_model="reviewer",
        theme="bright",
        source_text=SOURCE,
        rebuild_timing_before_tts=True,
        rebuild_page_from_source=True,
        cache_dir=tmp_path / "cache",
    )
    with pytest.raises(ReviewServiceUnavailable):
        course_visuals.generate_course_visuals(
            deepcopy(original), output_dir=tmp_path / "one", **options
        )
    course_visuals.generate_course_visuals(
        deepcopy(original), output_dir=tmp_path / "two", **options
    )
    assert wired[0]["plan"] == 2 and wired[0]["render"] == 2 and wired[0]["review"] == 3


def test_invalid_composition_recovers_by_editing_not_repeating_compile(
    tmp_path, wired, monkeypatch
):
    def planner(*args, **kwargs):
        wired[0]["plan"] += 1
        if wired[0]["plan"] == 1:
            candidate = arguments()
            candidate["composition"] = {
                "visual_ids": ["main"],
                "axis": "horizontal",
                "horizontal_free": True,
            }
            return model_plan_json({"tool": "create", "arguments": candidate})
        candidate = arguments()
        candidate["composition"] = {"visual_ids": ["main"], "axis": "single"}
        return model_plan_json({"tool": "revise", "arguments": candidate})

    monkeypatch.setattr(tools, "chat_with_system", planner)
    invoke(tmp_path, "first", max_iterations=1)
    path = invoke(tmp_path, "second", max_iterations=1)
    assert cache.usable_run(json.loads(path.read_text(encoding="utf-8")))
    assert wired[0]["plan"] == 2


def test_protocol_retry_of_same_pixels_cannot_forget_prior_rejection(tmp_path, wired, monkeypatch):
    from test_visual_tools import review

    # Use the real protocol parser; only transport is mocked.
    monkeypatch.setattr(tools, "review_revision", REAL_REVIEW)
    transport_calls = []

    def transport(prompt, **kwargs):
        if kwargs.get("max_tokens") == 6000:
            wired[0]["plan"] += 1
            return model_plan_json({"tool": "create", "arguments": arguments()})
        transport_calls.append(1)
        if len(transport_calls) <= 2:
            return json.dumps(
                {
                    "verdict": "REJECT",
                    "scores": {},
                    "issues": [
                        {
                            "category": "factual_error",
                            "issue": "known error",
                            "change": "fix content",
                        }
                    ],
                    "reason": "invalid envelope with known rejection",
                }
            )
        return model_plan_json(
            {
                "verdict": "ACCEPT",
                "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
                "issues": [],
                "reason": "new answer",
                "relation_audit": review()["relation_audit"],
                "fact_audit": fact_audit(),
            }
        )

    monkeypatch.setattr(tools, "chat_with_system", transport)
    first = invoke(tmp_path, "first", max_iterations=1)
    assert json.loads(first.read_text(encoding="utf-8"))["status"] == "STOPPED_REVIEW_PROTOCOL"
    second = invoke(tmp_path, "second", max_iterations=1)
    assert json.loads(second.read_text(encoding="utf-8"))["status"] == "STOPPED_REVIEW_REJECTED"
    assert wired[0]["plan"] == 1 and len(transport_calls) == 3


def test_same_pixel_cross_run_recovery_preserves_raw_relation_denial(tmp_path, wired, monkeypatch):
    from test_visual_tools import review

    monkeypatch.setattr(tools, "review_revision", REAL_REVIEW)
    calls = []

    def transport(prompt, **kwargs):
        if kwargs.get("max_tokens") == 6000:
            return model_plan_json({"tool": "create", "arguments": arguments()})
        calls.append(1)
        reply = review()
        reply["fact_audit"] = fact_audit()
        if len(calls) <= 2:
            reply["relation_audit"] = {"comparison_operands": {
                "status": "incorrect", "reason": "比较对象类型不一致"}}
        return json.dumps(reply)

    monkeypatch.setattr(tools, "chat_with_system", transport)
    first = invoke(tmp_path, "denied-first", max_iterations=1)
    assert json.loads(first.read_text(encoding="utf-8"))["status"] == "STOPPED_REVIEW_PROTOCOL"
    second = invoke(tmp_path, "denied-resume", max_iterations=1)
    state = json.loads(second.read_text(encoding="utf-8"))
    assert not cache.usable_run(state)
    carried = list(second.parent.glob("recovered-*/prior-review-findings.json"))
    if not carried:
        carried = list(second.parent.rglob("prior-review-findings.json"))
    assert carried
    prior = json.loads(carried[0].read_text(encoding="utf-8"))
    assert prior["verdict"] == "REVISE" and prior["checks"]["accuracy"] is False
    assert any("comparison_operands" in issue["issue"] for issue in prior["issues"])


@pytest.mark.parametrize("invalid", [-1, 5, True, "bad"])
def test_invalid_prior_score_cannot_erase_known_low_score(tmp_path, invalid):
    prior = cache.merge_findings([{"scores": {"accuracy": 1}}, {"scores": {"accuracy": invalid}}])
    assert prior["scores"]["accuracy"] == 1
    directory = tmp_path / "same-pixels"
    tools.dispatch("create", arguments(), source=SOURCE, output_dir=directory, render=False)
    report = tools._save_review(
        directory,
        json.dumps(
            {
                "verdict": "ACCEPT",
                "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
                "issues": [],
                "reason": "new reply",
            }
        ),
        [],
        model="reviewer",
        has_images=True,
        prior_report=prior,
    )
    assert report["scores"]["accuracy"] == 1
    assert report["verdict"] == "REVISE"


def test_auto_layout_render_recovery_in_real_browser(tmp_path, wired, monkeypatch):
    from playwright.sync_api import sync_playwright
    from test_visual_interface import relation

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge", headless=True)
        except BrowserError:
            pytest.skip("Edge unavailable for real render recovery test")
        browser.close()

    def planner(*args, **kwargs):
        wired[0]["plan"] += 1
        return model_plan_json({"tool": "create", "arguments": relation()})

    def preview(directory, **kwargs):
        wired[0]["render"] += 1
        if wired[0]["render"] == 1:
            raise BrowserError("injected first render failure")
        return REAL_PREVIEW(directory, **kwargs)

    def review(directory, **kwargs):
        # Test fixture only: geometry is real; semantic approval is not claimed.
        wired[0]["review"] += 1
        geometry = json.loads((directory / "geometry.json").read_text(encoding="utf-8"))
        return tools._save_review(
            directory,
            json.dumps(
                {
                    "verdict": "ACCEPT",
                    "scores": dict.fromkeys(
                        ["accuracy", "relevance", "readability", "composition"], 4
                    ),
                    "issues": [],
                    "reason": "offline test fixture",
                }
            ),
            geometry,
            model=kwargs["model"],
            has_images=True,
        )

    monkeypatch.setattr(tools, "chat_with_system", planner)
    monkeypatch.setattr(tools, "preview_revision", preview)
    monkeypatch.setattr(tools, "review_revision", review)
    with pytest.raises(BrowserError):
        invoke(tmp_path, "first")
    second = invoke(tmp_path, "second")
    assert invoke(tmp_path, "third") == second
    assert wired[0]["plan"] == 1 and wired[0]["render"] == 2 and wired[0]["review"] == 1
    state = json.loads(second.read_text(encoding="utf-8"))
    revision = json.loads(
        (Path(state["accepted_revision"]) / "revision.json").read_text(encoding="utf-8")
    )
    assert revision["recovery_stage"] == "render"
    assert revision["geometry"] and not any(r["issues"] for r in revision["geometry"])
