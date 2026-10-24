import json
import sys
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_review_policy import review_disposition


def cosmetic_review():
    return {
        "verdict": "REVISE",
        "reason": "Content intact; improve spacing",
        "scores": {"accuracy": 4, "relevance": 4, "readability": 3, "composition": 2},
        "checks": dict.fromkeys(["accuracy", "relevance", "completeness", "readability"], True),
        "issues": [
            {
                "visual_id": "main",
                "category": "spacing",
                "issue": "Large gap",
                "change": "Reduce whitespace",
            }
        ],
    }


@pytest.mark.parametrize("policy", [None, "strict", "development"])
def test_cli_forwards_visual_policy_without_changing_other_review_flags(
    tmp_path, monkeypatch, policy
):
    from textbook2video import cli
    from textbook2video.pipeline import orchestrator

    calls = []
    monkeypatch.setattr(orchestrator, "produce", lambda *a, **kw: calls.append(kw) or tmp_path)
    argv = ["t2v", "produce", "missing.pdf", "--lesson", "2"]
    if policy:
        argv.extend(["--visual-review-policy", policy])
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert calls[0]["visual_review_policy"] == policy
    assert calls[0]["agent_review_strict"] is False


def test_cosmetic_warning_is_not_strict_approval():
    report = cosmetic_review()
    before = deepcopy(report)
    decision = review_disposition(report, [])
    assert decision["draft_usable"] and not decision["strict_approved"]
    assert decision["warnings"] == report["issues"]
    assert report == before


@pytest.mark.parametrize(
    "problem",
    [
        "accuracy",
        "relevance",
        "readability",
        "completeness",
        "reject",
        "unknown",
        "untyped",
        "factual_error",
        "missing_content",
        "unreadable",
        "irrelevant_content",
        "geometry",
        "checks",
        "missing_checks",
        "empty_issues",
        "invalid_scores",
        "coverage",
    ],
)
def test_cosmetic_label_cannot_override_hard_evidence(problem):
    report = cosmetic_review()
    geometry, plan = [], None
    if problem in {"accuracy", "relevance", "readability"}:
        report["scores"][problem] = 2
    elif problem == "completeness":
        report["checks"]["completeness"] = False
    elif problem == "reject":
        report["verdict"] = "REJECT"
    elif problem == "untyped":
        del report["issues"][0]["category"]
    elif problem == "geometry":
        geometry = [{"issues": ["clipped"]}]
    elif problem == "checks":
        report["checks"] = []
    elif problem == "missing_checks":
        del report["checks"]
    elif problem == "empty_issues":
        report["issues"] = []
    elif problem == "invalid_scores":
        report["scores"]["accuracy"] = True
    elif problem == "coverage":
        plan = {
            "replaces_element_ids": ["e1"],
            "coverage": [{"element_id": "e1", "decision": "represented"}],
        }
        report["coverage"] = [{"element_id": "e1", "verdict": "missing", "reason": "Absent"}]
    else:
        report["issues"][0]["category"] = problem
    result = review_disposition(report, geometry, plan)
    assert not result["draft_usable"] and not result["strict_approved"]


def test_negative_checks_block_even_accept_and_legacy_accept_still_supported():
    report = cosmetic_review()
    report.update(verdict="ACCEPT", issues=[], scores=dict.fromkeys(report["scores"], 4))
    assert review_disposition(report, [])["strict_approved"]
    report["checks"]["completeness"] = False
    assert not review_disposition(report, [])["draft_usable"]
    del report["checks"]
    assert review_disposition(report, [])["strict_approved"]


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_typed_checks_cannot_be_coerced_into_strict_approval(value):
    report = cosmetic_review()
    report.update(verdict="ACCEPT", issues=[], scores=dict.fromkeys(report["scores"], 4))
    report["checks"]["completeness"] = value
    assert not review_disposition(report, [])["draft_usable"]


def test_malformed_issue_category_is_a_blocker_not_an_exception():
    report = cosmetic_review()
    report["issues"][0]["category"] = ["spacing"]
    assert not review_disposition(report, [])["draft_usable"]


def test_protocol_repair_does_not_erase_negative_completeness(tmp_path):
    from test_visual_tools import SOURCE, graph

    revision = tmp_path / "revision"
    tools.dispatch(
        "create", {"visuals": [graph()]}, source=SOURCE, output_dir=revision, render=False
    )
    prior = cosmetic_review()
    prior["checks"]["completeness"] = False
    saved = tools._save_review(
        revision,
        json.dumps(cosmetic_review()),
        [],
        model="test",
        has_images=True,
        attempt=1,
        prior_report=prior,
    )
    assert saved["checks"]["completeness"] is False
    assert not review_disposition(saved, [])["draft_usable"]


@pytest.mark.parametrize("initial_verdict", ["missing", "unsupported", "irrelevant"])
def test_protocol_repair_cannot_erase_prior_negative_coverage(
    tmp_path, monkeypatch, initial_verdict
):
    from test_visual_tools import reviewable_revision

    directory = reviewable_revision(tmp_path, monkeypatch)
    first = cosmetic_review()
    first["coverage"] = [
        {
            "element_id": "note",
            "verdict": initial_verdict,
            "reason": "Original supported fact not represented",
        }
    ]
    del first["reason"]  # Trigger same-image envelope completion, not a new diagram.
    second = cosmetic_review()
    second["coverage"] = [{"element_id": "note", "verdict": "covered", "reason": "Now covered"}]
    replies = iter([first, second])
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: json.dumps(next(replies)))
    saved = tools.review_revision(directory, model="test")
    record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    assert saved["coverage"][0]["verdict"] == "covered"  # Keep final raw result auditable.
    assert saved["prior_coverage_conflicts"] == first["coverage"]
    assert not review_disposition(saved, record["geometry"], record["page_plan"])["draft_usable"]


@pytest.mark.parametrize("policy", ["bogus", "development"])
def test_research_rejects_development_or_unknown_policy_before_any_io(policy, tmp_path):
    from textbook2video.pipeline.orchestrator import produce

    with pytest.raises(ValueError, match="visual.*policy"):
        produce(
            "missing.pdf",
            p0_research=True,
            visual_review_policy=policy,
            output_dir=tmp_path / "unused",
        )
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("development", "DRAFT_WITH_WARNINGS_PENDING_HUMAN"),
        ("strict", "STOPPED_ITERATION_BUDGET"),
    ],
)
def test_real_dispatch_loop_distinguishes_draft_from_approval(
    tmp_path, monkeypatch, policy, expected
):
    from test_visual_tools import SOURCE, graph

    monkeypatch.setattr(
        tools,
        "chat_with_system",
        lambda *a, **kw: json.dumps({"tool": "create", "arguments": {"visuals": [graph()]}}),
    )
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    monkeypatch.setattr(tools, "review_revision", lambda *a, **kw: cosmetic_review())
    run_path = tools.run_visual_agent(
        SOURCE, "Data processing", tmp_path / policy, max_iterations=1, review_policy=policy
    )
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == expected and run["accepted_revision"] is None
    assert bool(run["usable_revision"]) == (policy == "development")
    assert run["history"][0]["review"]["verdict"] == "REVISE"


def test_course_adapter_consumes_draft_only_with_explicit_development_policy(tmp_path, monkeypatch):
    from test_visual_tools import SOURCE, graph

    from textbook2video.pipeline import course_visuals

    revision = tmp_path / "revision"
    tools.dispatch(
        "create", {"visuals": [graph()]}, source=SOURCE, output_dir=revision, render=False
    )
    report = tools._save_review(
        revision, json.dumps(cosmetic_review()), [], model="test", has_images=True
    )
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "status": "DRAFT_WITH_WARNINGS_PENDING_HUMAN",
                "accepted_revision": None,
                "usable_revision": str(revision),
                "review_policy": "development",
                "history": [{"revision": str(revision), "review_sha256": tools.digest(report)}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run_path)
    segment = {"id": 1, "narration": SOURCE, "elements": []}
    with pytest.raises(ValueError, match="review did not pass"):
        course_visuals.generate_course_visuals(
            [deepcopy(segment)], output_dir=tmp_path, model="test", theme="bright"
        )
    planned = deepcopy(segment)
    images = course_visuals.generate_course_visuals(
        [planned], output_dir=tmp_path, model="test", theme="bright", review_policy="development"
    )
    assert images and planned["visual_review"]["warnings"]
    assert planned["visual_review"]["model_verdict"] == "REVISE"
    # A cached usable path/status must never override subsequently negative evidence.
    report["checks"]["completeness"] = False
    (revision / "review.json").write_text(json.dumps(report), encoding="utf-8")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["history"][0]["review_sha256"] = tools.digest(report)
    run_path.write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(ValueError, match="review does not match"):
        course_visuals.generate_course_visuals(
            [deepcopy(segment)],
            output_dir=tmp_path,
            model="test",
            theme="bright",
            review_policy="development",
        )
