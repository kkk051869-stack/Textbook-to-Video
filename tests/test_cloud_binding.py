from textbook2video.research.cloud_binding import build_cloud_binding_report


class FakeClient:
    def chat(self, messages, *, max_tokens):
        assert max_tokens == 400
        return (
            {
                "status": "bound",
                "target_element_ids": ["e1"],
                "confidence": 0.8,
                "rationale": "match",
            },
            "raw",
        )


def test_cloud_binding_keeps_raw_response_and_allowed_target_only():
    script = {
        "segments": [
            {"id": "s1", "narration_propositions": [{"id": "p1", "text": "explain ledger"}]}
        ]
    }
    storyboard = {
        "segments": [{"id": "s1", "elements": [{"id": "e1", "type": "text", "text": "ledger"}]}]
    }
    report = build_cloud_binding_report(
        script, storyboard, case_id="case", client=FakeClient(), model="fake"
    )
    assert report["metrics"]["bound_count"] == 1
    assert report["bindings"][0]["target_element_ids"] == ["e1"]
    assert report["bindings"][0]["raw_response"] == "raw"
