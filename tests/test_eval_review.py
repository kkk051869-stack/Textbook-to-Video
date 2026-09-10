from textbook2video.eval.review import build_review_index, write_review_index


def test_review_index_links_issue_to_registered_evidence(tmp_path):
    report = {
        "run_id": "run-demo",
        "case_id": "case-demo",
        "lesson_id": "lesson-demo",
        "issues": [
            {
                "evaluator": "vlm_readability",
                "severity": "major",
                "type": "READABILITY_LOW_SCORE",
                "message": "text is clipped",
                "slide": 2,
                "evidence_ids": ["frame-2"],
                "review_status": "unreviewed",
            }
        ],
        "evidence": [
            {
                "evidence_id": "frame-2",
                "kind": "video_frame",
                "path": "frames/frame-002.jpg",
            }
        ],
    }

    index = build_review_index([report])

    assert index["pending_count"] == 1
    assert index["items"][0]["slide"] == 2
    assert index["items"][0]["evidence"][0]["path"] == "frames/frame-002.jpg"
    json_path, markdown_path = write_review_index(tmp_path, [report])
    assert json_path.exists()
    assert "frame-002.jpg" in markdown_path.read_text(encoding="utf-8")
