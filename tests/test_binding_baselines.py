from textbook2video.research.binding_baselines import (
    element_text,
    jaccard_similarity,
    lexical_jaccard_bind,
)


def test_lexical_baseline_selects_semantically_overlapping_element() -> None:
    elements = [
        {"id": "e1", "type": "image", "payload": {"description": "太阳加热水面产生蒸发"}},
        {"id": "e2", "type": "diagram", "payload": {"description": "水蒸气遇冷形成小水滴"}},
    ]
    result = lexical_jaccard_bind("水蒸气遇冷凝结成小水滴", elements)
    assert result["status"] == "bound"
    assert result["target_element_ids"] == ["e2"]
    assert result["binding_source"] == "lexical_jaccard"


def test_lexical_baseline_abstains_below_threshold() -> None:
    result = lexical_jaccard_bind(
        "量子纠缠",
        [{"id": "e1", "type": "image", "payload": {"description": "植物光合作用"}}],
        threshold=0.2,
    )
    assert result["status"] == "abstained"
    assert result["target_element_ids"] == []


def test_element_text_excludes_ids_but_reads_nested_payload() -> None:
    surface = element_text(
        {
            "id": "case-seg-001-el-001",
            "legacy_id": "e1",
            "payload": {"description": "水循环图", "items": ["蒸发", "凝结"]},
        }
    )
    assert "水循环图" in surface
    assert "蒸发" in surface
    assert "case-seg" not in surface
    assert jaccard_similarity("蒸发", surface) > 0


def test_ties_are_stable_and_can_return_multiple_targets() -> None:
    elements = [
        {"id": "e2", "text": "哈希散列"},
        {"id": "e1", "text": "哈希散列"},
    ]
    result = lexical_jaccard_bind("哈希散列", elements, max_targets=2)
    assert result["target_element_ids"] == ["e1", "e2"]
