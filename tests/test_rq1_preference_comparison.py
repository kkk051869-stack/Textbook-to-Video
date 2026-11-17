import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_rq1_preference_comparison.py"
SPEC = importlib.util.spec_from_file_location("run_rq1_preference_comparison", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_aggregate_reports_top1_top2_rejection_and_cost() -> None:
    rows = [
        {
            "method_choices": {"m": "none"},
            "judgment": {
                "abstain": False,
                "best_action": "none",
                "ranking": ["none", "retrieve", "generate"],
                "rejected_actions": ["generate"],
            },
        },
        {
            "method_choices": {"m": "retrieve"},
            "judgment": {
                "abstain": False,
                "best_action": "generate",
                "ranking": ["generate", "retrieve", "none"],
                "rejected_actions": ["none"],
            },
        },
    ]

    result = MODULE._aggregate(rows)["m"]

    assert result["top1_rate"] == 0.5
    assert result["rank_top2_rate"] == 1.0
    assert result["acceptable_top2_rate"] == 1.0
    assert result["rejected_count"] == 0
    assert result["external_retrieval_requests"] == 1
    assert result["generation_requests"] == 0


def test_option_order_is_deterministic_and_reuse_requires_real_image(tmp_path: Path) -> None:
    image = tmp_path / "candidate.png"
    image.write_bytes(b"png")
    proposition = {"id": "p1", "text": "结构关系"}

    assets = {
        "fig-1": {
            "path": image,
            "caption": "结构图",
            "kind": "source-image",
            "source_locator": "page-1",
        }
    }
    first, images = MODULE._action_options(proposition, ["fig-1"], assets)
    second, _ = MODULE._action_options(proposition, ["fig-1"], assets)

    assert first == second
    assert {item["action"] for item in first} == {"none", "reuse", "retrieve", "generate"}
    assert images == [image]
    reuse = next(item for item in first if item["action"] == "reuse")
    assert reuse["proposal"]["source_caption"] == "结构图"
