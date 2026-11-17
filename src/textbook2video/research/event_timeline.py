"""Shared runtime timeline writes for course bindings and legacy research adapters.

The persisted ``research_p0`` metadata key is retained for historical artifacts.
No timing, selection, signaling or rendering policy is chosen here.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any


def _find_element(segment: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    return next(
        (
            element
            for element in segment.get("elements", []) or []
            if isinstance(element, dict) and str(element.get("id") or "") == element_id
        ),
        None,
    )


def element_target_aliases(segment: dict[str, Any], element_id: str) -> set[str]:
    """Return production target aliases that refer to one storyboard element.

    Older storyboards commonly used the source-image id as an animation target,
    while the clean staged storyboard uses a stable element id (for example
    ``brief-pdf-p004-fig02``).  Treating those values as unrelated leaves a
    dead legacy event in the runtime timeline and produces ``target_missing``
    even though the intended element is present.  Research adapters canonicalize all aliases
    to the actual element id without changing the baseline storyboard.
    """
    aliases = {str(element_id)}
    element = _find_element(segment, str(element_id))
    if not isinstance(element, dict):
        return aliases
    for key in ("source_image_id", "figure_id"):
        value = str(element.get(key) or "").strip()
        if value:
            aliases.add(value)
    source = str(element.get("src") or "").strip()
    if source:
        aliases.add(source)
        aliases.add(Path(source).stem)
    return aliases


def set_runtime_timeline_event(
    segment: dict[str, Any],
    *,
    target: str,
    action: str,
    effect: str,
    trigger: float,
    hold_sec: float | None,
    research_metadata: dict[str, Any],
    preserve_legacy: bool = False,
) -> None:
    """Update the runtime-precedence ``timeline`` without changing other targets.

    ``animation_gen.build_slide_timelines`` gives a non-empty ``timeline``
    precedence over legacy ``animations``.  P0 must therefore edit both
    representations.  A grouped timeline target is split so only the planned
    object receives the intervention.
    """
    timeline = segment.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        return
    updated: list[Any] = []
    current_event_id = str(research_metadata.get("event_id") or "")
    target_aliases = element_target_aliases(segment, target)
    has_existing_p0_target = any(
        isinstance(item, dict)
        and target_aliases.intersection(
            [part.strip() for part in str(item.get("target") or "").split(",") if part.strip()]
        )
        and isinstance(item.get("research_p0"), dict)
        and str(item["research_p0"].get("event_id") or "")
        for item in timeline
    )
    replaced_legacy_target = False
    updated_current_event = False
    for item in timeline:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        targets = [
            part.strip() for part in str(item.get("target") or "").split(",") if part.strip()
        ]
        if not target_aliases.intersection(targets):
            updated.append(item)
            continue

        item_research = item.get("research_p0")
        item_event_id = (
            str(item_research.get("event_id") or "")
            if isinstance(item_research, dict) else ""
        )
        # Re-applying the same event is idempotent.
        if item_event_id == current_event_id:
            clone = copy.deepcopy(item)
            clone.update({
                "event_id": current_event_id,
                "target": target,
                "action": action,
                "effect": effect,
                "at_sec": trigger,
                "trigger_at_sec": trigger,
                "research_p0": research_metadata,
            })
            if hold_sec is not None:
                clone["hold_sec"] = hold_sec
            updated.append(clone)
            updated_current_event = True
            continue

        # Preserve a different P0 event already attached to this target.  It
        # is a real independent intervention (for example the reveal that
        # precedes this focus), not a legacy item to be replaced.
        if item_event_id or preserve_legacy:
            updated.append(copy.deepcopy(item))
            continue

        # Remove all aliases from the legacy item.  If it also targets an
        # unrelated element, retain that unrelated target in the grouped item.
        remaining_targets = [
            item_target for item_target in targets if item_target not in target_aliases
        ]
        if remaining_targets:
            untouched = copy.deepcopy(item)
            untouched["target"] = ",".join(remaining_targets)
            updated.append(untouched)

        # The first P0 event replaces the old production event for this
        # target.  Later P0 events (e.g. focus after show) are appended and
        # therefore remain independently observable.
        if not has_existing_p0_target and not replaced_legacy_target:
            clone = copy.deepcopy(item)
            clone.update({
                "event_id": current_event_id,
                "target": target,
                "action": action,
                "effect": effect,
                "at_sec": trigger,
                "trigger_at_sec": trigger,
                "research_p0": research_metadata,
            })
            if hold_sec is not None:
                clone["hold_sec"] = hold_sec
            updated.append(clone)
            replaced_legacy_target = True
    if not updated_current_event and (has_existing_p0_target or not replaced_legacy_target):
        event: dict[str, Any] = {
            "event_id": research_metadata["event_id"],
            "target": target,
            "action": action,
            "effect": effect,
            "at_sec": trigger,
            "trigger_at_sec": trigger,
            "research_p0": research_metadata,
        }
        if hold_sec is not None:
            event["hold_sec"] = hold_sec
        updated.append(event)
    # Keep the runtime list chronologically ordered after appending a second
    # P0 event to an existing target.  Browser scheduling uses this list as the
    # source of deterministic event order, so focus must never precede reveal.
    def _timeline_time(item: Any) -> float:
        if not isinstance(item, dict):
            return float("inf")
        try:
            return float(item.get("at_sec", item.get("trigger_at_sec", float("inf"))))
        except (TypeError, ValueError):
            return float("inf")

    segment["timeline"] = sorted(updated, key=_timeline_time)


