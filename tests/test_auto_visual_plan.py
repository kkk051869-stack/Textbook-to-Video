import json
from pathlib import Path

from textbook2video.research.auto_visual_plan import build_auto_visual_plan


def test_auto_visual_plan_generates_specs_bindings_and_events(tmp_path: Path, monkeypatch) -> None:
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    graph.write_text(json.dumps({"narration_propositions": [{
        "id": "p1", "segment_id": "s1", "text": "验证节点依次确认交易。",
    }]}), encoding="utf-8")
    decisions.write_text(json.dumps({"decisions": [{
        "narration_proposition_id": "p1", "action": "generate", "generation_prompt": "交易确认流程",
    }]}), encoding="utf-8")
    monkeypatch.setattr(
        "textbook2video.research.auto_visual_plan.chat_with_system",
        lambda *_args, **_kwargs: json.dumps({"visuals": [{
            "proposition_id": "p1", "kind": "flow", "title": "交易确认", "items": ["提交", "验证", "确认"],
        }]}, ensure_ascii=False),
    )

    path = build_auto_visual_plan(
        proposition_graph_path=graph, visual_decision_path=decisions,
        output_path=tmp_path / "auto.json", model="ecnu-plus",
    )
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert plan["visuals"][0]["kind"] == "flow"
    assert plan["bindings"][0]["proposition_id"] == "p1"
    assert plan["plan"]["events"][0]["target_element_id"] == "visual-auto-001-p1"


def test_auto_visual_plan_normalizes_flat_comparison_to_flow(tmp_path: Path, monkeypatch) -> None:
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    graph.write_text(
        json.dumps(
            {
                "narration_propositions": [
                    {"id": "p1", "segment_id": "s1", "text": "对比流程"}
                ]
            }
        ),
        encoding="utf-8",
    )
    decisions.write_text(
        json.dumps({"decisions": [{"narration_proposition_id": "p1", "action": "generate"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "textbook2video.research.auto_visual_plan.chat_with_system",
        lambda *_args, **_kwargs: json.dumps(
            {
                "visuals": [
                    {
                        "proposition_id": "p1",
                        "kind": "comparison",
                        "title": "对比",
                        "items": ["A", "A1", "B", "B1"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    path = build_auto_visual_plan(
        proposition_graph_path=graph,
        visual_decision_path=decisions,
        output_path=tmp_path / "auto.json",
    )
    visual = json.loads(path.read_text(encoding="utf-8"))["visuals"][0]
    assert visual["kind"] == "flow"
    assert visual["items"] == ["A", "A1", "B", "B1"]


def test_auto_visual_plan_normalizes_generic_image_alias(tmp_path: Path, monkeypatch) -> None:
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    graph.write_text(
        json.dumps(
            {
                "narration_propositions": [
                    {"id": "p1", "segment_id": "s1", "text": "场景"}
                ]
            }
        ),
        encoding="utf-8",
    )
    decisions.write_text(
        json.dumps({"decisions": [{"narration_proposition_id": "p1", "action": "generate"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "textbook2video.research.auto_visual_plan.chat_with_system",
        lambda *_args, **_kwargs: json.dumps(
            {
                "visuals": [
                    {
                        "proposition_id": "p1",
                        "kind": "image",
                        "title": "场景",
                        "prompt": "A classroom scene",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    path = build_auto_visual_plan(
        proposition_graph_path=graph,
        visual_decision_path=decisions,
        output_path=tmp_path / "auto.json",
    )
    visual = json.loads(path.read_text(encoding="utf-8"))["visuals"][0]
    assert visual["kind"] == "scene"


def test_auto_visual_plan_normalizes_non_numeric_chart(tmp_path: Path, monkeypatch) -> None:
    graph = tmp_path / "graph.json"
    decisions = tmp_path / "decisions.json"
    graph.write_text(
        json.dumps(
            {"narration_propositions": [{"id": "p1", "segment_id": "s1", "text": "流程"}]}
        ),
        encoding="utf-8",
    )
    decisions.write_text(
        json.dumps({"decisions": [{"narration_proposition_id": "p1", "action": "generate"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "textbook2video.research.auto_visual_plan.chat_with_system",
        lambda *_args, **_kwargs: json.dumps(
            {
                "visuals": [
                    {
                        "proposition_id": "p1",
                        "kind": "chart",
                        "title": "流程",
                        "items": ["输入", "处理", "输出"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    path = build_auto_visual_plan(
        proposition_graph_path=graph,
        visual_decision_path=decisions,
        output_path=tmp_path / "auto.json",
    )
    visual = json.loads(path.read_text(encoding="utf-8"))["visuals"][0]
    assert visual["kind"] == "flow"
