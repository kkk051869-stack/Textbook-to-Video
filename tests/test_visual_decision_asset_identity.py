"""Asset identity remains an execution constraint across research conditions."""

import json

import pytest

from textbook2video.research import visual_decision as decision


@pytest.mark.parametrize("condition", [None, *sorted(decision.RQ1_RESEARCH_CONDITIONS)])
@pytest.mark.parametrize("image_id", [None, "fig-source", "native-operation"])
def test_prompt_and_gate_share_image_identity(tmp_path, monkeypatch, condition, image_id):
    def write(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    graph = write("graph.json", {"narration_propositions": [{
        "id": "p1", "segment_id": "s1", "text": "A source claim.", "source_refs": ["u1"],
    }]})
    evidence = write("source.json", {
        "source_units": [{"id": "u1", "text": "A source claim."}],
        "source_images": [{"id": "fig-source", "caption": "Source figure"}],
    })
    catalog = write("catalog.json", {"summary": {
        "existing_native_components": [{"id": "native-operation", "text": "Operation"}],
    }})

    def response(prompt, **kwargs):
        payload = json.loads(prompt)
        assert payload["allowed_source_image_ids"] == (
            [] if condition == "no_source" else ["fig-source"]
        )
        assert any("empty list means reuse is unavailable" in r for r in payload["rules"])
        assert any("handled by binding" in r for r in payload["rules"])
        return json.dumps({"decisions": [{
            "narration_proposition_id": "p1",
            "action": "reuse" if image_id else "none",
            "source_image_id": image_id,
            "rationale": "Fixture, not a semantic judgment.",
        }]})

    monkeypatch.setattr(decision, "chat_with_system", response)
    kwargs = dict(
        proposition_graph_path=graph, source_evidence_path=evidence,
        retrieval_catalog_path=catalog, output_path=tmp_path / "out.json",
        research_condition=condition,
    )
    if image_id == "native-operation" or (condition == "no_source" and image_id):
        with pytest.raises(ValueError, match="unavailable source image|hidden source image"):
            decision.decide_visual_support(**kwargs)
        assert not (tmp_path / "out.json").exists()
    else:
        decision.decide_visual_support(**kwargs)
        assert json.loads((tmp_path / "out.json").read_text())["decisions"][0]["action"] == (
            "reuse" if image_id else "none"
        )


def test_ordinary_decision_receives_existing_components_without_reuse_identity(tmp_path, monkeypatch):
    def write(name, value):
        p=tmp_path/name; p.write_text(json.dumps(value), encoding='utf-8'); return p
    elements=[{'id': 'flow', 'type': 'flow_step', 'steps': ['Input', 'Output']}]
    graph=write('graph.json', {'narration_propositions': [{'id': 'p1', 'segment_id': 's1', 'text': 'Input becomes output.', 'source_refs': ['u1']}]})
    source=write('source.json', {'source_units': [{'id': 'u1', 'text': 'Input becomes output.'}], 'source_images': []})
    board=write('board.json', {'segments': [{'id': 's1', 'elements': elements}]})
    def response(prompt, **kwargs):
        payload=json.loads(prompt)
        assert payload['existing_page_components']==elements
        assert payload['allowed_source_image_ids']==[]
        return json.dumps({'decisions': [{'narration_proposition_id': 'p1', 'action': 'none', 'rationale': 'The existing flow explains the claim.'}]})
    monkeypatch.setattr(decision, 'chat_with_system', response)
    out=decision.decide_visual_support(proposition_graph_path=graph, source_evidence_path=source, storyboard_path=board, output_path=tmp_path/'decision.json', consider_existing_components=True)
    assert json.loads(out.read_text())['decisions'][0]['action']=='none'
