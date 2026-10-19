import json

from textbook2video.research.proposition_graph import (
    _evidence_for_segment,
    _is_structural_source_unit,
    build_proposition_graph,
)


def test_ungrounded_knowledge_propositions_are_repaired_once(
    tmp_path, monkeypatch
) -> None:
    raw = tmp_path / "lesson.txt"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    lesson_plan = tmp_path / "lesson_plan.json"
    output = tmp_path / "graph.json"
    raw.write_text("区块链由多个区块按顺序连接。", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "source_units": [
                    {
                        "id": "raw-unit-0001",
                        "text": "区块链由多个区块按顺序连接。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storyboard.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": "1",
                        "narration": "区块链由多个区块按顺序连接。",
                        "knowledge_point_ids": ["kp-1"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lesson_plan.write_text(
        json.dumps(
            {"knowledge_points": [{"id": "kp-1", "name": "区块链"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    responses = iter(
        [
            {
                "knowledge_propositions": [
                    {
                        "local_id": "kp1",
                        "knowledge_point_id": "kp-1",
                        "text": "这是不相关的结论",
                        "source_unit_ids": ["raw-unit-0001"],
                    }
                ],
                "narration_propositions": [
                    {
                        "segment_id": "1",
                        "text": "区块链由多个区块按顺序连接。",
                        "knowledge_proposition_local_ids": ["kp1"],
                    }
                ],
            },
            {
                "repairs": [
                    {
                        "local_id": "kp1",
                        "text": "区块链由多个区块按顺序连接",
                        "source_unit_ids": ["raw-unit-0001"],
                    }
                ],
            },
        ]
    )

    def fake_chat(*_args, **_kwargs) -> str:
        return json.dumps(next(responses), ensure_ascii=False)

    monkeypatch.setattr(
        "textbook2video.research.proposition_graph.chat_with_system", fake_chat
    )
    build_proposition_graph(
        raw_path=raw,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        lesson_plan_path=lesson_plan,
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["knowledge_propositions"][0]["text"] == "区块链由多个区块按顺序连接"


def test_chinese_evidence_retrieval_prefers_content_over_title() -> None:
    units = [
        {"id": "raw-unit-0001", "text": "# 区块链 - 四、区块链是信任数据库"},
        {
            "id": "raw-unit-0012",
            "text": "区块链实质上是一种分布式记账方式，所有参与者均维护一份完整的账本。",
        },
        {
            "id": "raw-unit-0013",
            "text": "输入数据发生微小变动，会导致哈希输出发生显著变化。",
        },
    ]

    selected = _evidence_for_segment(
        units,
        "每个参与者都有一份完整的账本副本。",
        limit=1,
    )

    assert selected[0]["id"] == "raw-unit-0012"


def test_structural_source_units_are_not_treated_as_factual_evidence() -> None:
    assert _is_structural_source_unit("# 标题")
    assert _is_structural_source_unit("- lesson_id: `lesson_002`")
    assert _is_structural_source_unit("（一）链式数据结构")
    assert _is_structural_source_unit("图7-6 区块链数据结构")
    assert not _is_structural_source_unit("区块链是一种分布式记账方式。")
