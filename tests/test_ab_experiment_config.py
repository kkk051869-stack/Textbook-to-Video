import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from textbook2video.research.experiment_config import (
    ExperimentConfigError,
    validate_experiment_config,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "ab_experiment_config_v1.schema.json"
DATASET_SCHEMA_PATH = ROOT / "contracts" / "ab_dataset_manifest_v1.schema.json"
FROZEN_SCHEMA_PATH = ROOT / "contracts" / "ab_frozen_file_manifest_v1.schema.json"
TEMPLATE_PATH = ROOT / "configs" / "experiments" / "ab_single_lesson_pilot.template.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _file_ref(root: Path, relative: str, content: str) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _frozen_manifest_ref(
    root: Path,
    *,
    relative: str,
    artifact_type: str,
    payload_relative: str,
    payload_content: str,
) -> dict[str, str]:
    payload = _file_ref(root, payload_relative, payload_content)
    return _file_ref(
        root,
        relative,
        json.dumps(
            {
                "schema_version": "t2v-frozen-file-manifest-v1",
                "manifest_id": f"test-{artifact_type}-v1",
                "artifact_type": artifact_type,
                "files": [
                    {
                        "file_id": f"test-{artifact_type}-file-1",
                        "role": "frozen-input",
                        **payload,
                    }
                ],
            }
        ),
    )


def _runnable_config(tmp_path: Path) -> tuple[Path, Path, dict]:
    for source in (SCHEMA_PATH, DATASET_SCHEMA_PATH, FROZEN_SCHEMA_PATH):
        schema_target = tmp_path / "contracts" / source.name
        schema_target.parent.mkdir(parents=True, exist_ok=True)
        schema_target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    config = _load(TEMPLATE_PATH)
    config["config_status"] = "RUNNABLE"
    config["run_id"] = "20261017-aaaaaaaa-ab-pilot"
    config["dataset"]["dataset_id"] = "ab-real-lessons-dev-v1"
    source_reference = _file_ref(tmp_path, "datasets/ab-real-lessons-dev-v1/source.json", "{}")
    config["dataset"]["manifest"] = _file_ref(
        tmp_path,
        "datasets/ab-real-lessons-dev-v1/manifest.json",
        json.dumps(
            {
                "schema_version": "t2v-ab-dataset-manifest-v1",
                "dataset_id": "ab-real-lessons-dev-v1",
                "split": "dev",
                "case_ids": ["lesson_002"],
                "files": [
                    {
                        "file_id": "lesson-002-source",
                        "case_id": "lesson_002",
                        "role": "source",
                        **source_reference,
                    }
                ],
            }
        ),
    )
    config["model"] = {
        "provider": "ecnu",
        "model_id": "ecnu-plus",
        "api_base_label": "ECNU_GATEWAY",
    }
    config["frozen_inputs"] = {
        "research_schema": _file_ref(tmp_path, "contracts/research.json", "{}"),
        "prompts": [_file_ref(tmp_path, "prompts/p0.md", "frozen prompt")],
        "gold": _file_ref(tmp_path, "evaluation/gold.json", '{"gold": true}'),
        "gold_access_stage": "evaluation-only",
        "candidate_universe": _frozen_manifest_ref(
            tmp_path,
            relative="inputs/universe.manifest.json",
            artifact_type="candidate-universe",
            payload_relative="inputs/universe.json",
            payload_content="[]",
        ),
        "candidate_subset": _frozen_manifest_ref(
            tmp_path,
            relative="inputs/subset.manifest.json",
            artifact_type="candidate-subset",
            payload_relative="inputs/subset.json",
            payload_content="[]",
        ),
        "narration_manifest": _frozen_manifest_ref(
            tmp_path,
            relative="inputs/narration.manifest.json",
            artifact_type="narration",
            payload_relative="inputs/narration.json",
            payload_content="{}",
        ),
        "audio_manifest": _frozen_manifest_ref(
            tmp_path,
            relative="inputs/audio.manifest.json",
            artifact_type="audio",
            payload_relative="inputs/audio.json",
            payload_content="{}",
        ),
    }
    config["outputs"]["root"] = "runs/ab-single-lesson-pilot-v1/20261017-aaaaaaaa-ab-pilot"
    config_path = tmp_path / "configs" / "run.json"
    _write_json(config_path, config)
    return tmp_path, config_path, config


def test_ab_experiment_template_matches_schema() -> None:
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_load(TEMPLATE_PATH))


def test_filled_runnable_config_verifies_hashes_and_gold_isolation(tmp_path: Path) -> None:
    root, config_path, _config = _runnable_config(tmp_path)
    result = validate_experiment_config(config_path, repo_root=root, expected_mode="pilot")
    assert result["config_sha256"]
    assert len(result["verified_files"]) == 13


def test_text_hash_accepts_lf_crlf_checkout_equivalence(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    prompt_path = root / config["frozen_inputs"]["prompts"][0]["path"]
    prompt_path.write_bytes(b"first line\nsecond line\n")
    config["frozen_inputs"]["prompts"][0]["sha256"] = hashlib.sha256(
        b"first line\r\nsecond line\r\n"
    ).hexdigest()
    _write_json(config_path, config)

    result = validate_experiment_config(config_path, repo_root=root, expected_mode="pilot")

    prompt_entry = next(
        item
        for item in result["verified_files"]
        if item["label"] == "frozen_inputs.prompts[0]"
    )
    assert prompt_entry["sha256"] == hashlib.sha256(
        b"first line\nsecond line\n"
    ).hexdigest()


def test_gold_isolation_compares_text_after_line_ending_normalization(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    prompt_path = root / config["frozen_inputs"]["prompts"][0]["path"]
    prompt_path.write_bytes(b"same\ncontent\n")
    config["frozen_inputs"]["prompts"][0]["sha256"] = hashlib.sha256(
        prompt_path.read_bytes()
    ).hexdigest()
    gold_path = root / config["frozen_inputs"]["gold"]["path"]
    gold_path.write_bytes(b"same\r\ncontent\r\n")
    config["frozen_inputs"]["gold"]["sha256"] = hashlib.sha256(
        gold_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)

    with pytest.raises(ExperimentConfigError, match="gold/evaluation content hash"):
        validate_experiment_config(config_path, repo_root=root, expected_mode="pilot")


def test_runnable_config_rejects_placeholder_anywhere(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["dataset"]["case_ids"][0] = "TODO_REPLACE_CASE"
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="unresolved placeholder"):
        validate_experiment_config(config_path, repo_root=root)


def test_fill_me_in_placeholder_is_rejected(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["run_id"] = "FILL_ME_IN"
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="unresolved placeholder"):
        validate_experiment_config(config_path, repo_root=root)


def test_non_locked_mode_cannot_access_locked_split(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["mode"] = "development"
    config["dataset"]["split"] = "locked-test"
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="schema validation failed"):
        validate_experiment_config(config_path, repo_root=root)


def test_locked_test_requires_hashed_authorization_record(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["mode"] = "locked-test"
    config["dataset"]["split"] = "locked-test"
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    manifest["split"] = "locked-test"
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="schema validation failed"):
        validate_experiment_config(config_path, repo_root=root)

    evidence = _file_ref(root, "authorizations/locked-test.md", "approved once")
    config["locked_test_authorization"] = {
        "authorization_id": "locked-test-20261017-v1",
        "run_id": config["run_id"],
        "authorized_by": "research-lead",
        "authorized_at": "2026-10-17T13:30:00+08:00",
        "purpose": "single-use-locked-test",
        "evidence": evidence,
    }
    _write_json(config_path, config)
    validate_experiment_config(config_path, repo_root=root, expected_mode="locked-test")

    with pytest.raises(ExperimentConfigError, match="does not match requested mode"):
        validate_experiment_config(
            config_path,
            repo_root=root,
            expected_mode="development",
            require_runnable=False,
        )


def test_gold_cannot_be_reused_as_generation_input(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["frozen_inputs"]["prompts"][0] = deepcopy(config["frozen_inputs"]["gold"])
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="gold/evaluation"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_manifest_cannot_reference_gold_path_or_hash(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    gold = config["frozen_inputs"]["gold"]
    manifest_path = root / config["dataset"]["manifest"]["path"]
    _write_json(
        manifest_path,
        {
            "schema_version": "t2v-ab-dataset-manifest-v1",
            "dataset_id": config["dataset"]["dataset_id"],
            "split": config["dataset"]["split"],
            "case_ids": config["dataset"]["case_ids"],
            "files": [
                {
                    "file_id": "forbidden-gold",
                    "case_id": "lesson_002",
                    "role": "source",
                    "path": "./evaluation/./gold.json",
                    "sha256": gold["sha256"],
                }
            ],
        },
    )
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="gold/evaluation path"):
        validate_experiment_config(config_path, repo_root=root)


def test_dataset_manifest_rejects_transitive_path_without_hash(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    _write_json(
        manifest_path,
        {
            "schema_version": "t2v-ab-dataset-manifest-v1",
            "dataset_id": config["dataset"]["dataset_id"],
            "split": config["dataset"]["split"],
            "case_ids": config["dataset"]["case_ids"],
            "files": [
                {
                    "file_id": "source-without-hash",
                    "case_id": "lesson_002",
                    "role": "source",
                    "path": "datasets/ab-real-lessons-dev-v1/source.json",
                }
            ],
        },
    )
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="schema validation failed"):
        validate_experiment_config(config_path, repo_root=root)


def test_dataset_manifest_rejects_nonstandard_file_field(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    manifest["file"] = "./evaluation/./gold.json"
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="Additional properties"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_payload_string_cannot_resolve_to_gold(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"file": "./evaluation/./gold.json"})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="resolves a string to gold"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_payload_cannot_reference_undeclared_local_file(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    secondary_path = root / "datasets/ab-real-lessons-dev-v1/secondary.json"
    _write_json(secondary_path, {"undeclared": True})
    source_path = root / manifest["files"][0]["path"]
    _write_json(
        source_path,
        {"next_manifest": "datasets/ab-real-lessons-dev-v1/secondary.json"},
    )
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="references undeclared local file"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_payload_cannot_assemble_gold_path_from_fields(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"directory": "evaluation", "filename": "gold.json"})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="resolves a string to gold"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_payload_cannot_reference_undeclared_file_uri(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    secondary_path = root / "datasets/ab-real-lessons-dev-v1/secondary.json"
    _write_json(secondary_path, {"undeclared": True})
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"next_manifest": secondary_path.as_uri()})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="references undeclared local file"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_payload_cannot_reference_percent_encoded_gold_uri(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    gold_path = root / config["frozen_inputs"]["gold"]["path"]
    encoded_gold_uri = gold_path.as_uri().replace("gold.json", "g%6fld.json")
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"reference": encoded_gold_uri})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="resolves a string to gold"):
        validate_experiment_config(config_path, repo_root=root)


def test_plain_text_prompt_cannot_reference_percent_encoded_gold_uri(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    gold_path = root / config["frozen_inputs"]["gold"]["path"]
    encoded_gold_uri = gold_path.as_uri().replace("gold.json", "g%6fld.json")
    prompt_path = root / config["frozen_inputs"]["prompts"][0]["path"]
    prompt_path.write_text(f"Read {encoded_gold_uri} before generation", encoding="utf-8")
    config["frozen_inputs"]["prompts"][0]["sha256"] = hashlib.sha256(
        prompt_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="resolves a string to gold"):
        validate_experiment_config(config_path, repo_root=root)


def test_windows_double_slash_path_is_still_a_local_dependency(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    secondary_path = root / "datasets/ab-real-lessons-dev-v1/secondary.json"
    _write_json(secondary_path, {"undeclared": True})
    doubled_slash_path = str(secondary_path).replace("\\", "/").replace(":/", "://", 1)
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"next_manifest": doubled_slash_path})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="references undeclared local file"):
        validate_experiment_config(config_path, repo_root=root)


def test_long_normalizable_local_path_is_not_skipped(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    secondary_relative = "datasets/ab-real-lessons-dev-v1/secondary.json"
    _write_json(root / secondary_relative, {"undeclared": True})
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"next_manifest": "./" * 600 + secondary_relative})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="references undeclared local file"):
        validate_experiment_config(config_path, repo_root=root)


def test_development_without_gold_still_rejects_undeclared_local_file(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["mode"] = "development"
    config["frozen_inputs"]["gold"] = None
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    secondary_path = root / "datasets/ab-real-lessons-dev-v1/secondary.json"
    _write_json(secondary_path, {"undeclared": True})
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {"next_manifest": secondary_path.as_uri()})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="references undeclared local file"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_json_path_analysis_has_a_fail_closed_budget(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, {f"field_{index}": f"value_{index}" for index in range(65)})
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="too many string fields"):
        validate_experiment_config(config_path, repo_root=root)


def test_generation_json_direct_strings_share_the_candidate_budget(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    manifest_path = root / config["dataset"]["manifest"]["path"]
    manifest = _load(manifest_path)
    source_path = root / manifest["files"][0]["path"]
    _write_json(source_path, [f"value_{index}" for index in range(10_001)])
    manifest["files"][0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    _write_json(manifest_path, manifest)
    config["dataset"]["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="local-path candidate budget"):
        validate_experiment_config(config_path, repo_root=root)


def test_prompt_text_cannot_resolve_equivalent_gold_path(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    prompt_path = root / config["frozen_inputs"]["prompts"][0]["path"]
    prompt_path.write_text("Read ./evaluation/./gold.json before generation", encoding="utf-8")
    config["frozen_inputs"]["prompts"][0]["sha256"] = hashlib.sha256(
        prompt_path.read_bytes()
    ).hexdigest()
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="resolves a string to gold"):
        validate_experiment_config(config_path, repo_root=root)


def test_file_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    config["frozen_inputs"]["research_schema"]["sha256"] = "0" * 64
    _write_json(config_path, config)
    with pytest.raises(ExperimentConfigError, match="SHA-256 mismatch"):
        validate_experiment_config(config_path, repo_root=root)


def test_existing_output_directory_is_rejected(tmp_path: Path) -> None:
    root, config_path, config = _runnable_config(tmp_path)
    (root / config["outputs"]["root"]).mkdir(parents=True)
    with pytest.raises(ExperimentConfigError, match="already exists"):
        validate_experiment_config(config_path, repo_root=root)
