from __future__ import annotations

import json
from copy import deepcopy

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_narration_refs import (
    materialize_narration_refs,
    narration_units,
)
from textbook2video.research.visual_object_edits import apply_object_updates

TEXT = " \n采集0.5 BTC。\r\n处理数据。 显示结果。 \n"


def panels():
    return {"visuals": [
        {"id": ident, "kind": "flow", "schema_version": "teaching-visual-v2",
         "title": "数据处理", "teaching_goal": "理解数据处理", "narration_refs": refs,
         "nodes": [{"id": "a", "label": "采集", "evidence": TEXT},
                   {"id": "b", "label": "处理", "evidence": TEXT}],
         "edges": [{"source": "a", "target": "b", "evidence": TEXT}]}
        for ident, refs in (("first", ["narration-001", "narration-002"]),
                            ("second", ["narration-003"]))
    ]}


def test_narration_units_preserve_all_whitespace_punctuation_and_decimals():
    units = narration_units(TEXT)
    assert "".join(unit["text"] for unit in units) == TEXT
    assert len(units) == 3 and "0.5" in units[0]["text"]
    assert units[0]["start"] == 0 and units[-1]["end"] == len(TEXT)
    english = "Input 0.5 BTC. Process it! Show it."
    assert "".join(u["text"] for u in narration_units(english)) == english


def test_model_selected_narration_ids_materialize_and_pass_existing_exact_partition(tmp_path):
    original = panels()
    before = deepcopy(original)
    path = tools.dispatch("create", original, source=TEXT, output_dir=tmp_path / "good",
                          narration_text=TEXT, render=False)
    tools.verify_revision(path.parent)
    specs = json.loads((path.parent / "specs.json").read_text(encoding="utf-8"))
    assert "".join(spec["narration_span"] for spec in specs) == TEXT
    assert original == before


@pytest.mark.parametrize("refs", [
    [], ["narration-999"], ["narration-001", "narration-003"],
    ["narration-002", "narration-001"], ["narration-001", "narration-001"],
    "narration-001", [1],
])
def test_narration_refs_never_guess_reorder_duplicate_or_bridge_units(refs):
    args = {"visuals": [{"id": "x", "narration_refs": refs}]}
    with pytest.raises(ValueError, match="narration_refs"):
        materialize_narration_refs(args, TEXT)


def test_explicit_span_is_never_rewritten_and_global_partition_still_rejects_gaps(tmp_path):
    args = panels()
    args["visuals"][0]["narration_span"] = "重写的旁白"
    with pytest.raises(ValueError, match="conflicts"):
        materialize_narration_refs(args, TEXT)
    for refs in (["narration-001"], ["narration-001", "narration-002", "narration-003"]):
        args = panels()
        args["visuals"][0]["narration_refs"] = refs
        with pytest.raises(ValueError, match="partition narration_text exactly"):
            tools.dispatch("create", args, source=TEXT, output_dir=tmp_path / str(len(refs)),
                           narration_text=TEXT, render=False)


def test_citation_refresh_tracks_explicit_narration_spans_across_updates():
    original, _ = materialize_narration_refs(panels(), TEXT)
    updates = [{"visual_id": "first", "set": {"narration_refs": ["narration-001"]}}]
    changed = apply_object_updates(original, {"updates": updates})
    assert "narration_span" not in changed["visuals"][0]
    assert changed["applied_updates"][0]["refreshed_evidence"]["narration_span"] == (
        original["visuals"][0]["narration_span"]
    )
    changed = apply_object_updates(original, {"updates": [
        {"visual_id": "first", "set": {"narration_span": "错误内容"}}, *updates,
    ]})
    with pytest.raises(ValueError, match="conflicts"):
        materialize_narration_refs(changed, TEXT)


@pytest.mark.parametrize("order", [(1, 1), (2, 1)])
def test_repeated_sentence_text_cannot_hide_duplicate_or_reordered_ids(order):
    args = {"visuals": [{"id": f"panel-{i}", "narration_refs": [f"narration-{ref:03}"]}
                        for i, ref in enumerate(order)]}
    with pytest.raises(ValueError, match="identity order"):
        materialize_narration_refs(args, "甲。甲。")


def test_mixed_legacy_span_and_refs_still_use_absolute_original_offsets():
    args = {"visuals": [{"id": "legacy", "narration_span": "甲。"},
                        {"id": "ref", "narration_refs": ["narration-001"]}]}
    with pytest.raises(ValueError, match="identity order"):
        materialize_narration_refs(args, "甲。甲。")
    args["visuals"][1]["narration_refs"] = ["narration-002"]
    normalized, _ = materialize_narration_refs(args, "甲。甲。")
    assert "".join(spec["narration_span"] for spec in normalized["visuals"]) == "甲。甲。"


def test_composition_cannot_swap_equal_text_panels_with_distinct_narration_ids(tmp_path):
    args = panels()
    for i, spec in enumerate(args["visuals"], 1):
        spec["narration_refs"] = [f"narration-{i:03}"]
    args["composition"] = {"visual_ids": ["second", "first"], "axis": "single"}
    with pytest.raises(ValueError, match="narration_refs identity order"):
        tools.dispatch("create", args, source=TEXT, output_dir=tmp_path / "bad-order",
                       narration_text="甲。甲。", render=False)
