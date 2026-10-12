"""Conservative, explicit signaling policy for the dynamic P0 planner.

The old P0 pilot used one focus cue for the first bound element in a segment.
This policy makes ``NO_SIGNAL`` the valid default and emits a cue only when a
learner could reasonably confuse multiple concurrent visual targets or when a
proposition explicitly asks for a cue.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SIGNAL_POLICY_VERSION = "p0-signaling-policy-v1.0"
NO_SIGNAL = "NO_SIGNAL"
SIGNAL_ACTIONS = frozenset({"focus", "highlight", "pulse", "dim", NO_SIGNAL})


def choose_signal(
    proposition: dict[str, Any],
    *,
    target_element_id: str | None,
    related_target_count: int = 1,
    signal_count_in_window: int = 0,
    max_signals_in_window: int = 1,
    confidence: float = 1.0,
) -> dict[str, Any]:
    """Choose one cue, or explicitly choose no cue.

    ``signal_request`` may be ``focus``, ``highlight`` or ``pulse``; it is
    still rejected when the target is absent, confidence is low, or the local
    density budget is exhausted.
    """
    prop_id = str(proposition.get("id") or proposition.get("proposition_id") or "")
    requested = str(proposition.get("signal_request") or "").lower().strip()
    if not target_element_id:
        return _decision(prop_id, NO_SIGNAL, "missing_target")
    if float(confidence) < 0.45:
        return _decision(prop_id, NO_SIGNAL, "low_binding_confidence")
    if signal_count_in_window >= max_signals_in_window and not bool(
        proposition.get("force_signal")
    ):
        return _decision(prop_id, NO_SIGNAL, "signal_density_budget_exhausted")
    ambiguity = bool(proposition.get("ambiguous_visual_reference"))
    explicit = bool(proposition.get("requires_signal")) or bool(proposition.get("force_signal"))
    if requested in {"none", "no_signal"}:
        return _decision(prop_id, NO_SIGNAL, "explicit_no_signal")
    if requested in {"focus", "highlight", "pulse"}:
        return _decision(prop_id, requested, "explicit_signal_request")
    if related_target_count <= 1 and not (ambiguity or explicit):
        return _decision(prop_id, NO_SIGNAL, "single_unambiguous_target")
    if ambiguity or explicit or related_target_count > 1:
        return _decision(prop_id, "focus", "multiple_or_ambiguous_targets")
    return _decision(prop_id, NO_SIGNAL, "no_signaling_need_detected")


def _decision(proposition_id: str, action: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SIGNAL_POLICY_VERSION,
        "proposition_id": proposition_id,
        "signal_action": action,
        # ``highlight``/``pulse`` are renderer-supported effects.  Do not emit
        # a research-only label that the production runtime silently ignores.
        "signal_effect": None
        if action == NO_SIGNAL
        else ("pulse" if action == "pulse" else "highlight"),
        "status": "NO_SIGNAL" if action == NO_SIGNAL else "SIGNAL",
        "reason": reason,
    }


def validate_signal_policy(
    decisions: Iterable[dict[str, Any]],
    *,
    valid_target_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Validate policy decisions and report cue counts without judging pedagogy."""
    findings: list[dict[str, Any]] = []
    records = [item for item in decisions if isinstance(item, dict)]
    for item in records:
        action = str(item.get("signal_action") or "")
        target = str(item.get("target_element_id") or "")
        if action not in SIGNAL_ACTIONS:
            findings.append(
                {"severity": "ERROR", "code": "UNKNOWN_SIGNAL_ACTION", "action": action}
            )
        if action != NO_SIGNAL and valid_target_ids is not None and target not in valid_target_ids:
            findings.append(
                {"severity": "ERROR", "code": "SIGNAL_TARGET_MISSING", "target": target}
            )
    signal_count = sum(str(item.get("signal_action") or "") != NO_SIGNAL for item in records)
    return {
        "schema_version": SIGNAL_POLICY_VERSION,
        "decision_count": len(records),
        "signal_count": signal_count,
        "no_signal_count": len(records) - signal_count,
        "findings": findings,
        "pass": not any(item["severity"] == "ERROR" for item in findings),
    }


__all__ = [
    "NO_SIGNAL",
    "SIGNAL_ACTIONS",
    "SIGNAL_POLICY_VERSION",
    "choose_signal",
    "validate_signal_policy",
]
