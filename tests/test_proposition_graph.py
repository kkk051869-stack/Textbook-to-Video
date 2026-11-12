import json

import pytest

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


def test_empty_proposition_segment_uses_minimal_repair(tmp_path, monkeypatch) -> None:
    raw = tmp_path / "lesson.txt"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    lesson_plan = tmp_path / "lesson_plan.json"
    output = tmp_path / "graph.json"
    source_text = "区块链由多个区块按顺序连接。"
    raw.write_text(source_text, encoding="utf-8")
    evidence.write_text(
        json.dumps({"source_units": [{"id": "raw-1", "text": source_text}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    storyboard.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": "1",
                        "narration": source_text,
                        "knowledge_point_ids": ["kp-1"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lesson_plan.write_text(
        json.dumps({"knowledge_points": [{"id": "kp-1", "name": "区块链"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    responses = iter(
        [
            {},
            {},
            {
                "knowledge_propositions": [
                    {
                        "local_id": "kp1",
                        "knowledge_point_id": "kp-1",
                        "text": "区块链由多个区块按顺序连接",
                        "source_unit_ids": ["raw-1"],
                    }
                ],
                "narration_propositions": [
                    {
                        "segment_id": "1",
                        "text": source_text,
                        "knowledge_proposition_local_ids": ["kp1"],
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(
        "textbook2video.research.proposition_graph.chat_with_system",
        lambda *_args, **_kwargs: json.dumps(next(responses), ensure_ascii=False),
    )
    build_proposition_graph(
        raw_path=raw,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        lesson_plan_path=lesson_plan,
        output_path=output,
    )
    assert json.loads(output.read_text(encoding="utf-8"))["narration_propositions"]


def test_unlinked_narration_proposition_uses_minimal_link_repair(
    tmp_path, monkeypatch
) -> None:
    raw = tmp_path / "lesson.txt"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    lesson_plan = tmp_path / "lesson_plan.json"
    output = tmp_path / "graph.json"
    source_text = "区块链由多个区块按顺序连接。"
    raw.write_text(source_text, encoding="utf-8")
    evidence.write_text(
        json.dumps({"source_units": [{"id": "raw-1", "text": source_text}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    storyboard.write_text(
        json.dumps(
            {"segments": [{"id": "1", "narration": source_text, "knowledge_point_ids": ["kp-1"]}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lesson_plan.write_text(
        json.dumps({"knowledge_points": [{"id": "kp-1", "name": "区块链"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    generated = {
        "knowledge_propositions": [
            {
                "local_id": "kp1",
                "knowledge_point_id": "kp-1",
                "text": "区块链由多个区块按顺序连接",
                "source_unit_ids": ["raw-1"],
            }
        ],
        "narration_propositions": [
            {"segment_id": "1", "text": source_text, "knowledge_proposition_local_ids": []}
        ],
    }
    responses = iter(
        [
            generated,
            {"links": []},
            {"repair_id": "1", "knowledge_proposition_local_ids": ["kp1"]},
        ]
    )
    monkeypatch.setattr(
        "textbook2video.research.proposition_graph.chat_with_system",
        lambda *_args, **_kwargs: json.dumps(next(responses), ensure_ascii=False),
    )
    build_proposition_graph(
        raw_path=raw,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        lesson_plan_path=lesson_plan,
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["narration_propositions"][0]["knowledge_proposition_ids"]


def test_exact_english_source_anchor_supports_chinese_proposition(tmp_path, monkeypatch) -> None:
    raw = tmp_path / "lesson.txt"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    lesson_plan = tmp_path / "lesson_plan.json"
    output = tmp_path / "graph.json"
    raw.write_text("Motion compensation removes artifacts.", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {"source_units": [{"id": "raw-1", "text": "Motion compensation removes artifacts."}]}
        ),
        encoding="utf-8",
    )
    storyboard.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": "1",
                        "narration": "运动补偿能够去除伪影。",
                        "knowledge_point_ids": ["kp-1"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lesson_plan.write_text(
        json.dumps({"knowledge_points": [{"id": "kp-1", "name": "运动补偿"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    generated = {
        "knowledge_propositions": [
            {
                "local_id": "kp1",
                "knowledge_point_id": "kp-1",
                "text": "运动补偿能够去除伪影",
                "source_unit_ids": ["raw-1"],
                "source_anchor": "Motion compensation removes artifacts",
            }
        ],
        "narration_propositions": [
            {
                "segment_id": "1",
                "text": "运动补偿能够去除伪影。",
                "knowledge_proposition_local_ids": ["kp1"],
            }
        ],
    }
    monkeypatch.setattr(
        "textbook2video.research.proposition_graph.chat_with_system",
        lambda *_args, **_kwargs: json.dumps(generated, ensure_ascii=False),
    )
    build_proposition_graph(
        raw_path=raw,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        lesson_plan_path=lesson_plan,
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["knowledge_propositions"][0]["source_anchor"]


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


@pytest.mark.parametrize(
    ("allow_partial", "use_clause_ids"), [(False, False), (True, False), (True, True)]
)
def test_small_source_batch_builds_valid_graph_with_one_model_call(
    tmp_path, monkeypatch, allow_partial, use_clause_ids
) -> None:
    raw = tmp_path / "lesson.txt"
    evidence = tmp_path / "evidence.json"
    storyboard = tmp_path / "storyboard.json"
    lesson_plan = tmp_path / "lesson_plan.json"
    output = tmp_path / "graph.json"
    raw.write_text(
        "FineGym has three semantic levels: event, set, and element. "
        "Actions are decomposed into temporal sub-actions.",
        encoding="utf-8",
    )
    repeated_clause = "动作还会沿时间拆分成子动作。"
    second_narration = f"{repeated_clause} {repeated_clause}" if use_clause_ids else repeated_clause
    evidence.write_text(
        json.dumps(
            {
                "source_units": [
                    {"id": "raw-1", "text": "FineGym has three semantic levels: event, set, and element."},
                    {"id": "raw-2", "text": "Actions are decomposed into temporal sub-actions."},
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
                    {"id": "1", "narration": "FineGym具有Event、Set和Element三级语义。", "knowledge_point_ids": ["kp-1"]},
                    {"id": "2", "narration": second_narration, "knowledge_point_ids": ["kp-2"]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lesson_plan.write_text(
        json.dumps(
            {"knowledge_points": [{"id": "kp-1", "name": "语义层级"}, {"id": "kp-2", "name": "时间层级"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    generated = {
        "knowledge_propositions": [
            {
                "segment_id": "1", "local_id": "kp1-p1", "knowledge_point_id": "kp-1",
                "text": "FineGym包含event、set和element三个语义层级。",
                "source_unit_ids": ["raw-1"],
                "source_anchor": "FineGym has three semantic levels: event, set, and element",
            },
            {
                "segment_id": "2", "local_id": "kp2-p1", "knowledge_point_id": "kp-2",
                "text": "动作被分解为时间上的子动作。",
                "source_unit_ids": ["raw-2"],
                "source_anchor": "Actions are decomposed into temporal sub-actions",
            },
        ],
        "narration_propositions": [
            {"segment_id": "1", "text": "FineGym具有Event、Set和Element三级语义。", "knowledge_proposition_local_ids": ["kp1-p1"]},
            {"segment_id": "2", "text": "动作还会沿时间拆分成子动作。", "knowledge_proposition_local_ids": ["kp2-p1"]},
        ],
    }
    if use_clause_ids:
        generated["narration_propositions"] = [
            {"segment_id": "1", "narration_clause_ids": ["1-c1"],
             "knowledge_proposition_local_ids": ["kp1-p1"]},
            {"segment_id": "2", "narration_clause_ids": ["2-c2"], "text": "改写内容",
             "knowledge_proposition_local_ids": ["kp2-p1"]},
            {"segment_id": "2", "narration_clause_ids": ["1-c1"],
             "knowledge_proposition_local_ids": ["kp2-p1"]},
        ]
    elif allow_partial:
        generated["narration_propositions"].append({
            "segment_id": "2", "text": "动作会按照时间拆分为子动作。",
            "knowledge_proposition_local_ids": ["kp2-p1"],
        })
    calls = []

    def fake_chat(prompt, **kwargs):
        assert kwargs["timeout"] == 180
        calls.append(prompt)
        return json.dumps(generated, ensure_ascii=False)

    monkeypatch.setattr("textbook2video.research.proposition_graph.chat_with_system", fake_chat)
    build_proposition_graph(
        raw_path=raw,
        source_evidence_path=evidence,
        storyboard_path=storyboard,
        lesson_plan_path=lesson_plan,
        output_path=output,
        batch_small_source=True,
        allow_partial=allow_partial,
        request_timeout_sec=180,
        use_narration_clause_ids=use_clause_ids,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert len(payload["knowledge_propositions"]) == 2
    assert {item["segment_id"] for item in payload["narration_propositions"]} == {"1", "2"}
    prompt_payload = json.loads(calls[0])
    rejected = [item["reason"] for item in payload["rejected_claims"]]
    if use_clause_ids:
        assert rejected == ["invalid_narration_clause_ids"]
        second = payload["narration_propositions"][1]
        assert second["text"] == repeated_clause
        assert second["span"]["start"] == len(repeated_clause) + 1
        assert [c["id"] for c in prompt_payload["segments"][1]["narration_clauses"]] == [
            "2-c1", "2-c2",
        ]
        assert "text" not in prompt_payload["output_schema"]["narration_propositions"][0]
    else:
        assert rejected == (["narration_span_not_found"] if allow_partial else [])
    assert {item["id"] for item in prompt_payload["source_units"]} == {"raw-1", "raw-2"}
    response_trace = json.loads(
        output.with_name("graph_model_response.json").read_text(encoding="utf-8")
    )
    assert response_trace["response"]["knowledge_propositions"][0]["segment_id"] == "1"


def test_structural_source_units_are_not_treated_as_factual_evidence() -> None:
    assert _is_structural_source_unit("# 标题")
    assert _is_structural_source_unit("- lesson_id: `lesson_002`")
    assert _is_structural_source_unit("（一）链式数据结构")
    assert _is_structural_source_unit("图7-6 区块链数据结构")
    assert not _is_structural_source_unit("区块链是一种分布式记账方式。")


def test_unmatched_cross_language_context_keeps_source_order_and_full_short_source():
    units = [{'id': 'later', 'text': 'Temporal decomposition uses sub-actions.'},
             {'id': 'first', 'text': 'Semantic hierarchy has three levels.'}]
    assert _evidence_for_segment(units, '动作可以沿时间分解。', limit=1) == units


def test_unmatched_large_context_refuses_arbitrary_first_lines():
    import pytest
    units = [{'id': str(i), 'text': 'English source passage ' * 1000} for i in range(3)]
    with pytest.raises(ValueError, match='no reliable'):
        _evidence_for_segment(units, '没有词面对应的中文。')


def test_source_anchor_can_cross_verified_adjacent_lines_but_not_omitted_content():
    from textbook2video.research.proposition_graph import _has_valid_source_anchor
    raw = 'First claim\ncontinues here. OMITTED Second claim'
    units = [{'text': 'First claim', 'char_span': {'start': 0, 'end': 11}},
             {'text': 'continues here.', 'char_span': {'start': 12, 'end': 27}}]
    assert _has_valid_source_anchor({'source_anchor': 'First claim continues here.'}, units, raw)
    assert not _has_valid_source_anchor({'source_anchor': 'First claim Second claim'}, units, raw)
