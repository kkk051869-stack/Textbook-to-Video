"""Validate and materialize one primary visual before rendering a course page."""

from __future__ import annotations

from copy import deepcopy

from textbook2video.animation_ids import resolve_element_targets

SUPPORT_TYPES = {"text", "quote", "label", "badge", "highlight_box"}


def visible_facts(element: dict) -> list[str]:
    """Collect displayed content, excluding prompts, provenance and style metadata."""
    values = []

    def collect(value):
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, dict):
            for key in ("text", "title", "content", "label", "value", "description"):
                if key in value:
                    collect(value[key])

    for key in ("text", "items", "steps", "rows", "content", "description", "source_caption"):
        if key in element:
            collect(element[key])
    return list(dict.fromkeys(values))


def apply_visual_page_plan(
    segment: dict,
    primary_id: str,
    plan: dict,
    *,
    visual_specs: list[dict] | None = None,
    source_text: str | None = None,
) -> dict:
    """Return auditable replacements; preserve event timing and narration.

    Replaced visual/list events now target the primary diagram at their original
    onset. Their original IDs and targets remain in the replacement log.
    """
    destination = segment
    segment = deepcopy(segment)
    original = deepcopy(segment)
    if not isinstance(plan, dict) or not str(plan.get("reason") or "").strip():
        raise ValueError("visual page requires a source-aware replacement reason")
    body = {
        str(e["id"]): e
        for e in segment["elements"]
        if e.get("type") not in {"heading", "subheading"} and str(e["id"]) != primary_id
    }
    support, replaced = plan.get("support_element_ids"), plan.get("replaces_element_ids")
    if not isinstance(support, list) or not isinstance(replaced, list):
        raise ValueError("page plan needs explicit support and replacement ID lists")
    ids = support + replaced
    if (
        any(not isinstance(i, str) for i in ids)
        or len(set(ids)) != len(ids)
        or set(ids) != set(body)
    ):
        raise ValueError("page plan must partition every existing body element exactly once")
    if len(support) > 2 or any(body[i]["type"] not in SUPPORT_TYPES for i in support):
        raise ValueError("one-primary page supports at most two short explanatory text elements")
    if sum(len(str(body[i].get("text") or "")) for i in support) > 120:
        raise ValueError("support text exceeds the readable page budget; split the page")
    coverage = plan.get("coverage", [])
    if not isinstance(coverage, list) or len(coverage) != len(replaced):
        declared = (
            {item.get("element_id") for item in coverage if isinstance(item, dict)}
            if isinstance(coverage, list)
            else set()
        )
        raise ValueError(
            "replacement requires coverage for every removed element; "
            f"missing IDs: {sorted(set(replaced) - declared)}"
        )
    proofs = {item.get("element_id"): item for item in coverage if isinstance(item, dict)}
    if len(proofs) != len(coverage) or set(proofs) != set(replaced):
        raise ValueError("coverage must identify every removed element exactly once")
    refs = set()
    for spec in visual_specs or []:
        refs.add(spec["id"])
        nodes = spec.get("nodes", spec.get("diagram", {}).get("nodes", []))
        refs.update(f"{spec['id']}:{node['id']}" for node in nodes)
    for ident, proof in proofs.items():
        if proof.get("fact_quotes") != visible_facts(body[ident]):
            raise ValueError("coverage must enumerate all original visible facts verbatim")
        if proof.get("decision") not in {
            "represented",
            "unsupported_in_source",
            "irrelevant_to_goal",
        }:
            raise ValueError("coverage needs a representation or explicit omission decision")
        if not str(proof.get("reason") or "").strip():
            raise ValueError("coverage needs an explanation for each element")
        if proof["decision"] == "represented":
            targets = proof.get("visual_refs")
            if not isinstance(targets, list) or not targets:
                raise ValueError("covered content needs explicit visual references")
            if visual_specs is not None and not set(targets).issubset(refs):
                raise ValueError(
                    f"coverage references a missing visual object for {ident}; "
                    f"missing={sorted(set(targets) - refs)}; allowed={sorted(refs)}. "
                    "Use an existing visual/node ID; diagram constraints are not node IDs."
                )
            quote = proof.get("source_evidence")
            if not isinstance(quote, str) or not quote.strip():
                raise ValueError(
                    f"coverage needs source evidence for element {ident}; add source_ref "
                    "from source_units to this coverage entry, not only to visual nodes"
                )
            if source_text is not None and quote not in source_text:
                raise ValueError(
                    f"coverage source_evidence for {ident} must be an exact source excerpt; "
                    f"the supplied quote is {quote!r}"
                )
        if body[ident].get("src") and not body[ident].get("source_image_path"):
            raise ValueError("replacing an existing image requires its pixels for review")
    record = {
        "primary_visual_id": primary_id,
        "support_element_ids": support,
        "reason": plan["reason"],
        "replaced_elements": [deepcopy(body[i]) for i in replaced],
        "retargeted_events": [],
        "coverage": deepcopy(coverage),
    }
    for field in ("timeline", "animations"):
        retargeted_sources = set()
        for event in segment.get(field) or []:
            if not isinstance(event, dict):
                raise ValueError("page events must be objects")
            original_target = event.get("target")
            target_text = (
                ",".join(original_target) if isinstance(original_target, list) else original_target
            )
            targets = resolve_element_targets(
                target_text, segment["elements"], preserve_unresolved=True
            )
            if any(target in replaced for target in targets):
                retargeted_sources.update(target for target in targets if target in replaced)
                if str(event.get("action") or "show") != "show":
                    raise ValueError(
                        "emphasis/hide replacement requires an explicit object-level event map"
                    )
                record["retargeted_events"].append({"field": field, "before": deepcopy(event)})
                mapped = list(
                    dict.fromkeys(
                        primary_id if target in replaced else target for target in targets
                    )
                )
                event["target"] = ",".join(mapped)
            else:
                # Freeze positional eN aliases before deleting any earlier element.
                event["target"] = ",".join(targets)
        if len(retargeted_sources) > 1:
            raise ValueError("multiple timed objects cannot collapse onto one primary visual")
    segment["elements"] = [e for e in segment["elements"] if str(e["id"]) not in replaced]
    segment["visual_page_plan"] = record
    from textbook2video.animation_gen import build_slide_timelines

    for field in ("timeline", "animations"):
        before, after = deepcopy(original), deepcopy(segment)
        if field == "animations":
            before.pop("timeline", None)
            after.pop("timeline", None)
        if not original.get(field):
            continue
        compiled_before = build_slide_timelines([before])[0]
        compiled_after = build_slide_timelines([after])[0]
        keys = ("action", "effect", "start_ms", "duration_ms", "hold_ms", "easing")
        if [tuple(e[k] for k in keys) for e in compiled_before] != [
            tuple(e[k] for k in keys) for e in compiled_after
        ]:
            raise ValueError("page replacement changed compiled event timing or behavior")
    destination.clear()
    destination.update(segment)
    return record
