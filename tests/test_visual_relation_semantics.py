from copy import deepcopy

import pytest

from textbook2video.research.visual_relation_semantics import (
    RELATION_QUESTIONS,
    materialize_relation_audit,
    relation_findings,
    validate_relation_audit,
)

SOURCE = "监测仪保存温度基准。传感器读取当前温度。监测仪比较当前温度与基准，发现超温。"
SPECS = [{"id": "temperature", "kind": "flow", "title": "温度监测",
          "nodes": [{"id": "baseline", "label": "监测仪保存基准"},
                    {"id": "current", "label": "传感器读取当前温度"},
                    {"id": "compare", "label": "比较温度与基准"}],
          "edges": [{"source": "current", "target": "compare", "label": "当前温度"}]}]


def audit():
    return {key: {"status": "visible", "reason": "由监测仪基准和当前读数表达",
                  "visual_id": "temperature", "source_evidence": SOURCE,
                  "visible_evidence": ["监测仪保存基准", "比较温度与基准"]}
            for key in RELATION_QUESTIONS}


def test_relation_audit_requires_source_and_actual_visible_objects_without_mutation():
    report = {"relation_audit": audit()}
    before = deepcopy((report, SPECS))
    validate_relation_audit(report, SPECS, SOURCE)
    assert (report, SPECS) == before
    assert relation_findings(report) == []


@pytest.mark.parametrize("change", [
    {"visual_id": "invented"}, {"source_evidence": "原文不存在的检测者"},
    {"visible_evidence": ["温度监测"]},  # Title alone is not visible relationship proof.
    {"visible_evidence": ["不存在的比较双方"]}, {"status": []}, {"reason": ""},
])
def test_forged_incomplete_or_nonvisible_relation_proof_is_a_protocol_failure(change):
    report = {"relation_audit": audit()}
    report["relation_audit"]["comparison_operands"].update(change)
    with pytest.raises(ValueError, match="relation_audit"):
        validate_relation_audit(report, SPECS, SOURCE)


def test_incomplete_audit_retains_negative_finding_for_same_image_protocol_repair():
    item = audit()["comparison_operands"]
    item.update(status="incorrect", reason="当前温度与传感器设备不是同一类型的比较对象")
    report = {"relation_audit": {"comparison_operands": item}}
    with pytest.raises(ValueError, match="every relationship question"):
        validate_relation_audit(report, SPECS, SOURCE)
    findings = relation_findings(report)
    assert len(findings) == 1 and findings[0]["category"] == "factual_error"
    assert "comparison_operands" in findings[0]["issue"]


def test_source_unspecified_roles_need_reason_but_do_not_require_invented_mechanics():
    report = {"relation_audit": {key: {"status": "not_specified",
                                      "reason": "原文未说明该角色，不要求补造"}
                                 for key in RELATION_QUESTIONS}}
    validate_relation_audit(report, SPECS, "原文仅定义温度。")
    assert relation_findings(report) == []


def test_relation_audit_source_ids_materialize_disjoint_quotes_without_mutating_raw_reply():
    report = {"relation_audit": audit()}
    item = report["relation_audit"]["state_ownership"]
    item.pop("source_evidence")
    item["source_ref"] = ["source-001", "source-003"]
    before = deepcopy(report)
    result, messages = materialize_relation_audit(report, SOURCE)
    quote = result["relation_audit"]["state_ownership"]["source_evidence"]
    assert quote == ["监测仪保存温度基准。", "监测仪比较当前温度与基准，发现超温。"]
    assert report == before and messages
    validate_relation_audit(result, SPECS, SOURCE)


@pytest.mark.parametrize("citation", [
    {"source_ref": "source-999"},
    {"source_ref": "source-001", "source_evidence": "监测仪比较当前温度与基准，发现超温。"},
    {"source_ref": "source-001", "source_evidence": "旁白不是原文"},
])
def test_relation_audit_invalid_id_or_explicit_conflicting_quote_is_never_repaired(citation):
    report = {"relation_audit": {"state_ownership": citation}}
    before = deepcopy(report)
    with pytest.raises(ValueError, match="source_ref"):
        materialize_relation_audit(report, SOURCE)
    assert report == before
