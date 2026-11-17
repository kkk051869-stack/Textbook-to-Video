from copy import deepcopy

import pytest

from textbook2video.research.visual_fact_audit import (
    build_review_targets,
    fact_audit_findings,
    validate_fact_audit,
)

NARRATION = "传感器读取温度。控制器保存阈值。控制器比较读数与阈值。"

SPECS = [
    {
        "id": "sensor-panel",
        "kind": "relationship",
        "title": "温度采集",
        "narration_refs": ["narration-001"],
        "diagram": {
            "nodes": [
                {"id": "sensor", "label": "传感器", "detail": "读取温度"},
                {"id": "controller", "label": "控制器"},
            ],
            "edges": [{"source": "sensor", "target": "controller", "label": "温度读数"}],
        },
    },
    {
        "id": "compare-panel",
        "kind": "relationship",
        "title": "阈值判断",
        "narration_refs": ["narration-002", "narration-003"],
        "diagram": {
            "nodes": [
                {"id": "controller", "label": "控制器", "detail": "保存阈值"},
                {"id": "reading", "label": "当前读数"},
                {"id": "threshold", "label": "阈值"},
            ],
            "edges": [
                {"source": "reading", "target": "controller", "label": "当前读数",
                 "directed": True},
                {"source": "threshold", "target": "controller", "label": "保存"},
            ],
            "constraint": "比较读数与阈值",
        },
        "rows": [["输入", "说明"], ["阈值", "控制器保存"]],
    },
]


def valid_report(specs=SPECS):
    targets = build_review_targets(specs, NARRATION)
    panels = []
    for target in targets["panels"]:
        visible = target["visual_id"] == "sensor-panel"
        panels.append({
            "visual_id": target["visual_id"],
            "units": [
                {
                    "narration_ref": ref,
                    "status": "visible",
                    "reason": "图中有对应的可见表达",
                    "visible_evidence": (
                        ["读取温度"] if visible else
                        ["保存阈值"] if ref == "narration-002" else
                        ["比较读数与阈值"]
                    ),
                }
                for ref in target["narration_refs"]
            ],
            "edges": [
                {**edge, "status": "supported", "reason": "端点、方向和动作均对应"}
                for edge in target["edges"]
            ],
        })
    return {"fact_audit": {"panels": panels}}, targets


def test_valid_multi_panel_audit_covers_every_unit_and_edge():
    report, targets = valid_report()

    validate_fact_audit(report, targets, SPECS)

    assert [panel["visual_id"] for panel in targets["panels"]] == [
        "sensor-panel", "compare-panel"
    ]
    assert fact_audit_findings(report) == []


@pytest.mark.parametrize("mutation", ["omit", "duplicate"])
def test_every_panel_narration_unit_must_be_reviewed_exactly_once(mutation):
    report, targets = valid_report()
    units = report["fact_audit"]["panels"][1]["units"]
    if mutation == "omit":
        units.pop()
    else:
        units[-1] = deepcopy(units[0])

    with pytest.raises(ValueError, match="narration unit once"):
        validate_fact_audit(report, targets, SPECS)


def test_other_panel_text_cannot_be_used_as_visible_evidence():
    report, targets = valid_report()
    # This phrase exists in sensor-panel, but not in compare-panel.
    report["fact_audit"]["panels"][1]["units"][0]["visible_evidence"] = ["读取温度"]

    with pytest.raises(ValueError, match="own panel"):
        validate_fact_audit(report, targets, SPECS)


@pytest.mark.parametrize("evidence", [["阈值判断"], [NARRATION]])
def test_title_or_narration_is_not_visible_evidence(evidence):
    report, targets = valid_report()
    report["fact_audit"]["panels"][1]["units"][0]["visible_evidence"] = evidence

    with pytest.raises(ValueError, match="own panel"):
        validate_fact_audit(report, targets, SPECS)


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "endpoint", "label", "direction"])
def test_each_edge_must_be_audited_once_with_exact_endpoints_and_label(mutation):
    report, targets = valid_report()
    edges = report["fact_audit"]["panels"][1]["edges"]
    if mutation == "omit":
        edges.pop()
    elif mutation == "duplicate":
        edges[-1] = deepcopy(edges[0])
    elif mutation == "endpoint":
        edges[0]["target"] = "threshold"
    elif mutation == "label":
        edges[0]["label"] = "错误标签"
    else:
        edges[0]["directed"] = False

    with pytest.raises(ValueError, match="review every edge once|edge targets do not match"):
        validate_fact_audit(report, targets, SPECS)


def test_negative_unit_and_edge_judgments_become_review_issues():
    report, targets = valid_report()
    panels = report["fact_audit"]["panels"]
    panels[1]["units"][0].update(status="missing", reason="图中没有阈值归属")
    panels[1]["units"][1].update(status="incorrect", reason="比较对象表达错误")
    panels[1]["edges"][0].update(status="unsupported", reason="原文未支持此方向")

    # Negative judgments are valid audit results; they should persist as review issues.
    validate_fact_audit(report, targets, SPECS)
    findings = fact_audit_findings(report)

    assert len(findings) == 3
    assert {finding["visual_id"] for finding in findings} == {"compare-panel"}
    assert [finding["category"] for finding in findings].count("missing_content") == 1
    assert [finding["category"] for finding in findings].count("factual_error") == 2
    assert all(finding["issue"] and finding["change"] for finding in findings)


def test_targets_partition_narration_and_capture_each_actual_edge():
    targets = build_review_targets(SPECS, NARRATION)

    assert [panel["narration_refs"] for panel in targets["panels"]] == [
        ["narration-001"], ["narration-002", "narration-003"]
    ]
    assert targets["panels"][0]["edges"] == [
        {"source": "sensor", "target": "controller", "label": "温度读数"}
    ]
    assert len(targets["panels"][1]["edges"]) == 2


@pytest.mark.parametrize("field", ["units", "edges"])
def test_malformed_status_is_a_protocol_error_and_negative_merge_is_safe(field):
    report, targets = valid_report()
    report["fact_audit"]["panels"][0][field][0]["status"] = ["visible"]
    with pytest.raises(ValueError, match="status and reason"):
        validate_fact_audit(report, targets, SPECS)
    assert fact_audit_findings(report) == []


def test_scene_observation_is_not_required_to_be_diagram_text():
    specs = [{"id": "scene", "kind": "scene"}]
    targets = build_review_targets(specs, "传感器读取温度。")
    report = {"fact_audit": {"panels": [{
        "visual_id": "scene", "edges": [], "units": [{
            "narration_ref": "narration-001", "status": "visible",
            "reason": "Screenshot depicts the action",
            "visible_evidence": ["A sensor is visibly attached to a thermometer"],
        }],
    }]}}
    validate_fact_audit(report, targets, specs)


@pytest.mark.parametrize("evidence", ["控制器保存", "Hidden content", "Hidden edge detail"])
def test_fields_not_rendered_by_this_visual_kind_cannot_be_visible_proof(evidence):
    specs = deepcopy(SPECS)
    specs[1]["content"] = "Hidden content"
    specs[1]["diagram"]["edges"][0]["detail"] = "Hidden edge detail"
    report, targets = valid_report(specs)
    report["fact_audit"]["panels"][1]["units"][0]["visible_evidence"] = [evidence]
    with pytest.raises(ValueError, match="own panel"):
        validate_fact_audit(report, targets, specs)


def test_wholly_unsupported_narration_does_not_require_inventing_visible_facts():
    report, targets = valid_report()
    report["fact_audit"]["panels"][0]["units"][0].update(
        status="unsupported", reason="The source does not support any claim in this unit"
    )
    validate_fact_audit(report, targets, SPECS)
    assert fact_audit_findings(report) == []


def test_explicit_retained_page_text_is_allowed_but_unlisted_original_text_is_not():
    report, _ = valid_report()
    proof = "An explicitly retained source-grounded page sentence"
    targets = build_review_targets(SPECS, NARRATION, retained_texts=[proof])
    report["fact_audit"]["panels"][0]["units"][0]["visible_evidence"] = [proof]
    validate_fact_audit(report, targets, SPECS)
    targets = build_review_targets(SPECS, NARRATION)
    with pytest.raises(ValueError, match="own panel"):
        validate_fact_audit(report, targets, SPECS)
