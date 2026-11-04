from __future__ import annotations

import hashlib
import json
from pathlib import Path

from textbook2video.research.visual_acquisition import execute_visual_acquisition


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def test_strict_license_gate_hash_checks_then_blocks_unverified_source_reuse(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source-image")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = tmp_path / "evidence.json"
    _write(evidence, {
        "source_images": [{
            "id": "figure-1",
            "local_path": str(source),
            "sha256": digest,
            "rights_status": "ARXIV_NONEXCLUSIVE_DISTRIBUTION_ONLY_REUSE_UNVERIFIED",
            "source_locator": "paper page 2",
        }]
    })
    decisions = tmp_path / "decisions.json"
    _write(decisions, {"decisions": [{
        "narration_proposition_id": "claim-1",
        "action": "reuse",
        "source_image_id": "figure-1",
    }]})

    result_path = execute_visual_acquisition(
        decision_path=decisions,
        output_dir=tmp_path / "out",
        source_evidence_path=evidence,
        enable_generation=False,
        require_explicit_license=True,
    )
    asset = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert asset["status"] == "SOURCE_REUSE_RIGHTS_NOT_CLEARED"
    assert asset["sha256"] == digest
    assert not list((tmp_path / "out" / "images").glob("*"))


def test_strict_license_gate_blocks_unverified_retrieval_without_materializing(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"candidate-image")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    catalog = tmp_path / "catalog.json"
    _write(catalog, {"assets": [{
        "id": "candidate-1",
        "path": str(candidate),
        "sha256": digest,
        "license": "ARXIV_NONEXCLUSIVE_DISTRIBUTION_ONLY_REUSE_UNVERIFIED",
        "caption": "FineGym temporal and semantic hierarchy",
        "tags": "temporal semantic hierarchy",
    }]})
    decisions = tmp_path / "decisions.json"
    _write(decisions, {"decisions": [{
        "narration_proposition_id": "claim-1",
        "action": "retrieve",
        "retrieval_query": "temporal semantic hierarchy",
    }]})

    result_path = execute_visual_acquisition(
        decision_path=decisions,
        output_dir=tmp_path / "out",
        retrieval_catalog_path=catalog,
        enable_generation=False,
        min_retrieval_score=0.0,
        require_explicit_license=True,
    )
    asset = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert asset["status"] == "RETRIEVAL_RIGHTS_NOT_CLEARED"
    assert asset["best_candidate_id"] == "candidate-1"
    assert asset["sha256"] == digest
    assert not list((tmp_path / "out" / "images").glob("*"))


def test_explicit_cc0_still_materializes_in_strict_mode(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    candidate.write_bytes(b"candidate-image")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    catalog = tmp_path / "catalog.json"
    _write(catalog, {"assets": [{
        "id": "candidate-1",
        "path": str(candidate),
        "sha256": digest,
        "license": "CC0 Public Domain",
        "caption": "Coral reef image",
        "tags": "coral reef",
    }]})
    decisions = tmp_path / "decisions.json"
    _write(decisions, {"decisions": [{
        "narration_proposition_id": "claim-1",
        "action": "retrieve",
        "retrieval_query": "coral reef",
    }]})

    result_path = execute_visual_acquisition(
        decision_path=decisions,
        output_dir=tmp_path / "out",
        retrieval_catalog_path=catalog,
        enable_generation=False,
        require_explicit_license=True,
    )
    asset = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert asset["status"] == "RETRIEVED_LOCAL_RAG"
    assert Path(asset["local_path"]).is_file()
    assert asset["sha256"] == digest
