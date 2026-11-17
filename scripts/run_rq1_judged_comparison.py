"""Run a small gold-blind RQ1 comparison with real LLM/VLM Judge calls."""

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

from textbook2video.research.rq1_judge import SCORE_FIELDS, judge_rq1_decision  # noqa: E402
from textbook2video.research.visual_decision_baselines import predict_baseline  # noqa: E402


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_action_stratified_sample(
    propositions: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    *,
    per_action: int = 1,
) -> list[dict[str, Any]]:
    """Select stable first-N examples for each current action without gold."""
    if per_action < 1:
        raise ValueError("per_action must be positive")
    proposition_by_id = {
        str(item.get("id") or ""): item for item in propositions if isinstance(item, dict)
    }
    selected: list[dict[str, Any]] = []
    for action in ("none", "reuse", "retrieve", "generate"):
        candidates = sorted(
            (
                item
                for item in decisions
                if isinstance(item, dict) and str(item.get("action") or "") == action
            ),
            key=lambda item: str(item.get("narration_proposition_id") or ""),
        )
        if len(candidates) < per_action:
            raise ValueError(f"not enough {action!r} decisions for stratified sample")
        for decision in candidates[:per_action]:
            proposition_id = str(decision.get("narration_proposition_id") or "")
            proposition = proposition_by_id.get(proposition_id)
            if proposition is None:
                raise ValueError(f"decision references unknown proposition: {proposition_id}")
            selected.append({"proposition": proposition, "current_decision": decision})
    return selected


def _segment_source_images(storyboard: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for index, segment in enumerate(storyboard.get("segments", []), start=1):
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or index)
        result[segment_id] = sorted(
            {
                str(element.get("source_image_id") or "")
                for element in segment.get("elements", [])
                if isinstance(element, dict)
                and str(element.get("source_image_id") or "").strip()
            }
        )
    return result


def _candidate_paths(
    candidate_universe: dict[str, Any], *, repo_root: Path
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for candidate in candidate_universe.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        path = repo_root / str(candidate.get("path") or "")
        if candidate_id and path.is_file():
            result[candidate_id] = path
    return result


def _method_decisions(
    sample: dict[str, Any], *, source_image_ids: list[str]
) -> dict[str, dict[str, Any]]:
    proposition = sample["proposition"]
    return {
        "never_retrieve": predict_baseline(
            policy="never_retrieve",
            proposition=proposition,
            source_image_ids=source_image_ids,
        ),
        "always_retrieve": predict_baseline(
            policy="always_retrieve",
            proposition=proposition,
            source_image_ids=source_image_ids,
        ),
        "keyword_heuristic": predict_baseline(
            policy="keyword_heuristic",
            proposition=proposition,
            source_image_ids=source_image_ids,
        ),
        "current_visual_decision": sample["current_decision"],
    }


def _blind_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Remove prose that can reveal a method name while preserving its action."""
    return {
        "action": decision.get("action"),
        "rationale": None,
        "source_image_id": decision.get("source_image_id"),
        "retrieval_query": decision.get("retrieval_query"),
        "acceptance_criteria": decision.get("acceptance_criteria") or [],
        "generation_prompt": decision.get("generation_prompt"),
        "rationale_withheld_for_method_blinding": True,
    }


def aggregate_judged_methods(rows: list[dict[str, Any]]) -> dict[str, Any]:
    methods: dict[str, dict[str, Any]] = {}
    for method in sorted({str(row["method"]) for row in rows}):
        selected = [row for row in rows if row["method"] == method]
        verdicts = Counter(str(row["judgment"]["verdict"]) for row in selected)
        actions = Counter(str(row["decision"].get("action") or "") for row in selected)
        score_means: dict[str, float | None] = {}
        for field in SCORE_FIELDS:
            values = [
                row["judgment"]["scores"].get(field)
                for row in selected
                if row["judgment"]["scores"].get(field) is not None
            ]
            score_means[field] = (
                round(sum(float(value) for value in values) / len(values), 6)
                if values
                else None
            )
        methods[method] = {
            "item_count": len(selected),
            "judge_kind_counts": dict(
                sorted(Counter(row["judgment"]["judge_kind"] for row in selected).items())
            ),
            "verdict_counts": dict(sorted(verdicts.items())),
            "accept_rate": round(verdicts["ACCEPT"] / len(selected), 6) if selected else None,
            "mean_scores": score_means,
            "action_counts": dict(sorted(actions.items())),
            "external_retrieval_requests": actions["retrieve"],
            "generation_requests": actions["generate"],
            "visual_asset_requests": actions["retrieve"] + actions["generate"],
        }
    return methods


def find_accepted_action_conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose propositions where Judge accepts mutually exclusive actions."""
    conflicts: list[dict[str, Any]] = []
    proposition_ids = sorted({str(row["proposition_id"]) for row in rows})
    for proposition_id in proposition_ids:
        accepted = [
            row
            for row in rows
            if row["proposition_id"] == proposition_id
            and row["judgment"]["verdict"] == "ACCEPT"
        ]
        actions = sorted({str(row["decision"].get("action") or "") for row in accepted})
        if len(actions) > 1:
            conflicts.append(
                {
                    "proposition_id": proposition_id,
                    "accepted_actions": actions,
                    "accepted_methods": sorted(str(row["method"]) for row in accepted),
                }
            )
    return conflicts


def run_judged_comparison(
    *,
    proposition_graph_path: Path,
    source_evidence_path: Path,
    visual_decisions_path: Path,
    storyboard_path: Path,
    candidate_universe_path: Path,
    output_dir: Path,
    model: str,
    per_action: int = 1,
    judge_call: Callable[..., dict[str, Any]] = judge_rq1_decision,
) -> Path:
    graph = _read(proposition_graph_path)
    evidence = _read(source_evidence_path)
    decisions = _read(visual_decisions_path)
    storyboard = _read(storyboard_path)
    candidate_universe = _read(candidate_universe_path)
    sample = select_action_stratified_sample(
        graph.get("narration_propositions", []),
        decisions.get("decisions", []),
        per_action=per_action,
    )
    source_units = {
        str(item.get("id") or ""): item
        for item in evidence.get("source_units", [])
        if isinstance(item, dict)
    }
    segment_images = _segment_source_images(storyboard)
    image_paths = _candidate_paths(candidate_universe, repo_root=REPO_ROOT)

    output_dir.mkdir(parents=True, exist_ok=True)
    judgments_dir = output_dir / "judgments"
    judgments_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for sampled in sample:
        proposition = sampled["proposition"]
        proposition_id = str(proposition.get("id") or "")
        source = [
            source_units[reference]
            for reference in proposition.get("source_refs", [])
            if reference in source_units
        ]
        methods = _method_decisions(
            sampled,
            source_image_ids=segment_images.get(str(proposition.get("segment_id") or ""), []),
        )
        for method, decision in methods.items():
            judge_decision = _blind_decision(decision)
            source_image_id = str(decision.get("source_image_id") or "")
            candidate_image = image_paths.get(source_image_id)
            fingerprint = _canonical_hash(
                {
                    "model": model,
                    "proposition": proposition,
                    "source_evidence": source,
                    "decision": judge_decision,
                    "candidate_image_sha256": hashlib.sha256(candidate_image.read_bytes()).hexdigest()
                    if candidate_image
                    else None,
                }
            )
            artifact_path = judgments_dir / f"{method}__{proposition_id}.json"
            if artifact_path.is_file():
                artifact = _read(artifact_path)
                if artifact.get("input_sha256") != fingerprint:
                    raise ValueError(f"stale Judge cache: {artifact_path}")
                judgment = artifact["judgment"]
            else:
                judgment = judge_call(
                    proposition=proposition,
                    source_evidence=source,
                    decision=judge_decision,
                    candidate_image=candidate_image,
                    model=model,
                )
                artifact = {
                    "schema_version": "rq1-judge-cache-v0.1",
                    "input_sha256": fingerprint,
                    "model": model,
                    "method_hidden_from_judge": True,
                    "judgment": judgment,
                }
                artifact_path.write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            rows.append(
                {
                    "method": method,
                    "proposition_id": proposition_id,
                    "stratum": sampled["current_decision"].get("action"),
                    "decision": decision,
                    "judgment": judgment,
                }
            )

    report_path = output_dir / "report.json"
    conflicts = find_accepted_action_conflicts(rows)
    report = {
        "schema_version": "rq1-gold-blind-judged-comparison-v0.1",
        "status": "DEVELOPMENT_SMALL_SAMPLE_NOT_FORMAL_EXPERIMENT",
        "model": model,
        "sample_strategy": "first proposition per current action, sorted by proposition ID",
        "sample_proposition_ids": [item["proposition"]["id"] for item in sample],
        "method_identity_hidden_from_judge": True,
        "methods": aggregate_judged_methods(rows),
        "judge_discrimination": {
            "accepted_action_conflict_count": len(conflicts),
            "accepted_action_conflict_rate": round(len(conflicts) / len(sample), 6),
            "conflicts": conflicts,
            "interpretation": (
                "A conflict means the same Judge accepted mutually exclusive actions for "
                "one proposition; method accept rates must not be treated as decisive."
            ),
        },
        "rows": rows,
        "limitations": [
            "The sample is intentionally small and action-stratified, not representative.",
            "LLM/VLM Judge scores are model evidence, not human gold or learning outcomes.",
            "Deterministic baselines receive only source-image bindings frozen in the storyboard.",
            "This development run does not authorize Phase 2-4 formal experiments.",
        ],
    }
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
    parser.add_argument("--per-action", type=int, default=1)
    args = parser.parse_args()
    print(
        run_judged_comparison(
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
