"""Bounded JSON-pointer edits to visual arguments, never source or audit records."""

from __future__ import annotations

import re
from copy import deepcopy

EDIT_ROOTS = {"visuals", "page_plan", "composition", "content_map"}


def apply_changes(base: dict, arguments: dict) -> dict:
    operations = arguments.get("changes")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 40:
        raise ValueError("revise changes requires 1-40 explicit operations")
    if EDIT_ROOTS.intersection(arguments):
        raise ValueError("use changes or replacement arguments, never both")
    result = {key: deepcopy(base[key]) for key in EDIT_ROOTS if key in base}
    references, explicit_quotes = [], set()

    def walk(value, path=""):
        if isinstance(value, list):
            for i, child in enumerate(value):
                yield from walk(child, f"{path}/{i}")
        elif isinstance(value, dict):
            for ref in ("source_ref", "constraint_source_ref", "narration_refs"):
                if ref in value:
                    field = {
                        "constraint_source_ref": "constraint_evidence",
                        "narration_refs": "narration_span",
                    }.get(ref) or ("source_evidence" if "element_id" in value else "evidence")
                    yield value, ref, field, f"{path}/{ref}"
            for key, child in value.items():
                yield from walk(child, f"{path}/{key}")

    before = {(id(obj), ref): deepcopy(obj[ref]) for obj, ref, _, _ in walk(result)}

    def mark_explicit(value):
        if isinstance(value, list):
            for child in value:
                mark_explicit(child)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key in {"evidence", "source_evidence", "constraint_evidence", "narration_span"}:
                    explicit_quotes.add((id(value), key))
                mark_explicit(child)

    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in {
            "add",
            "replace",
            "remove",
            "set",
        }:
            raise ValueError("edit operation must be add, replace, remove or set")
        path = operation.get("path")
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 500:
            raise ValueError("edit path must be a bounded absolute JSON pointer")
        if re.search(r"~(?![01])", path):
            raise ValueError("invalid JSON pointer escape")
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        if parts[0] not in EDIT_ROOTS or len(parts) > 12:
            raise ValueError("edits may only change visuals, page_plan, composition or content_map")
        target = result
        try:
            for part in parts[:-1]:
                target = (
                    target[_array_index(part, target)] if isinstance(target, list) else target[part]
                )
            key = parts[-1]
            op = operation["op"]
            if op != "remove" and "value" not in operation:
                raise ValueError("add/replace edit needs value")
            if isinstance(target, list):
                index = (
                    len(target)
                    if key == "-" and op == "add"
                    else _array_index(key, target, allow_end=op == "add")
                )
                if op == "add":
                    target.insert(index, deepcopy(operation["value"]))
                elif op in {"replace", "set"}:
                    target[index] = deepcopy(operation["value"])
                else:
                    target.pop(index)
                if op != "remove":
                    mark_explicit(target[index])
            elif isinstance(target, dict):
                if op in {"replace", "remove"} and key not in target:
                    raise ValueError(
                        "edit target does not exist; use op=add for a new optional field, "
                        "or target an existing field from previous_candidate"
                    )
                if op == "remove":
                    del target[key]
                else:
                    target[key] = deepcopy(operation["value"])
                    mark_explicit(target[key])
                if key in {"evidence", "source_evidence", "constraint_evidence", "narration_span"}:
                    explicit_quotes.add((id(target), key))
                if op != "remove" and key in {
                    "source_ref",
                    "constraint_source_ref",
                    "narration_refs",
                }:
                    field = {
                        "constraint_source_ref": "constraint_evidence",
                        "narration_refs": "narration_span",
                    }.get(key) or ("source_evidence" if "element_id" in target else "evidence")
                    references.append((target, field, path))
            else:
                raise ValueError("edit parent must be an object or array")
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"edit target does not exist: {path}") from exc
        except ValueError as exc:
            raise ValueError(f"edit failed at {path}: {exc}") from exc
    cleared = []
    missing = object()
    references.extend(
        (obj, field, path)
        for obj, ref, field, path in walk(result)
        if before.get((id(obj), ref), missing) != obj[ref]
    )
    for target, field, path in references:
        if (id(target), field) not in explicit_quotes and field in target:
            cleared.append({"reference_path": path, "field": field, "old_value": target.pop(field)})
    result.update({key: deepcopy(value) for key, value in arguments.items() if key != "changes"})
    if cleared:
        result["derived_fields_cleared"] = cleared
    result["applied_changes"] = deepcopy(operations)
    return result


def _array_index(value: str, items: list, *, allow_end=False) -> int:
    if value.startswith("@edge="):
        endpoints = value[len("@edge=") :].split("->")
        matches = [
            i
            for i, item in enumerate(items)
            if isinstance(item, dict)
            and len(endpoints) == 2
            and item.get("source") == endpoints[0]
            and item.get("target") == endpoints[1]
        ]
        if len(matches) != 1:
            raise ValueError(
                "edge selector must identify exactly one existing directed endpoint pair"
            )
        return matches[0]
    if value.startswith("@"):
        matches = [
            i
            for i, item in enumerate(items)
            if isinstance(item, dict) and value[1:] in (item.get("id"), item.get("element_id"))
        ]
        if len(matches) != 1:
            raise ValueError(
                "stable edit ID must identify exactly one existing array item; "
                "edges without IDs use @edge=source-id->target-id, never invented IDs"
            )
        return matches[0]
    length = len(items)
    if not re.fullmatch(r"0|[1-9][0-9]{0,3}", value):
        raise ValueError("edit array index must be a nonnegative canonical integer")
    index = int(value)
    if (index > length) if allow_end else (index >= length):
        raise ValueError(f"edit array index {index} is out of range for length {length}")
    return index
