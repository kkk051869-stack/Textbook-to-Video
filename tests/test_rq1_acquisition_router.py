from textbook2video.research.rq1_acquisition_router import route_acquisition


def test_composed_explanatory_diagram_routes_to_generation() -> None:
    original = {
        "action": "retrieve",
        "retrieval_query": "centralized vs decentralized network diagram",
        "acceptance_criteria": ["Side-by-side comparison of both mechanisms"],
    }

    routed = route_acquisition(original)

    assert routed["action"] == "generate"
    assert routed["retrieval_query"] is None
    assert routed["generation_prompt"].startswith("Create a source-bounded")
    assert routed["acquisition_routing"]["changed"] is True
    assert original["action"] == "retrieve"


def test_existing_real_world_asset_stays_retrieval() -> None:
    routed = route_acquisition(
        {
            "action": "retrieve",
            "retrieval_query": "historical photo of the 2008 financial crisis",
            "acceptance_criteria": ["Public-domain image with a source date"],
        }
    )

    assert routed["action"] == "retrieve"
    assert routed["acquisition_routing"]["retrieval_cues"]
    assert routed["acquisition_routing"]["changed"] is False


def test_non_retrieval_decision_is_unchanged() -> None:
    routed = route_acquisition({"action": "reuse", "source_image_id": "fig-1"})

    assert routed["action"] == "reuse"
    assert routed["acquisition_routing"]["changed"] is False


def test_ambiguous_retrieval_stays_for_review() -> None:
    routed = route_acquisition(
        {"action": "retrieve", "retrieval_query": "blockchain trust technology"}
    )

    assert routed["action"] == "retrieve"
    assert "preserve retrieval" in routed["acquisition_routing"]["reason"]


def test_mixed_historical_and_composition_request_requires_review() -> None:
    routed = route_acquisition(
        {
            "action": "retrieve",
            "retrieval_query": "historical photo and timeline infographic",
            "acceptance_criteria": ["Combine the dated event and document release"],
        }
    )

    assert routed["action"] == "retrieve"
    assert routed["acquisition_routing"]["review_required"] is True
    assert routed["acquisition_routing"]["composition_cues"]
    assert routed["acquisition_routing"]["retrieval_cues"]
