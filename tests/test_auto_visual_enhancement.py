from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.pipeline import course_visuals


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _segment() -> dict:
    return {
        "id": "lesson-new-1",
        "visual_type": "content",
        "title": "输入与输出",
        "narration": "输入经过处理后得到输出。",
        "elements": [
            {"id": "heading", "type": "heading", "text": "输入与输出"},
            {"id": "body", "type": "text", "text": "输入经过处理后得到输出。"},
        ],
        "timeline": [
            {"event_id": "existing-show", "target": "body", "action": "show", "at_sec": 0.0},
        ],
        "animations": [
            {"target": "body", "effect": "fadeIn", "trigger_at_sec": 0.0},
        ],
    }


def test_auto_storyboard_route_runs_decision_and_forces_preservation(tmp_path, monkeypatch):
    import textbook2video.pipeline.visual_page_render as page_render

    storyboard = {"lesson_title": "fixture", "segments": [_segment()], "metadata": {}}
    storyboard_path = _write_json(tmp_path / "fixture_storyboard.json", storyboard)
    source_path = tmp_path / "fixture_raw.txt"
    source_path.write_text("输入经过处理后得到输出。", encoding="utf-8")
    called = {}

    def selection(*args, **kwargs):
        called["selection"] = (args, kwargs)
        return {
            "source_storyboard_sha256": hashlib.sha256(storyboard_path.read_bytes()).hexdigest(),
            "human_review": "NOT_REVIEWED",
            "pages": {
                "lesson-new-1": {
                    "decisions": [{"action": "none", "narration_proposition_id": "p1"}],
                    "propositions": [{"id": "p1", "text": "输入经过处理后得到输出。"}],
                    "assets": [], "requires_generation": False,
                    "decision_status": "NONE", "unresolved_propositions": [],
                }
            },
        }

    monkeypatch.setattr(course_visuals, "prepare_course_asset_selection", selection)
    monkeypatch.setattr(course_visuals, "generate_course_visuals", lambda *args, **kwargs: {})
    monkeypatch.setattr(page_render, "course_page_html", lambda *args, **kwargs: "<html/>")
    monkeypatch.setattr(page_render, "validate_local_page", lambda *args, **kwargs: {"passed": True})

    output = course_visuals.prepare_course_storyboard(
        storyboard_path,
        output_dir=tmp_path / "runs",
        model="offline-test",
        review_model="offline-test",
        theme="bright",
        browser="chromium",
        source_path=source_path,
        review_policy="development",
        rebuild_page_from_source=True,
        auto_visual_enhancement=True,
        max_generated_visuals=1,
    )

    assert output.is_file()
    assert called["selection"][0][2] is None
    assert called["selection"][1]["enable_visual_generation"] is True
    assert called["selection"][1]["max_generated_visuals"] == 1
    document = json.loads(output.read_text(encoding="utf-8"))
    assert [e["id"] for e in document["segments"][0]["elements"]] == ["heading", "body"]


@pytest.mark.parametrize('existing', [False, True])
def test_auto_visual_insert_preserves_existing_page_ids_content_and_events(tmp_path, existing):
    segment = _segment()
    original = json.loads(json.dumps(segment))
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="240" viewBox="0 0 600 240"><text x="20" y="80">input to output</text></svg>'
    asset_path = tmp_path / "input-output.svg"
    asset_path.write_bytes(svg)
    sha = hashlib.sha256(svg).hexdigest()
    review = {"verdict": "ACCEPT", "visual_summary": "input leads to output", "reason": "matches proposition"}
    review_path = _write_json(tmp_path / "review.json", review)
    selection = {
        "pages": {
            "lesson-new-1": {
                "decisions": [{"action": "generate", "narration_proposition_id": "p1"}],
                "propositions": [{"id": "p1", "text": "输入经过处理后得到输出。"}],
                "assets": [{
                    "action": "generate", "asset_id": "generated-p1", "element_id": "visual-generated-p1",
                    "local_path": str(asset_path), "sha256": sha, "review_path": str(review_path),
                    "review": review, "proposition_ids": ["p1"],
                }],
                "requires_generation": True, "decision_status": "READY_WITH_PENDING_DECISIONS",
            }
        }
    }
    if existing:
        segment['elements'].append({'id': 'textbook-image', 'type': 'image', 'src': asset_path.name})
        original = json.loads(json.dumps(segment))
    pages = [segment]
    images = course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / "prepared", model="offline-test", theme="bright",
        review_policy="development", failure_policy="fallback", asset_selection=selection,
        preserve_existing_pages=True, source_image_dir=tmp_path,
    )

    page = pages[0]
    if existing:
        assert pages[0]['elements'][2]['id'] == 'textbook-image'
        assert len(pages[0]['elements']) == len(original['elements'])
        assert pages[0]['timeline'] == original['timeline']
        assert pages[0]['visual_review']['status'] == 'ASSETS_REUSED_PENDING_PAGE_REVIEW'
        assert pages[0]['visual_review']['inserted_asset_count'] == 0
        assert pages[0]['visual_review']['reused_asset_count'] == 1
        return
    assert images["lesson-new-1:visual-generated-p1"] == str(asset_path)
    assert [(e["id"], e.get("text")) for e in page["elements"][:2]] == [
        (e["id"], e.get("text")) for e in original["elements"]
    ]
    assert page["timeline"] == original["timeline"]
    assert page["animations"] == original["animations"]
    assert page["elements"][2]["id"] == "visual-generated-p1"
    assert page["local_visual_operations"][-1]["operation"] == "insert"
    assert page["visual_review"]["status"] == "ASSETS_INSERTED_PENDING_PAGE_REVIEW"
    assert list((tmp_path / "prepared").glob("course-pages-*/page-001/checkpoint.json"))


@pytest.mark.parametrize('layout_passes', [True, False])
def test_generated_svg_route_uses_local_composer_and_narration_binding(tmp_path, monkeypatch, layout_passes):
    segment = _segment()
    original = json.loads(json.dumps(segment))
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="240" viewBox="0 0 600 240"><text x="20" y="80">input to output</text></svg>'
    asset_path = tmp_path / "input-output.svg"
    asset_path.write_bytes(svg)
    review = {"verdict": "ACCEPT", "visual_summary": "Input leads to output", "reason": "matches proposition"}
    review_path = _write_json(tmp_path / "review.json", review)
    calls = {}

    def fake_compose(page, **kwargs):
        calls.update(kwargs)
        if not layout_passes:
            raise ValueError('local composition needs layout adjustment or page split; engineering fixture')
        element = {
            "id": kwargs["element_id"], "type": "image", "src": "input-output.svg",
            "description": "Input leads to output",
            "visual_asset_sha256": hashlib.sha256(svg).hexdigest(),
            **kwargs["element_metadata"],
        }
        course_visuals.apply_local_visual_plan(page, element)
        image_key = f"{page['id']}:{element['id']}"
        return {"images": {image_key: str(asset_path)}, "storyboard": "bundle/storyboard.json",
                "layout": {"passed": True}}

    monkeypatch.setattr(course_visuals, "compose_local_visual", fake_compose)
    selection = {"pages": {"lesson-new-1": {
        "decisions": [{"action": "generate", "narration_proposition_id": "p1"}],
        "propositions": [{"id": "p1", "text": "输入经过处理后得到输出。",
                          "source_refs": [{"source_unit_id": "source-1"}]}],
        "assets": [{
            "action": "generate", "asset_id": "generated-p1", "element_id": "auto-visual-p1",
            "local_path": str(asset_path), "sha256": hashlib.sha256(svg).hexdigest(),
            "review_path": str(review_path), "review": review,
            "proposition_ids": ["p1"], "visual_revision_path": str(tmp_path / "revision"),
        }],
        "requires_generation": False, "decision_status": "ASSETS_ACCEPTED_PENDING_PAGE_REVIEW",
    }}}
    pages = [segment]

    images = course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / "prepared", model="offline-test", theme="bright",
        browser="chromium", review_policy="development", asset_selection=selection,
        preserve_existing_pages=True,
    )

    if not layout_passes:
        assert pages[0]['elements'] == original['elements']
        assert pages[0]['timeline'] == original['timeline']
        assert pages[0]['visual_review']['composition_pending'] is True
        assert pages[0]['visual_review']['generation_pending'] is False
        assert pages[0]['visual_review']['visual_decision_pending'] is False
        assert pages[0]['visual_review']['inserted_asset_count'] == 0
        assert selection['pages']['lesson-new-1']['assets']  # asset approval survives layout failure
        return
    assert pages[0]['visual_review']['inserted_asset_count'] == 1
    assert "lesson-new-1:auto-visual-p1" in images
    assert pages[0]["elements"][-1]["visual_brief_proposition"] == "输入经过处理后得到输出。"
    assert pages[0]["elements"][-1]["visual_source_refs"] == [{"source_unit_id": "source-1"}]
    assert pages[0]["timeline"] == original["timeline"]
    assert pages[0]["animations"] == original["animations"]
    assert calls["theme"] == "bright"
    assert calls["element_metadata"]["visual_brief_proposition"] == "输入经过处理后得到输出。"


def test_auto_enhancement_is_development_only_and_requires_source(tmp_path):
    storyboard_path = _write_json(
        tmp_path / "storyboard.json", {"lesson_title": "x", "segments": [_segment()], "metadata": {}}
    )
    with pytest.raises(ValueError, match="development-only"):
        course_visuals.prepare_course_storyboard(
            storyboard_path, output_dir=tmp_path / "strict", model="x", theme="bright",
            browser="chromium", review_policy="strict", auto_visual_enhancement=True,
            source_path=tmp_path / "source.txt",
        )
    with pytest.raises(ValueError, match="requires the source textbook text"):
        course_visuals.prepare_course_storyboard(
            storyboard_path, output_dir=tmp_path / "no-source", model="x", theme="bright",
            browser="chromium", review_policy="development", auto_visual_enhancement=True,
        )


@pytest.mark.parametrize('policy', ['strict', 'development'])
@pytest.mark.parametrize('remaining', [None, 'retrieve', 'source'])
def test_generate_decision_compiles_reviews_and_binds_stable_element_id(tmp_path, monkeypatch, remaining, policy):
    source_path = tmp_path / "textbook.txt"
    source_path.write_text("输入经过处理后得到输出。", encoding="utf-8")
    storyboard_path = _write_json(
        tmp_path / "storyboard.json", {"segments": [_segment()], "metadata": {}}
    )
    evidence_path = _write_json(tmp_path / "source_evidence.json", {
        "source_units": [{"id": "source-1", "text": "输入经过处理后得到输出。"}],
    })
    graph_path = _write_json(tmp_path / "graph.json", {
        "source_evidence_path": str(evidence_path),
        "narration_propositions": [{
            "id": "p1", "segment_id": "lesson-new-1", "text": "输入经过处理后得到输出。",
            "source_refs": [{"source_unit_id": "source-1"}],
        }]
    })
    decisions_path = _write_json(tmp_path / "decisions.json", {
        "decisions": [{
            "narration_proposition_id": "p1", "action": "generate",
            "decision_state": "DECIDED", "abstain": False, "uncertain": False,
            "generation_prompt": "Show input, processing, and output.",
        }]
    })
    selection = {"pages": {"lesson-new-1": {
        "decisions": json.loads(decisions_path.read_text(encoding="utf-8"))["decisions"],
        "propositions": [{"id": "p1", "text": "输入经过处理后得到输出。", "source_refs": ["source-1"]}],
        "assets": [], "requires_generation": True,
        "unresolved_propositions": ["p1"], "decision_status": "PENDING_DECISION",
    }}}
    row = selection['pages']['lesson-new-1']
    if remaining == 'retrieve':
        row['decisions'].append({'action': 'retrieve', 'narration_proposition_id': 'p2'})
        row['unresolved_propositions'].append('p2')
    if remaining == 'source':
        row['source_grounding_rejections'] = [{'reason': 'unverified source'}]
    generated_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="240" viewBox="0 0 600 240"><text x="20" y="80">input - process - output</text></svg>'
    asset_id = "auto-001-p1"
    revision = tmp_path / "agent" / "revision-001"
    asset_path = revision / "compiled" / "assets" / "input-output.svg"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(generated_svg)
    _write_json(revision / "source.json", {"source_text": "教材依据：输入经过处理后得到输出。"})
    review = {"verdict": "ACCEPT" if policy == "strict" else "REVISE", "visual_summary": "Three connected steps", "reason": "matches source"}
    _write_json(revision / "review.json", review)
    _write_json(revision / "revision.json", {"geometry": [], "page_plan": {}})
    run_path = _write_json(revision.parent / "run.json", {
        "status": "MODEL_REVIEWED_PENDING_HUMAN" if policy == "strict" else "DRAFT_WITH_WARNINGS_PENDING_HUMAN", "accepted_revision": str(revision) if policy == "strict" else None, "usable_revision": str(revision),
    })
    calls = {}

    def fake_agent(source, goal, output_dir, **kwargs):
        assert kwargs["page_context"] is None  # Asset generation cannot replan the old page.
        assert kwargs['page_capacity'] == {'scope': 'offline-unit-capacity'}
        calls.update(source=source, goal=goal, output_dir=output_dir, kwargs=kwargs)
        return run_path

    monkeypatch.setattr(course_visuals, "run_visual_agent", fake_agent)
    monkeypatch.setattr(course_visuals, '_measure_generation_capacity',
                        lambda *a, **kw: {'scope': 'offline-unit-capacity'})
    monkeypatch.setattr(course_visuals, "verify_revision", lambda path: None)
    monkeypatch.setattr(course_visuals, "execution_assets", lambda path: [{
        "id": asset_id, "filename": asset_path.name,
        "sha256": hashlib.sha256(generated_svg).hexdigest(),
        "spec": {"kind": "flow", "title": "Input to output", "items": ["input", "process", "output"]},
    }])
    monkeypatch.setattr(course_visuals, "review_disposition", lambda *args, **kwargs: {"strict_approved": policy == "strict", "draft_usable": True})
    materialized_dir = tmp_path / "materialized"
    materialized_dir.mkdir()

    course_visuals._materialize_decided_visuals(
        selection=selection, storyboard_path=storyboard_path, source_path=source_path,
        graph_path=graph_path, decisions_path=decisions_path, output_dir=materialized_dir,
        model="offline-test", review_model="offline-test", max_generated_visuals=1, review_policy=policy,
    )

    assert selection["pages"]["lesson-new-1"]["assets"], {
        "results": selection["pages"]["lesson-new-1"].get("generation_results"),
        "failures": selection.get("generation_failures"), "calls": bool(calls),
    }
    asset = selection["pages"]["lesson-new-1"]["assets"][0]
    assert asset["element_id"] == "auto-visual-" + hashlib.sha256(b"p1").hexdigest()[:16]
    assert asset["sha256"] == hashlib.sha256(generated_svg).hexdigest()
    assert asset["source_refs"] == [{"source_unit_id": "source-1"}]
    assert row['requires_generation'] is bool(remaining)
    assert row['generation_pending_propositions'] == []
    if remaining == 'retrieve':
        assert row['unresolved_propositions'] == ['p2']
    if remaining == 'source':
        assert row['decision_status'] == 'PENDING_SOURCE_GROUNDING'
    # Replaying a saved accepted selection must never generate its asset again.
    monkeypatch.setattr(course_visuals, 'run_visual_agent', lambda *a, **kw: pytest.fail('duplicate generation'))
    course_visuals._materialize_decided_visuals(
        selection=selection, storyboard_path=storyboard_path, source_path=source_path,
        graph_path=graph_path, decisions_path=decisions_path, output_dir=materialized_dir,
        model='offline-test', review_model='offline-test', max_generated_visuals=1, review_policy=policy,
    )
    assert len(row['assets']) == 1
    assert selection["pages"]["lesson-new-1"]["generation_results"]["p1"] == (
        "VISUAL_AGENT_STRICT_ACCEPTED_PENDING_PAGE_REVIEW" if policy == "strict" else "VISUAL_AGENT_DRAFT_PENDING_PAGE_REVIEW"
    )
    assert calls["kwargs"]["max_iterations"] == 1
    assert calls["kwargs"]["review_policy"] == policy
    assert calls["kwargs"]["max_visuals"] == 1
    assert "输入经过处理后得到输出。" in calls["source"]


def test_generation_failure_does_not_erase_retrieval_or_source_pending():
    row={'decisions': [{'action': 'generate', 'narration_proposition_id': 'g'}],
         'unresolved_propositions': ['r', 'g'], 'generation_pending_propositions': ['g'],
         'source_grounding_rejections': [{'reason': 'unverified'}]}
    selection={'pages': {'p': row}}
    course_visuals._record_generation_failure(selection, row['decisions'], stage='visual-agent', error=ValueError('rejected'))
    assert row['unresolved_propositions'] == ['g', 'r']
    assert row['generation_pending_propositions'] == ['g']
    assert row['source_grounding_rejections']


def test_auto_decision_failure_preserves_page_and_records_fallback(tmp_path, monkeypatch):
    import textbook2video.pipeline.visual_page_render as page_render

    original = {'segments': [_segment()], 'metadata': {}}
    storyboard = _write_json(tmp_path / 'source_storyboard.json', original)
    source = tmp_path / 'source.txt'
    source.write_text(original['segments'][0]['narration'], encoding='utf-8')

    def failed(*args, **kwargs):
        raise ValueError('proposition source coverage incomplete')

    monkeypatch.setattr(course_visuals, 'prepare_course_asset_selection', failed)
    monkeypatch.setattr(page_render, 'course_page_html', lambda *a, **k: '<html/>')
    monkeypatch.setattr(page_render, 'validate_local_page', lambda *a, **k: {'passed': True})
    saved = course_visuals.prepare_course_storyboard(
        storyboard, output_dir=tmp_path / 'run', model='offline-test', theme='bright',
        source_path=source, review_policy='development', auto_visual_enhancement=True,
        browser='msedge')
    result = json.loads(saved.read_text(encoding='utf-8'))
    for key in ('elements', 'narration', 'timeline', 'animations'):
        assert result['segments'][0][key] == original['segments'][0][key]
    failure = result['metadata']['visual_enhancement_failures'][0]
    assert failure['status'] == 'FALLBACK_ORIGINAL_ENHANCEMENT_FAILED'
    assert failure['error_type'] == 'ValueError'
    assert 'source coverage incomplete' in failure['error']
