from __future__ import annotations

import json

import pytest

from textbook2video.research.visual_source_refs import materialize_source_refs, source_units
from textbook2video.research.visual_tools import dispatch


def test_invalid_source_feedback_identifies_exact_field_and_allowed_ids():
    with pytest.raises(ValueError) as error:
        materialize_source_refs(
            {"visuals": [{"nodes": [{"id": "n", "source_ref": "source-999"}]}]},
            "真实原文。", None,
        )
    assert "/visuals/0/nodes/0/source_ref" in str(error.value)
    assert "source-999" in str(error.value)
    assert "allowed=['source-001']" in str(error.value)


def test_constraint_reference_alias_materializes_only_explicit_original_quote():
    result, changes = materialize_source_refs(
        {"diagram": {"constraint": "无法反推", "constraint_evidence": "source-001"}},
        "无法反推。", None,
    )
    assert result["diagram"]["constraint_evidence"] == "无法反推。"
    assert result["diagram"]["constraint_source_ref"] == "source-001"
    assert result["diagram"]["constraint"] == "无法反推"
    assert changes
    with pytest.raises(ValueError, match="conflicts"):
        materialize_source_refs(
            {"diagram": {"constraint": "无法反推", "constraint_evidence": "虚构证据",
                         "constraint_source_ref": "source-001"}},
            "无法反推。", None,
        )


def test_reference_selection_materializes_only_verbatim_source_spans():
    source = "用户拥有0.5和0.3比特币。支付0.6，找零0.2。"
    result, changes = materialize_source_refs(
        {
            "nodes": [
                {"id": "input", "source_ref": "source-001"},
                {"id": "output", "source_ref": ["source-001", "source-002"]},
            ]
        },
        source,
        None,
    )
    assert result["nodes"][0]["evidence"] == "用户拥有0.5和0.3比特币。"
    assert result["nodes"][1]["evidence"] == source
    assert len(changes) == 2


def test_units_support_english_sentences_without_splitting_decimal_numbers():
    source = "Input 0.5 BTC. Output 0.3 BTC!"
    units = source_units(source)
    assert len(units) == 2
    assert "0.5" in units[0]["text"] and "0.3" in units[1]["text"]
    assert "".join(unit["text"] for unit in units) == source


def test_generation_instruction_cannot_create_a_new_source_reference():
    with pytest.raises(ValueError, match="existing source IDs"):
        materialize_source_refs(
            {"nodes": [{"id": "n", "source_ref": "prompt-001"}]}, "真实原文。", None
        )
    with pytest.raises(ValueError, match="conflicts"):
        materialize_source_refs(
            {"nodes": [{"id": "n", "source_ref": "source-001", "evidence": "模型虚构的断言。"}]},
            "真实原文。",
            None,
        )


def test_coverage_inventory_keeps_every_original_fact_without_model_retyping():
    source = "先采集，再处理。"
    context = [{"id": "steps", "type": "flow_step", "steps": ["采集", "处理"]}]
    result, _ = materialize_source_refs(
        {
            "page_plan": {
                "coverage": [
                    {
                        "element_id": "steps",
                        "decision": "represented",
                        "source_ref": "source-001",
                        "visual_refs": ["main"],
                        "reason": "流程图表达两个步骤",
                    }
                ]
            }
        },
        source,
        context,
    )
    proof = result["page_plan"]["coverage"][0]
    assert proof["fact_quotes"] == ["采集", "处理"]
    assert proof["source_evidence"] == source


def test_invalid_reference_preserves_an_attempt_that_can_be_revised(tmp_path):
    args = {
        "visuals": [
            {"id": "main", "kind": "none", "teaching_goal": "无需装饰图", "source_ref": "missing"}
        ]
    }
    with pytest.raises(ValueError, match="source_ref"):
        dispatch("create", args, source="真实原文。", output_dir=tmp_path / "bad", render=False)
    assert (tmp_path / "bad/failure.json").is_file()
    assert (tmp_path / "bad/raw_tool_request.json").is_file()
    args["visuals"][0]["source_ref"] = "source-001"
    args.update(parent=str(tmp_path / "bad"), reason="修正来源编号")
    path = dispatch(
        "revise", args, source="真实原文。", output_dir=tmp_path / "fixed", render=False
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["parent"] == str((tmp_path / "bad").resolve())
    assert record["normalizations"]


def test_reference_id_in_legacy_evidence_field_is_an_unambiguous_alias():
    result, changes = materialize_source_refs({"evidence": "source-001"}, "真实原文。", None)
    assert result["evidence"] == "真实原文。" and changes
    # A literal source identifier in source text remains a literal quote.
    result, changes = materialize_source_refs(
        {"evidence": "source-001"}, "标识为source-001。", None
    )
    assert result["evidence"] == "source-001" and not changes
