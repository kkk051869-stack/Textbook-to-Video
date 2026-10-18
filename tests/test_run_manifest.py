import hashlib
import json
from pathlib import Path

import pytest

from textbook2video.research.experiment_config import ExperimentConfigError
from textbook2video.research.run_manifest import record_input_access


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    generation = tmp_path / "generation.json"
    gold = tmp_path / "gold.json"
    generation.write_text("{}\n", encoding="utf-8")
    gold.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    access_log = output / "access_log.jsonl"
    access_log.touch()
    manifest = output / "manifest.json"
    _write_json(
        manifest,
        {
            "declared_inputs": [
                {
                    "label": "dataset.manifest.files[0]",
                    "path": "generation.json",
                    "sha256": hashlib.sha256(generation.read_bytes()).hexdigest(),
                },
                {
                    "label": "frozen_inputs.gold",
                    "path": "gold.json",
                    "sha256": hashlib.sha256(gold.read_bytes()).hexdigest(),
                },
            ],
            "access_log": "output/access_log.jsonl",
        },
    )
    return manifest, generation, gold, access_log


def test_records_declared_generation_input(tmp_path: Path) -> None:
    manifest, generation, _gold, log = _fixture(tmp_path)
    record_input_access(manifest, generation, stage="generation", repo_root=tmp_path)
    assert json.loads(log.read_text(encoding="utf-8"))["path"] == "generation.json"


def test_generation_cannot_access_gold(tmp_path: Path) -> None:
    manifest, _generation, gold, _log = _fixture(tmp_path)
    with pytest.raises(ExperimentConfigError, match="only during evaluation"):
        record_input_access(manifest, gold, stage="generation", repo_root=tmp_path)


def test_undeclared_or_changed_input_is_refused(tmp_path: Path) -> None:
    manifest, generation, _gold, _log = _fixture(tmp_path)
    undeclared = tmp_path / "other.json"
    undeclared.write_text("{}", encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="undeclared"):
        record_input_access(manifest, undeclared, stage="generation", repo_root=tmp_path)
    generation.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="hash mismatch"):
        record_input_access(manifest, generation, stage="generation", repo_root=tmp_path)


def test_gold_access_is_allowed_only_for_evaluation(tmp_path: Path) -> None:
    manifest, _generation, gold, log = _fixture(tmp_path)
    record_input_access(manifest, gold, stage="evaluation", repo_root=tmp_path)
    assert json.loads(log.read_text(encoding="utf-8"))["stage"] == "evaluation"


def test_manifest_windows_separator_is_normalized(tmp_path: Path) -> None:
    manifest, generation, _gold, log = _fixture(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["declared_inputs"][0]["path"] = "folder\\generation.json"
    generation.parent.joinpath("folder").mkdir()
    moved = generation.parent / "folder" / generation.name
    generation.replace(moved)
    _write_json(manifest, document)
    record_input_access(manifest, moved, stage="generation", repo_root=tmp_path)
    assert json.loads(log.read_text(encoding="utf-8"))["path"] == "folder/generation.json"
