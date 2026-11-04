from __future__ import annotations

import json

import pytest

from scripts import run_rq1_doc2present_v2 as rq1_v2


def test_call_ledger_reserves_before_transport_and_forbids_duplicate_or_over_budget(
    tmp_path, monkeypatch
) -> None:
    run_dir = tmp_path / "run-01"
    run_dir.mkdir()
    monkeypatch.setattr(rq1_v2.client, "litellm", None)
    monkeypatch.setattr(rq1_v2.client, "chat_with_system", lambda prompt, **kwargs: '{"ok": true}')
    protocol = {
        "budget": {"max_transport_calls": 1},
        "models": {"temperature": 0, "timeout_sec": 5},
    }
    ledger = []

    response, entry = rq1_v2._call_model(
        package_root=tmp_path,
        run_dir=run_dir,
        protocol=protocol,
        ledger=ledger,
        task_key="method:claim-1",
        stage="unit_test",
        model="fixture",
        prompt="fixed prompt",
        images=[],
        max_tokens=20,
        system_prompt="Return JSON.",
    )

    assert response == '{"ok": true}'
    assert entry["status"] == "OK"
    assert entry["reserved_before_transport"] is True
    saved = json.loads((run_dir / "calls.json").read_text(encoding="utf-8"))
    assert len(saved) == 1
    with pytest.raises(ValueError, match="already been reserved"):
        rq1_v2._call_model(
            package_root=tmp_path,
            run_dir=run_dir,
            protocol=protocol,
            ledger=ledger,
            task_key="method:claim-1",
            stage="unit_test",
            model="fixture",
            prompt="must not be sent",
            images=[],
            max_tokens=20,
            system_prompt="Return JSON.",
        )
    with pytest.raises(RuntimeError, match="BUDGET_EXHAUSTED"):
        rq1_v2._call_model(
            package_root=tmp_path,
            run_dir=run_dir,
            protocol=protocol,
            ledger=ledger,
            task_key="method:claim-2",
            stage="unit_test",
            model="fixture",
            prompt="must not be sent",
            images=[],
            max_tokens=20,
            system_prompt="Return JSON.",
        )


def test_resume_marks_reserved_unknown_call_without_making_it_retryable(tmp_path) -> None:
    run_dir = tmp_path / "run-01"
    run_dir.mkdir()
    ledger = [{"call_id": 1, "task_key": "judge:claim-1", "status": "STARTED"}]

    rq1_v2._recover_started_calls(run_dir, ledger)

    assert ledger[0]["status"] == "INTERRUPTED_REMOTE_RESULT_UNKNOWN"
    assert rq1_v2._task_key_exists(ledger, "judge:claim-1")
    assert json.loads((run_dir / "calls.json").read_text(encoding="utf-8")) == ledger


def test_source_normalization_dehyphenates_wrapped_words_but_keeps_elliptical_compounds() -> None:
    assert rq1_v2._norm_source("seman-\ntic hierarchy") == "semantic hierarchy"
    assert rq1_v2._norm_source("coarse-\nand fine-grained") == "coarse- and fine-grained"


def test_saved_judge_parser_requires_valid_json_object() -> None:
    assert rq1_v2._parse_json_response('{"acceptable_proposal_ids": []}') == {
        "acceptable_proposal_ids": []
    }
    with pytest.raises(json.JSONDecodeError):
        rq1_v2._parse_json_response("not JSON")
    with pytest.raises(ValueError, match="JSON object"):
        rq1_v2._parse_json_response("[]")


def test_final_manifest_ignores_only_a_stale_run_lock_entry(tmp_path) -> None:
    run_dir = tmp_path / "run-01"
    run_dir.mkdir()
    rq1_v2._write(run_dir / "protocol.json", {"schema_version": "test"})
    protocol = {"dataset_id": "fixture", "run_id": "fixture"}
    current = rq1_v2._build_output_manifest(run_dir, protocol)
    saved = {
        **current,
        "file_count": current["file_count"] + 1,
        "files": {
            **current["files"],
            "run.lock": {"sha256": "a" * 64, "size_bytes": 1},
        },
    }
    rq1_v2._write(run_dir / "output_manifest.json", saved)

    result = rq1_v2._verify_output_manifest(run_dir, protocol)

    assert result["status"] == "PASS"
    assert result["ignored_stale_transients"] == [
        "run.lock was included while finalizing under the run lock"
    ]


def test_saved_judge_recovery_uses_existing_transport_without_repeating_it(
    tmp_path, monkeypatch
) -> None:
    run_dir = tmp_path / "run-01"
    judges_dir = run_dir / "judges"
    proposal_dir = run_dir / "canonical_proposals"
    judges_dir.mkdir(parents=True)
    proposal_dir.mkdir()
    rq1_v2._write(
        run_dir / "protocol.json",
        {
            "run_id": "fixture-run",
            "budget": {"max_transport_calls": 160},
        },
    )
    rq1_v2._write(run_dir / "output_manifest.json", {"pre_recovery": True})
    raw = json.dumps(
        {
            "acceptable_proposal_ids": ["p1"],
            "rejected_proposal_ids": ["p2"],
            "preferred_proposal_ids": ["p1"],
            "uncertain_proposal_ids": [],
            "abstain": False,
            "uncertainty_reason": None,
            "assessment_by_proposal": {
                proposal_id: {
                    "visual_need": "NEEDED",
                    "source_sufficiency": "INSUFFICIENT",
                    "action_fit": "APPROPRIATE",
                    "uncertainty_fit": "APPROPRIATE",
                }
                for proposal_id in ("p1", "p2")
            },
            "strict_ranking": None,
        }
    )
    rq1_v2._write(
        run_dir / "calls.json",
        [
            {
                "call_id": 1,
                "task_key": "judge:claim-1",
                "stage": "canonical_decision_layer_judge",
                "status": "OK",
                "raw_response": raw,
            }
        ],
    )
    rq1_v2._write(
        proposal_dir / "claim-1.json",
        {
            "groups": [
                {"proposal_id": "p1", "view": {"action": "none"}},
                {"proposal_id": "p2", "view": {"action": "retrieve"}},
            ]
        },
    )
    rq1_v2._write(
        judges_dir / "claim-1-j1-forward.json",
        {
            "status": "INVALID_RESPONSE",
            "proposition_id": "claim-1",
            "judge_alias": "j1",
            "display_order": "forward",
            "planned": True,
            "call_id": 1,
            "proposal_record_path": "run-01/canonical_proposals/claim-1.json",
            "parse_error": {
                "type": "AttributeError",
                "message": "module has no attribute _parse_json",
            },
        },
    )
    monkeypatch.setattr(rq1_v2, "verify", lambda _root: {"status": "PASS"})
    monkeypatch.setattr(rq1_v2, "_refresh_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(rq1_v2, "_build_output_manifest", lambda *_args: {"recovered": True})

    result = rq1_v2._recover_saved_judges(tmp_path)

    recovered_row = json.loads((judges_dir / "claim-1-j1-forward.json").read_text(encoding="utf-8"))
    assert result["new_model_calls"] == 0
    assert result["model_request_repeats"] == 0
    assert result["call_count_before"] == result["call_count_after"] == 1
    assert recovered_row["status"] == "OK"
    assert recovered_row["judgment"]["preferred_proposal_ids"] == ["p1"]
    assert recovered_row["processing_recovery"]["model_request_repeated"] is False
    assert (run_dir / "recovery/pre_recovery_judge_rows.json").is_file()


def test_saved_material_review_recovery_keeps_proxy_and_license_status_separate(
    tmp_path, monkeypatch
) -> None:
    run_dir = tmp_path / "run-01"
    review_dir = run_dir / "asset_reviews"
    review_dir.mkdir(parents=True)
    rq1_v2._write(
        run_dir / "protocol.json",
        {
            "run_id": "fixture-run",
            "dataset_id": "fixture",
            "budget": {"max_transport_calls": 160},
        },
    )
    rq1_v2._write(run_dir / "output_manifest.json", {"pre_recovery": True})
    raw = json.dumps(
        {
            "claim_relation": "The diagram depicts the stated relation.",
            "fit": "MATCH",
            "redundant_or_decorative": False,
            "uncertainty": None,
            "visible_evidence": "Three labeled boxes and arrows are visible.",
        }
    )
    rq1_v2._write(
        run_dir / "calls.json",
        [
            {
                "call_id": 1,
                "task_key": "material_review:claim-1:asset-hash",
                "stage": "material_fit_proxy_review",
                "status": "OK",
                "images": [{"sha256": "asset-hash", "name": "asset.png"}],
                "raw_response": raw,
            }
        ],
    )
    rq1_v2._write(
        review_dir / "claim-1-asset.json",
        {
            "proxy_status": "INVALID_RESPONSE",
            "proposition_id": "claim-1",
            "object_id": "asset-1",
            "asset_sha256": "asset-hash",
            "rights_status": "UNVERIFIED",
            "formal_acceptance": False,
            "call_id": 1,
            "parse_error": {
                "type": "AttributeError",
                "message": "module has no attribute _parse_json",
            },
        },
    )
    monkeypatch.setattr(rq1_v2, "verify", lambda _root: {"status": "PASS"})
    monkeypatch.setattr(rq1_v2, "_refresh_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        rq1_v2,
        "_build_output_manifest",
        lambda *_args: {"recovered": True},
    )

    result = rq1_v2._recover_saved_material_reviews(tmp_path)

    recovered_row = json.loads((review_dir / "claim-1-asset.json").read_text(encoding="utf-8"))
    assert result["new_model_calls"] == 0
    assert result["model_request_repeats"] == 0
    assert result["formal_acceptance_count"] == 0
    assert result["call_count_before"] == result["call_count_after"] == 1
    assert recovered_row["proxy_status"] == "PROXY_REVIEWED"
    assert recovered_row["formal_acceptance"] is False
    assert recovered_row["rights_status"] == "UNVERIFIED"
    assert recovered_row["judgment"]["fit"] == "MATCH"
    assert recovered_row["processing_recovery"]["model_request_repeated"] is False
    assert (run_dir / "recovery/pre_material_review_rows.json").is_file()


def test_action_sensitivity_projects_ties_and_preserves_uncertainty(tmp_path) -> None:
    run_dir = tmp_path / "run-01"
    (run_dir / "canonical_proposals").mkdir(parents=True)
    proposal_groups = [
        {
            "proposal_id": "none-certain",
            "view": {
                "action": "none",
                "decision_state": "DECIDED",
                "uncertainty": {"abstain": False, "uncertain": False},
            },
        },
        {
            "proposal_id": "none-uncertain",
            "view": {
                "action": "none",
                "decision_state": "UNCERTAIN",
                "uncertainty": {"abstain": True, "uncertain": True},
            },
        },
    ]
    (run_dir / "canonical_proposals/claim-1.json").write_text(
        json.dumps({"groups": proposal_groups}), encoding="utf-8"
    )
    base = {
        "status": "OK",
        "judgment": {
            "abstain": False,
            "preferred_proposal_ids": ["none-certain", "none-uncertain"],
            "acceptable_proposal_ids": ["none-certain", "none-uncertain"],
            "uncertain_proposal_ids": ["none-uncertain"],
        },
    }
    rows = [
        {**base, "proposition_id": "claim-1", "judge_alias": "j1", "display_order": "forward"},
        {**base, "proposition_id": "claim-1", "judge_alias": "j1", "display_order": "reverse"},
    ]
    protocol = {
        "tasks": [{"proposition_id": "claim-1"}],
        "models": {"judge_models": ["j1"]},
    }

    result = rq1_v2._judge_action_sensitivity(run_dir, protocol, rows)

    pair = result["order_pairs"]["pairs"][0]
    assert pair["preferred_action_set_changed"] is False
    assert pair["preferred_action_profile_changed"] is False
    assert result["order_pairs"]["planned_pairs"] == 1
