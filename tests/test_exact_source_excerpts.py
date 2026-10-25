import json

import pytest

from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
from textbook2video.research import visual_tools as tools
from textbook2video.research.exact_source_excerpts import exact_evidence

SOURCE = "甲采集数据。中间未选事实。丙展示结果。"
REFS = ["source-001", "source-003"]
QUOTES = ["甲采集数据。", "丙展示结果。"]


@pytest.mark.parametrize("kind", ["flow", "relationship", "table", "none"])
def test_disjoint_refs_roundtrip_through_compilation_and_integrity(kind, tmp_path):
    spec = {
        "id": "main",
        "title": "数据说明",
        "kind": kind,
        "teaching_goal": "解释两段原文",
        "source_ref": REFS,
    }
    nodes = [
        {"id": str(i), "label": label, "source_ref": REFS}
        for i, label in enumerate(["输入", "处理", "输出"])
    ]
    edges = [
        {"source": "0", "target": "1", "source_ref": REFS},
        {"source": "1", "target": "2", "source_ref": REFS},
    ]
    if kind == "flow":
        spec.update(nodes=nodes, edges=edges)
    elif kind == "relationship":
        for i, node in enumerate(nodes):
            node["column"] = i
        spec["diagram"] = {
            "version": "teaching-relationship-v1",
            "layout": "one_way",
            "columns": ["输入", "处理", "输出"],
            "nodes": nodes,
            "edges": edges,
        }
    elif kind == "table":
        spec["rows"] = [["名称", "说明"], ["甲", "采集"], ["丙", "展示"]]
    revision = tools.dispatch(
        "create", {"visuals": [spec]}, source=SOURCE, output_dir=tmp_path / kind, render=False
    )
    tools.verify_revision(revision.parent)
    compiled = json.loads((revision.parent / "specs.json").read_text(encoding="utf-8"))[0]
    assert compiled["evidence"] == QUOTES
    if kind in {"flow", "relationship"}:
        container = compiled.get("diagram", compiled)
        assert all(n["evidence"] == QUOTES for n in container["nodes"])
        assert all(e["evidence"] == QUOTES for e in container["edges"])
    assert "evidence" not in spec


@pytest.mark.parametrize("bad", [[], [""], ["甲采集数据。", "虚构"], ["甲采集数据。丙展示结果。"]])
def test_no_empty_forged_or_joined_excerpt_is_accepted(bad):
    with pytest.raises(ValueError):
        exact_evidence(bad, SOURCE)
    with pytest.raises(ValueError, match="within 5"):
        exact_evidence(QUOTES, SOURCE, limit=5)


def test_page_coverage_accepts_separate_quotes_and_checks_every_quote():
    segment = {
        "id": 1,
        "narration": "甲采集数据。",
        "elements": [{"id": "old", "type": "text", "text": "甲采集数据"}],
    }
    proof = {
        "element_id": "old",
        "decision": "represented",
        "reason": "图中说明",
        "visual_refs": ["main"],
        "fact_quotes": ["甲采集数据"],
        "source_evidence": QUOTES,
    }
    plan = {
        "reason": "整合说明",
        "support_element_ids": [],
        "replaces_element_ids": ["old"],
        "coverage": [proof],
    }
    apply_visual_page_plan(
        segment, "main", plan, visual_specs=[{"id": "main", "nodes": []}], source_text=SOURCE
    )
    proof["source_evidence"] = [QUOTES[0], "伪造"]
    original = {
        "id": 1,
        "narration": "甲采集数据。",
        "elements": [{"id": "old", "type": "text", "text": "甲采集数据"}],
    }
    with pytest.raises(ValueError, match="exact source excerpt"):
        apply_visual_page_plan(
            original, "main", plan, visual_specs=[{"id": "main", "nodes": []}], source_text=SOURCE
        )
    assert original["elements"][0]["id"] == "old"
