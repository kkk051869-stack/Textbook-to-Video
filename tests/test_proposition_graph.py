from textbook2video.research.proposition_graph import (
    _evidence_for_segment,
    _is_structural_source_unit,
)


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
