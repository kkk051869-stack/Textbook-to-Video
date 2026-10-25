"""Materialize model-selected source IDs without fuzzy quote repair."""

from __future__ import annotations

import re
from copy import deepcopy

SOURCE_REFERENCE_POLICY = {
    "model_supplies": "Nonempty source_ref ID(s); omit optional unused references, never use []",
    "executor_supplies": "Exact source excerpts; do not retype evidence fields",
    "noncontiguous_ids": (
        "Separate exact excerpts in source order, never joined or expanded across gaps"
    ),
    "explicit_quotes": (
        "Every submitted excerpt must be inside an explicitly selected contiguous span"
    ),
}


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

    def visit(value, path=""):
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")
        elif isinstance(value, dict):
            fields = [("source_ref", "source_evidence" if "element_id" in value else "evidence")]
            if "constraint" in value:
                fields.append(("constraint_source_ref", "constraint_evidence"))
            for reference_field, field in fields:
                alias = value.get(field)
                if (
                    reference_field not in value
                    and isinstance(alias, str)
                    and alias in units
                    and alias not in source
                ):
                    value[reference_field] = value.pop(field)
                    changes.append(f"Interpreted {field}={alias} as an explicit source ID")
                if reference_field not in value:
                    continue
                selected = value[reference_field]
                selected = selected if isinstance(selected, list) else [selected]
                if any(isinstance(ref, str) and "," in ref for ref in selected):
                    enumerated = [part.strip() for ref in selected if isinstance(ref, str)
                                  for part in ref.split(",")]
                    if (all(isinstance(ref, str) for ref in selected)
                            and enumerated and all(ref in units for ref in enumerated)
                            and len(set(enumerated)) == len(enumerated)):
                        selected = enumerated
                        value[reference_field] = selected
                        changes.append(
                            f"Normalized explicitly comma-enumerated source IDs at "
                            f"{path}/{reference_field}; no IDs inferred"
                        )
                if (
                    not selected
                    or any(not isinstance(ref, str) or ref not in units for ref in selected)
                    or len(set(selected)) != len(selected)
                ):
                    raise ValueError(
                        f"source_ref must select existing source IDs exactly once at "
                        f"{path}/{reference_field}; received={selected!r}; allowed={list(units)!r}"
                    )
                # Keep actual offsets: concatenating nonadjacent units would create
                # synthetic quotes and the bounding span can include unselected facts.
                ranges = []
                for ref, unit in units.items():
                    if ref not in selected:
                        continue
                    if ranges and not source[ranges[-1][1]:unit["start"]].strip():
                        ranges[-1][1] = unit["end"]
                    else:
                        ranges.append([unit["start"], unit["end"]])
                selected_excerpts = [source[a:b] for a, b in ranges]
                default_excerpt = (
                    selected_excerpts[0] if len(selected_excerpts) == 1 else selected_excerpts
                )
                excerpt = value.get(field, default_excerpt)
                excerpts = [excerpt] if isinstance(excerpt, str) else excerpt
                if (
                    not isinstance(excerpts, list) or not excerpts
                    or any(not isinstance(text, str) or not text.strip()
                           or not any(text in source[a:b] for a, b in ranges)
                           for text in excerpts)
                ):
                    matches = [
                        ref for ref, unit in units.items()
                        if isinstance(excerpt, str) and excerpt.strip()
                        and excerpt in source[unit["start"]:unit["end"]]
                    ]
                    raise ValueError(
                        f"{field} conflicts with source_ref at {path}/{field}; "
                        "the quote must be a verbatim span inside contiguous explicitly "
                        "selected source units; select intervening units or supply an "
                        "exact excerpt contained in the selected units. "
                        f"received_quote={excerpt!r}; selected_ids={selected!r}; "
                        f"selected_source_text={selected_excerpts!r}; "
                        f"exact_unit_matches={matches!r}. "
                        f"Choose the correct source IDs, or explicitly remove stale {field} "
                        "to materialize text from your selected IDs. No quote or ID was changed."
                    )
                if field in value and excerpt != default_excerpt:
                    changes.append(f"Verified explicit {field} excerpt without rewriting it")
                value[field] = excerpt
                changes.append(f"Materialized {field} from source IDs {','.join(selected)}")
            ident = value.get("element_id")
            if ident in elements and "decision" in value and "fact_quotes" not in value:
                value["fact_quotes"] = visible_facts(elements[ident])
                changes.append(f"Inventoried every original visible fact for {ident}")
            for key, child in list(value.items()):
                if key not in {
                    "source_ref", "constraint_source_ref", "applied_updates", "applied_changes"
                }:
                    visit(child, f"{path}/{key}")

    visit(normalized)
    return normalized, changes
