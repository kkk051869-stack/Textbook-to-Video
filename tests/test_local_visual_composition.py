"""Engineering fixtures only: non-blockchain water-cycle pages, no semantic approval."""
from __future__ import annotations

import hashlib
import json
import shutil
import socket
from copy import deepcopy
from pathlib import Path

import pytest

from textbook2video.animation_gen import build_slide_timelines
from textbook2video.pipeline import course_visuals
from textbook2video.pipeline.course_visuals import load_local_storyboard_page
from textbook2video.pipeline.visual_page_plan import apply_local_visual_plan
from textbook2video.pipeline.visual_page_render import course_page_html
from textbook2video.research import visual_tools

SOURCE = "水受热蒸发。水蒸气遇冷凝结。"


@pytest.fixture(autouse=True)
def fail_model_transport(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network/model/health request in offline validation")

    import httpx
    import litellm

    original_connect = socket.socket.connect

    def offline_connect(sock, address):
        # Windows asyncio uses a loopback socketpair for its internal wakeup.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        return forbidden()

    monkeypatch.setattr(socket.socket, "connect", offline_connect)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(litellm, "completion", forbidden)
    monkeypatch.setattr(litellm, "acompletion", forbidden)
    monkeypatch.setattr(course_visuals, "check_review_health", forbidden)
    monkeypatch.setattr(course_visuals, "run_visual_agent", forbidden)


@pytest.fixture
def fixture_bundle(tmp_path):
    spec = {
        "id": "water-cycle", "schema_version": "teaching-visual-v2", "kind": "flow",
        "title": "水的状态变化（工程夹具）", "teaching_goal": "说明蒸发与凝结",
        "layout_direction": "vertical", "text_scale": 1.5,
        "nodes": [{"id": "evaporation", "label": "水受热蒸发", "evidence": SOURCE},
                  {"id": "condensation", "label": "水蒸气遇冷凝结", "evidence": SOURCE}],
        "edges": [{"source": "evaporation", "target": "condensation", "evidence": SOURCE}],
    }
    revision = tmp_path / "engineering-fixture-revision"
    visual_tools.dispatch("create", {"visuals": [spec]}, source=SOURCE,
                          output_dir=revision, render=False)
    manifest = json.loads((revision / "compiled/visual_assets.json").read_text(encoding="utf-8"))
    return revision, manifest["assets"][0]


def page():
    return {
        "id": "water-lesson", "visual_type": "illustration", "narration": SOURCE,
        "audio_duration_sec": 8,
        "elements": [
            {"id": "heading", "type": "heading", "text": "水循环 · 工程夹具"},
            {"id": "body", "type": "text", "text": "水受热蒸发", "source_refs": ["fixture-p1"]},
            {"id": "component", "type": "icon_group", "items": ["观察", "解释"]},
        ],
        "timeline": [{"event_id": "body-show", "target": "body", "action": "show", "at_sec": .1},
                     {"event_id": "component-show", "target": "e3", "at_sec": .3}],
        "animations": [{"event_id": "legacy", "target": "body", "trigger_at_sec": .1}],
    }


def coverage():
    return {"element_id": "body", "decision": "represented", "fact_quotes": ["水受热蒸发"],
            "visual_refs": ["water-cycle:evaporation"], "source_evidence": SOURCE,
            "reason": "工程夹具：原文字完整呈现在蒸发节点中"}


def compose(segment, fixture_bundle, output_dir, **kwargs):
    revision, asset = fixture_bundle
    return course_visuals.compose_local_visual(
        segment, revision=revision, asset_id=asset["id"], output_dir=output_dir,
        engineering_fixture=True, **kwargs,
    )


def assert_compiled_retained(before, after):
    assert build_slide_timelines([before]) == build_slide_timelines([after])


def test_A_insert_preserves_content_ids_sources_and_events(fixture_bundle, tmp_path):
    segment = page()
    before = deepcopy(segment)
    result = compose(segment, fixture_bundle, tmp_path / "A-insert")
    assert segment["elements"][:-1] == before["elements"]
    for key in ("narration", "timeline", "animations", "audio_duration_sec"):
        assert segment[key] == before[key]
    assert_compiled_retained(before, segment)
    assert result["layout"]["passed"]
    other = page()
    other["elements"].insert(1, {"id": "extra", "type": "badge", "text": "补充"})
    # Element ID generation is independent of insertion order (compiler may
    # reject positional events whose meaning changes, so compare without them).
    other["timeline"] = other["animations"] = []
    compose(other, fixture_bundle, tmp_path / "A-stable-id")
    assert segment["elements"][-1]["id"] == other["elements"][-1]["id"]


def test_B_textbook_pixels_overlays_and_runtime_events(fixture_bundle, tmp_path):
    segment = page()
    segment["elements"] = segment["elements"][:2] + [
        {"id": "book-image", "type": "image", "src": "fixture-book.svg",
         "description": "工程夹具教材图", "source_refs": ["fixture-figure-1"]},
        {"id": "focus", "type": "focus_box", "target": "book-image", "bbox": [.1, .2, .35, .3]},
        {"id": "callout", "type": "callout", "target": "book-image",
         "bbox": [.55, .65, .2, .15], "label": "观察点"},
    ]
    segment["timeline"] = [
        {"event_id": "figure", "target": "book-image", "at_sec": .05},
        {"event_id": "focus-event", "target": "focus", "at_sec": .1},
        {"event_id": "callout-event", "target": "callout", "at_sec": .15},
        {"event_id": "signal", "target": "focus", "action": "highlight", "at_sec": .9},
    ]
    source_dir = tmp_path / "source-page"
    source_images = source_dir / "images"
    source_images.mkdir(parents=True)
    image = source_images / "fixture-book.svg"
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 180">'
                     '<rect width="400" height="180" fill="#dbeafe"/>'
                     '<circle cx="120" cy="80" r="35" fill="#38bdf8"/></svg>', encoding="utf-8")
    source_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    segment["elements"][2].update(
        source_image_id="fixture-figure-1", visual_asset_sha256=source_hash,
    )
    source_storyboard = source_dir / "storyboard.json"
    source_storyboard.write_text(json.dumps({
        "lesson_title": "工程夹具",
        "segments": [deepcopy(segment)],
        "metadata": {"available_images": [{"id": "fixture-figure-1",
                                             "filename": "fixture-book.svg",
                                             "sha256": source_hash}]},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    before = deepcopy(segment)
    result = compose(segment, fixture_bundle, tmp_path / "B-textbook-overlays",
                     storyboard_path=source_storyboard)
    assert segment["elements"][:-1] == before["elements"]
    assert segment["timeline"] == before["timeline"]
    assert_compiled_retained(before, segment)
    # Use the existing runtime and trace, independently of full-show screenshots.
    # Simulate a later process: the saved storyboard and images/ manifest are
    # the only inputs. The original source and compose return value are unused.
    saved_storyboard = tmp_path / "B-textbook-overlays" / "storyboard.json"
    assert saved_storyboard.is_file()
    assert (saved_storyboard.parent / "images" / "fixture-book.svg").is_file()
    shutil.rmtree(source_dir)
    reloaded, reloaded_images = load_local_storyboard_page(saved_storyboard, "water-lesson")
    assert reloaded == segment
    assert reloaded["timeline"] == before["timeline"]
    assert reloaded["animations"] == before["animations"]
    assert build_slide_timelines([reloaded]) == build_slide_timelines([segment])
    reloaded_html = course_page_html(reloaded, reloaded_images, theme="dark-blue-academic")
    assert reloaded_html == Path(result["static_html"]).read_text(encoding="utf-8")
    assert result["layout"]["save_reload_render"]["passed"]

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        runtime = browser.new_page(viewport={"width": 1366, "height": 768})
        runtime.route("https://**/*", lambda route: route.abort())
        runtime.route("http://**/*", lambda route: route.abort())
        runtime.goto(Path(result["html"]).as_uri())
        runtime.wait_for_function(
            "window.exportAnimationTrace && window.exportAnimationTrace().length>=4"
        )
        runtime.wait_for_timeout(2000)
        trace = runtime.evaluate("window.exportAnimationTrace()")
        (tmp_path / "B-textbook-overlays/runtime-trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        assert len(trace) == 4
        assert all(e["status"] == "executed" for e in trace)
        assert {e["target"] for e in trace} == {"book-image", "focus", "callout"}

    persisted = json.loads(saved_storyboard.read_text(encoding="utf-8"))
    persisted["metadata"]["available_images"][0]["sha256"] = "0" * 64
    saved_storyboard.write_text(
        json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="conflicting expected hashes"):
        load_local_storyboard_page(saved_storyboard, "water-lesson")
        for event in trace:
            assert runtime.locator(f'[data-anim-id="{event["target"]}"]').count() == 1
        # Annotation geometry remains relative to the actual textbook pixels.
        geometry = runtime.evaluate("""() => {
            const img=document.querySelector('[data-anim-id="book-image"] img')
                .getBoundingClientRect();
            const focus=document.querySelector('[data-anim-id="focus"]').getBoundingClientRect();
            return [(focus.x-img.x)/img.width,(focus.y-img.y)/img.height,
                    focus.width/img.width,focus.height/img.height];
        }""")
        assert geometry == pytest.approx([.1, .2, .35, .3], abs=.01)
        runtime.screenshot(path=str(tmp_path / "B-textbook-overlays/runtime-1366x768.png"))
        browser.close()


def test_C_replace_one_text_object_preserves_other_events(fixture_bundle, tmp_path):
    segment = page()
    before = deepcopy(segment)
    result = compose(segment, fixture_bundle, tmp_path / "C-replace", replace_element_id="body",
                     coverage=coverage())
    ident = segment["elements"][1]["id"]
    assert segment["elements"][0] == before["elements"][0]
    assert segment["elements"][2:] == before["elements"][2:]
    assert segment["timeline"][1:] == before["timeline"][1:]
    assert segment["local_visual_operations"][0]["replaced_elements"] == [before["elements"][1]]
    expected = build_slide_timelines([before])[0]
    expected[0].update(target=ident, selector=f'[data-anim-id="{ident}"]')
    assert build_slide_timelines([segment])[0] == expected
    assert result["layout"]["passed"]


@pytest.mark.parametrize("action,target,effect", [
    ("highlight", "body", None), ("hide", "body", None), ("show", "body,component", None),
    *[("show", "body", effect) for effect in
      ("highlight", "pulse", "fadeOut", "drawPath", "growBar", "legacy")],
])
def test_D_unsafe_event_rejected_atomically(fixture_bundle, tmp_path, action, target, effect):
    segment = page()
    segment["timeline"][0].update(action=action, target=target, effect=effect)
    before = deepcopy(segment)
    with pytest.raises(ValueError, match="object map"):
        compose(segment, fixture_bundle, tmp_path / "D-reject", replace_element_id="body",
                coverage=coverage())
    assert segment == before


@pytest.mark.parametrize("location", ["element", "timeline", "animations"])
def test_research_binding_replacement_requires_object_map(fixture_bundle, tmp_path, location):
    segment = page()
    item = segment["elements"][1] if location == "element" else segment[location][0]
    item["research_p0"] = {"visual_id": "original-object"}
    before = deepcopy(segment)
    with pytest.raises(ValueError, match="object map"):
        compose(segment, fixture_bundle, tmp_path / "research-reject",
                replace_element_id="body", coverage=coverage())
    assert segment == before


@pytest.mark.parametrize("failure", [
    "hash", "collision", "missing", "dependency", "source", "coverage",
])
def test_E_integrity_and_dependencies_fail_closed(fixture_bundle, tmp_path, failure):
    segment = page()
    kwargs = {}
    if failure == "hash":
        revision, asset = fixture_bundle
        (revision / "compiled/assets" / asset["filename"]).write_text("changed", encoding="utf-8")
    elif failure == "collision":
        kwargs["element_id"] = "component"
    elif failure == "missing":
        kwargs["replace_element_id"] = "nonexistent"
    else:
        kwargs.update(replace_element_id="body", coverage=coverage())
        if failure == "dependency":
            segment["elements"].append({"id": "dependent", "type": "focus_box", "target": "body"})
        elif failure == "source":
            kwargs["coverage"]["source_evidence"] = "伪造的来源"
        elif failure == "coverage":
            kwargs["coverage"]["fact_quotes"] = []
    before = deepcopy(segment)
    with pytest.raises(ValueError):
        compose(segment, fixture_bundle, tmp_path / "E-reject", **kwargs)
    assert segment == before


@pytest.mark.parametrize("hash_location", ["element", "asset_inventory"])
def test_retained_image_hash_drift_fails_atomically_even_in_fixture_mode(
    fixture_bundle, tmp_path, hash_location,
):
    segment = page()
    image = tmp_path / "retained.svg"
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"/>',
                     encoding="utf-8")
    retained = {"id": "retained", "type": "image", "src": "retained.svg"}
    if hash_location == "element":
        retained["visual_asset_sha256"] = "0" * 64
    else:
        segment["local_visual_operations"] = [{"asset_inventory": [{
            "key": "water-lesson:retained", "path": "images/retained.svg",
            "sha256": "0" * 64,
        }]}]
    segment["elements"].append(retained)
    before = deepcopy(segment)
    output = tmp_path / f"retained-hash-{hash_location}"
    with pytest.raises(ValueError, match="retained image hash drift"):
        compose(segment, fixture_bundle, output,
                images={"water-lesson:retained": str(image)})
    assert segment == before
    assert not output.exists()


def test_new_asset_filename_collision_gets_deterministic_unique_name(fixture_bundle, tmp_path):
    revision, asset = fixture_bundle
    segment = page()
    collision_name = f"local-visual-{asset['sha256'][:16]}.svg"
    source = tmp_path / collision_name
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 20"/>',
                      encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    segment["elements"] = [segment["elements"][0], {
        "id": "existing-image", "type": "image", "src": collision_name,
        "visual_asset_sha256": source_hash,
    }]
    segment["timeline"] = []
    segment["animations"] = []
    result = compose(segment, fixture_bundle, tmp_path / "filename-collision",
                     images={"water-lesson:existing-image": str(source)})
    saved, assets = course_visuals.load_local_storyboard_page(
        tmp_path / "filename-collision" / "storyboard.json", "water-lesson"
    )
    existing = next(e for e in saved["elements"] if e["id"] == "existing-image")
    inserted = next(e for e in saved["elements"] if e["id"].startswith("local-visual-"))
    assert existing["src"] == collision_name
    assert inserted["src"] != collision_name
    copied_hash = hashlib.sha256(
        Path(assets[f"water-lesson:{existing['id']}"]).read_bytes()
    ).hexdigest()
    assert copied_hash == source_hash
    assert result["layout"]["save_reload_render"]["passed"]


def test_F_crowded_page_rejected_without_deleting_or_shrinking(fixture_bundle, tmp_path):
    segment = page()
    segment["elements"].extend({"id": f"paragraph-{i}", "type": "text", "text": SOURCE * 10}
                               for i in range(8))
    before = deepcopy(segment)
    with pytest.raises(ValueError, match="adjustment or page split"):
        compose(segment, fixture_bundle, tmp_path / "F-crowded")
    assert segment == before
    report = json.loads((tmp_path / "F-crowded/layout.json").read_text(encoding="utf-8"))
    assert all(v["issues"] for v in report["viewports"])


def test_unreviewed_asset_needs_explicit_fixture_mode(fixture_bundle, tmp_path):
    revision, asset = fixture_bundle
    segment = page()
    before = deepcopy(segment)
    with pytest.raises(ValueError, match="unreviewed"):
        course_visuals.compose_local_visual(segment, revision=revision, asset_id=asset["id"],
                                           output_dir=tmp_path / "not-approved")
    assert segment == before


def test_replacement_refs_must_identify_rendered_facts(fixture_bundle, tmp_path):
    segment = page()
    before = deepcopy(segment)
    proof = coverage()
    proof["visual_refs"] = ["water-cycle:condensation"]
    with pytest.raises(ValueError, match="adjustment or page split"):
        compose(segment, fixture_bundle, tmp_path / "unrepresented-content",
                replace_element_id="body", coverage=proof)
    assert segment == before
    report = json.loads((tmp_path / "unrepresented-content/layout.json").read_text("utf-8"))
    assert any(i["type"] == "replacement_fact_not_visible"
               for v in report["viewports"] for i in v["issues"])


def test_insertion_does_not_make_unresolved_positional_events_resolve():
    segment = page()
    segment["timeline"] = [{"target": "e4", "at_sec": 1}]
    with pytest.raises(ValueError, match="unrelated compiled event"):
        apply_local_visual_plan(segment, {"id": "new", "type": "image"})
