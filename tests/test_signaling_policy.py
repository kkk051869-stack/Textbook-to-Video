from textbook2video.research.signaling_policy import audit_signaling_policy


def _storyboard(role: str = "explain") -> dict:
    return {
        "case_id": "case_1",
        "segments": [
            {
                "id": "s1",
                "elements": [{"id": "e1", "semantic_role": role}],
            }
        ],
    }


def _schedule(action: str = "show") -> dict:
    return {
        "case_id": "case_1",
        "events": [{"event_id": "v1", "target_element_id": "e1", "action": action}],
    }


def test_show_is_not_automatically_signaling() -> None:
    report = audit_signaling_policy(_storyboard("explain"), _schedule("show"))
    assert report["events"][0]["status"] == "not_applicable"
    assert report["metrics"]["signal_present"] == 0


def test_declared_signal_role_without_cue_is_reported() -> None:
    report = audit_signaling_policy(_storyboard("signal"), _schedule("show"))
    assert report["events"][0]["status"] == "missing_signal"


def test_highlight_without_signal_role_is_only_a_proxy_warning() -> None:
    report = audit_signaling_policy(_storyboard("explain"), _schedule("highlight"))
    assert report["events"][0]["status"] == "possibly_excessive_signal"
    assert "not pedagogical necessity" in report["warning"]
