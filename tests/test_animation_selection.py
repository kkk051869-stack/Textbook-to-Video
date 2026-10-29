from textbook2video.animation_gen import (
    _remove_blocked_image_events,
    load_textbook_images,
    parse_storyboard,
    page_selection_suffix,
    select_segments_by_pages,
)


def _segment(segment_id):
    return {"id": segment_id, "narration": f"slide {segment_id}"}


def test_select_segments_by_pages_preserves_order_and_dedupes():
    segments = [_segment(1), _segment(2), _segment(3)]

    selected = select_segments_by_pages(segments, [3, 1, 3])

    assert [seg["id"] for seg in selected] == [3, 1]


def test_select_segments_by_pages_rejects_out_of_range():
    segments = [_segment(1), _segment(2)]

    try:
        select_segments_by_pages(segments, [2, 4])
    except ValueError as exc:
        assert "有效范围 1-2" in str(exc)
    else:
        raise AssertionError("out-of-range page should be rejected")


def test_page_selection_suffix_is_stable():
    assert page_selection_suffix(None) == ""
    assert page_selection_suffix([3]) == "-p3"
    assert page_selection_suffix([2, 4, 4, 6]) == "-p2_4_6"


def test_inventoried_source_image_requires_accept_review(tmp_path):
    (tmp_path / "frame.jpeg").write_bytes(b"not-decoded-in-this-test")
    image = {
        "id": "source_frame",
        "type": "image",
        "src": "frame.jpeg",
        "source_image_id": "pdf-p004-img01",
    }
    segments = [{"id": 2, "elements": [image]}]

    result = load_textbook_images(
        segments,
        tmp_path,
        [{"id": "pdf-p004-img01", "filename": "frame.jpeg"}],
    )

    assert result == {}
    assert image["_render_blocked"] is True


def test_accepted_source_image_and_unrelated_events_are_preserved(tmp_path):
    (tmp_path / "diagram.svg").write_text("<svg/>", encoding="utf-8")
    image = {
        "id": "diagram",
        "type": "image",
        "src": "diagram.svg",
        "source_image_id": "figure-1",
        "visual_relevance_verdict": "ACCEPT",
    }
    segments = [{
        "id": 1,
        "elements": [image, {"id": "label", "type": "text", "text": "kept"}],
        "animations": [
            {"target": "diagram", "effect": "fadeIn"},
            {"target": "label", "effect": "fadeIn"},
        ],
        "timeline": [{"target": "diagram,label", "action": "show"}],
    }]

    result = load_textbook_images(
        segments,
        tmp_path,
        [{"id": "figure-1", "filename": "diagram.svg"}],
    )
    _remove_blocked_image_events(segments)

    assert result == {"1:diagram": str(tmp_path / "diagram.svg")}
    assert [item["target"] for item in segments[0]["animations"]] == ["diagram", "label"]
    assert segments[0]["timeline"] == [{"target": "diagram,label", "action": "show"}]


def test_generated_asset_is_not_treated_as_an_unreviewed_courseware_source(tmp_path):
    (tmp_path / "auto.svg").write_text("<svg/>", encoding="utf-8")
    image = {"id": "auto", "type": "image", "src": "auto.svg"}

    result = load_textbook_images(
        [{"id": 1, "elements": [image]}],
        tmp_path,
        [{"id": "auto-001", "filename": "auto.svg", "vlm_verdict": "REJECT"}],
    )

    assert result == {"1:auto": str(tmp_path / "auto.svg")}
    assert "_render_blocked" not in image


def test_blocked_source_image_events_are_removed_without_hiding_other_targets():
    segments = [{
        "id": 1,
        "elements": [
            {"id": "bad", "type": "image", "_render_blocked": True},
            {"id": "label", "type": "text", "text": "kept"},
        ],
        "animations": [{"target": "bad", "effect": "fadeIn"}],
        "timeline": [{"target": "bad,label", "action": "show"}],
    }]

    _remove_blocked_image_events(segments)

    assert segments[0]["animations"] == []
    assert segments[0]["timeline"] == [{"target": "label", "action": "show"}]


def test_parse_storyboard_retains_source_review_inventory(tmp_path):
    storyboard_path = tmp_path / "storyboard.json"
    storyboard_path.write_text(
        """{
          "lesson_title": "Test",
          "segments": [{
            "id": 1, "visual_type": "illustration", "narration": "Narration",
            "elements": [{"id": "h", "type": "heading", "text": "Title"}]
          }],
          "metadata": {
            "total_slides": 1,
            "available_images": [{"id": "source-1", "vlm_verdict": "REJECT"}]
          }
        }""",
        encoding="utf-8",
    )

    parsed = parse_storyboard(storyboard_path)

    assert parsed["metadata"]["available_images"][0]["vlm_verdict"] == "REJECT"

def test_blocked_picture_annotation_events_follow_renderer_exclusion():
    segments = [{"id": 1, "elements": [
        {"id": "picture", "type": "image", "_render_blocked": True},
        {"id": "focus", "type": "focus_box", "target": "picture"},
        {"id": "callout", "type": "callout", "target_image": "picture"},
        {"id": "body", "type": "text", "text": "Preserved"}],
        "timeline": [{"target": "focus,body", "action": "show"}],
        "animations": [{"target": "callout", "effect": "highlight"}]}]
    audit = _remove_blocked_image_events(segments)
    assert segments[0]["timeline"] == [{"target": "body", "action": "show"}]
    assert segments[0]["animations"] == []
    assert audit[0]["blocked_images"] == ["picture"]
    assert audit[0]["excluded_targets"] == ["callout", "focus", "picture"]
    assert len(audit[0]["events"]) == 2
