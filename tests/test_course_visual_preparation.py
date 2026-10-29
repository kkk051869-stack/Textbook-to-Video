from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from visual_plan_test_utils import model_plan_json

from textbook2video.pipeline import course_visuals, orchestrator
from textbook2video.research import visual_tools as tools

SOURCE = "采集数据。处理数据。"


@pytest.fixture(autouse=True)
def offline_review_health(monkeypatch):
    monkeypatch.setattr(course_visuals, "check_review_health", lambda *a, **kw: None)


def approved_panels(tmp_path, *, spans=("采集数据。", "处理数据。")):
    specs = [
        {
            "id": f"panel-{i}",
            "schema_version": "teaching-visual-v2",
            "kind": "flow",
            "title": f"阶段{i}",
            "teaching_goal": "理解数据处理",
            "narration_span": span,
            "nodes": [
                {"id": "a", "label": "输入", "evidence": SOURCE},
                {"id": "b", "label": "输出", "evidence": SOURCE},
            ],
            "edges": [{"source": "a", "target": "b", "evidence": SOURCE}],
        }
        for i, span in enumerate(spans, 1)
    ]
    directory = tmp_path / "approved"
    tools.dispatch("create", {"visuals": specs}, source=SOURCE, output_dir=directory, render=False)
    report = tools._save_review(
        directory,
        json.dumps(
            {
                "verdict": "ACCEPT",
                "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
                "issues": [],
                "reason": "fixture review",
            }
        ),
        [],
        model="test",
        has_images=True,
    )
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "status": "MODEL_REVIEWED_PENDING_HUMAN",
                "accepted_revision": str(directory),
                "history": [{"revision": str(directory), "review_sha256": tools.digest(report)}],
            }
        ),
        encoding="utf-8",
    )
    return run_path


def board():
    return {
        "total_slides": 1,
        "segments": [
            {
                "id": "lesson-part",
                "narration": SOURCE,
                "audio_duration_sec": 10,
                "visual_type": "process",
                "elements": [{"id": "h", "type": "heading", "text": "数据处理"}],
                "timeline": [{"target": "h", "at_sec": 2}],
            }
        ],
    }


@pytest.mark.parametrize('action,verdict', [
    ('none', 'ACCEPT'), ('reuse', 'ACCEPT'), ('retrieve', 'ACCEPT'),
    ('reuse', 'REJECT'), ('retrieve', 'NO_MATCH')])
def test_ordinary_course_consumes_existing_acquisition_before_generation(monkeypatch, tmp_path, action, verdict):
    from textbook2video.research import proposition_graph, visual_decision
    from textbook2video.llm import client

    data = board()
    images = tmp_path / 'images'
    images.mkdir()
    image = images / 'source.png'
    image.write_bytes(b'pixels')
    data['metadata'] = {'available_images': [{'id': 'fig-1', 'filename': image.name}]}
    data['segments'][0]['elements'].append({
        'id': 'old-image', 'type': 'image', 'src': image.name, 'source_image_id': 'fig-1'})
    source, path, catalog = tmp_path/'source.md', tmp_path/'storyboard.json', tmp_path/'catalog.json'
    source.write_text(SOURCE, encoding='utf-8')
    path.write_text(json.dumps(data), encoding='utf-8')
    catalog.write_text(json.dumps({'assets': [] if verdict == 'NO_MATCH' else [
        {'id': 'external', 'path': str(image), 'title': '数据处理', 'license': 'CC0'}]}), encoding='utf-8')

    def graph(**kwargs):
        import hashlib
        result = kwargs['output_path']
        result.write_text(json.dumps({
            'raw_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'storyboard_path': str(path), 'source_evidence_path': str(kwargs['source_evidence_path']),
            'narration_propositions': [
            {'id': 'p1', 'segment_id': 'lesson-part', 'text': SOURCE,
             'span': {'start': 0, 'end': len(SOURCE)}}]}), encoding='utf-8')
        return result

    def decision(**kwargs):
        result = kwargs['output_path']
        result.write_text(json.dumps({
            'storyboard_path': str(path), 'proposition_graph_path': str(kwargs['proposition_graph_path']),
            'source_evidence_path': str(kwargs['source_evidence_path']), 'decisions': [{
            'narration_proposition_id': 'p1', 'action': action,
            'source_image_id': 'fig-1', 'retrieval_query': '数据处理'}]}), encoding='utf-8')
        return result

    monkeypatch.setattr(proposition_graph, 'build_proposition_graph', graph)
    monkeypatch.setattr(visual_decision, 'decide_visual_support', decision)
    monkeypatch.setattr(client, 'chat_with_images', lambda *a, **kw: json.dumps({
        'verdict': verdict, 'visual_summary': '数据处理示意图', 'reason': 'mock pixel review'}))
    selection = course_visuals.prepare_course_asset_selection(
        path, source, catalog, tmp_path/'selection', model='test', review_model='test')
    if verdict != 'ACCEPT':
        assert selection['pages']['lesson-part']['requires_generation'] is True
        assert selection['pages']['lesson-part']['assets'] == []
        return
    assert selection['pages']['lesson-part']['requires_generation'] is False
    monkeypatch.setattr(course_visuals, 'run_visual_agent',
                        lambda *a, **kw: pytest.fail('selected assets must not be redrawn'))
    monkeypatch.setattr(course_visuals, 'prepare_course_asset_selection', lambda *a, **kw: selection)
    result = course_visuals.prepare_course_storyboard(
        path, output_dir=tmp_path/'course', model='test', theme='dark-blue-academic',
        browser='msedge', source_path=source, retrieval_catalog_path=catalog,
        review_policy='development')
    final = json.loads(result.read_text(encoding='utf-8'))
    assert final['segments'][0]['narration'] == SOURCE
    assert path.read_text(encoding='utf-8') == json.dumps(data)
    actual = [e for e in final['segments'][0]['elements'] if e['type'] == 'image']
    assert len(actual) == (0 if action == 'none' else 1)
    for element in actual:
        assert (result.parent/'images'/element['src']).read_bytes() == b'pixels'
        assert element['proposition_ids'] == ['p1']
    report = final['metadata']['course_visuals']
    assert report['reviewed_page_count'] == 0
    assert report['fallback_page_count'] == 0
    assert report['asset_selected_page_count'] == 1
    assert report['status'] == 'ASSET_SELECTION_PENDING_PAGE_REVIEW'
    source.write_text('不同教材，但旁白保持不变。', encoding='utf-8')
    with pytest.raises(ValueError, match='source hash mismatch'):
        course_visuals._review_course_asset_selection(
            path, source, tmp_path/'wrong-source', tmp_path/'selection/proposition_graph.json',
            tmp_path/'selection/visual_decisions.json', tmp_path/'selection/acquisition/visual_acquisition.json',
            review_model='test')


def test_acquisition_cannot_bypass_strict_page_review(tmp_path, monkeypatch):
    monkeypatch.setattr(course_visuals, 'prepare_course_asset_selection',
                        lambda *a, **kw: pytest.fail('must reject before API work'))
    with pytest.raises(ValueError, match='requires development'):
        course_visuals.prepare_course_storyboard(
            tmp_path/'missing.json', output_dir=tmp_path/'out', model='test',
            theme='dark-blue-academic', browser='msedge', review_policy='strict',
            retrieval_catalog_path=tmp_path/'catalog.json')
    with pytest.raises(ValueError, match='requires development'):
        course_visuals.generate_course_visuals(
            board()['segments'], output_dir=tmp_path/'direct', model='test',
            theme='dark-blue-academic', review_policy='strict', asset_selection={'pages': {}})


def test_mixed_page_reuses_covered_span_and_only_generates_missing_span(monkeypatch, tmp_path):
    import hashlib

    data = board()
    path, source = tmp_path/'storyboard.json', tmp_path/'source.md'
    path.write_text(json.dumps(data), encoding='utf-8')
    source.write_text(SOURCE, encoding='utf-8')
    image = tmp_path/'approved.png'
    image.write_bytes(b'approved fixture pixels')
    report = {'verdict': 'ACCEPT', 'reason': 'fixture review', 'visual_summary': '采集数据'}
    review_path = tmp_path/'review.json'
    review_path.write_text(json.dumps(report), encoding='utf-8')
    boundary = SOURCE.index('处理')
    props = [{'id': f'p{i}', 'text': SOURCE[a:b], 'span': {'start': a, 'end': b}}
             for i, (a, b) in enumerate([(0, boundary), (boundary, len(SOURCE))], 1)]
    selection = {'pages': {'lesson-part': {
        'requires_generation': True, 'propositions': props,
        'decisions': [{'narration_proposition_id': 'p1', 'action': 'reuse'},
                      {'narration_proposition_id': 'p2', 'action': 'generate'}],
        'assets': [{'local_path': str(image), 'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                    'proposition_ids': ['p1'], 'review': report, 'review_path': str(review_path)}]}}}
    generated = []
    def generate(segments, **kwargs):
        generated.extend(s['narration'] for s in segments)
        return {}
    monkeypatch.setattr(course_visuals, 'prepare_course_asset_selection', lambda *a, **kw: selection)
    monkeypatch.setattr(course_visuals, '_generate_course_visuals_strict', generate)
    output = course_visuals.prepare_course_storyboard(
        path, output_dir=tmp_path/'out', model='test', theme='dark-blue-academic',
        browser='msedge', source_path=source, retrieval_catalog_path=tmp_path/'catalog.json',
        review_policy='development')
    result = json.loads(output.read_text(encoding='utf-8'))
    assert generated == [SOURCE[boundary:]]
    assert len(result['segments']) == 2
    assert ''.join(s['narration'] for s in result['segments']) == SOURCE
    assert result['segments'][0]['visual_origin_segment_id'] == 'lesson-part'
    assert any(e['type'] == 'image' for e in result['segments'][0]['elements'])
    assert path.read_text(encoding='utf-8') == json.dumps(data)
    assert selection['pages'].keys() == {'lesson-part'}


def test_mixed_split_abstains_without_a_complete_exact_partition():
    segment = board()['segments'][0]
    selection = {'pages': {'lesson-part': {
        'requires_generation': True, 'assets': [{'proposition_ids': ['p1']}], 'decisions': [],
        'propositions': [{'id': 'p1', 'span': {'start': 1, 'end': 2}, 'text': SOURCE[1:2]}]}}}
    parts, _ = course_visuals._split_mixed_acquisition_pages([segment], selection)
    assert parts == [segment]


def test_development_fallback_is_transactional_and_other_pages_still_enhance(monkeypatch, tmp_path):
    run = approved_panels(tmp_path)
    calls = []

    def planner(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("private transport details must not enter report")
        return run

    monkeypatch.setattr(course_visuals, "run_visual_agent", planner)
    data = board()
    first = data["segments"][0]
    first["elements"].extend([
        {"id": "body", "type": "text", "text": "原分镜正文"},
        {"id": "intent", "type": "image", "description": "旧配图意图"},
    ])
    data["segments"].append(dict(deepcopy(first), id="second"))
    source = tmp_path / "storyboard.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    raw = tmp_path / "source.md"
    raw.write_text(SOURCE, encoding="utf-8")
    path = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge",
        source_path=raw, review_policy="development",
    )
    result = json.loads(path.read_text(encoding="utf-8"))
    fallback, *enhanced = result["segments"]
    assert len(calls) == 2 and len(enhanced) == 2
    assert fallback["elements"] == first["elements"][:-1]
    assert fallback["timeline"] == [] and fallback["animations"] == []
    assert "audio_duration_sec" not in fallback
    assert fallback["visual_review"]["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED"
    assert "private transport details" not in json.dumps(result)
    assert len(fallback["visual_review"]["omitted_image_intents"]) == 1
    assert "".join(s["narration"] for s in result["segments"]) == SOURCE * 2
    report = result["metadata"]["course_visuals"]
    assert report["fallback_page_count"] == 1 and report["reviewed_page_count"] == 2
    assert report["status"] == "COMPLETED_WITH_ENHANCEMENT_FALLBACKS_PENDING_HUMAN"
    assert report["page_strategy"] == "mixed-with-original-fallbacks"
    assert len(report["assets"]) == 2
    assert len(list(path.parent.glob("course-pages-*/page-*/checkpoint.json"))) == 2
    assert json.loads(source.read_text(encoding="utf-8")) == data


@pytest.mark.parametrize("policy", ["strict", "development"])
def test_strict_or_stop_does_not_silently_fallback(monkeypatch, tmp_path, policy):
    def fail(*args, **kwargs):
        raise TimeoutError("offline")

    monkeypatch.setattr(course_visuals, "run_visual_agent", fail)
    segments = board()["segments"]
    before = deepcopy(segments)
    with pytest.raises(course_visuals.EnhancementUnavailable):
        course_visuals.generate_course_visuals(
            segments, output_dir=tmp_path, model="test", theme="bright", review_policy=policy,
        )
    assert segments == before


def test_fallback_never_swallows_integrity_failure(monkeypatch, tmp_path):
    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)

    def corrupt(*args, **kwargs):
        raise ValueError("compiled asset hash drift")

    monkeypatch.setattr(course_visuals, "verify_revision", corrupt)
    segments = board()["segments"]
    before = deepcopy(segments)
    with pytest.raises(ValueError, match="hash drift"):
        course_visuals.generate_course_visuals(
            segments, output_dir=tmp_path, model="test", theme="bright",
            review_policy="development", failure_policy="fallback",
        )
    assert segments == before


def test_fallback_forbidden_for_strict_before_any_planning(tmp_path):
    with pytest.raises(ValueError, match="requires development"):
        course_visuals.generate_course_visuals(
            board()["segments"], output_dir=tmp_path, model="test", theme="bright",
            failure_policy="fallback",
        )


@pytest.mark.parametrize("exception_name", [
    "Timeout", "APIConnectionError", "RateLimitError", "ServiceUnavailableError",
])
def test_real_gateway_exception_types_reach_fallback(monkeypatch, tmp_path, exception_name):
    from litellm import exceptions

    def fail(*args, **kwargs):
        raise getattr(exceptions, exception_name)(
            message="offline", model="test", llm_provider="openai"
        )

    monkeypatch.setattr(course_visuals, "run_visual_agent", fail)
    segments = board()["segments"]
    course_visuals.generate_course_visuals(
        segments, output_dir=tmp_path, model="test", theme="bright",
        review_policy="development", failure_policy="fallback",
    )
    assert segments[0]["visual_review"]["status"] == "FALLBACK_ORIGINAL_NOT_REVIEWED"


def test_integrity_failure_inside_agent_is_not_repairable_or_fallback(monkeypatch, tmp_path):
    fixture = approved_panels(tmp_path)
    revision = Path(json.loads(fixture.read_text(encoding="utf-8"))["accepted_revision"])
    specs = json.loads((revision / "specs.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: model_plan_json({
        "tool": "create", "arguments": {"visuals": specs},
    }))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])
    checked = []

    def damaged_review(directory, **kwargs):
        checked.append(directory)
        (directory / "source.json").write_text('{}', encoding="utf-8")
        tools.verify_revision(directory)

    monkeypatch.setattr(tools, "review_revision", damaged_review)
    segments = board()["segments"]
    before = deepcopy(segments)
    with pytest.raises(tools.RevisionIntegrityError, match="integrity failure"):
        course_visuals.generate_course_visuals(
            segments, output_dir=tmp_path / "real-agent", model="test", theme="bright",
            source_text=SOURCE, rebuild_timing_before_tts=True,
            rebuild_page_from_source=True, review_policy="development", failure_policy="fallback",
        )
    assert len(checked) == 1 and segments == before
    run = next((tmp_path / "real-agent").rglob("run.json"))
    assert json.loads(run.read_text(encoding="utf-8"))["error_type"] == "RevisionIntegrityError"


def test_split_panels_are_actual_pages_before_tts_and_preserve_every_word(monkeypatch, tmp_path):
    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    segments = board()["segments"]
    original = deepcopy(segments)
    images = course_visuals.generate_course_visuals(
        segments, output_dir=tmp_path, model="test", theme="bright", rebuild_timing_before_tts=True
    )
    assert len(segments) == 2 and len(images) == 2
    assert "".join(s["narration"] for s in segments) == SOURCE
    assert len({s["id"] for s in segments}) == 2
    for child in segments:
        assert child["timeline"] == [] and child["animations"] == []
        assert child["visual_timing_rebuild"]["original_timeline"] == original[0]["timeline"]
        assert child["visual_origin_segment_id"] == "lesson-part"


def test_a_split_cannot_omit_or_rewrite_narration(monkeypatch, tmp_path):
    run = approved_panels(tmp_path, spans=("采集数据。", "处理。"))
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    with pytest.raises(ValueError, match="partition narration verbatim"):
        course_visuals.generate_course_visuals(
            board()["segments"],
            output_dir=tmp_path,
            model="test",
            theme="bright",
            rebuild_timing_before_tts=True,
        )


def test_source_first_rebuild_archives_legacy_instead_of_forcing_its_claims(monkeypatch, tmp_path):
    run = approved_panels(tmp_path)
    seen = []

    def plan(source, goal, directory, **kwargs):
        seen.append((source, goal, kwargs))
        assert kwargs["page_context"] == []
        assert kwargs["narration_text"] == SOURCE
        return run

    monkeypatch.setattr(course_visuals, "run_visual_agent", plan)
    original = board()
    original["segments"][0]["elements"].append({
        "id": "obsolete", "type": "flow_step", "steps": ["unsupported broadcast step"]
    })
    source_board = tmp_path / "storyboard.json"
    source_board.write_text(json.dumps(original), encoding="utf-8")
    raw = tmp_path / "raw.txt"
    raw.write_text(SOURCE, encoding="utf-8")
    output = course_visuals.prepare_course_storyboard(
        source_board, output_dir=tmp_path, model="test", theme="bright", browser="msedge",
        source_path=raw,
    )
    rebuilt = json.loads(output.read_text(encoding="utf-8"))
    assert seen[0][0] == SOURCE
    assert "".join(s["narration"] for s in rebuilt["segments"]) == SOURCE
    assert json.loads(source_board.read_text(encoding="utf-8")) == original
    for segment in rebuilt["segments"]:
        archived = segment["visual_timing_rebuild"]
        assert archived["original_elements"] == original["segments"][0]["elements"]
        assert archived["original_timeline"] == original["segments"][0]["timeline"]
        assert archived["page_strategy"] == "source-narration-rebuild"
        assert all(e["id"] != "obsolete" for e in segment["elements"])
    assert rebuilt["metadata"]["course_visuals"]["page_strategy"] == "source-narration-rebuild"


def test_title_only_course_cannot_claim_source_rebuild_or_model_review(monkeypatch, tmp_path):
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: pytest.fail("no API"))
    title = {"id": "title", "visual_type": "title", "narration": "Opening",
             "elements": [], "visual_review": {"status": "OLD_REVIEW_NOT_THIS_RUN"}}
    source = tmp_path / "title.json"
    source.write_text(json.dumps({"segments": [title]}), encoding="utf-8")
    result = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge"
    )
    report = json.loads(result.read_text(encoding="utf-8"))["metadata"]["course_visuals"]
    assert report["status"] == "NOT_REVIEWED_NO_CONTENT_PAGES"
    assert report["page_strategy"] == "no-content-pages"
    assert report["requested_page_strategy"] == "source-narration-rebuild"
    assert report["source_scope"] == "not-used-no-content-pages"
    assert report["reviewed_page_count"] == 0 and report["page_reviews"] == []
    assert report["skipped_pages"][0]["segment_id"] == "title"


def test_source_first_uses_actual_agent_dispatch_without_model_replacement_plan(
    monkeypatch, tmp_path
):
    # Transport/reviewer mocked; actual planner loop, dispatch, sealed assets,
    # adapter consumption and page split execute together.
    fixture_run = approved_panels(tmp_path)
    fixture = json.loads(fixture_run.read_text(encoding="utf-8"))
    specs = json.loads((
        Path(fixture["accepted_revision"]) / "specs.json"
    ).read_text(encoding="utf-8"))
    monkeypatch.setattr(tools, "chat_with_system", lambda *a, **kw: model_plan_json({
        "tool": "create", "arguments": {"visuals": specs}
    }))
    monkeypatch.setattr(tools, "preview_revision", lambda *a, **kw: [])

    def reviewer(directory, **kwargs):
        return tools._save_review(directory, json.dumps({
            "verdict": "ACCEPT", "issues": [], "reason": "Fixture source/complete narration review",
            "scores": dict.fromkeys(["accuracy", "relevance", "readability", "composition"], 4),
        }), [], model="test", has_images=True)

    monkeypatch.setattr(tools, "review_revision", reviewer)
    segments = board()["segments"]
    segments[0]["elements"].append({"id": "old", "type": "text", "text": "obsolete claim"})
    images = course_visuals.generate_course_visuals(
        segments, output_dir=tmp_path / "actual", model="test", theme="bright", source_text=SOURCE,
        rebuild_timing_before_tts=True, rebuild_page_from_source=True,
    )
    assert len(images) == 2 and "".join(s["narration"] for s in segments) == SOURCE
    assert all(s["visual_review"]["status"] == "MODEL_REVIEWED_PENDING_HUMAN" for s in segments)


@pytest.mark.parametrize("before_tts,text", [(False, SOURCE), (True, None)])
def test_source_first_rebuild_cannot_use_narration_as_textbook_or_old_audio(
    monkeypatch, tmp_path, before_tts, text
):
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: pytest.fail("no API"))
    segments = board()["segments"]
    before = deepcopy(segments)
    with pytest.raises(ValueError, match="requires textbook text"):
        course_visuals.generate_course_visuals(
            segments, output_dir=tmp_path, model="test", theme="bright",
            source_text=text, rebuild_timing_before_tts=before_tts, rebuild_page_from_source=True,
        )
    assert segments == before


def test_prepared_storyboard_and_images_are_new_artifacts_not_overwritten_input(
    monkeypatch, tmp_path
):
    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board(), ensure_ascii=False), encoding="utf-8")
    original = source.read_bytes()
    raw = tmp_path / "textbook.txt"
    raw.write_text(SOURCE, encoding="utf-8")
    output = course_visuals.prepare_course_storyboard(
        source,
        output_dir=tmp_path,
        model="test",
        theme="bright",
        browser="msedge",
        source_path=raw,
        source_scope="textbook",
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert source.read_bytes() == original and output != source
    assert result["total_slides"] == 2
    assert result["metadata"]["course_visuals"]["source_scope"] == "textbook"
    review_report = json.loads(
        (output.parent / "visual-review-report.json").read_text(encoding="utf-8")
    )
    assert review_report == result["metadata"]["course_visuals"]
    assert review_report["review_policy"] == "strict"
    assert review_report["human_review"] == "NOT_REVIEWED"
    for segment in result["segments"]:
        picture = next(e for e in segment["elements"] if e["type"] == "image")
        assert (output.parent / "images" / picture["src"]).is_file()


def test_production_prepares_visuals_before_measured_audio_alignment(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board()), encoding="utf-8")
    planned = tmp_path / "planned.json"
    planned.write_text(json.dumps(board()), encoding="utf-8")
    calls = []

    def prepare(*args, **kwargs):
        assert kwargs["review_policy"] == "development"
        calls.append("visuals")
        return planned

    def tts(data, path, audio_dir, **kwargs):
        assert calls == ["visuals"] and path == planned
        assert data["segments"][0]["narration"] == SOURCE
        calls.append("measured_tts")
        return [7.125]

    monkeypatch.setattr(course_visuals, "prepare_course_storyboard", prepare)
    monkeypatch.setattr(orchestrator, "run_tts", tts)
    arts = orchestrator.Artifacts(
        stem="lesson",
        title="数据处理",
        raw_path=tmp_path / "raw.txt",
        script_path=tmp_path / "script.txt",
        storyboard_path=source,
        output_dir=tmp_path,
    )
    orchestrator._prepare_default_course_visuals(
        arts,
        model="test",
        theme="bright",
        browser="msedge",
        voice=None,
        rate=None,
        reuse_audio=False,
        frozen_audio_dir=None,
        timing_mode="semantic",
    )
    assert calls == ["visuals", "measured_tts"] and arts.durations == [7.125]
    assert arts.storyboard_path == planned


def test_split_cannot_reuse_ordinary_old_audio_cache(monkeypatch, tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board()), encoding="utf-8")
    split = board()
    split["segments"] = [
        dict(split["segments"][0], narration="采集数据。"),
        dict(split["segments"][0], id="second", narration="处理数据。"),
    ]
    planned = tmp_path / "planned.json"
    planned.write_text(json.dumps(split), encoding="utf-8")
    monkeypatch.setattr(course_visuals, "prepare_course_storyboard", lambda *a, **kw: planned)
    monkeypatch.setattr(
        orchestrator, "run_tts", lambda *a, **kw: pytest.fail("old audio must not be reused")
    )
    arts = orchestrator.Artifacts(
        stem="lesson",
        title="data",
        raw_path=tmp_path / "raw.txt",
        script_path=tmp_path / "script.txt",
        storyboard_path=source,
        output_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="cached/frozen"):
        orchestrator._prepare_default_course_visuals(
            arts,
            model="test",
            theme="bright",
            browser="msedge",
            voice=None,
            rate=None,
            reuse_audio=True,
            frozen_audio_dir=None,
            timing_mode="legacy",
        )


def test_copied_cover_and_distinct_panels_cannot_overwrite_each_other(monkeypatch, tmp_path):
    import hashlib

    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    source = tmp_path / "source.json"
    source_images = tmp_path / "images"
    source_images.mkdir()
    name = "generated-page-002.svg"
    cover_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><title>original-cover</title></svg>'
    (source_images / name).write_bytes(cover_bytes)
    data = board()
    data["segments"].insert(
        0,
        {
            "id": "cover",
            "narration": "开场。",
            "visual_type": "title",
            "elements": [{"id": "cover-picture", "type": "image", "src": name}],
        },
    )
    source.write_text(json.dumps(data), encoding="utf-8")
    destination = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge",
        rebuild_page_from_source=False,
    )
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert (destination.parent / "images" / name).read_bytes() == cover_bytes
    records = result["metadata"]["course_visuals"]["assets"]
    assert len(records) == 2 and records[0]["filename"] != records[1]["filename"]
    for record in records:
        actual = (destination.parent / "images" / record["filename"]).read_bytes()
        assert hashlib.sha256(actual).hexdigest() == record["sha256"]
    assert len(list((destination.parent / "images").iterdir())) == 3


def test_copied_asset_hash_is_checked_again_at_render_time(monkeypatch, tmp_path):
    from textbook2video.animation_gen import load_textbook_images

    run = approved_panels(tmp_path)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run)
    source = tmp_path / "source.json"
    source.write_text(json.dumps(board()), encoding="utf-8")
    path = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge",
        rebuild_page_from_source=False,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    record = data["metadata"]["course_visuals"]["assets"][0]
    (path.parent / "images" / record["filename"]).write_bytes(b"changed after review")
    with pytest.raises(ValueError, match="hash drift"):
        load_textbook_images(data["segments"], path.parent / "images")


def test_textbook_asset_is_not_retained_on_two_course_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(
        course_visuals, "run_visual_agent", lambda *a, **kw: pytest.fail("cover skipped")
    )
    images = tmp_path / "images"
    images.mkdir()
    (images / "same.svg").write_bytes(b"original")
    source = tmp_path / "source.json"
    data = {
        "segments": [
            {
                "id": str(i),
                "narration": "cover",
                "visual_type": "title",
                "elements": [{"id": "pic", "type": "image", "src": "same.svg"}],
            }
            for i in range(2)
        ]
    }
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="at most one"):
        course_visuals.prepare_course_storyboard(
            source, output_dir=tmp_path, model="test", theme="bright", browser="msedge"
        )


def test_development_duplicate_original_image_is_omitted_without_blocking(monkeypatch, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "same.svg").write_bytes(b"original")
    raw = tmp_path / "raw.md"
    raw.write_text(SOURCE, encoding="utf-8")

    def offline(*a, **kw):
        raise TimeoutError("offline")

    monkeypatch.setattr(course_visuals, "run_visual_agent", offline)
    data = board()
    data["segments"][0]["elements"].append({"id": "p", "type": "image", "src": "same.svg"})
    data["segments"].append(dict(deepcopy(data["segments"][0]), id="second"))
    source = tmp_path / "storyboard.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    path = course_visuals.prepare_course_storyboard(
        source, output_dir=tmp_path, model="test", theme="bright", browser="msedge",
        source_path=raw, review_policy="development",
    )
    result = json.loads(path.read_text(encoding="utf-8"))
    assert any(e.get("src") == "same.svg" for e in result["segments"][0]["elements"])
    assert all(e.get("type") != "image" for e in result["segments"][1]["elements"])
    assert result["metadata"]["course_visuals"]["omitted_images"][0]["reason"] == (
        "duplicate-textbook-image-not-reused"
    )
    assert (path.parent / "images" / "same.svg").read_bytes() == b"original"
    assert "".join(s["narration"] for s in result["segments"]) == SOURCE * 2
    assert json.loads(source.read_text(encoding="utf-8")) == data
