"""Validate and materialize one primary visual before rendering a course page."""

from __future__ import annotations

from copy import deepcopy

from textbook2video.animation_ids import resolve_element_targets
from textbook2video.research.exact_source_excerpts import exact_evidence

SUPPORT_TYPES = {"text", "quote", "label", "badge", "highlight_box"}


def apply_local_visual_plan(segment, element, *, replace_element_id=None, coverage=None,
                            visual_spec=None, source_text=None):
    """Stage an insert or one text-object replacement without touching other objects.

    Caller owns the transaction and must render/validate before committing it.
    This engineering operation does not create research annotations or events.
    """
    from textbook2video.animation_gen import build_slide_timelines
    from textbook2video.animation_ids import sanitize_animation_id

    original = deepcopy(segment)
    elements = segment.get("elements", [])
    ids = [e.get("id") for e in elements]
    if (not ids or len(set(ids)) != len(ids)
            or any(not isinstance(i, str) or not i or sanitize_animation_id(i) != i for i in ids)):
        raise ValueError("local composition requires existing unique, selector-safe element IDs")
    retired_ids = {e["id"] for op in segment.get("local_visual_operations", [])
                   for e in op.get("replaced_elements", [])}
    if (element["id"] in set(ids) | retired_ids
            or sanitize_animation_id(element["id"]) != element["id"]):
        raise ValueError("local visual element ID conflict or unsafe ID")
    if segment.get("visual_page_plan"):
        raise ValueError("local composition needs an original page, not a whole-page visual plan")
    record = {"operation": "insert", "element_id": element["id"], "replaced_elements": [],
              "coverage": [], "retargeted_events": []}
    if replace_element_id is not None:
        if segment.get("research_generation_v2") or segment.get("events"):
            raise ValueError(
                "research event bindings need an explicit object map before replacement"
            )
        if replace_element_id not in ids:
            raise ValueError("local replacement target does not exist")
        target = elements[ids.index(replace_element_id)]
        # Pixel/geometry replacement needs an object-level mapping, outside this MVP.
        if target.get("type") not in {"text", "quote", "badge"} or not visible_facts(target):
            raise ValueError(
                "local replacement supports text objects only; geometry needs an object map"
            )
        if target.get("research_p0") or target.get("research_generation_v2"):
            raise ValueError("research object bindings require an object map before replacement")
        for other in elements:
            for key in ("target", "target_image", "image_id"):
                if replace_element_id in resolve_element_targets(other.get(key), elements):
                    raise ValueError("replacement has an overlay or other element dependency")
        if not isinstance(coverage, dict) or coverage.get("decision") != "represented":
            raise ValueError("local replacement must represent all content, never omit it")
        # Reuse the existing verbatim fact/source/reference validation unchanged.
        probe = {"elements": [deepcopy(target), deepcopy(element)]}
        proof = apply_visual_page_plan(
            probe, element["id"],
            {"reason": coverage.get("reason"), "support_element_ids": [],
             "replaces_element_ids": [replace_element_id], "coverage": [coverage]},
            visual_specs=[visual_spec], source_text=source_text,
        )
        record.update(operation="replace", replaced_elements=proof["replaced_elements"],
                      coverage=proof["coverage"])
        for field in ("timeline", "animations"):
            for event in segment.get(field) or []:
                targets = resolve_element_targets(event.get("target"), elements,
                                                  preserve_unresolved=True)
                if replace_element_id not in targets:
                    continue
                safe_effects = {
                    None, "fadeIn", "fadeInUp", "fadeInDown", "fadeInLeft", "fadeInRight",
                    "bounceIn", "zoomIn", "slideInLeft", "slideInRight",
                }
                if (targets != [replace_element_id] or event.get("action", "show") != "show"
                        or event.get("stagger") or event.get("effect") not in safe_effects
                        or event.get("research_p0") or event.get("research_generation_v2")):
                    raise ValueError(
                        "replacement event requires an object map: only ungrouped show is safe"
                    )
                record["retargeted_events"].append({"field": field, "before": deepcopy(event)})
                event["target"] = element["id"]
        elements[ids.index(replace_element_id)] = element
    else:
        if coverage is not None:
            raise ValueError("insert must not declare replacement coverage")
        elements.append(element)
    # Positional aliases of unrelated events must keep exactly the same meaning.
    # Check both event representations, including the inactive legacy fallback.
    for field in ("timeline", "animations"):
        before, after = deepcopy(original), deepcopy(segment)
        if field == "animations":
            before.pop("timeline", None)
            after.pop("timeline", None)
        compiled = build_slide_timelines([before])[0]
        for event in compiled:
            if replace_element_id is not None and event["target"] == replace_element_id:
                event["target"] = element["id"]
                event["selector"] = f'[data-anim-id="{element["id"]}"]'
        if compiled != build_slide_timelines([after])[0]:
            raise ValueError("local composition changed an unrelated compiled event")
    segment.setdefault("local_visual_operations", []).append(record)
    return record


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
        if not isinstance(spec, dict) or not isinstance(spec.get("id"), str):
            raise ValueError("visual coverage needs an object with a stable visual ID")
        refs.add(spec["id"])
        diagram = spec.get("diagram", {})
        if not isinstance(diagram, dict):
            raise ValueError(
                f"visual={spec['id']}: diagram must be an object, never a string; "
                "table visuals use kind=table with rows"
            )
        nodes = spec.get("nodes", diagram.get("nodes", []))
        if not isinstance(nodes, list) or any(
            not isinstance(node, dict) or not isinstance(node.get("id"), str) for node in nodes
        ):
            raise ValueError(f"visual={spec['id']}: nodes must be objects with stable node IDs")
        refs.update(f"{spec['id']}:{node['id']}" for node in nodes)
        if spec.get("kind") == "relationship" and diagram.get("constraint"):
            # '@' is not a legal node ID character in either visual dialect.
            refs.add(f"{spec['id']}:@constraint")
    if visual_specs is not None:
        missing_targets = {
            ident: sorted(set(proof["visual_refs"]) - refs)
            for ident, proof in proofs.items()
            if proof.get("decision") == "represented"
            and isinstance(proof.get("visual_refs"), list)
            and all(isinstance(target, str) for target in proof["visual_refs"])
            and set(proof["visual_refs"]) - refs
        }
        if missing_targets:
            raise ValueError(
                f"coverage references a missing visual object; all missing references="
                f"{missing_targets}; allowed={sorted(refs)}. "
                "Correct every listed coverage entry in one revision; use existing visual/node IDs."
            )
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
                    "Use an existing visual/node ID or a nonempty rendered relationship constraint."
                )
            quote = proof.get("source_evidence")
            if not quote or isinstance(quote, str) and not quote.strip():
                raise ValueError(
                    f"coverage needs source evidence for element {ident}; add source_ref "
                    "from source_units to this coverage entry, not only to visual nodes"
                )
            exact_evidence(
                quote, source_text, limit=None, label=f"coverage source_evidence for {ident}"
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
