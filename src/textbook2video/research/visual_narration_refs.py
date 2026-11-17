"""Materialize explicit narration sentence selections without retyping audio text."""

from __future__ import annotations

from copy import deepcopy

from textbook2video.research.visual_source_refs import source_units


def narration_units(text: str) -> list[dict]:
    units = source_units(text)
    previous = 0
    for i, unit in enumerate(units):
        unit.update(id=f"narration-{i + 1:03}", start=previous)
        if i == len(units) - 1:
            unit["end"] = len(text)
        unit["text"] = text[previous:unit["end"]]
        previous = unit["end"]
    return units


def materialize_narration_refs(arguments: dict, narration: str | None) -> tuple[dict, list[str]]:
    result, messages = deepcopy(arguments), []
    specs = result.get("visuals")
    selected_offsets = {}
    for spec in specs if isinstance(specs, list) else []:
        if not isinstance(spec, dict) or "narration_refs" not in spec:
            continue
        if narration is None:
            raise ValueError("narration_refs require the immutable narration_text")
        units = narration_units(narration)
        by_id = {unit["id"]: i for i, unit in enumerate(units)}
        refs = spec["narration_refs"]
        if (not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in by_id for ref in refs)):
            raise ValueError("narration_refs must list existing narration unit IDs")
        positions = [by_id[ref] for ref in refs]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("narration_refs must be unique, consecutive and in original order")
        span = narration[units[positions[0]]["start"]:units[positions[-1]]["end"]]
        if "narration_span" in spec and spec["narration_span"] != span:
            raise ValueError("explicit narration_span conflicts with narration_refs")
        spec["narration_span"] = span
        selected_offsets[id(spec)] = (units[positions[0]]["start"], units[positions[-1]]["end"])
        messages.append(f"Materialized exact narration_span for {spec.get('id')} from {refs}")
    if selected_offsets:
        cursor = 0
        for spec in specs:
            span = spec.get("narration_span") if isinstance(spec, dict) else None
            if not isinstance(span, str) or not span:
                raise ValueError("panels must partition narration_text exactly with nonempty spans")
            begin, end = selected_offsets.get(id(spec), (cursor, cursor + len(span)))
            if begin != cursor or narration[begin:end] != span:
                selected = spec.get("narration_refs")
                next_units = [
                    u["id"] for u in narration_units(narration) if u["start"] >= cursor
                ]
                raise ValueError(
                    "panels must partition narration_text exactly in "
                    "narration_refs identity order; "
                    f"visual={spec.get('id')}, selected={selected}, "
                    f"expected_next_units={next_units}. Each unit belongs to ONE panel only; "
                    "do not repeat units already assigned to a previous panel."
                )
            cursor = end
        if cursor != len(narration):
            raise ValueError(
                "panels must partition narration_text exactly without missing unit IDs"
            )
    return result, messages
