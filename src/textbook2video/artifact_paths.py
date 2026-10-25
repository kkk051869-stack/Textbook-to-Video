"""Bound filesystem names without changing semantic visual identifiers."""

import hashlib
import re


def artifact_stem(identifier: str) -> str:
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", identifier):
        raise ValueError("artifact identifier must be a safe logical ID")
    return (
        identifier
        if len(identifier) <= 24
        and not re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", identifier, flags=re.IGNORECASE)
        else "v-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
    )


def unique_artifact_stem(identifier: str, used: set[str]) -> str:
    stem = artifact_stem(identifier)
    candidate, number = stem, 0
    while candidate.casefold() in used:
        number += 1
        suffix = f"-{number}"
        candidate = stem[: 24 - len(suffix)] + suffix
    used.add(candidate.casefold())
    return candidate
