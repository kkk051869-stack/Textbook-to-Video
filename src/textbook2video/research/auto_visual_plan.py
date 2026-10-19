"""AI planning bridge from P0 propositions to executable teaching visuals."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_system

from .p0_integration import P0_PLAN_VERSION
from .visual_synthesis import IMAGE_KINDS, SVG_KINDS

AUTO_VISUAL_PLAN_VERSION = "p0-auto-visual-plan-v1"


def _read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _parse(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("auto visual planner did not return JSON")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict) or not isinstance(value.get("visuals"), list):
        raise ValueError("auto visual planner requires a visuals array")
    return value


def _normalize_svg_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Make flat model specs executable without discarding teaching content.

    A comparison renderer needs two top-level alternatives.  When a model
    instead returns a flat sequence of steps, use a flow rather than silently
    dropping the extra labels or manufacturing an arbitrary grouping.
    """
    normalized = dict(proposal)
    kind = str(normalized.get("kind") or "").lower()
    items = normalized.get("items")
    if kind == "image":
        normalized["kind"] = "scene"
        normalized["normalization"] = {
            "from_kind": "image",
            "reason": "generic image alias normalized to supported scene generation",
        }
        kind = "scene"
    if kind == "comparison" and isinstance(items, list) and len(items) != 2:
        normalized["kind"] = "flow"
        normalized["normalization"] = {
            "from_kind": "comparison",
            "reason": (
                "flat comparison requires exactly two alternatives; "
                "preserved all items as flow"
            ),
        }
    return normalized


def build_auto_visual_plan(
    *,
    proposition_graph_path: str | Path,
    visual_decision_path: str | Path,
    output_path: str | Path,
    model: str | None = None,
) -> Path:
    """Ask the planner for specs, then deterministically create bindings/events.

    Only propositions explicitly marked ``generate`` become new visuals.  The
    model supplies declarative visual content; IDs, binding targets, and P0
    events are generated locally so they remain auditable and non-ambiguous.
    """
    graph = _read(proposition_graph_path)
    decisions = _read(visual_decision_path)
    props = {
        str(item.get("id") or ""): item
        for item in graph.get("narration_propositions", [])
        if isinstance(item, dict) and item.get("id")
    }
    requested = [
        {
            "proposition_id": str(item.get("narration_proposition_id") or ""),
            "segment_id": str(props.get(str(item.get("narration_proposition_id") or ""), {}).get("segment_id") or ""),
            "text": str(props.get(str(item.get("narration_proposition_id") or ""), {}).get("text") or ""),
            "generation_prompt": str(item.get("generation_prompt") or ""),
        }
        for item in decisions.get("decisions", [])
        if isinstance(item, dict) and str(item.get("action") or "").lower() == "generate"
    ]
    if not requested:
        document = {"schema_version": AUTO_VISUAL_PLAN_VERSION, "visuals": [], "bindings": [], "plan": {"schema_version": P0_PLAN_VERSION, "events": []}}
        Path(output_path).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return Path(output_path)
    reply = _parse(chat_with_system(
        json.dumps({
            "task": "Create one pedagogically precise visual spec for each requested proposition.",
            "rules": [
                "Use SVG kinds for exact relationships: " + ", ".join(sorted(SVG_KINDS)),
                "Use image kinds only for genuinely figurative content: " + ", ".join(sorted(IMAGE_KINDS)),
                "Return every proposition_id exactly once; SVG specs need non-empty items (table may use rows; chart/proportion numeric values).",
                "comparison requires exactly two top-level items; use flow for a flat multi-step sequence.",
                "Do not invent factual claims beyond the proposition text or prompt.",
            ],
            "requested": requested,
            "response_schema": {"visuals": [{"proposition_id": "id", "kind": "supported kind", "title": "short", "items": ["labels"], "description": "optional", "prompt": "required for image"}]},
        }, ensure_ascii=False),
        system_prompt="You are an instructional visual planner. Output only valid JSON.",
        model=model,
        temperature=0.0,
        max_tokens=4096,
        timeout=600,
    ))
    supplied = {str(item.get("proposition_id") or ""): item for item in reply["visuals"] if isinstance(item, dict)}
    expected = {item["proposition_id"] for item in requested}
    if set(supplied) != expected:
        raise ValueError("auto visual planner must cover exactly the generated propositions")
    visuals: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for ordinal, request in enumerate(requested, start=1):
        proposal = _normalize_svg_proposal(dict(supplied[request["proposition_id"]]))
        kind = str(proposal.get("kind") or "").lower()
        if kind not in SVG_KINDS | IMAGE_KINDS:
            raise ValueError(f"auto visual planner returned unsupported kind: {kind}")
        asset_id = f"auto-{ordinal:03d}-{request['proposition_id']}"
        element_id = f"visual-{asset_id}"
        proposal.update({"id": asset_id, "kind": kind, "title": str(proposal.get("title") or request["text"])})
        if kind in SVG_KINDS and not isinstance(proposal.get("items"), list):
            raise ValueError(f"auto SVG visual requires items: {request['proposition_id']}")
        if kind in IMAGE_KINDS and not str(proposal.get("prompt") or proposal.get("description") or "").strip():
            raise ValueError(f"auto image visual requires prompt: {request['proposition_id']}")
        visuals.append(proposal)
        bindings.append({"asset_id": asset_id, "proposition_id": request["proposition_id"], "segment_id": request["segment_id"], "element_id": element_id, "description": proposal["title"]})
        events.append({"id": f"p0-auto-{ordinal:03d}", "segment_id": request["segment_id"], "proposition_id": request["proposition_id"], "target_element_id": element_id, "action": "show", "effect": "fadeInUp"})
    document = {"schema_version": AUTO_VISUAL_PLAN_VERSION, "planner": {"model": model, "source": "AI VisualSpec + deterministic binding/event compiler"}, "visuals": visuals, "bindings": bindings, "plan": {"schema_version": P0_PLAN_VERSION, "events": events}}
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination
