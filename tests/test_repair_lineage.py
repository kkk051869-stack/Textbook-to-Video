import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.repair.lineage import RepairLineageWriter, artifact_reference
from textbook2video.repair.storyboard import repair_storyboard_with_lineage


def test_artifact_reference_hashes_existing_and_explains_missing(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"fixture")
    ref = artifact_reference(artifact, root=tmp_path)
    assert ref.path == "artifact.bin"
    assert ref.sha256 == hashlib.sha256(b"fixture").hexdigest()

    missing = artifact_reference(tmp_path / "missing.bin", root=tmp_path)
    assert missing.path is None
    assert missing.sha256 is None
    assert "does not exist" in (missing.reason or "")


def test_lineage_writer_appends_and_rejects_duplicate_ids(tmp_path):
    lineage = RepairLineageWriter(tmp_path / "repair_lineage.json", case_id="case", run_id="run")
    before = tmp_path / "before.bin"
    after = tmp_path / "after.bin"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    record = lineage.append_record(
        repair_id="r1",
        case_id="case",
        run_id="run",
        source_issue_id="i1",
        issue_type="LAYOUT_ISSUE",
        stage="render",
        severity="major",
        repair_strategy="deterministic_css",
        round=1,
        before_artifact=before,
        after_artifact=after,
        result="succeeded",
        model="N/A",
        token=None,
    )
    assert record["before_artifact"]["sha256"] == hashlib.sha256(b"before").hexdigest()
    assert record["after_artifact"]["sha256"] == hashlib.sha256(b"after").hexdigest()
    loaded = json.loads((tmp_path / "repair_lineage.json").read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "textbookeval-repair-lineage-v0.1"
    assert len(loaded["repairs"]) == 1
    with pytest.raises(ValueError, match="duplicate repair_id"):
        lineage.append_record(
            repair_id="r1", case_id="case", run_id="run", source_issue_id="i1",
            issue_type="LAYOUT_ISSUE", stage="render", severity="major",
            repair_strategy="deterministic_css", round=1,
            before_artifact=before, after_artifact=after,
        )


def test_existing_storyboard_repair_writes_candidate_and_lineage(tmp_path):
    storyboard = tmp_path / "storyboard.json"
    storyboard.write_text(json.dumps({
        "lesson_title": "Demo",
        "segments": [{
            "id": 1,
            "narration": "这是一个足够长的核心概念讲解，用于确定性修复 fixture。",
            "visual_type": "definition",
            "elements": [{"id": "title", "type": "heading", "text": "核心概念"}],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    candidate, record = repair_storyboard_with_lineage(
        storyboard,
        candidate_dir=tmp_path / "candidate-work",
        case_id="case",
        run_id="run",
        source_issue={"issue_id": "i1", "type": "STORYBOARD_THIN", "stage": "storyboard", "severity": "major"},
    )
    assert storyboard.read_bytes() != candidate.read_bytes()
    assert record["repair_id"]
    assert record["repair_strategy"] == "storyboard_repair"
    lineage = json.loads((tmp_path / "candidate-work" / "repair_lineage.json").read_text(encoding="utf-8"))
    assert len(lineage["repairs"]) == 1
    assert lineage["repairs"][0]["model"] == "N/A"
    assert lineage["repairs"][0]["token"] is None
