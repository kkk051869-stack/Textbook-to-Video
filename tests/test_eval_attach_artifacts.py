import hashlib
import json

from textbook2video.eval.attach_artifacts import attach_artifacts
from textbook2video.eval.dataset import load_case


def test_attach_artifacts_records_relative_path_and_hash(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "case_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "textbookeval-case-v0.1",
                "case_id": "case_demo",
                "lesson_id": "lesson_demo",
                "status": "candidate",
                "dataset_version": "pilot3-test",
                "source": {
                    "files": [
                        {
                            "role": "source_json",
                            "path": "source.json",
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    storyboard = artifacts / "storyboard.json"
    storyboard.write_text("{}", encoding="utf-8")

    attach_artifacts(
        manifest,
        artifacts,
        ["storyboard=storyboard.json"],
        system_id="internal_C01",
        provenance="cloud historical baseline",
    )
    case = load_case(manifest)

    assert case.raw["baseline_artifacts"]["storyboard"]["path"] == "storyboard.json"
    assert case.raw["baseline_artifacts"]["storyboard"]["sha256"] == hashlib.sha256(
        storyboard.read_bytes()
    ).hexdigest()
    assert case.raw["systems"]["baseline"]["system_id"] == "internal_C01"

    html = artifacts / "animation.html"
    html.write_text("<html></html>", encoding="utf-8")
    attach_artifacts(
        manifest,
        artifacts,
        ["html=animation.html"],
        system_id="internal_C01",
    )
    updated = load_case(manifest)
    assert "storyboard" in updated.raw["baseline_artifacts"]
    assert "html" in updated.raw["baseline_artifacts"]
