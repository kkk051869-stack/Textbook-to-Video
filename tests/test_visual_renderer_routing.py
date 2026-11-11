"""Renderer routing fixtures: mechanical compatibility, never semantic approval."""

import copy
import json

import pytest

from textbook2video.research import visual_tools as tools
from textbook2video.research.visual_model_interface import renderer_graphs

SOURCE = "输入经过处理产生中间结果，中间结果经过处理产生输出。"


def graph(pairs=(("a", "b"), ("b", "c"), ("c", "d"))):
    ids = sorted({i for edge in pairs for i in edge})
    return {
        "visuals": [
            {
                "id": "g",
                "kind": "relationship",
                "title": "处理流程",
                "teaching_goal": "理解输入与输出的处理关系",
                "nodes": [{"id": i, "label": i, "source_ref": ["source-001"]} for i in ids],
                "edges": [
                    {"source": a, "target": b, "source_ref": ["source-001"]} for a, b in pairs
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    "pairs",
    [
        [("a", "b"), ("b", "c"), ("c", "d")],
        [("a", "c"), ("b", "d"), ("c", "e"), ("d", "e")],
        [("a", "b")],
    ],
)
def test_incompatible_directed_dag_routes_without_content_change(pairs):
    original = graph(pairs)
    before = copy.deepcopy(original)
    routed, notes = renderer_graphs(original)
    assert original == before
    expected = copy.deepcopy(original)
    expected["visuals"][0]["kind"] = "flow"
    assert routed == expected  # Includes IDs, every label/detail and every source ref.
    assert any("relationship -> flow" in n and "not semantic approval" in n for n in notes)
    assert renderer_graphs(routed) == (routed, [])


def test_compatible_three_stage_template_keeps_existing_renderer():
    routed, notes = renderer_graphs(graph([("a", "b"), ("b", "c")]))
    assert routed["visuals"][0]["kind"] == "relationship"
    assert "diagram" in routed["visuals"][0]
    assert not any("relationship -> flow" in n for n in notes)


@pytest.mark.parametrize(
    "bad",
    [
        "cycle",
        "missing",
        "duplicate_id",
        "duplicate_edge",
        "self",
        "undirected",
        "constraint",
        "amount",
        "column",
        "unknown",
        "association",
        "compares",
    ],
)
def test_routing_never_hides_invalid_or_unrendered_content(bad):
    args = graph()
    spec = args["visuals"][0]
    if bad == "cycle":
        spec["edges"].append({"source": "d", "target": "a"})
    elif bad == "missing":
        spec["edges"][0]["target"] = "absent"
    elif bad == "duplicate_id":
        spec["nodes"].append(copy.deepcopy(spec["nodes"][0]))
    elif bad == "duplicate_edge":
        spec["edges"].append(copy.deepcopy(spec["edges"][0]))
    elif bad == "self":
        spec["edges"][0]["target"] = "a"
    elif bad == "undirected":
        spec["edges"][0]["directed"] = False
    elif bad == "constraint":
        spec["constraint"] = "输入"
    elif bad == "amount":
        spec["nodes"][0]["value"] = "100"
    elif bad == "column":
        spec["nodes"][0]["column"] = 0
    elif bad in {"association", "compares"}:
        spec["edges"][0]["relation"] = bad
    else:
        spec["unknown_field"] = "must not disappear"
    before = copy.deepcopy(args)
    with pytest.raises(ValueError):
        renderer_graphs(args)
    assert args == before


def test_explicit_legacy_diagram_is_authoritative_not_rerouted():
    original = graph()
    s = original["visuals"][0]
    s["diagram"] = {"layout": "auto", "nodes": s.pop("nodes"), "edges": s.pop("edges")}
    assert renderer_graphs(original) == (original, [])
    with pytest.raises(ValueError, match="three stages"):
        tools.normalize_visual_arguments(original, automatic_layout=True)


def test_routed_graph_reaches_real_svg_compiler_and_retains_raw_request(tmp_path):
    args = graph()
    result = tools.dispatch(
        "create",
        args,
        source=SOURCE,
        output_dir=tmp_path / "compile",
        automatic_layout=True,
        render=False,
        allow_images=False,
    )
    directory = result.parent
    raw = json.loads((directory / "raw_tool_request.json").read_text(encoding="utf-8"))
    assert raw["arguments"] == args
    resolved = json.loads((directory / "request.json").read_text(encoding="utf-8"))["arguments"]
    assert resolved["visuals"][0]["kind"] == "flow"
    assert [n["id"] for n in resolved["visuals"][0]["nodes"]] == ["a", "b", "c", "d"]
    svgs = list((directory / "compiled/assets").glob("*.svg"))
    assert svgs and all(
        f'data-node-id="{n}"' in svgs[0].read_text(encoding="utf-8") for n in "abcd"
    )
    record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    assert "relationship -> flow" in json.dumps(record)


@pytest.mark.parametrize("bad", ["source", "role", "capacity"])
def test_other_strict_gates_remain_after_routing(tmp_path, bad):
    args = graph()
    if bad == "source":
        args["visuals"][0]["nodes"][0]["source_ref"] = ["source-999"]
    elif bad == "role":
        args["visuals"][0]["nodes"][0]["role"] = "imaginary-role"
    else:
        args = graph([(f"n{i}", f"n{i + 1}") for i in range(8)])
    with pytest.raises(ValueError):
        tools.dispatch(
            "create",
            args,
            source=SOURCE,
            output_dir=tmp_path / bad,
            automatic_layout=True,
            render=False,
            allow_images=False,
        )
