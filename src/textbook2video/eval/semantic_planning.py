"""Read-only validation for sentence-anchored semantic animation timing."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_TOLERANCE_SEC = 0.01
SEMANTIC_TRIGGER_SOURCE = "text_match"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _key(value: Any) -> str:
    return str(value).strip()


def _iter_cues(sentence_cues: Any, segment_id: Any) -> Iterable[tuple[int, dict[str, Any]]]:
    """Yield cue index and cue for one segment from either sidecar shape."""
    groups: Any = sentence_cues
    if isinstance(sentence_cues, dict):
        groups = sentence_cues.get("segments", [])
    if isinstance(groups, list) and groups and all(isinstance(item, dict) for item in groups):
        # A sidecar has [{segment_id, cues}], while a direct cue list has
        # [{text, start_sec}, ...].
        if any("cues" in item for item in groups):
            for group in groups:
                if _key(group.get("segment_id")) != _key(segment_id):
                    continue
                cues = group.get("cues", [])
                if isinstance(cues, list):
                    for index, cue in enumerate(cues, start=1):
                        if isinstance(cue, dict):
                            yield index, cue
                return
        else:
            for index, cue in enumerate(groups, start=1):
                if isinstance(cue, dict):
                    yield index, cue


def _cue_lookup(sentence_cues: Any, segment_id: Any) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for index, cue in _iter_cues(sentence_cues, segment_id):
        cue_id = _key(cue.get("sentence_id") or cue.get("id"))
        if cue_id:
            lookup[cue_id] = cue
        # Timing's deterministic fallback id is sentence_N.  Keep it as a
        # compatibility alias for sidecars that omit sentence_id.
        lookup.setdefault(f"sentence_{index}", cue)
        lookup.setdefault(f"segment-{_key(segment_id)}-sentence-{index}", cue)
    return lookup


def _segment_duration(segment: dict[str, Any]) -> float | None:
    return _number(segment.get("audio_duration_sec"))


def evaluate_semantic_planning(
    timed_storyboard: dict[str, Any],
    sentence_cues: Any,
    *,
    tolerance_sec: float = DEFAULT_TOLERANCE_SEC,
    case_id: str | None = None,
    lesson_id: str | None = None,
    source_paths: dict[str, str | Path | None] | None = None,
) -> dict[str, Any]:
    """Validate that reliable semantic triggers remain at their cue anchors.

    This function does not repair or reorder timings.  A semantic match is
    reliable only when ``trigger_source == text_match`` and it has a non-empty
    ``matched_sentence_id``.  It reports element-level anchor deltas and
    same-sentence trigger spread so callers can gate a recording run before
    launching a browser.
    """
    tolerance = max(0.0, float(tolerance_sec))
    semantic_elements: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    bounds_violations: list[dict[str, Any]] = []

    for slide_index, segment in enumerate(timed_storyboard.get("segments", []) or [], start=1):
        if not isinstance(segment, dict):
            continue
        segment_id = segment.get("id", slide_index)
        duration = _segment_duration(segment)
        cues = _cue_lookup(sentence_cues, segment_id)
        for animation in segment.get("animations", []) or []:
            if not isinstance(animation, dict):
                continue
            if animation.get("trigger_source") != SEMANTIC_TRIGGER_SOURCE:
                continue
            sentence_id = _key(animation.get("matched_sentence_id"))
            if not sentence_id:
                continue
            element = {
                "lesson_id": lesson_id,
                "case_id": case_id,
                "segment_id": _key(segment_id),
                "slide_id": slide_index,
                "element_id": _key(animation.get("target")),
                "matched_sentence_id": sentence_id,
                "trigger_source": SEMANTIC_TRIGGER_SOURCE,
                "lead_sec": _number(animation.get("lead_sec")),
                "trigger_at_sec": _number(animation.get("trigger_at_sec")),
            }
            semantic_elements.append(element)
            grouped[(_key(segment_id), sentence_id)].append(element)
            cue = cues.get(sentence_id)
            if cue is None:
                violations.append({**element, "reason": "missing_sentence_cue"})
                continue
            sentence_start = _number(cue.get("start_sec", cue.get("start")))
            lead = element["lead_sec"]
            actual = element["trigger_at_sec"]
            if sentence_start is None or lead is None or actual is None:
                violations.append({**element, "reason": "missing_anchor_metadata"})
                continue
            expected = max(0.0, sentence_start - max(0.0, lead))
            if duration is not None:
                expected = min(expected, max(0.0, duration))
            delta = abs(actual - expected)
            record = {
                **element,
                "sentence_start_sec": sentence_start,
                "expected_trigger_at_sec": round(expected, 6),
                "delta_sec": round(delta, 6),
            }
            if delta > tolerance:
                violations.append({**record, "reason": "semantic_anchor_delta"})
            if duration is not None and not (0.0 <= actual <= duration):
                bounds_violations.append({**record, "reason": "trigger_out_of_bounds"})

    sync_violations: list[dict[str, Any]] = []
    for (segment_id, sentence_id), elements in grouped.items():
        values = [item["trigger_at_sec"] for item in elements if item["trigger_at_sec"] is not None]
        if len(values) < 2:
            continue
        spread = max(values) - min(values)
        if spread > tolerance:
            sync_violations.append({
                "segment_id": segment_id,
                "matched_sentence_id": sentence_id,
                "element_ids": [item["element_id"] for item in elements],
                "trigger_values_sec": sorted(set(round(value, 6) for value in values)),
                "spread_sec": round(spread, 6),
            })

    paths = source_paths or {}
    status = "ok" if not violations and not sync_violations and not bounds_violations else "failed"
    return {
        "schema_version": "textbookeval-semantic-planning-v0.1",
        "report_type": "semantic_planning_gate",
        "case_id": case_id,
        "lesson_id": lesson_id,
        "status": status,
        "passed": status == "ok",
        "tolerance_sec": tolerance,
        "metrics": {
            "semantic_element_count": len(semantic_elements),
            "semantic_anchor_violation_count": len(violations),
            "same_sentence_group_count": sum(len(items) > 1 for items in grouped.values()),
            "same_sentence_sync_violation_count": len(sync_violations),
            "max_same_sentence_spread_sec": round(
                max((item["spread_sec"] for item in sync_violations), default=0.0), 6
            ),
            "trigger_bounds_violation_count": len(bounds_violations),
        },
        "violations": violations,
        "same_sentence_sync_violations": sync_violations,
        "trigger_bounds_violations": bounds_violations,
        "evaluated_elements": semantic_elements,
        "inputs": {
            "timed_storyboard": str(paths.get("timed_storyboard")) if paths.get("timed_storyboard") else None,
            "sentence_cues": str(paths.get("sentence_cues")) if paths.get("sentence_cues") else None,
        },
    }


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate fixed semantic timing anchors")
    parser.add_argument("--timed-storyboard", required=True, type=Path)
    parser.add_argument("--sentence-cues", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--lesson-id")
    parser.add_argument("--tolerance-sec", type=float, default=DEFAULT_TOLERANCE_SEC)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = evaluate_semantic_planning(
        _load_json(args.timed_storyboard),
        _load_json(args.sentence_cues),
        tolerance_sec=args.tolerance_sec,
        case_id=args.case_id,
        lesson_id=args.lesson_id,
        source_paths={"timed_storyboard": args.timed_storyboard, "sentence_cues": args.sentence_cues},
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
