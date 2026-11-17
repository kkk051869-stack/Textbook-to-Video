"""Compare RQ1 methods against a forced-choice, method-blind preference Judge."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from textbook2video.research.rq1_preference_judge import (  # noqa: E402
    PREFERENCE_JUDGE_VERSION,
    judge_rq1_action_preferences,
)
from textbook2video.research.rq1_acquisition_router import route_acquisition  # noqa: E402
from textbook2video.research.visual_decision_baselines import predict_baseline  # noqa: E402


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _sample_by_action(
    propositions: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    per_action: int,
) -> list[dict[str, Any]]:
    proposition_by_id = {
        str(item.get("id") or ""): item for item in propositions if isinstance(item, dict)
    }
    sample: list[dict[str, Any]] = []
    for action in ("none", "reuse", "retrieve", "generate"):
        candidates = sorted(
            [
                item
                for item in decisions
                if isinstance(item, dict) and str(item.get("action") or "") == action
            ],
            key=lambda item: str(item.get("narration_proposition_id") or ""),
        )
        if len(candidates) < per_action:
            raise ValueError(f"not enough {action} examples for requested sample")
        for decision in candidates[:per_action]:
            proposition_id = str(decision.get("narration_proposition_id") or "")
            sample.append(
                {
                    "proposition": proposition_by_id[proposition_id],
                    "current_decision": decision,
                    "stratum": action,
                }
            )
    return sample


def _segment_images(storyboard: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for index, segment in enumerate(storyboard.get("segments", []), start=1):
        if not isinstance(segment, dict):
            continue
        result[str(segment.get("id") or index)] = sorted(
            {
                str(element.get("source_image_id"))
                for element in segment.get("elements", [])
                if isinstance(element, dict) and element.get("source_image_id")
            }
        )
    return result


def _candidate_assets(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for item in document.get("candidates", []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "")
        path = REPO_ROOT / str(item.get("path") or "")
        if candidate_id and path.is_file():
            assets[candidate_id] = {
                "path": path,
                "caption": item.get("caption"),
                "kind": item.get("kind"),
                "source_locator": item.get("source_locator"),
            }
    return assets


def _action_options(
    proposition: dict[str, Any],
    source_image_ids: list[str],
    candidate_assets: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[Path]]:
    text = str(proposition.get("text") or "").strip()
    options: list[dict[str, Any]] = [
        {
            "action": "none",
            "proposal": "Use narration/text only; add no visual for this proposition.",
            "cost_level": 0,
        },
        {
            "action": "retrieve",
            "proposal": {
                "query": text,
                "acceptance_criteria": [
                    "must directly explain the proposition",
                    "must avoid generic stock imagery and unsupported facts",
                ],
            },
            "cost_level": 2,
        },
        {
            "action": "generate",
            "proposal": (
                "Create a concise source-bounded instructional schematic that explains: "
                f"{text}"
            ),
            "cost_level": 3,
        },
    ]
    images: list[Path] = []
    for image_id in source_image_ids:
        asset = candidate_assets.get(image_id)
        if asset:
            path = asset["path"]
            images.append(path)
            options.append(
                {
                    "action": "reuse",
                    "proposal": {
                        "source_image_id": image_id,
                        "attached_image_number": len(images),
                        "source_caption": asset.get("caption"),
                        "asset_kind": asset.get("kind"),
                        "source_locator": asset.get("source_locator"),
                    },
                    "cost_level": 1,
                }
            )
            break
    options.sort(key=lambda option: _hash([proposition.get("id"), option["action"]]))
    return options, images


def _method_choices(
    sample: dict[str, Any], source_image_ids: list[str]
) -> dict[str, str]:
    proposition = sample["proposition"]
    choices = {
        policy: str(
            predict_baseline(
                policy=policy,
                proposition=proposition,
                source_image_ids=source_image_ids,
            )["action"]
        )
        for policy in ("never_retrieve", "always_retrieve", "keyword_heuristic")
    }
    choices["current_visual_decision"] = str(sample["current_decision"].get("action") or "")
    choices["routed_visual_decision"] = str(
        route_acquisition(sample["current_decision"]).get("action") or ""
    )
    return choices


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    methods: dict[str, dict[str, Any]] = {}
    method_names = sorted({name for row in rows for name in row["method_choices"]})
    for method in method_names:
        valid = [row for row in rows if not row["judgment"]["abstain"]]
        choices = [row["method_choices"][method] for row in valid]
        top1 = sum(choice == row["judgment"]["best_action"] for choice, row in zip(choices, valid))
        rank_top2 = sum(
            choice in row["judgment"]["ranking"][:2] for choice, row in zip(choices, valid)
        )
        acceptable_top2 = sum(
            choice in row["judgment"]["ranking"][:2]
            and choice not in row["judgment"]["rejected_actions"]
            for choice, row in zip(choices, valid)
        )
        rejected = sum(
            choice in row["judgment"]["rejected_actions"]
            for choice, row in zip(choices, valid)
        )
        ranks = [
            row["judgment"]["ranking"].index(choice) + 1
            for choice, row in zip(choices, valid)
            if choice in row["judgment"]["ranking"]
        ]
        action_counts = Counter(choices)
        methods[method] = {
            "evaluated_count": len(valid),
            "top1_count": top1,
            "top1_rate": round(top1 / len(valid), 6) if valid else None,
            "rank_top2_count": rank_top2,
            "rank_top2_rate": round(rank_top2 / len(valid), 6) if valid else None,
            "acceptable_top2_count": acceptable_top2,
            "acceptable_top2_rate": round(acceptable_top2 / len(valid), 6)
            if valid
            else None,
            "rejected_count": rejected,
            "rejected_rate": round(rejected / len(valid), 6) if valid else None,
            "mean_rank": round(sum(ranks) / len(ranks), 6) if ranks else None,
            "action_counts": dict(sorted(action_counts.items())),
            "external_retrieval_requests": action_counts["retrieve"],
            "generation_requests": action_counts["generate"],
            "visual_asset_requests": action_counts["retrieve"] + action_counts["generate"],
        }
    return methods


def run_preference_comparison(
    *,
    proposition_graph_path: Path,
    source_evidence_path: Path,
    visual_decisions_path: Path,
    storyboard_path: Path,
    candidate_universe_path: Path,
    output_dir: Path,
    model: str,
    per_action: int = 3,
    judge_call: Callable[..., dict[str, Any]] = judge_rq1_action_preferences,
) -> Path:
    graph = _read(proposition_graph_path)
    evidence = _read(source_evidence_path)
    decisions = _read(visual_decisions_path)
    storyboard = _read(storyboard_path)
    candidate_universe = _read(candidate_universe_path)
    sample = _sample_by_action(
        graph.get("narration_propositions", []),
        decisions.get("decisions", []),
        per_action=per_action,
    )
    source_units = {
        str(item.get("id") or ""): item
        for item in evidence.get("source_units", [])
        if isinstance(item, dict)
    }
    segment_images = _segment_images(storyboard)
    candidate_assets = _candidate_assets(candidate_universe)
    output_dir.mkdir(parents=True, exist_ok=True)
    judgments_dir = output_dir / "judgments"
    judgments_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for item in sample:
        proposition = item["proposition"]
        proposition_id = str(proposition.get("id") or "")
        source = [
            source_units[reference]
            for reference in proposition.get("source_refs", [])
            if reference in source_units
        ]
        source_image_ids = segment_images.get(str(proposition.get("segment_id") or ""), [])
        options, images = _action_options(proposition, source_image_ids, candidate_assets)
        fingerprint = _hash(
            {
                "model": model,
                "judge_version": PREFERENCE_JUDGE_VERSION,
                "proposition": proposition,
                "source": source,
                "options": options,
                "image_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in images],
            }
        )
        cache_path = judgments_dir / f"{proposition_id}.json"
        if cache_path.is_file():
            cached = _read(cache_path)
            if cached.get("input_sha256") != fingerprint:
                raise ValueError(f"stale preference Judge cache: {cache_path}")
            judgment = cached["judgment"]
        else:
            judgment = judge_call(
                proposition=proposition,
                source_evidence=source,
                options=options,
                candidate_images=images,
                model=model,
            )
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": "rq1-preference-judge-cache-v0.1",
                        "input_sha256": fingerprint,
                        "model": model,
                        "judgment": judgment,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        rows.append(
            {
                "proposition_id": proposition_id,
                "stratum": item["stratum"],
                "option_order": [option["action"] for option in options],
                "method_choices": _method_choices(item, source_image_ids),
                "judgment": judgment,
            }
        )

    winner_positions = Counter(
        row["option_order"].index(row["judgment"]["best_action"]) + 1
        for row in rows
        if row["judgment"]["best_action"] in row["option_order"]
    )
    report = {
        "schema_version": "rq1-preference-comparison-v0.1",
        "status": "DEVELOPMENT_SMALL_SAMPLE_NOT_FORMAL_EXPERIMENT",
        "model": model,
        "sample_count": len(sample),
        "sample_strategy": f"first {per_action} propositions per current action",
        "method_identity_hidden_from_judge": True,
        "winner_action_counts": dict(
            sorted(Counter(row["judgment"]["best_action"] for row in rows).items())
        ),
        "winner_option_position_counts": {
            str(position): count for position, count in sorted(winner_positions.items())
        },
        "first_position_win_rate": round(winner_positions[1] / len(rows), 6),
        "judge_abstain_count": sum(row["judgment"]["abstain"] for row in rows),
        "judge_format_repair_count": sum(
            bool(row["judgment"].get("format_repair_used")) for row in rows
        ),
        "methods": _aggregate(rows),
        "rows": rows,
        "limitations": [
            "This is a 12-item development sample, not a formal paper experiment.",
            "The same model acts as preference Judge; results require order-sensitivity checks "
            "and independent model review, with unresolved cases reported explicitly.",
            "Retrieve and generate are judged as action specifications, not executed asset outcomes.",
            "Top-1 agreement with the Judge is not a learning-effect measurement.",
        ],
    }
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposition-graph", required=True, type=Path)
    parser.add_argument("--source-evidence", required=True, type=Path)
    parser.add_argument("--visual-decisions", required=True, type=Path)
    parser.add_argument("--storyboard", required=True, type=Path)
    parser.add_argument("--candidate-universe", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default="ecnu-plus")
    parser.add_argument("--per-action", type=int, default=3)
    args = parser.parse_args()
    print(
        run_preference_comparison(
            proposition_graph_path=args.proposition_graph,
            source_evidence_path=args.source_evidence,
            visual_decisions_path=args.visual_decisions,
            storyboard_path=args.storyboard,
            candidate_universe_path=args.candidate_universe,
            output_dir=args.output_dir,
            model=args.model,
            per_action=args.per_action,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
