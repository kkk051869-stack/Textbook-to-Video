"""Run method-blind preference comparisons on the unseen RQ1 holdout."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_rq1_preference_comparison import (  # noqa: E402
    _action_options,
    _aggregate,
    _candidate_assets,
    _hash,
    _method_choices,
    _segment_images,
)
from textbook2video.research.rq1_preference_judge import (  # noqa: E402
    PREFERENCE_JUDGE_VERSION,
    judge_rq1_action_preferences,
)
from textbook2video.research.rq1_acquisition_router import (  # noqa: E402
    ROUTER_VERSION,
    route_acquisition,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def run_unseen_comparison(
    *,
    holdout_dir: Path,
    decisions_path: Path,
    output_dir: Path,
    model: str,
) -> Path:
    graph = _read(holdout_dir / "proposition_graph.json")
    evidence = _read(holdout_dir / "source_evidence.json")
    storyboard = _read(holdout_dir / "storyboard.json")
    candidate_universe = _read(holdout_dir / "candidate_universe.json")
    decisions = _read(decisions_path)
    propositions = [item for item in graph.get("narration_propositions", []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in propositions}
    decision_by_id = {
        str(item.get("narration_proposition_id")): item
        for item in decisions.get("decisions", [])
        if isinstance(item, dict)
    }
    if set(by_id) != set(decision_by_id):
        raise ValueError("holdout propositions and decisions do not match")
    source_units = {
        str(item.get("id")): item
        for item in evidence.get("source_units", [])
        if isinstance(item, dict) and item.get("id")
    }
    segment_images = _segment_images(storyboard)
    candidate_assets = _candidate_assets(candidate_universe)
    output_dir.mkdir(parents=True, exist_ok=True)
    judgments_dir = output_dir / "judgments"
    judgments_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for proposition in sorted(propositions, key=lambda item: str(item.get("id") or "")):
        proposition_id = str(proposition["id"])
        current_decision = decision_by_id[proposition_id]
        source = [
            source_units[reference]
            for reference in proposition.get("source_refs", [])
            if reference in source_units
        ]
        source_image_ids = segment_images.get(str(proposition.get("segment_id") or ""), [])
        options, images = _action_options(proposition, source_image_ids, candidate_assets)
        routed_decision = route_acquisition(current_decision)
        fingerprint = _hash(
            {
                "model": model,
                "judge_version": PREFERENCE_JUDGE_VERSION,
                "router_version": ROUTER_VERSION,
                "proposition": proposition,
                "source": source,
                "options": options,
                "current_decision": current_decision,
                "routed_decision": routed_decision,
                "image_sha256": [hashlib.sha256(path.read_bytes()).hexdigest() for path in images],
            }
        )
        cache_path = judgments_dir / f"{proposition_id}.json"
        if cache_path.is_file():
            cached = _read(cache_path)
            if cached.get("input_sha256") != fingerprint:
                raise ValueError(f"stale unseen preference Judge cache: {cache_path}")
            judgment = cached["judgment"]
        else:
            judgment = judge_rq1_action_preferences(
                proposition=proposition,
                source_evidence=source,
                options=options,
                candidate_images=images,
                model=model,
            )
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": "rq1-unseen-preference-judge-cache-v0.1",
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
                "case_id": proposition_id.split("-kprop-")[0],
                "stratum": str(current_decision.get("action") or ""),
                "option_order": [option["action"] for option in options],
                "method_choices": _method_choices(
                    {"proposition": proposition, "current_decision": current_decision},
                    source_image_ids,
                ),
                "routing": routed_decision.get("acquisition_routing"),
                "judgment": judgment,
            }
        )
    report = {
        "schema_version": "rq1-unseen-preference-comparison-v0.1",
        "status": "UNSEEN_DEVELOPMENT_HOLDOUT_NOT_FORMAL_EXPERIMENT",
        "model": model,
        "sample_count": len(rows),
        "sample_strategy": "three deterministic blank-packet propositions per unseen lesson",
        "method_identity_hidden_from_judge": True,
        "router_version": ROUTER_VERSION,
        "judge_version": PREFERENCE_JUDGE_VERSION,
        "current_action_counts": dict(sorted(Counter(row["method_choices"]["current_visual_decision"] for row in rows).items())),
        "routed_action_counts": dict(sorted(Counter(row["method_choices"]["routed_visual_decision"] for row in rows).items())),
        "router_changed_count": sum(
            row["method_choices"]["current_visual_decision"]
            != row["method_choices"]["routed_visual_decision"]
            for row in rows
        ),
        "judge_abstain_count": sum(row["judgment"]["abstain"] for row in rows),
        "judge_format_repair_count": sum(bool(row["judgment"].get("format_repair_used")) for row in rows),
        "methods": _aggregate(rows),
        "rows": rows,
        "limitations": [
            "This is a gold-blind development holdout, not a human-gold test set.",
            "The propositions come from a legacy blank pilot packet; no historical annotation or prediction was read.",
            "The same Judge model supplies the preference reference; agreement is not human correctness.",
            "Retrieve and generate are judged as acquisition requests, not executed asset outcomes.",
        ],
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdout-dir", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default="ecnu-plus")
    args = parser.parse_args()
    print(run_unseen_comparison(
        holdout_dir=args.holdout_dir,
        decisions_path=args.decisions,
        output_dir=args.output_dir,
        model=args.model,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
