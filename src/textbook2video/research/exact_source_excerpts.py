"""Exact source excerpts, kept separate when selected source spans are disjoint."""

from __future__ import annotations


def exact_evidence(value, source=None, *, limit=4000, label="evidence"):
    excerpts = [value] if isinstance(value, str) else value
    if (
        not isinstance(excerpts, list)
        or not excerpts
        or any(not isinstance(text, str) or not text.strip() for text in excerpts)
        or limit is not None
        and sum(len(text) for text in excerpts) > limit
    ):
        budget = f" within {limit} characters" if limit is not None else ""
        raise ValueError(f"{label} must contain nonempty exact source excerpts{budget}")
    if source is not None and any(text not in source for text in excerpts):
        raise ValueError(f"{label} must be an exact source excerpt in every selected span")
    return excerpts
