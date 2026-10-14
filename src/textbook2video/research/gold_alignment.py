"""Strict, read-only alignment of reviewed A labels to current P0 outputs.

The adapter deliberately joins by normalized case and exact proposition text,
then follows the current proposition graph's knowledge-to-narration edges.
It never injects annotation data into generation inputs or mutates the gold.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

LABELS = ("none", "source-sufficient", "extra-support-needed")
RETRIEVAL_LABELS = ("no", "retrieve", "generation-candidate")


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _case_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _text_key(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").casefold())


def _predict_need(decision: dict[str, Any]) -> str:
    state = str(decision.get("decision_state") or "DECIDED").upper()
    action = str(decision.get("action") or "").lower()
    sufficiency = str(decision.get("source_sufficiency") or "UNKNOWN").upper()
    if state != "DECIDED" or decision.get("abstain") or decision.get("uncertain"):
        return "uncertain"
    if action == "none":
        return "none" if sufficiency in {"NOT_APPLICABLE", "UNKNOWN"} else "uncertain"
    if action == "reuse":
        return "source-sufficient" if sufficiency in {"SUFFICIENT", "UNKNOWN"} else "uncertain"
    if action in {"retrieve", "generate"}:
        return "extra-support-needed" if sufficiency in {"INSUFFICIENT", "UNKNOWN"} else "uncertain"
    return "uncertain"


def _predict_retrieval(decision: dict[str, Any]) -> str:
    state = str(decision.get("decision_state") or "DECIDED").upper()
    action = str(decision.get("action") or "").lower()
    if state != "DECIDED" or decision.get("abstain") or decision.get("uncertain"):
        return "uncertain"
    return {
        "none": "no",
        "reuse": "no",
        "retrieve": "retrieve",
        "generate": "generation-candidate",
    }.get(action, "uncertain")


def _classification(
    references: list[str],
    predictions: list[str],
    *,
    labels: tuple[str, ...] = LABELS,
) -> dict[str, Any]:
    confusion = {label: {guess: 0 for guess in labels} for label in labels}
    for reference, prediction in zip(references, predictions):
        confusion[reference][prediction] += 1
    per_class: dict[str, dict[str, float | int]] = {}
    f1s: list[float] = []
    for label in labels:
        tp = confusion[label][label]
        support = sum(confusion[label].values())
        predicted = sum(confusion[actual][label] for actual in labels)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        per_class[label] = {
            "support": support,
            "predicted_count": predicted,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }
    count = len(references)
    return {
        "label_order": list(labels),
        "item_count": count,
        "exact_agreement": sum(a == b for a, b in zip(references, predictions)) / count
        if count
        else None,
        "accuracy": sum(a == b for a, b in zip(references, predictions)) / count if count else None,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "confusion_matrix": confusion,
        "per_class": per_class,
    }


def evaluate_reviewed_gold(
    *,
    gold_path: str | Path,
    proposition_graph_path: str | Path,
    visual_decisions_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Compare one case's reviewed gold to current P0 decisions without edits."""
    gold = _read_json(gold_path)
    graph = _read_json(proposition_graph_path)
    decisions_doc = _read_json(visual_decisions_path)
    if (
        gold.get("gold_status") != "HUMAN_REVIEWED_GOLD"
        or gold.get("review_status") != "CONFIRMED_BY_USER"
    ):
        raise ValueError("input must be a user-confirmed HUMAN_REVIEWED_GOLD artifact")

    graph_case = _case_key(graph.get("case_id"))
    gold_items = [
        item
        for item in gold.get("items", [])
        if isinstance(item, dict) and _case_key(item.get("case_id")) == graph_case
    ]
    if not gold_items:
        raise ValueError(f"gold has no items for graph case {graph.get('case_id')!r}")

    kprops = [item for item in graph.get("knowledge_propositions", []) if isinstance(item, dict)]
    nprops = [item for item in graph.get("narration_propositions", []) if isinstance(item, dict)]
    decision_rows = [item for item in decisions_doc.get("decisions", []) if isinstance(item, dict)]
    decision_by_id = {
        str(item.get("narration_proposition_id") or ""): item for item in decision_rows
    }
    if len(decision_by_id) != len(decision_rows):
        raise ValueError("visual decisions contain missing or duplicate narration proposition IDs")

    aligned: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for item in gold_items:
        annotation = item.get("annotation") if isinstance(item.get("annotation"), dict) else {}
        reference = annotation.get("visual_support_need")
        if reference not in (*LABELS, "uncertain"):
            raise ValueError(f"unsupported gold label: {reference!r}")
        reference_retrieval = annotation.get("retrieval_need")
        if reference_retrieval not in (*RETRIEVAL_LABELS, "uncertain"):
            raise ValueError(f"unsupported gold retrieval label: {reference_retrieval!r}")
        key = _text_key(item.get("proposition_text"))
        candidates = [kp for kp in kprops if _text_key(kp.get("text")) == key and key]
        if len(candidates) != 1:
            unmatched.append(
                {
                    "gold_proposition_id": item.get("knowledge_proposition_id"),
                    "reason": "no_exact_text_match"
                    if not candidates
                    else "ambiguous_exact_text_match",
                    "candidate_ids": [kp.get("id") for kp in candidates],
                }
            )
            continue
        kp = candidates[0]
        linked_nprops = [
            prop
            for prop in nprops
            if str(kp.get("id"))
            in [str(value) for value in prop.get("knowledge_proposition_ids", [])]
        ]
        linked_decisions = [
            decision_by_id[str(prop.get("id"))]
            for prop in linked_nprops
            if str(prop.get("id")) in decision_by_id
        ]
        if not linked_nprops or len(linked_decisions) != len(linked_nprops):
            unmatched.append(
                {
                    "gold_proposition_id": item.get("knowledge_proposition_id"),
                    "reason": "missing_linked_visual_decision",
                    "graph_proposition_id": kp.get("id"),
                    "linked_narration_count": len(linked_nprops),
                    "linked_decision_count": len(linked_decisions),
                }
            )
            continue
        need_labels = [_predict_need(decision) for decision in linked_decisions]
        predicted = need_labels[0] if len(set(need_labels)) == 1 else "uncertain"
        retrieval_labels = [_predict_retrieval(decision) for decision in linked_decisions]
        predicted_retrieval = (
            retrieval_labels[0] if len(set(retrieval_labels)) == 1 else "uncertain"
        )
        aligned.append(
            {
                "case_id": item.get("case_id"),
                "gold_proposition_id": item.get("knowledge_proposition_id"),
                "graph_proposition_id": kp.get("id"),
                "reference": reference,
                "prediction": predicted,
                "reference_retrieval": reference_retrieval,
                "prediction_retrieval": predicted_retrieval,
                "linked_narration_proposition_ids": [prop.get("id") for prop in linked_nprops],
                "status": "ALIGNED"
                if predicted != "uncertain"
                else "PREDICTION_UNCERTAIN_OR_CONFLICTING",
            }
        )

    scored = [row for row in aligned if row["reference"] in LABELS and row["prediction"] in LABELS]
    references = [row["reference"] for row in scored]
    predictions = [row["prediction"] for row in scored]
    support = Counter(row["reference"] for row in scored)
    retrieval_scored = [
        row
        for row in aligned
        if row["reference_retrieval"] in RETRIEVAL_LABELS
        and row["prediction_retrieval"] in RETRIEVAL_LABELS
    ]
    retrieval_references = [row["reference_retrieval"] for row in retrieval_scored]
    retrieval_predictions = [row["prediction_retrieval"] for row in retrieval_scored]
    retrieval_support = Counter(retrieval_references)
    out = Path(output_path)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite evaluation artifact: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "a-visual-support-gold-evaluation-v0.1",
        "artifact_type": "exploratory_visual_support_gold_evaluation",
        "status": "EXPLORATORY_NOT_FORMAL_METHOD_CLAIM",
        "case_id": graph.get("case_id"),
        "inputs": {
            "gold_path": str(gold_path),
            "proposition_graph_path": str(proposition_graph_path),
            "visual_decisions_path": str(visual_decisions_path),
        },
        "input_sha256": {
            "gold": _sha256(gold_path),
            "proposition_graph": _sha256(proposition_graph_path),
            "visual_decisions": _sha256(visual_decisions_path),
        },
        "item_count": len(gold_items),
        "aligned_count": len(aligned),
        "scored_count": len(scored),
        "retrieval_scored_count": len(retrieval_scored),
        "coverage": len(scored) / len(gold_items) if gold_items else 0.0,
        "reference_class_counts_scored": dict(sorted(support.items())),
        "reference_retrieval_counts_scored": dict(sorted(retrieval_support.items())),
        "underpowered_classes": [label for label in LABELS if support.get(label, 0) < 5],
        "metrics": _classification(references, predictions),
        "retrieval_metrics": _classification(
            retrieval_references,
            retrieval_predictions,
            labels=RETRIEVAL_LABELS,
        ),
        "aligned_items": aligned,
        "unmatched_items": unmatched,
        "limitations": [
            (
                "Alignment requires unique exact proposition-text matches after "
                "whitespace/punctuation normalization."
            ),
            (
                "Multiple linked narration decisions must agree; otherwise the "
                "prediction is uncertain."
            ),
            (
                "The gold is user-reviewed working gold, not inter-annotator "
                "agreement or external accuracy."
            ),
            (
                "Retrieval/generation metrics are exploratory and are reported "
                "separately from visual-support need."
            ),
            "This evaluation is post-generation only and must not be used as generation input.",
        ],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


__all__ = ["LABELS", "RETRIEVAL_LABELS", "evaluate_reviewed_gold"]
