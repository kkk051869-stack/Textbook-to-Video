"""Bounded JSON-pointer edits to visual arguments, never source or audit records."""

from __future__ import annotations

import re
from copy import deepcopy

EDIT_ROOTS = {"visuals", "page_plan", "composition"}


def apply_changes(base: dict, arguments: dict) -> dict:
    operations = arguments.get("changes")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 40:
        raise ValueError("revise changes requires 1-40 explicit operations")
    if EDIT_ROOTS.intersection(arguments):
        raise ValueError("use changes or replacement arguments, never both")
    result = {key: deepcopy(base[key]) for key in EDIT_ROOTS if key in base}
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in {
            "add",
            "replace",
            "remove",
        }:
            raise ValueError("edit operation must be add, replace or remove")
        path = operation.get("path")
        if not isinstance(path, str) or not path.startswith("/") or len(path) > 500:
            raise ValueError("edit path must be a bounded absolute JSON pointer")
        if re.search(r"~(?![01])", path):
            raise ValueError("invalid JSON pointer escape")
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        if parts[0] not in EDIT_ROOTS or len(parts) > 12:
            raise ValueError("edits may only change visuals, page_plan or composition")
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
                elif op == "replace":
                    target[index] = deepcopy(operation["value"])
                else:
                    target.pop(index)
            elif isinstance(target, dict):
                if op in {"replace", "remove"} and key not in target:
                    raise ValueError("edit target does not exist")
                if op == "remove":
                    del target[key]
                else:
                    target[key] = deepcopy(operation["value"])
            else:
                raise ValueError("edit parent must be an object or array")
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"edit target does not exist: {path}") from exc
        except ValueError as exc:
            raise ValueError(f"edit failed at {path}: {exc}") from exc
    result.update({key: deepcopy(value) for key, value in arguments.items() if key != "changes"})
    result["applied_changes"] = deepcopy(operations)
    return result


def _array_index(value: str, items: list, *, allow_end=False) -> int:
    if value.startswith("@"):
        matches = [
            i
            for i, item in enumerate(items)
            if isinstance(item, dict) and value[1:] in (item.get("id"), item.get("element_id"))
        ]
        if len(matches) != 1:
            raise ValueError("stable edit ID must identify exactly one existing array item")
        return matches[0]
    length = len(items)
    if not re.fullmatch(r"0|[1-9][0-9]{0,3}", value):
        raise ValueError("edit array index must be a nonnegative canonical integer")
    index = int(value)
    if (index > length) if allow_end else (index >= length):
        raise ValueError(f"edit array index {index} is out of range for length {length}")
    return index
