from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from textbook2video import animation_gen
from textbook2video.pipeline import course_visuals, orchestrator, visual_page_render
from textbook2video.research import visual_tools
from textbook2video.research.visual_tools import ReviewResponseError, digest


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _page() -> dict:
    return {
        "id": "lesson-page-1", "visual_type": "content", "title": "说明",
        "narration": "教材说明一个对象。", "elements": [
            {"id": "heading", "type": "heading", "text": "说明"},
            {"id": "body", "type": "text", "text": "教材说明一个对象。"},
        ],
        "timeline": [{"event_id": "original-show", "target": "body",
                      "action": "show", "at_sec": 0.0}],
        "animations": [],
    }


def _png(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    # Deterministic 1x1 RGBA fixture; keep tests independent of optional Pillow.
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\x33\x77\xaa\xff"))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_invalid_visual_agent_review_is_kept_unreviewed_and_inserted(tmp_path, monkeypatch):
    source = tmp_path / "raw.txt"
    source.write_text("教材说明输入经过处理得到输出。", encoding="utf-8")
    board_path = _write_json(tmp_path / "storyboard.json", {
        "lesson_title": "夹具课程", "segments": [_page()], "metadata": {},
    })
    unit = {"id": "u1", "text": "输入经过处理得到输出。"}
    evidence_path = _write_json(tmp_path / "source-evidence.json", {"source_units": [unit]})
    proposition = {
        "id": "p1", "segment_id": "lesson-page-1", "text": "输入经过处理得到输出。",
        "source_refs": [{"source_unit_id": "u1"}],
    }
    graph_path = _write_json(tmp_path / "graph.json", {
        "narration_propositions": [proposition], "source_evidence_path": str(evidence_path),
    })
    decision = {
        "action": "generate", "decision_state": "DECIDED",
        "narration_proposition_id": "p1", "generation_prompt": "表达输入处理和输出。",
    }
    decisions_path = _write_json(tmp_path / "decisions.json", {"decisions": [decision]})
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120">'
           b'<text x="10" y="40">Input to output</text></svg>')
    revision = tmp_path / "compiled-revision"
    asset_path = revision / "compiled" / "assets" / "diagram.svg"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(svg)
    _write_json(revision / "revision.json", {"geometry": [], "page_plan": {}})
    _write_json(revision / "source.json", {"source_text": "输入经过处理得到输出。"})
    entry = {"revision": str(revision)}
    run_state = {"history": [entry], "review_policy": "development"}
    monkeypatch.setattr(visual_tools, "verify_revision", lambda path: None)
    monkeypatch.setattr(course_visuals, "verify_revision", lambda path: None)
    assert visual_tools._retain_unreviewed_draft(
        run_state, entry, revision, ReviewResponseError("invalid reviewer protocol"),
        review_policy="development",
    )
    status_path = revision / "review-status.json"
    status_digest = digest(json.loads(status_path.read_text(encoding="utf-8")))
    assert entry["review_status_sha256"] == status_digest
    run_path = _write_json(tmp_path / "agent-run.json", run_state)
    monkeypatch.setattr(course_visuals, "run_visual_agent", lambda *a, **kw: run_path)
    monkeypatch.setattr(course_visuals, "_measure_generation_capacity", lambda *a, **kw: {})
    monkeypatch.setattr(course_visuals, "verify_revision", lambda path: None)
    monkeypatch.setattr(course_visuals, "execution_assets", lambda path: [{
        "id": "compiled-1", "filename": "diagram.svg", "sha256": hashlib.sha256(svg).hexdigest(),
        "spec": {"kind": "flow", "title": "输入到输出"},
    }])
    selection = {"pages": {"lesson-page-1": {
        "decisions": [decision], "propositions": [proposition], "assets": [],
        "requires_generation": True, "unresolved_propositions": ["p1"],
        "generation_pending_propositions": ["p1"], "source_grounding_rejections": [],
    }}}
    course_visuals._materialize_decided_visuals(
        selection=selection, storyboard_path=board_path, source_path=source,
        graph_path=graph_path, decisions_path=decisions_path,
        output_dir=tmp_path / "materialize", model="offline-fixture",
        review_model="offline-fixture", max_generated_visuals=1, review_policy="development",
    )
    asset = selection["pages"]["lesson-page-1"]["assets"][0]
    assert asset["review_status"] == "UNREVIEWED"
    assert asset["review" ]["review_status"] == "UNREVIEWED"
    assert asset["review_status_sha256"] == digest(asset["review"])

    def fake_compose(page, **kwargs):
        element = {
            "id": kwargs["element_id"], "type": "image", "src": "diagram.svg",
            "description": "输入到输出", "visual_asset_sha256": hashlib.sha256(svg).hexdigest(),
            **kwargs["element_metadata"],
        }
        course_visuals.apply_local_visual_plan(page, element)
        return {
            "images": {f"{page['id']}:{element['id']}": str(asset_path)},
            "storyboard": "offline/storyboard.json", "layout": {"passed": False},
            "layout_status": "USED_WITH_WARNING",
        }

    monkeypatch.setattr(course_visuals, "compose_local_visual", fake_compose)
    pages = [_page()]
    images = course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / "apply", model="offline-fixture", theme="bright",
        review_policy="development", asset_selection=selection, preserve_existing_pages=True,
    )
    assert any(item.get("id") == asset["element_id"] for item in pages[0]["elements"])
    inserted = next(item for item in pages[0]["elements"] if item.get("id") == asset["element_id"])
    assert inserted["visual_review_status"] == "UNREVIEWED"
    assert pages[0]["timeline"] == _page()["timeline"]
    assert f"lesson-page-1:{asset['element_id']}" in images
    assert selection["pages"]["lesson-page-1"]["composition_results"][asset["element_id"]][
        "status"
    ] == "LOCAL_COMPOSITION_LAYOUT_WARNING"


def test_soft_reject_is_used_with_warning_while_hash_failure_isolated(tmp_path):
    rejected_path = tmp_path / "rejected.png"
    accepted_path = tmp_path / "accepted.png"
    bad_actual = _png(rejected_path)
    accepted_hash = _png(accepted_path)
    reject_review = {"verdict": "REJECT", "reason": "model quality warning",
                     "visual_summary": "reviewer rejected quality"}
    accept_review = {"verdict": "ACCEPT", "reason": "matches the source",
                     "visual_summary": "accepted figure"}
    rejected_review_path = _write_json(tmp_path / "reject-review.json", reject_review)
    accepted_review_path = _write_json(tmp_path / "accept-review.json", accept_review)

    def asset(path, sha, review, review_path, status, ident):
        return {
            "asset_id": ident, "element_id": ident, "action": "retrieve",
            "local_path": str(path), "sha256": sha, "review_path": str(review_path),
            "review": review, "review_status": status, "review_policy": "development",
            "proposition_ids": [],
        }

    selection = {"pages": {"lesson-page-1": {
        "assets": [
            asset(rejected_path, bad_actual, reject_review, rejected_review_path,
                  "USED_WITH_WARNING", "quality-warning"),
            asset(rejected_path, "0" * 64, accept_review, accepted_review_path,
                  "VALIDATED", "bad-hash"),
            asset(accepted_path, accepted_hash, accept_review, accepted_review_path,
                  "VALIDATED", "good-asset"),
        ],
        "decisions": [], "propositions": [], "requires_generation": False,
        "decision_status": "ASSETS_READY", "unresolved_propositions": [],
    }}}
    pages = [_page()]
    images = course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / "run", model="offline-fixture", theme="bright",
        review_policy="development", asset_selection=selection, preserve_existing_pages=True,
    )
    assert any(item.get("id") == "good-asset" for item in pages[0]["elements"])
    assert any(item.get("id") == "quality-warning" for item in pages[0]["elements"])
    assert not any(item.get("id") == "bad-hash" for item in pages[0]["elements"])
    assert pages[0]["elements"][-1]["visual_review_status"] == "VALIDATED"
    warning = next(item for item in pages[0]["elements"]
                   if item.get("id") == "quality-warning")
    assert warning["visual_review_status"] == "USED_WITH_WARNING"
    assert warning["visual_relevance_verdict"] == "REJECT"
    failure = selection["pages"]["lesson-page-1"]["asset_admission_failures"][0]
    assert failure["status"] == "REJECTED"
    assert failure["stage"] == "selected-asset-admission"
    assert "lesson-page-1:good-asset" in images
    assert bad_actual != "0" * 64


def test_one_local_asset_composition_failure_does_not_mutate_page_or_block_peer(
    tmp_path, monkeypatch,
):
    assets = []
    for ident in ("bad-compose", "good-compose"):
        path = tmp_path / f"{ident}.png"
        sha = _png(path)
        review = {"verdict": "ACCEPT", "reason": "source grounded", "visual_summary": ident}
        review_path = _write_json(tmp_path / f"{ident}-review.json", review)
        assets.append({
            "asset_id": ident, "element_id": ident, "action": "retrieve",
            "local_path": str(path), "sha256": sha, "review_path": str(review_path),
            "review": review, "review_status": "VALIDATED", "review_policy": "development",
            "proposition_ids": [],
        })
    page = _page()
    original = json.loads(json.dumps(page))
    selection = {"pages": {page["id"]: {
        "assets": assets, "decisions": [], "propositions": [],
        "requires_generation": False, "decision_status": "ASSETS_READY",
        "unresolved_propositions": [],
    }}}

    def apply_one(page_value, element):
        if element["id"] == "bad-compose":
            raise ValueError("fixture local layout cannot include this asset")
        page_value["elements"].append(element)

    monkeypatch.setattr(course_visuals, "apply_local_visual_plan", apply_one)
    pages = [page]
    images = course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / "isolated-compose", model="offline-fixture",
        theme="bright", review_policy="development", asset_selection=selection,
        preserve_existing_pages=True,
    )
    assert pages[0]["timeline"] == original["timeline"]
    assert next(e for e in pages[0]["elements"] if e["id"] == "body") == original["elements"][1]
    assert not any(e.get("id") == "bad-compose" for e in pages[0]["elements"])
    assert any(e.get("id") == "good-compose" for e in pages[0]["elements"])
    assert "lesson-page-1:good-compose" in images
    failure = selection["pages"][page["id"]]["asset_admission_failures"][0]
    assert failure["stage"] == "local-composition"
    assert failure["status"] == "REJECTED"


def test_development_renderer_compiles_valid_events_and_records_local_failures(
    tmp_path, monkeypatch,
):
    image_path = tmp_path / "images" / "figure.png"
    _png(image_path)
    dangerous_svg = tmp_path / "images" / "danger.svg"
    dangerous_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    wrong_hash_path = tmp_path / "images" / "wrong-hash.png"
    _png(wrong_hash_path)
    story = {"lesson_title": "fixture", "metadata": {
        "total_slides": 1, "available_images": [{
            "id": "figure-source", "visual_relevance_verdict": "REJECT",
        }],
    }, "segments": [{
        "id": "s1", "visual_type": "content", "narration": "说明对象。",
        "elements": [
            {"id": "body", "type": "text", "text": "说明对象。"},
            {"id": "figure", "type": "image", "src": "figure.png",
             "source_image_id": "figure-source"},
            {"id": "danger", "type": "image", "src": "danger.svg"},
            {"id": "bad-hash", "type": "image", "src": "wrong-hash.png",
             "visual_asset_sha256": "0" * 64},
            {"id": "traversal", "type": "image", "src": "../outside.png"},
        ],
        "timeline": [
            {"event_id": "valid", "target": "body", "action": "focus", "start_ms": 0},
            {"event_id": "missing-target", "target": "not-on-page",
             "action": "focus", "start_ms": 200},
            {"event_id": "unknown-action", "target": "body", "action": "sparkle", "start_ms": 300},
            {"event_id": "missing-time", "target": "body", "action": "focus"},
            {"event_id": "nan-time", "target": "body", "action": "focus", "start_ms": "nan"},
        ],
        "animations": [{"target": "body"}],
    }]}
    board = _write_json(tmp_path / "storyboard.json", story)
    captured = {}
    monkeypatch.setenv("T2V_SKIP_SVG", "1")
    monkeypatch.setattr(animation_gen, "package_cjk_font", lambda out: {
        "font_asset_exists": True, "font_family": "fixture", "font_asset_relative_path": "",
        "font_sha256": "fixture",
    })
    from textbook2video import template_renderer

    monkeypatch.setattr(
        template_renderer, "render_slide",
        lambda *a, **kw: "<div class='slide'></div>",
    )
    def capture_images(slides, batch, images):
        captured["images"] = dict(images)
        return slides

    monkeypatch.setattr(animation_gen, "inject_generated_images", capture_images)

    def merge(**kwargs):
        captured["timelines"] = kwargs["timelines"]
        return "<!doctype html><html><body>fixture</body></html>"

    monkeypatch.setattr(animation_gen, "merge_html", merge)
    monkeypatch.setattr(animation_gen, "run_layout_qa", lambda *a, **kw: (True, {"slides": []}))
    monkeypatch.setattr(animation_gen, "validate_output", lambda *a, **kw: {"all_pass": True})
    output = animation_gen.generate(
        board, output_dir=tmp_path / "html", skip_image_gen=True, visual_tools_enabled=False,
        layout_repair_attempts=0, event_validation_policy="development",
        asset_review_policy="development",
    )
    report = json.loads((output.parent / "event-validation.json").read_text(encoding="utf-8"))
    source_report = json.loads(
        (output.parent / "source-asset-admission.json").read_text(encoding="utf-8")
    )
    assert output.is_file()
    assert captured["images"]["s1:figure"] == str(image_path.resolve())
    assert not {"s1:danger", "s1:bad-hash", "s1:traversal"}.intersection(captured["images"])
    assert source_report["status"] == "USED_WITH_WARNING"
    assert source_report["assets"][0]["status"] == "USED_WITH_WARNING"
    assert source_report["assets"][0]["used"] is True
    rejected = [asset for asset in source_report["assets"] if asset["status"] == "REJECTED"]
    assert {asset["element_id"] for asset in rejected} == {"danger", "bad-hash", "traversal"}
    assert {item["reason"] for item in source_report["diagnostics"]} >= {
        "image_decode_failed", "image_hash_mismatch", "unsafe_image_path",
    }
    assert [item["event_id"] for item in captured["timelines"][0]] == ["valid"]
    assert report["compiled_event_count"] == 1
    assert report["status"] == "USED_WITH_WARNING"
    assert {item["reason"] for item in report["excluded_or_adjusted"]} >= {
        "target_not_found", "unsupported_action", "time_missing_or_invalid",
        "non_finite_time",
    }
    import pytest

    with pytest.raises(ValueError, match="缺少字段: effect"):
        animation_gen.parse_storyboard(board)


def test_development_image_review_is_warning_but_bad_hash_and_dangerous_image_are_rejected(
    tmp_path,
):
    good = tmp_path / "images" / "reviewed.png"
    _png(good)
    dangerous = tmp_path / "images" / "danger.svg"
    dangerous.parent.mkdir(parents=True, exist_ok=True)
    dangerous.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    segments = [{"id": "s1", "elements": [
        {"id": "reviewed", "type": "image", "src": "reviewed.png",
         "source_image_id": "figure-1"},
        {"id": "hash-bad", "type": "image", "src": "reviewed.png",
         "visual_asset_sha256": "0" * 64},
        {"id": "danger", "type": "image", "src": "danger.svg"},
        {"id": "path-bad", "type": "image", "src": "../outside.png"},
    ]}]
    diagnostics = []
    loaded = animation_gen.load_textbook_images(
        segments, good.parent,
        [{"id": "figure-1", "visual_relevance_verdict": "REJECT"}],
        review_policy="development", diagnostics=diagnostics,
    )
    assert loaded["s1:reviewed"] == str(good.resolve())
    assert segments[0]["elements"][0]["visual_review_status"] == "USED_WITH_WARNING"
    assert {item["reason"] for item in diagnostics} >= {
        "source_review_not_accepted", "image_hash_mismatch",
        "image_decode_failed", "unsafe_image_path",
    }
    assert all(item.get("_render_blocked") for item in segments[0]["elements"][1:])


def test_layout_issues_warn_in_development_but_remain_strictly_blocking(tmp_path, monkeypatch):
    segment = _page()
    report = {
        "passed": False, "blocked_network": [],
        "viewports": [{"viewport": [1366, 768], "issues": [{"type": "content_overflow"}],
                       "warnings": []}],
    }
    monkeypatch.setattr(visual_page_render, "course_page_html", lambda *a, **kw: "<html/>")
    monkeypatch.setattr(visual_page_render, "validate_local_page", lambda *a, **kw: report)
    result = visual_page_render.measure_generation_capacity(
        segment, {}, output_dir=tmp_path / "dev-capacity", theme="bright", browser="chromium",
        review_policy="development",
    )
    assert result["original_page_status"] == "USED_WITH_WARNING"
    assert result["original_page_warning_count"] == 1
    import pytest

    with pytest.raises(ValueError, match="original page requires layout adjustment"):
        visual_page_render.measure_generation_capacity(
            segment, {}, output_dir=tmp_path / "strict-capacity", theme="bright",
            browser="chromium", review_policy="strict",
        )


def test_optional_research_v2_failure_is_incomplete_and_does_not_mutate_storyboard(
    tmp_path, monkeypatch,
):
    import pytest

    from textbook2video.research import proposition_schema

    monkeypatch.setenv("T2V_RESEARCH_GENERATION_V2", "1")
    raw = tmp_path / "raw.txt"
    raw.write_text("教材文本", encoding="utf-8")
    board_path = _write_json(tmp_path / "storyboard.json", {
        "segments": [{"id": "s1", "narration": "讲解", "elements": []}],
    })
    board = json.loads(board_path.read_text(encoding="utf-8"))
    before = json.loads(json.dumps(board))
    monkeypatch.setattr(
        proposition_schema, "annotate_storyboard_v2",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("fixture projection failure")),
    )
    orchestrator._dual_write_research_generation_v2(
        output_dir=tmp_path, stem="fixture", raw_path=raw, lesson_plan={},
        segments=["讲解"], storyboard=board, storyboard_path=board_path,
    )
    status = json.loads(
        (tmp_path / "fixture_research_generation_v2_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "INCOMPLETE"
    assert status["integrity"] == "INCOMPLETE"
    assert status["stage"] == "build-projections"
    assert board == before
    assert json.loads(board_path.read_text(encoding="utf-8")) == before

    strict_dir = tmp_path / "strict"
    strict_dir.mkdir()
    with pytest.raises(ValueError, match="fixture projection failure"):
        orchestrator._dual_write_research_generation_v2(
            output_dir=strict_dir, stem="fixture", raw_path=raw, lesson_plan={},
            segments=["讲解"], storyboard=json.loads(json.dumps(before)),
            storyboard_path=_write_json(strict_dir / "storyboard.json", before),
            required=True,
        )


def test_unreviewed_visual_is_never_counted_as_validated_or_admitted_by_strict_policy(
    tmp_path,
):
    status = {
        "review_status": "UNREVIEWED", "reason": "invalid response schema",
        "response_files": ["review-response-01.txt"],
        "protocol_error_files": ["review-protocol-error-01.json"],
        "asset_execution_integrity": "VERIFIED",
    }
    from textbook2video.research.visual_review_policy import review_disposition

    strict = review_disposition(status, [], None, policy="strict")
    development = review_disposition(status, [], None, policy="development")
    assert strict["strict_approved"] is False
    assert strict["draft_usable"] is False
    assert strict["quality_status"] == "UNREVIEWED"
    assert development["strict_approved"] is False
    assert development["draft_usable"] is True
    assert development["quality_status"] == "UNREVIEWED"
    assert development["warnings"][0]["response_files"] == ["review-response-01.txt"]
    entry = {"status": "COMPILED"}
    state = {"history": [entry], "status": "COMPILED"}
    assert not visual_tools._retain_unreviewed_draft(
        state, entry, tmp_path, ReviewResponseError("invalid response"),
        review_policy="strict",
    )
    assert state["status"] == "COMPILED"
    assert entry["status"] == "COMPILED"


@pytest.mark.parametrize("review_failure", ["protocol", "service"])
def test_acquired_unreviewed_asset_survives_selection_and_reaches_page(
    tmp_path, monkeypatch, review_failure,
):
    from textbook2video.llm import client

    page = _page()
    text = page['narration']
    source = tmp_path / 'source.txt'
    source.write_text(text, encoding='utf-8')
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    board_path = _write_json(tmp_path / 'board.json', {'segments': [page]})
    evidence = _write_json(tmp_path / 'evidence.json', {'document': {'sha256': sha}})
    graph = _write_json(tmp_path / 'graph.json', {
        'raw_sha256': sha, 'storyboard_path': str(board_path),
        'source_evidence_path': str(evidence), 'narration_propositions': [
            {'id': ident, 'segment_id': page['id'], 'text': text,
             'span': {'start': 0, 'end': len(text)}} for ident in ('p1', 'p2')],
    })
    decisions = _write_json(tmp_path / 'decisions.json', {
        'storyboard_path': str(board_path), 'proposition_graph_path': str(graph),
        'source_evidence_path': str(evidence), 'decisions': [
            {'narration_proposition_id': ident, 'action': 'reuse'} for ident in ('p1', 'p2')],
    })
    image = tmp_path / 'figure.png'
    image_sha = _png(image)
    acquired = _write_json(tmp_path / 'acquired.json', {
        'decision_path': str(decisions), 'source_evidence_path': str(evidence), 'assets': [
            {'proposition_id': ident, 'action': 'reuse', 'asset_id': ident,
             'status': 'SOURCE_REUSED_PENDING_VLM_REVIEW', 'license': 'CC0',
             'filename': image.name, 'local_path': str(path), 'sha256': image_sha}
            for ident, path in [('p1', image), ('p2', tmp_path / 'missing.png')]],
    })

    def review(*args, **kwargs):
        if review_failure == 'service':
            raise TimeoutError('offline fixture service failure')
        return '{"verdict":"UNKNOWN"}'

    monkeypatch.setattr(client, 'chat_with_images', review)
    selection = course_visuals._review_course_asset_selection(
        board_path, source, tmp_path / 'selection', graph, decisions, acquired,
        review_model='offline-fixture', review_policy='development',
    )
    row = selection['pages'][page['id']]
    assert len(row['assets']) == 1
    asset = row['assets'][0]
    assert asset['review_status'] == 'UNREVIEWED'
    assert row['asset_admission_failures'][0]['stage'] == 'acquired-asset-integrity'
    with pytest.raises(ValueError, match='not usable'):
        course_visuals._validate_page_asset(asset, review_policy='strict')
    pages = [_page()]
    course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / 'render', model='offline-fixture', theme='bright',
        review_policy='development', asset_selection=selection, preserve_existing_pages=True,
    )
    inserted = [e for e in pages[0]['elements'] if e.get('visual_review_status') == 'UNREVIEWED']
    assert len(inserted) == 1
    assert pages[0]['timeline'] == _page()['timeline']
    # A persisted warning cannot authorize a different file or hash.
    image.write_bytes(b'changed asset')
    with pytest.raises(ValueError, match='hash drift'):
        course_visuals._validate_page_asset(asset, review_policy='development')


def test_revise_draft_is_admitted_without_claiming_validation(tmp_path, monkeypatch):
    path = tmp_path / 'figure.png'
    sha = _png(path)
    review = {
        'verdict': 'REVISE', 'reason': 'quality warning', 'visual_summary': 'figure',
        'scores': dict.fromkeys(('accuracy', 'relevance', 'readability', 'composition'), 2),
        'issues': [],
    }
    review_path = _write_json(tmp_path / 'revision' / 'review.json', review)
    _write_json(review_path.parent / 'revision.json', {'geometry': [], 'page_plan': {}})
    monkeypatch.setattr(course_visuals, 'verify_revision', lambda path: None)
    selection = {'pages': {'lesson-page-1': {
        'assets': [{'asset_id': 'draft', 'element_id': 'draft', 'action': 'generate',
                    'local_path': str(path), 'sha256': sha, 'review': review,
                    'review_path': str(review_path), 'visual_revision_path': str(review_path.parent),
                    'review_status': 'USED_WITH_WARNING', 'review_policy': 'development',
                    'proposition_ids': []}],
        'decisions': [], 'propositions': [], 'requires_generation': False,
    }}}
    pages = [_page()]
    course_visuals.generate_course_visuals(
        pages, output_dir=tmp_path / 'render', model='offline-fixture', theme='bright',
        review_policy='development', asset_selection=selection, preserve_existing_pages=True,
    )
    element = next(e for e in pages[0]['elements'] if e['id'] == 'draft')
    assert element['visual_review_status'] == 'USED_WITH_WARNING'
    assert element['visual_relevance_verdict'] == 'REVISE'
