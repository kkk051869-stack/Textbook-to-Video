"""Stable element ids shared by storyboard normalization and HTML rendering."""

from __future__ import annotations

import re
from typing import Any, Iterable


_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_POSITIONAL_TARGET = re.compile(r"e(\d+)")


def sanitize_animation_id(value: Any) -> str:
    """Return the selector-safe form used by ``data-anim-id``."""
    return _UNSAFE_ID_CHARS.sub("", str(value or "").strip())


def normalize_element_ids(elements: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every element one deterministic, unique, selector-safe id.

    Existing ids are preserved whenever they are safe and unique. Missing ids
    use the stable positional form ``eN``. Duplicate or unsafe ids receive a
    deterministic suffix rather than making all matching runtime events
    ambiguous.
    """
    normalized: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            continue

        requested = str(element.get("id") or "").strip()
        candidate = sanitize_animation_id(requested) or f"e{index}"
        if candidate in used:
            fallback = f"e{index}"
            candidate = fallback if fallback not in used else f"{candidate}-{index}"
            suffix = 2
            while candidate in used:
                candidate = f"{fallback}-{suffix}"
                suffix += 1

        used.add(candidate)
        normalized.append({**element, "id": candidate})
    return normalized


def resolve_element_targets(
    value: Any,
    elements: Iterable[dict[str, Any]],
    *,
    preserve_unresolved: bool = False,
) -> list[str]:
    """Resolve comma-separated ids and legacy positional ``eN`` targets.

    ``preserve_unresolved`` keeps a selector-safe placeholder for a target that
    is not present in the element catalog.  This lets the browser runtime emit
    ``target_missing`` instead of making the planned event disappear.
    """
    normalized = [e for e in elements if isinstance(e, dict) and e.get("id")]
    ordered_ids = [str(e["id"]) for e in normalized]
    known = set(ordered_ids)
    resolved: list[str] = []
    for part in str(value or "").split(","):
        raw = part.strip()
        if not raw:
            continue
        target = sanitize_animation_id(raw)
        if target in known and (raw == target or _POSITIONAL_TARGET.fullmatch(raw)):
            candidate = target
        elif target in known and preserve_unresolved:
            candidate = f"unresolved-{target}"
            suffix = 2
            while candidate in known or candidate in resolved:
                candidate = f"unresolved-{target}-{suffix}"
                suffix += 1
        else:
            match = _POSITIONAL_TARGET.fullmatch(raw)
            if match:
                index = int(match.group(1)) - 1
                if 0 <= index < len(ordered_ids):
                    candidate = ordered_ids[index]
                elif preserve_unresolved:
                    candidate = target or f"unresolved-{index + 1}"
                else:
                    continue
            elif preserve_unresolved:
                candidate = target
                if not candidate:
                    continue
                if candidate in known:
                    candidate = f"unresolved-{candidate}"
                suffix = 2
                base = candidate
                while candidate in known or candidate in resolved:
                    candidate = f"{base}-{suffix}"
                    suffix += 1
            else:
                continue
        if candidate not in resolved:
            resolved.append(candidate)
    return resolved
