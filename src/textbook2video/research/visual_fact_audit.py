"""Per-panel narration and per-edge screenshot review obligations.

This checks review coverage and evidence location, not semantic entailment.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

from textbook2video.research.visual_grammar import GRAPH_KINDS
from textbook2video.research.visual_narration_refs import narration_units

VISIBLE_FACT_RULES = (
    "Audit EACH panel separately. For every narration unit assigned to that panel, "
    "decide whether its source-supported facts are actually visible in THAT panel's "
    "node/edge text, constraint or table cells. For a scene image, describe the "
    "visible screenshot instead of citing nonexistent diagram text. A title, teaching goal, "
    "narration, "
    "source citation, another panel, or background knowledge is not visible proof. "
    "A unit containing several facts is visible only if ALL supported facts are shown. "
    "For EACH edge, judge the exact source node, target node, label and direction: "
    "does that arrow assert the source's actual subject, action and object? "
    "Explicit retained_page_texts may support a fact only when still visible in "
    "that panel's actual screenshot; replaced or merely archived original text cannot. "
    "Do not use a generic flow to excuse a wrong verb or an unstated owner. "
)

FACT_AUDIT_RULES = VISIBLE_FACT_RULES + (
    "Return fact_audit.panels with one entry per target panel. Each entry must contain "
    "visual_id, units:[{narration_ref,status:visible|missing|incorrect|unsupported,"
    "reason,visible_evidence:[select exact strings from this panel's visible_texts; "
    "use screenshot observations for scene] "
    "for visible}], and "
    "edges:[{source,target,label/directed if present,status:supported|incorrect|unsupported,"
    "reason}]. Cover every target exactly once. A unit may be unsupported ONLY when "
    "the source supports NONE of its facts; explain this source limit, never use it "
    "for a missing diagram fact. For mixed units, assess all supported facts and omit "
    "only unsupported details. Missing/incorrect units and incorrect/unsupported edges "
    "force revision regardless of numeric scores. This audit does not replace the "
    "full source, screenshot or human review."
)


def _diagram(spec):
    return spec.get("diagram") if spec.get("kind") == "relationship" else spec


def _visible_texts(spec):
    diagram = _diagram(spec)
    if not isinstance(diagram, dict):
        return []
    texts = []
    kind = spec.get("kind")
    if kind in GRAPH_KINDS | {"comparison", "relationship"}:
        for objects in ("nodes", "edges"):
            for obj in diagram.get(objects, []):
                if isinstance(obj, dict):
                    fields = ("label", "detail") if objects == "nodes" else ("label",)
                    texts.extend(value for key in fields
                                 if isinstance(value := obj.get(key), str) and value)
    if (kind == "relationship" and isinstance(diagram.get("constraint"), str)
            and diagram["constraint"]):
        texts.append(diagram["constraint"])
    for row in spec.get("rows", []) if kind == "table" else []:
        if isinstance(row, list):
            texts.extend(cell for cell in row if isinstance(cell, str) and cell)
    if kind in {"code", "formula"} and isinstance(spec.get("content"), str) and spec["content"]:
        texts.append(spec["content"])
        texts.extend(line for line in spec["content"].splitlines() if line.strip())
    if kind in {"chart", "proportion"} and isinstance(spec.get("unit"), str) and spec["unit"]:
        texts.append(spec["unit"])
    points = spec.get("series", []) if kind in {"chart", "proportion"} else []
    total = sum(point.get("value", 0) for point in points) if kind == "proportion" else 0
    for point in points:
        if isinstance(point, dict):
            if isinstance(point.get("label"), str) and point["label"]:
                texts.append(point["label"])
            if type(point.get("value")) in (int, float):
                value = f"{point['value']:g}"
                if kind == "proportion" and total > 0:
                    value += f" ({point['value'] / total:.0%})"
                texts.append(value)
    return texts


def build_review_targets(
    specs: list[dict], narration_text: str, *, retained_texts: list[str] | None = None,
) -> dict:
    """Derive obligations from the immutable page narration and actual graph edges."""
    if not isinstance(narration_text, str) or not narration_text:
        raise ValueError("fact_audit requires nonempty narration_text")
    units = narration_units(narration_text)
    if not units:
        raise ValueError("fact_audit requires narration units")
    if not isinstance(specs, list) or not specs:
        raise ValueError("fact_audit requires visual panels")
    retained_texts = retained_texts or []
    if any(not isinstance(text, str) or not text.strip() for text in retained_texts):
        raise ValueError("fact_audit retained text must be nonempty")
    by_ref = {unit["id"]: unit for unit in units}
    cursor = 0
    panels = []
    for spec in specs:
        if not isinstance(spec, dict) or not isinstance(spec.get("id"), str):
            raise ValueError("fact_audit requires identified panels")
        refs = spec.get("narration_refs")
        if refs is None:
            span = spec.get("narration_span")
            if span is None and len(specs) == 1:
                span = narration_text
            if not isinstance(span, str) or not span or not narration_text.startswith(span, cursor):
                raise ValueError("fact_audit cannot assign panel narration")
            end = cursor + len(span)
            refs = [unit["id"] for unit in units
                    if unit["start"] >= cursor and unit["end"] <= end]
            if not refs or by_ref[refs[0]]["start"] != cursor or by_ref[refs[-1]]["end"] != end:
                raise ValueError("fact_audit panel narration must align to units")
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in by_ref for ref in refs)):
            raise ValueError("fact_audit requires existing narration references")
        if by_ref[refs[0]]["start"] != cursor:
            raise ValueError("fact_audit narration partition is out of order")
        expected = [unit["id"] for unit in units
                    if unit["start"] >= cursor and unit["end"] <= by_ref[refs[-1]]["end"]]
        if refs != expected:
            raise ValueError("fact_audit narration partition must be complete")
        cursor = by_ref[refs[-1]]["end"]
        diagram = _diagram(spec)
        edges = []
        graph = spec.get("kind") in GRAPH_KINDS | {"comparison", "relationship"}
        for edge in diagram.get("edges", []) if isinstance(diagram, dict) and graph else []:
            if not isinstance(edge, dict):
                raise ValueError("fact_audit requires structured edges")
            target = {"source": edge.get("source"), "target": edge.get("target")}
            for key in ("label", "directed"):
                if key in edge:
                    target[key] = edge[key]
            edges.append(target)
        panels.append({"visual_id": spec["id"], "kind": spec.get("kind"),
                       "narration_refs": deepcopy(refs),
                       "edges": edges, "visible_texts": _visible_texts(spec),
                       "retained_page_texts": deepcopy(retained_texts)})
    if cursor != len(narration_text):
        raise ValueError("fact_audit narration partition omits content")
    return {"panels": panels,
            "narration_units": [{"id": unit["id"], "text": unit["text"]} for unit in units]}


def validate_fact_audit(report: dict, targets: dict, specs: list[dict]) -> None:
    """Reject omitted/duplicated targets or evidence borrowed from another panel."""
    audit = report.get("fact_audit") if isinstance(report, dict) else None
    panels = audit.get("panels") if isinstance(audit, dict) else None
    expected = targets.get("panels") if isinstance(targets, dict) else None
    if (not isinstance(panels, list) or not isinstance(expected, list)
            or len(panels) != len(expected)):
        raise ValueError("fact_audit must review every panel exactly once")
    by_id = {spec["id"]: spec for spec in specs}
    expected_by_id = {panel["visual_id"]: panel for panel in expected}
    if (len(expected_by_id) != len(expected)
            or any(not isinstance(p, dict) or not isinstance(p.get("visual_id"), str)
                   for p in panels)
            or {p["visual_id"] for p in panels} != set(expected_by_id)):
        raise ValueError("fact_audit panel IDs must match the rendered panels exactly")
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError("fact_audit panel must be an object")
        visual_id = panel["visual_id"]
        target = expected_by_id[visual_id]
        actual_units = panel.get("units")
        if (not isinstance(actual_units, list)
                or len(actual_units) != len(target["narration_refs"])
                or any(not isinstance(unit, dict)
                       or not isinstance(unit.get("narration_ref"), str)
                       for unit in actual_units)
                or Counter(unit.get("narration_ref") for unit in actual_units)
                != Counter(target["narration_refs"])):
            raise ValueError(f"fact_audit {visual_id} must review each narration unit once")
        visible_texts = set(_visible_texts(by_id[visual_id])) | set(
            target.get("retained_page_texts", [])
        )
        for unit in actual_units:
            if (not isinstance(unit.get("status"), str)
                    or unit["status"] not in {"visible", "missing", "incorrect", "unsupported"}
                    or not isinstance(unit.get("reason"), str) or not unit["reason"].strip()):
                raise ValueError("fact_audit unit requires status and reason")
            evidence = unit.get("visible_evidence")
            if unit["status"] == "visible" and (
                not isinstance(evidence, list) or not evidence
                or any(not isinstance(text, str) or not text.strip()
                       or (target["kind"] != "scene" and text not in visible_texts)
                       for text in evidence)
            ):
                raise ValueError("fact_audit visible proof must be exact text in its own panel")
        actual_edges = panel.get("edges")
        if (not isinstance(actual_edges, list)
                or len(actual_edges) != len(target["edges"])
                or any(not isinstance(edge, dict)
                       or not isinstance(edge.get("source"), str)
                       or not isinstance(edge.get("target"), str)
                       or ("label" in edge and not isinstance(edge["label"], str))
                       or ("directed" in edge and type(edge["directed"]) is not bool)
                       for edge in actual_edges)):
            raise ValueError(f"fact_audit {visual_id} must review every edge once")
        def identities(entries):
            return Counter(
                (edge.get("source"), edge.get("target"), edge.get("label"),
                 edge.get("directed")) for edge in entries
            )
        if identities(actual_edges) != identities(target["edges"]):
            raise ValueError(f"fact_audit {visual_id} edge targets do not match actual graph")
        for edge in actual_edges:
            if (not isinstance(edge.get("status"), str)
                    or edge["status"] not in {"supported", "incorrect", "unsupported"}
                    or not isinstance(edge.get("reason"), str) or not edge["reason"].strip()):
                raise ValueError("fact_audit edge requires status and reason")


def fact_audit_findings(report: dict) -> list[dict]:
    """Turn negative scoped judgments into persistent ordinary review issues."""
    audit = report.get("fact_audit") if isinstance(report, dict) else None
    panels = audit.get("panels") if isinstance(audit, dict) else None
    findings = []
    for panel in panels if isinstance(panels, list) else []:
        if not isinstance(panel, dict):
            continue
        visual_id = panel.get("visual_id", "")
        for unit in panel.get("units", []) if isinstance(panel.get("units"), list) else []:
            if (not isinstance(unit, dict) or not isinstance(unit.get("status"), str)
                    or unit["status"] not in {"missing", "incorrect"}):
                continue
            category = "missing_content" if unit["status"] == "missing" else "factual_error"
            findings.append({
                "visual_id": visual_id, "category": category,
                "issue": (f"narration {unit.get('narration_ref')}: "
                          f"{unit.get('reason') or 'Unresolved fact'}"),
                "change": "Correct the source-grounded fact in this panel's visible content.",
            })
        for edge in panel.get("edges", []) if isinstance(panel.get("edges"), list) else []:
            if (not isinstance(edge, dict) or not isinstance(edge.get("status"), str)
                    or edge["status"] not in {"incorrect", "unsupported"}):
                continue
            findings.append({
                "visual_id": visual_id, "category": "factual_error",
                "issue": (f"edge {edge.get('source')}→{edge.get('target')}: "
                          f"{edge.get('reason') or 'Unsupported edge'}"),
                "change": "Correct this edge's subject, action, object and direction.",
            })
    return findings
