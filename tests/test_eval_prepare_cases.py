import json

from textbook2video.eval.dataset import load_case
from textbook2video.eval.prepare_cases import prepare_candidate_case


def test_prepare_candidate_keeps_draft_status_and_splits_heldout(tmp_path):
    package = tmp_path / "package"
    source = package / "sources" / "frozen" / "lesson_001"
    private = package / "private_annotations" / "B" / "lesson_001"
    (source / "images").mkdir(parents=True)
    private.mkdir(parents=True)
    (source / "source.json").write_text("{}", encoding="utf-8")
    (source / "source.pdf").write_bytes(b"pdf")
    (source / "images" / "figure.png").write_bytes(b"png")
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "lesson_id": "lesson_001",
                "title": "Demo",
                "source_type": "docx",
                "source_locator": "chapter=1",
                "paragraph_count": 2,
                "image_count": 1,
                "review_status": "draft",
            }
        ),
        encoding="utf-8",
    )
    (private / "annotation.json").write_text(
        json.dumps(
            {
                "lesson_id": "lesson_001",
                "annotation_status": "draft",
                "heldout_questions": [{"id": "q1", "question": "Demo?"}],
            }
        ),
        encoding="utf-8",
    )

    manifest_path = prepare_candidate_case(
        package,
        tmp_path / "dataset",
        "lesson_001",
        dataset_version="pilot3-test",
    )
    case = load_case(manifest_path)

    assert case.status == "candidate"
    assert case.raw["metadata"]["freeze_blocked"] is True
    assert case.raw["annotation"]["review_status"] == "draft"
    heldout = json.loads((manifest_path.parent / "private" / "heldout_questions.json").read_text())
    assert heldout["questions"][0]["id"] == "q1"
    assert any(asset.role == "source_image_01" for asset in case.assets())
