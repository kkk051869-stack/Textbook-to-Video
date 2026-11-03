"""Run a gold-separated, development-only RQ1 comparison on aligned propositions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from textbook2video.research.rq1_evaluation import evaluate_rq1_predictions  # noqa: E402
from textbook2video.research.visual_decision_baselines import keyword_hits  # noqa: E402


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _text_key(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def _align_references(
    gold: dict[str, Any], graph: dict[str, Any]
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Align by unique proposition text; IDs may be reused after re-segmentation."""
    case_id = str(graph.get("case_id") or "").replace("-", "_")
    graph_by_text: dict[str, list[dict[str, Any]]] = {}
    for proposition in graph.get("knowledge_propositions", []):
        if not isinstance(proposition, dict):
            continue
        graph_by_text.setdefault(_text_key(proposition.get("text")), []).append(proposition)
    references: dict[str, str] = {}
    unmatched: list[dict[str, Any]] = []
    for item in gold.get("items", []):
        if not isinstance(item, dict) or str(item.get("case_id") or "") != case_id:
            continue
        candidates = graph_by_text.get(_text_key(item.get("proposition_text")), [])
        if len(candidates) != 1:
            unmatched.append(
                {
                    "gold_proposition_id": item.get("knowledge_proposition_id"),
                    "reason": "no_exact_text_match"
                    if not candidates
                    else "ambiguous_exact_text_match",
                    "candidate_ids": [candidate.get("id") for candidate in candidates],
                }
            )
            continue
        graph_id = str(candidates[0].get("id") or "")
        references[graph_id] = str(
            (item.get("annotation") or {}).get("visual_support_need")
        )
    return references, unmatched


def _need_from_decision(decision: dict[str, Any]) -> str:
    if str(decision.get("decision_state") or "DECIDED").upper() != "DECIDED":
        return "uncertain"
    if decision.get("abstain") or decision.get("uncertain"):
        return "uncertain"
    return {
        "none": "none",
        "reuse": "source-sufficient",
        "retrieve": "extra-support-needed",
        "generate": "extra-support-needed",
    }.get(str(decision.get("action") or "").lower(), "uncertain")


def _current_method_predictions(
    graph: dict[str, Any], decisions: dict[str, Any]
) -> list[dict[str, Any]]:
    decisions_by_id = {
        str(item.get("narration_proposition_id") or ""): item
        for item in decisions.get("decisions", [])
        if isinstance(item, dict)
    }
    by_knowledge: dict[str, list[dict[str, Any]]] = {}
    for proposition in graph.get("narration_propositions", []):
        if not isinstance(proposition, dict):
            continue
        decision = decisions_by_id.get(str(proposition.get("id") or ""))
        if decision is None:
            continue
        for knowledge_id in proposition.get("knowledge_proposition_ids", []):
            by_knowledge.setdefault(str(knowledge_id), []).append(decision)
    rows: list[dict[str, Any]] = []
    for proposition in graph.get("knowledge_propositions", []):
        if not isinstance(proposition, dict):
            continue
        proposition_id = str(proposition.get("id") or "")
        linked = by_knowledge.get(proposition_id, [])
        labels = {_need_from_decision(item) for item in linked}
        actions = {str(item.get("action") or "") for item in linked}
        confidences = [float(item.get("confidence", 0.5)) for item in linked]
        rows.append(
            {
                "proposition_id": proposition_id,
                "label": next(iter(labels)) if len(labels) == 1 else "uncertain",
                "action": next(iter(actions)) if len(actions) == 1 else "mixed",
                "confidence": min(confidences) if confidences else 0.0,
                "abstain": not linked or len(labels) != 1,
            }
        )
    return rows


def _baseline_predictions(
    graph: dict[str, Any], policy: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for proposition in graph.get("knowledge_propositions", []):
        if not isinstance(proposition, dict):
            continue
        text = str(proposition.get("text") or "")
        hits = keyword_hits(text)
        if policy == "never_retrieve":
            label, action, confidence = "none", "none", 1.0
        elif policy == "always_retrieve":
            label, action, confidence = "extra-support-needed", "retrieve", 1.0
        elif policy == "keyword_heuristic":
            triggered = bool(hits)
            label = "extra-support-needed" if triggered else "none"
            action = "retrieve" if triggered else "none"
            confidence = 0.75 if triggered else 0.6
        else:
            raise ValueError(f"unsupported baseline: {policy}")
        rows.append(
            {
                "proposition_id": str(proposition.get("id") or ""),
                "label": label,
                "action": action,
                "confidence": confidence,
                "abstain": False,
                "keyword_hits": hits,
            }
        )
    return rows


def run_comparison(
    *, gold_path: Path, graph_path: Path, decisions_path: Path, output_path: Path
) -> Path:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite comparison: {output_path}")
    graph = _read(graph_path)
    decisions = _read(decisions_path)

    # Predictions are produced before the gold file is opened.  This keeps the
    # evaluator from becoming an accidental method implementation.
    methods = {
        policy: _baseline_predictions(graph, policy)
        for policy in ("never_retrieve", "always_retrieve", "keyword_heuristic")
    }
    methods["current_visual_decision"] = _current_method_predictions(graph, decisions)

    gold = _read(gold_path)
    references, unmatched = _align_references(gold, graph)
    if not references:
        raise ValueError(
            "no uniquely text-aligned reviewed RQ1 references; the graph and gold "
            "represent different proposition segmentations"
        )

    results = {
        name: evaluate_rq1_predictions(
            references,
            [row for row in rows if row["proposition_id"] in references],
        )
        for name, rows in methods.items()
    }
    payload = {
        "schema_version": "rq1-small-method-comparison-v0.1",
        "status": "DEVELOPMENT_SMALL_SAMPLE_NOT_FORMAL_EXPERIMENT",
        "case_id": graph.get("case_id"),
        "reference_count": len(references),
        "unmatched_reference_count": len(unmatched),
        "unmatched_references": unmatched,
        "methods": results,
        "limitations": [
            "This run uses only gold propositions that align with the current case artifacts.",
            "The class distribution is underpowered and unsuitable for a paper-level claim.",
            "Judge scores are a separate gold-blind evidence layer and are not included unless persisted independently.",
            "No Phase 2-4 formal experiment is authorized by this development comparison.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--proposition-graph", required=True, type=Path)
    parser.add_argument("--visual-decisions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        run_comparison(
            gold_path=args.gold,
            graph_path=args.proposition_graph,
            decisions_path=args.visual_decisions,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
