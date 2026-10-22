"""Materialize model-selected source IDs without fuzzy quote repair."""

from __future__ import annotations

import re
from copy import deepcopy


def source_units(source: str) -> list[dict]:
    units = []
    for match in re.finditer(r".+?(?:[。！？]|(?<=[.!?])(?=\s|$)|\n+|$)", source, re.S):
        if match.group().strip():
            units.append(
                {
                    "id": f"source-{len(units) + 1:03}",
                    "text": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    return units


def materialize_source_refs(
    arguments: dict, source: str, page_context: list | None
) -> tuple[dict, list[str]]:
    """Every emitted quote is a verbatim span of the provided source only.

    The model must explicitly select the reference. A missing/invalid quote
    without a reference remains invalid; generation instructions are never a
    reference source. Display-fact inventory comes from immutable page context,
    while the model still supplies its coverage decision and visual targets.
    """
    from textbook2video.pipeline.visual_page_plan import visible_facts

    normalized = deepcopy(arguments)
    units = {unit["id"]: unit for unit in source_units(source)}
    elements = {str(e["id"]): e for e in page_context or []}
    changes = []

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            field = "source_evidence" if "element_id" in value else "evidence"
            alias = value.get(field)
            if (
                "source_ref" not in value
                and isinstance(alias, str)
                and alias in units
                and alias not in source
            ):
                value["source_ref"] = value.pop(field)
                changes.append(f"Interpreted {field}={alias} as an explicit source ID")
            if "source_ref" in value:
                selected = value["source_ref"]
                selected = selected if isinstance(selected, list) else [selected]
                if (
                    not selected
                    or any(not isinstance(ref, str) or ref not in units for ref in selected)
                    or len(set(selected)) != len(selected)
                ):
                    raise ValueError("source_ref must select existing source IDs exactly once")
                begin = min(units[ref]["start"] for ref in selected)
                end = max(units[ref]["end"] for ref in selected)
                quote = source[begin:end]
                if field in value and value[field] != quote:
                    raise ValueError(
                        f"{field} conflicts with source_ref; use references without retyping quotes"
                    )
                value[field] = quote
                changes.append(f"Materialized {field} from source IDs {','.join(selected)}")
            ident = value.get("element_id")
            if ident in elements and "decision" in value and "fact_quotes" not in value:
                value["fact_quotes"] = visible_facts(elements[ident])
                changes.append(f"Inventoried every original visible fact for {ident}")
            for key, child in list(value.items()):
                if key != "source_ref":
                    visit(child)

    visit(normalized)
    return normalized, changes
