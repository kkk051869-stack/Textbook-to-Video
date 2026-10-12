"""Local, auditable P0 visual-support planner.

This is a deterministic planning baseline, not a claim that visual necessity
or retrieval has been solved.  It turns the stable propositions and existing
production storyboard elements created by :mod:`p0_integration` into an
explicit plan.  Only a semantically supported binding to an *existing*
element becomes a scheduled event; an unmet visual need is exported as a
retrieval request for a later RAG/acquisition stage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .p0_integration import P0_PLAN_VERSION, P0IntegrationPaths

_TEXT_KEYS = ("text", "title", "label", "caption", "description", "alt", "name", "quote")
_LIST_KEYS = ("items", "steps", "headers", "rows", "points", "labels", "values")
_EXPLANATORY_TYPES = {
    "image",
    "diagram",
    "illustration",
    "chart",
    "bar",
    "flow_step",
    "comparison_panel",
    "table",
    "highlight_box",
    "focus_box",
    "callout",
    "icon_group",
    "text",
    "quote",
}
_NON_VISUALIZABLE_MARKERS = ("总结", "小结", "因此", "此外", "接下来", "本节", "我们")
_VISUALIZABLE_MARKERS = (
    "结构",
    "过程",
    "机制",
    "关系",
    "步骤",
    "流程",
    "组成",
    "变化",
    "原理",
    "模型",
    "系统",
    "图",
    "数据",
    "对比",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _collect_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, list):
        return [text for item in value for text in _collect_text(item)]
    if isinstance(value, dict):
        result: list[str] = []
        for key in _TEXT_KEYS + _LIST_KEYS:
            result.extend(_collect_text(value.get(key)))
        return result
    return []


def _features(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.lower())
    if not normalized:
        return set()
    features = set(re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        features.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            features.add(run)
    return {item for item in features if item}


def _similarity(left: str, right: str) -> tuple[float, list[str]]:
    left_features, right_features = _features(left), _features(right)
    overlap = sorted(left_features & right_features)
    if not left_features or not right_features:
        return 0.0, overlap
    score = len(overlap) / max(1, min(len(left_features), len(right_features)))
    return round(score, 4), overlap


def _visual_need(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 5 or any(marker in cleaned for marker in _NON_VISUALIZABLE_MARKERS):
        return "NO", "short_or_discourse_proposition"
    if any(marker in cleaned for marker in _VISUALIZABLE_MARKERS):
        return "YES", "contains_visualizable_concept_marker"
    return "UNCERTAIN", "no_deterministic_visual_marker"


def _element_records(storyboard: dict[str, Any], segment_id: str) -> list[dict[str, Any]]:
    for index, segment in enumerate(storyboard.get("segments", []) or [], start=1):
        resolved_id = str(segment.get("id") or index) if isinstance(segment, dict) else ""
        if resolved_id != segment_id or not isinstance(segment, dict):
            continue
        records = []
        for element in segment.get("elements", []) or []:
            if not isinstance(element, dict):
                continue
            element_id = str(element.get("id") or "").strip()
            element_type = str(element.get("type") or "")
            if not element_id or element_type not in _EXPLANATORY_TYPES:
                continue
            text = " ".join(_collect_text(element))
            if text:
                records.append({
                    "id": element_id,
                    "type": element_type,
                    "text": text,
                    "source_image_id": str(element.get("source_image_id") or element.get("src") or ""),
                })
        return records
    return []


def build_local_p0_plan(
    paths: P0IntegrationPaths,
    *,
    source_evidence_path: str | Path | None = None,
    visual_decision_path: str | Path | None = None,
    require_visual_decisions: bool = False,
) -> Path:
    """Build an auditable local P0 plan from an unmodified production candidate."""
    candidate = _read_json(paths.candidate_storyboard_path)
    sidecar = _read_json(paths.sidecar_path)
    used_targets: set[tuple[str, str]] = set()
    decisions: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    retrieved_visuals: list[dict[str, Any]] = []
    signaled_segments: set[str] = set()
    source_evidence: dict[str, Any] = {}
    explicit_decisions: dict[str, dict[str, Any]] = {}
    if source_evidence_path and Path(source_evidence_path).is_file():
        source_evidence = _read_json(Path(source_evidence_path))
    if visual_decision_path and Path(visual_decision_path).is_file():
        decision_document = _read_json(Path(visual_decision_path))
        explicit_decisions = {
            str(item.get("narration_proposition_id") or ""): item
            for item in decision_document.get("decisions", [])
            if isinstance(item, dict)
        }
    elif require_visual_decisions:
        raise ValueError(
            "formal P0 planning requires a persisted visual-decision artifact"
        )
    for proposition in sidecar.get("propositions", []):
        if not isinstance(proposition, dict):
            continue
        proposition_id = str(proposition.get("id") or "")
        segment_id = str(proposition.get("segment_id") or "")
        text = str(proposition.get("text") or "")
        need, need_reason = _visual_need(text)
        candidates = []
        for element in _element_records(candidate, segment_id):
            score, evidence = _similarity(text, element["text"])
            candidates.append({**element, "score": score, "evidence": evidence})
        candidates.sort(key=lambda item: (-item["score"], item["id"]))
        explicit = explicit_decisions.get(proposition_id)
        explicit_action = str(explicit.get("action") or "").lower() if explicit else ""
        explicit_source = str(explicit.get("source_image_id") or "") if explicit else ""
        explicit_state = str(explicit.get("decision_state") or "").upper() if explicit else ""
        explicit_abstain = bool(explicit and explicit.get("abstain")) or explicit_state == "ABSTAIN"
        explicit_uncertain = bool(explicit and explicit.get("uncertain")) or explicit_state == "UNCERTAIN"
        if require_visual_decisions and explicit is None:
            raise ValueError(f"missing visual decision for proposition: {proposition_id}")
        if require_visual_decisions and explicit_action == "reuse" and not explicit_source:
            raise ValueError(f"reuse decision lacks source_image_id: {proposition_id}")
        if explicit_abstain or explicit_uncertain:
            decisions.append({
                "proposition_id": proposition_id,
                "segment_id": segment_id,
                "visual_need": "UNCERTAIN" if explicit_uncertain else "NO",
                "acquisition": "ABSTAIN" if explicit_abstain else "UNCERTAIN",
                "rationale": explicit.get("rationale"),
                "decision_state": "UNCERTAIN" if explicit_uncertain else "ABSTAIN",
                "confidence": explicit.get("confidence"),
                "status": "EXPLICIT_ABSTAIN_OR_UNCERTAIN",
            })
            continue
        if explicit_action == "reuse":
            need, need_reason = "YES", "explicit_vlm_reuse_decision"
        if explicit_action == "none":
            decisions.append({
                "proposition_id": proposition_id, "segment_id": segment_id,
                "visual_need": "NO", "acquisition": "NONE",
                "rationale": explicit.get("rationale"),
                "status": "EXPLICIT_VISUAL_DECISION",
            })
            continue
        if explicit_action in {"retrieve", "generate"}:
            # An external/generated asset is not eligible until the acquisition
            # stage has materialized it and VLM review has accepted it.
            decisions.append({
                "proposition_id": proposition_id, "segment_id": segment_id,
                "visual_need": "YES", "acquisition": explicit_action.upper(),
                "rationale": explicit.get("rationale"),
                "request": explicit,
                "status": "PENDING_ACQUISITION_AND_VLM_REVIEW",
            })
            continue
        best = next(
            (
                item
                for item in candidates
                if (item["score"] >= 0.25 or bool(explicit_source))
                and (
                    not explicit_source
                    or str(item.get("id") or "") == explicit_source
                    or str(item.get("source_image_id") or "") == explicit_source
                )
                and (
                    bool(explicit_source)
                    or (segment_id, item["id"]) not in used_targets
                )
            ),
            None,
        )
        if require_visual_decisions and explicit_action == "reuse" and best is None:
            raise ValueError(
                f"VLM-approved source image {explicit_source!r} is not bound to an "
                f"element in storyboard segment {segment_id}; regenerate the storyboard "
                "with the accepted visual briefs before P0 planning"
            )

        decision: dict[str, Any] = {
            "proposition_id": proposition_id,
            "segment_id": segment_id,
            "visual_need": need,
            "visual_need_reason": need_reason,
            "source_evidence_status": (
                "AVAILABLE_FOR_MACHINE_CANDIDATE_LINKING"
                if source_evidence else "UNAVAILABLE_FROM_CURRENT_PRODUCTION_ARTIFACT"
            ),
            "candidate_count": len(candidates),
            "status": "DETERMINISTIC_BASELINE_NOT_GOLD",
        }
        if best is not None and need != "NO":
            target_key = (segment_id, best["id"])
            first_binding_for_target = target_key not in used_targets
            used_targets.add(target_key)
            decision.update(
                {
                    "acquisition": "REUSE",
                    "target_element_id": best["id"],
                    "binding_score": best["score"],
                    "binding_evidence": best["evidence"],
                }
            )
            bindings.append(
                {
                    "proposition_id": proposition_id,
                    "segment_id": segment_id,
                    "target_element_id": best["id"],
                    "target_type": best["type"],
                    "score": best["score"],
                    "evidence": best["evidence"],
                    "status": (
                        "BOUND_TO_EXISTING_PRODUCTION_ELEMENT"
                        if first_binding_for_target
                        else "BOUND_TO_SHARED_EXISTING_PRODUCTION_ELEMENT"
                    ),
                }
            )
            # Keep reveal and signaling as two independent events.  A focus
            # cue must never be the only event that makes an object visible:
            # this distinction is required both for fair Baseline/P0 timing
            # comparisons and for diagnosing an early/late reveal separately
            # from an unnecessary or overloaded signal.
            if first_binding_for_target:
                is_primary_signal = segment_id not in signaled_segments
                if is_primary_signal:
                    signaled_segments.add(segment_id)
                events.append(
                    {
                        "id": f"p0-{proposition_id}-show",
                        "segment_id": segment_id,
                        "proposition_id": proposition_id,
                        "target_element_id": best["id"],
                        "lead_sec": 0.0,
                        "action": "show",
                        "hold_sec": 0.0,
                        "effect": "fadeInUp",
                        "signal": None,
                    }
                )
                if is_primary_signal:
                    events.append(
                        {
                            "id": f"p0-{proposition_id}-focus",
                            "segment_id": segment_id,
                            "proposition_id": proposition_id,
                            "target_element_id": best["id"],
                            # A small offset makes the reveal and cue
                            # independently observable in the runtime trace.
                            "lead_sec": 0.2,
                            "action": "focus",
                            "hold_sec": 2.0,
                            "effect": "highlight",
                            "signal": "focus_outline",
                        }
                    )
        elif need == "NO":
            decision["acquisition"] = "NONE"
        else:
            decision.update(
                {
                    "acquisition": "RETRIEVE_REQUIRED_PRE_STORYBOARD",
                    "retrieval_query": text,
                    "retrieval_reason": "no_semantically_supported_unused_existing_element; VLM-verified visual brief required",
                    "retrieval_status": "REQUESTED_NO_POST_STORYBOARD_MATERIALIZATION",
                }
            )
        decisions.append(decision)

    plan_path = paths.sidecar_path.with_name(
        paths.sidecar_path.name.replace("_research_p0.json", "_plan.json")
    )
    plan = {
        "schema_version": P0_PLAN_VERSION,
        "planner": {
            "name": "local_deterministic_p0_planner_v0.1",
            "model": None,
            "claim": "heuristic planning baseline; not pedagogical gold or retrieval execution",
        },
        "decisions": decisions,
        "bindings": bindings,
        "events": events,
        "source_evidence_path": str(source_evidence_path) if source_evidence_path else None,
        "visual_decision_path": str(visual_decision_path) if visual_decision_path else None,
        "retrieved_visuals": retrieved_visuals,
    }
    _write_json(plan_path, plan)
    return plan_path


__all__ = ["build_local_p0_plan"]
