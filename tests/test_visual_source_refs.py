from __future__ import annotations

import json

import pytest

from textbook2video.research.visual_source_refs import materialize_source_refs, source_units
from textbook2video.research.visual_tools import dispatch


def test_explicit_exact_excerpt_is_preserved_only_within_selected_source_units():
    source = "哈希是单向函数，无法反推。另一个未选中的说法。最后一项。"
    result, changes = materialize_source_refs(
        {"diagram": {"constraint": "无法反推", "constraint_evidence": "无法反推",
                     "constraint_source_ref": "source-001"}}, source, None,
    )
    assert result["diagram"]["constraint_evidence"] == "无法反推"
    assert any("without rewriting" in change for change in changes)
    for excerpt in ("可以反推", "另一个未选中的说法", "", "   "):
        with pytest.raises(ValueError, match="conflicts"):
            materialize_source_refs(
                {"source_ref": ["source-001", "source-003"], "evidence": excerpt}, source, None,
            )


def test_invalid_source_feedback_identifies_exact_field_and_allowed_ids():
    with pytest.raises(ValueError) as error:
        materialize_source_refs(
            {"visuals": [{"nodes": [{"id": "n", "source_ref": "source-999"}]}]},
            "真实原文。", None,
        )
    assert "/visuals/0/nodes/0/source_ref" in str(error.value)
    assert "source-999" in str(error.value)
    assert "allowed=['source-001']" in str(error.value)


@pytest.mark.parametrize("reference", ["source-001, source-002", ["source-001,source-002"]])
def test_explicit_comma_enumeration_keeps_exact_selected_ids_and_original_quote(reference):
    source = "甲。乙。"
    result, changes = materialize_source_refs({"source_ref": reference}, source, None)
    assert result["source_ref"] == ["source-001", "source-002"]
    assert result["evidence"] == source
    assert any("no IDs inferred" in change for change in changes)


@pytest.mark.parametrize("reference", [
    "source-001,source-001", "source-001,unknown", "source-001,", "source-001..source-002",
    ["source-001,source-002", 2],
])
def test_source_enumeration_never_repairs_ambiguous_ranges_duplicates_or_unknown_ids(reference):
    with pytest.raises(ValueError, match="existing source IDs"):
        materialize_source_refs({"source_ref": reference}, "甲。乙。", None)


@pytest.mark.parametrize("field,ref_field", [
    ("evidence", "source_ref"), ("source_evidence", "source_ref"),
    ("constraint_evidence", "constraint_source_ref"),
])
def test_nonadjacent_source_units_cannot_silently_include_intervening_facts(field, ref_field):
    source = "甲。乙。丙。"
    value = {ref_field: ["source-001", "source-003"], field: source}
    if field == "source_evidence":
        value["element_id"] = "note"
    elif field == "constraint_evidence":
        value["constraint"] = "甲"
    with pytest.raises(ValueError, match="contiguous explicitly selected"):
        materialize_source_refs(value, source, None)
    value.pop(field)
    materialized, _ = materialize_source_refs(value, source, None)
    assert materialized[field] == ["甲。", "丙。"]
    assert materialized[ref_field] == ["source-001", "source-003"]
    for forged in ([source], ["甲。丙。"], ["甲。", "乙。"], ["甲。", "虚构"]):
        with pytest.raises(ValueError, match="contiguous explicitly selected"):
            materialize_source_refs({**value, field: forged}, source, None)
    value[field] = "丙。"
    result, _ = materialize_source_refs(value, source, None)
    assert result[field] == "丙。"


def test_nonadjacent_units_do_not_form_synthetic_adjacent_quotes():
    # Concatenating selected 1+4 would match the unselected 2+3 verbatim.
    with pytest.raises(ValueError, match="contiguous explicitly selected"):
        materialize_source_refs(
            {"source_ref": ["source-001", "source-004"], "evidence": "甲。丙。"},
            "甲。甲。丙。丙。", None,
        )


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


def test_conflict_feedback_identifies_exact_quote_matches_without_fixing_a_claim():
    args = {"source_ref": "source-001", "evidence": "乙句。"}
    with pytest.raises(ValueError) as error:
        materialize_source_refs(args, "甲句。乙句。", None)
    message = str(error.value)
    assert "selected_ids=['source-001']" in message
    assert "exact_unit_matches=['source-002']" in message
    assert "received_quote='乙句。'" in message
    assert args == {"source_ref": "source-001", "evidence": "乙句。"}
    with pytest.raises(ValueError, match=r"exact_unit_matches=\[\]"):
        materialize_source_refs({"source_ref": "source-001", "evidence": "FORGED"}, "甲句。", None)
