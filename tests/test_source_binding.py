import hashlib
import json
import shutil
from pathlib import Path

import pytest

from textbook2video.pipeline import source_binding


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "repo"
    (root / "contracts").mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "contracts/ab_dataset_manifest_v1.schema.json",
        root / "contracts/ab_dataset_manifest_v1.schema.json",
    )
    dataset = root / "dataset"
    case = dataset / "cases/lesson_002"
    (case / "baseline").mkdir(parents=True)
    (case / "source").mkdir()
    board = case / "baseline/storyboard.json"
    board.write_text('{"segments": []}', encoding="utf-8")
    text = case / "source/text.md"
    text.write_bytes("教材原文。\n".encode("utf-8"))
    files = [
        {
            "file_id": role,
            "case_id": "lesson_002",
            "role": role,
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for role, path in [("storyboard", board), ("source", text)]
    ]
    manifest = {
        "schema_version": "t2v-ab-dataset-manifest-v1",
        "dataset_id": "test",
        "split": "dev",
        "case_ids": ["lesson_002"],
        "files": files,
    }
    return root, board, text, dataset / "dataset_manifest.json", manifest


def save_manifest(package):
    package[3].write_text(json.dumps(package[4]), encoding="utf-8")


def test_binding_resolves_exact_manifest_source_and_normalized_text_hash(package):
    root, board, text, _, _ = package
    save_manifest(package)
    text.write_bytes(text.read_bytes().replace(b"\n", b"\r\n"))
    binding = source_binding.bind_storyboard_source(board, repo_root=root)
    assert binding["source_path"] == str(text.resolve())
    assert binding["source_sha256"] == hashlib.sha256(text.read_bytes()).hexdigest()
    assert binding["source_sha256"] != binding["declared_source_sha256"]


@pytest.mark.parametrize(
    "problem",
    [
        "source_hash",
        "board_hash",
        "duplicate_source",
        "duplicate_board",
        "missing_source",
        "wrong_case",
        "cross_case_path",
        "escape",
        "locked-test",
        "validation",
        "case_ids",
    ],
)
def test_invalid_binding_fails_before_output_copy(package, problem):
    root, board, text, _, manifest = package
    if problem == "source_hash":
        text.write_text("改过的原文", encoding="utf-8")
    elif problem == "board_hash":
        board.write_text('{"changed": true}', encoding="utf-8")
    elif problem == "duplicate_source":
        manifest["files"].append(dict(manifest["files"][1]))
    elif problem == "duplicate_board":
        manifest["files"].append(dict(manifest["files"][0]))
    elif problem == "missing_source":
        manifest["files"].pop()
    elif problem == "wrong_case":
        manifest["files"][1]["case_id"] = "lesson_003"
    elif problem == "cross_case_path":
        other = text.parents[2] / "lesson_003.md"
        other.write_bytes(text.read_bytes())
        manifest["files"][1]["path"] = other.relative_to(root).as_posix()
    elif problem == "escape":
        manifest["files"][1]["path"] = "../outside.md"
    elif problem == "case_ids":
        manifest["case_ids"] = ["lesson_003"]
    else:
        manifest["split"] = problem
    save_manifest(package)
    with pytest.raises(ValueError):
        source_binding.bind_storyboard_source(board, repo_root=root)


def test_unmanifested_files_do_not_guess_source_md(package):
    root, board, _, _, _ = package
    assert source_binding.bind_storyboard_source(board, repo_root=root) is None


def test_adapter_attaches_manifest_before_copy_or_tts(package, monkeypatch):
    from textbook2video.pipeline import orchestrator

    root, board, text, _, _ = package
    save_manifest(package)
    real_bind = source_binding.bind_storyboard_source
    monkeypatch.setattr(
        source_binding, "bind_storyboard_source", lambda path: real_bind(path, repo_root=root)
    )
    before = board.read_bytes()
    output = root / "output"
    artifacts = orchestrator._artifacts_from_storyboard(board, output_dir=output, skip_tts=True)
    assert artifacts.raw_path == text.resolve() and board.read_bytes() == before
    working = json.loads(artifacts.storyboard_path.read_text(encoding="utf-8"))
    assert working["metadata"]["textbook_source_binding"]["case_id"] == "lesson_002"
    with pytest.raises(ValueError, match="separate output"):
        orchestrator._artifacts_from_storyboard(board, skip_tts=True)
    with pytest.raises(ValueError, match="outside the dataset"):
        orchestrator._artifacts_from_storyboard(
            board, output_dir=board.parents[2] / "another-output", skip_tts=True
        )
    text.write_text("hash changed", encoding="utf-8")
    untouched = root / "untouched"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        orchestrator._artifacts_from_storyboard(board, output_dir=untouched, skip_tts=True)
    assert not untouched.exists()
