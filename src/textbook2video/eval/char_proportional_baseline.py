"""Counterfactual reproduction of the pre-semantic char-proportional timing.

The production timing path now uses sentence provenance and a configurable lead.
This module intentionally does *not* modify that path.  It replays the timing
algorithm from commit ``82b3bb6`` so Phase 3A can compare the current semantic
plan with the historical counterfactual on exactly the same elements.

Historical source of truth (``git show 82b3bb6``):

* ``pipeline/subtitles.py::build_subtitle_cues`` allocates each sentence cue by
  visible narration length (``max_chars=28``, ``min_cue_sec=0.8``).
* ``pipeline/timing.py::build_segment_timing`` matches an element to the cue
  with the highest character/bigram Jaccard score (threshold ``0.08``), uses
  ``0.0`` for the first/heading element, and otherwise uses evenly spaced
  fallback times.
* ``_fit_monotonic`` clamps to ``_max_trigger_sec`` and enforces a ``0.3``
  second gap in element order; overflow falls back to evenly spaced times.

Reports use only production animations whose ``trigger_source`` is a semantic
match (``text_match``/``semantic``) and whose sentence provenance can be
resolved.  Fallback animations are retained in the source report only as
exclusions, never in the primary baseline metrics.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from textbook2video.pipeline.subtitles import build_subtitle_cues
from textbook2video.pipeline.timing import _element_text as _current_element_text
from textbook2video.pipeline.timing import apply_timing

__all__ = [
    "HISTORICAL_COMMIT",
    "build_char_proportional_cues",
    "build_char_proportional_timing",
    "aggregate_baseline_rows",
    "build_baseline_report",
    "build_overall_report",
    "evaluate_char_proportional_baseline",
    "generate_pilot3_reports",
    "write_baseline_reports",
]


HISTORICAL_COMMIT = "82b3bb6"
HISTORICAL_TIMING_PATH = "src/textbook2video/pipeline/timing.py"
HISTORICAL_SUBTITLE_PATH = "src/textbook2video/pipeline/subtitles.py"
HISTORICAL_MAX_CHARS = 28
HISTORICAL_MIN_CUE_SEC = 0.8
HISTORICAL_SIMILARITY_THRESHOLD = 0.08
HISTORICAL_MIN_GAP_SEC = 0.3
DEFAULT_LEAD_SEC = 1.0

_TEXT_KEYS = (
    "text",
    "title",
    "label",
    "caption",
    "description",
    "name",
    "quote",
)
_LIST_KEYS = ("items", "steps", "headers", "rows", "points", "labels", "values")


def _normalize_text(text: Any) -> str:
    value = str(text or "").lower()
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def _features(text: Any) -> set[str]:
    value = _normalize_text(text)
    if not value:
        return set()
    return set(value) | {value[index : index + 2] for index in range(max(0, len(value) - 1))}


def _similarity(left: Any, right: Any) -> float:
    first, second = _features(left), _features(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def _collect_text(value: Any) -> list[str]:
    """The historical collector, deliberately excluding newer semantic fields."""
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, list):
        output: list[str] = []
        for item in value:
            output.extend(_collect_text(item))
        return output
    if isinstance(value, dict):
        output = []
        for key in _TEXT_KEYS:
            output.extend(_collect_text(value.get(key)))
        for key in _LIST_KEYS:
            output.extend(_collect_text(value.get(key)))
        return output
    return []


def _legacy_element_text(element: dict[str, Any]) -> str:
    return " ".join(_collect_text(element))


def _segment_cues(segment: dict[str, Any]) -> list[dict[str, Any]]:
    cues = build_subtitle_cues(
        {"segments": [segment]},
        max_chars=HISTORICAL_MAX_CHARS,
        min_cue_sec=HISTORICAL_MIN_CUE_SEC,
    )
    return [
        {
            "index": cue.index,
            "start": float(cue.start_sec),
            "end": float(cue.end_sec),
            "text": cue.text,
            "sentence_id": cue.sentence_id,
        }
        for cue in cues
    ]


def build_char_proportional_cues(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the historical visible-character proportional cues for one segment."""
    return _segment_cues(segment)


def _max_trigger_sec(duration: float) -> float:
    if duration <= 0:
        return 0.0
    if duration <= 1.0:
        return max(0.0, duration * 0.6)
    return max(0.0, min(duration * 0.8, duration - 0.2))


def _even_times(count: int, max_sec: float) -> list[float]:
    if count <= 0:
        return []
    if count == 1 or max_sec <= 0:
        return [0.0] * count
    step = max_sec / (count - 1)
    return [round(index * step, 2) for index in range(count)]


def _fit_monotonic(times: list[float], max_sec: float) -> list[float]:
    """Exact pre-semantic clamp/min-gap/overflow behavior."""
    if not times:
        return []
    if len(times) == 1:
        return [round(max(0.0, min(times[0], max_sec)), 2)]

    output: list[float] = []
    for value in times:
        value = max(0.0, min(float(value), max_sec))
        if output and value < output[-1] + HISTORICAL_MIN_GAP_SEC:
            value = output[-1] + HISTORICAL_MIN_GAP_SEC
        output.append(value)
    if output[-1] > max_sec:
        return _even_times(len(times), max_sec)
    return [round(value, 2) for value in output]


def _best_cue(element_text: str, cues: list[dict[str, Any]]) -> dict[str, Any] | None:
    best_score = 0.0
    best: dict[str, Any] | None = None
    for index, cue in enumerate(cues):
        score = _similarity(element_text, cue.get("text", ""))
        if score > best_score:
            best_score = score
            best = {
                "cue_index": index,
                "cue_start_sec": float(cue.get("start", 0.0)),
                "cue_text": str(cue.get("text", "")),
                "score": round(score, 6),
            }
    return best if best_score >= HISTORICAL_SIMILARITY_THRESHOLD else None


def build_char_proportional_timing(segment: dict[str, Any]) -> list[dict[str, Any]]:
    """Replay old ``build_segment_timing`` without touching ``segment``.

    The returned entries are counterfactual records, not production animation
    objects.  Their ``trigger_at_sec`` is safe to compare but must never be
    written over a storyboard's production trigger.
    """
    duration = segment.get("audio_duration_sec")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return []
    elements = [
        element
        for element in segment.get("elements", []) or []
        if isinstance(element, dict) and str(element.get("id") or "").strip()
    ]
    if not elements:
        return []

    cues = _segment_cues(segment)
    max_sec = _max_trigger_sec(float(duration))
    fallback = _even_times(len(elements), max_sec)
    proposed: list[float] = []
    provenance: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        if index == 0 or element.get("type") == "heading":
            proposed.append(0.0)
            provenance.append(
                {"method": "structural_zero", "element_text": _legacy_element_text(element)}
            )
            continue
        element_text = _legacy_element_text(element)
        matched = _best_cue(element_text, cues)
        if matched is None:
            proposed.append(fallback[index])
            provenance.append(
                {
                    "method": "legacy_even_time_fallback",
                    "element_text": element_text,
                }
            )
        else:
            proposed.append(float(matched["cue_start_sec"]))
            provenance.append(
                {
                    "method": "legacy_fuzzy_cue_start",
                    "element_text": element_text,
                    **matched,
                }
            )

    fitted = _fit_monotonic(proposed, max_sec)
    return [
        {
            "target": str(element.get("id")),
            "trigger_at_sec": trigger,
            "baseline_method": details["method"],
            "baseline_inputs": {
                "element_text": details.get("element_text", ""),
                "cue_index": details.get("cue_index"),
                "cue_text": details.get("cue_text"),
                "cue_start_sec": details.get("cue_start_sec"),
                "match_score": details.get("score"),
                "max_trigger_sec": round(max_sec, 6),
                "historical_similarity_threshold": HISTORICAL_SIMILARITY_THRESHOLD,
                "historical_min_gap_sec": HISTORICAL_MIN_GAP_SEC,
            },
        }
        for element, trigger, details in zip(elements, fitted, provenance)
    ]


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _sidecar_cues(segment: dict[str, Any], sentence_cues: Any) -> list[dict[str, Any]]:
    selected: Any = sentence_cues
    if isinstance(sentence_cues, dict):
        selected = [
            cue
            for group in sentence_cues.get("segments", []) or []
            if isinstance(group, dict) and str(group.get("segment_id")) == str(segment.get("id"))
            for cue in group.get("cues", []) or []
            if isinstance(cue, dict)
        ]
    elif isinstance(sentence_cues, list):
        selected = [
            cue
            for cue in sentence_cues
            if isinstance(cue, dict)
            and (
                cue.get("segment_id") is None
                or str(cue.get("segment_id")) == str(segment.get("id"))
            )
        ]
    cues = build_subtitle_cues(
        {"segments": [segment]},
        max_chars=HISTORICAL_MAX_CHARS,
        min_cue_sec=HISTORICAL_MIN_CUE_SEC,
        sentence_cues=selected,
    )
    return [
        {
            "id": cue.sentence_id or f"sentence_{cue.index}",
            "sentence_id": cue.sentence_id or f"sentence_{cue.index}",
            "sentence_index": cue.sentence_index or cue.index,
            "start_sec": float(cue.start_sec),
            "end_sec": float(cue.end_sec),
            "text": cue.text,
        }
        for cue in cues
    ]


def _sentence_lookup(segment: dict[str, Any], sentence_cues: Any) -> dict[str, dict[str, Any]]:
    return {str(cue["id"]): cue for cue in _sidecar_cues(segment, sentence_cues)}


def _segment_id(value: Any) -> str:
    return str(value) if value is not None else ""


def _production_rows(
    storyboard: dict[str, Any],
    timed_storyboard: dict[str, Any],
    sentence_cues: Any,
    *,
    case_id: str,
    lesson_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_segments = {
        _segment_id(segment.get("id")): segment
        for segment in storyboard.get("segments", []) or []
        if isinstance(segment, dict)
    }
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for timed_segment in timed_storyboard.get("segments", []) or []:
        if not isinstance(timed_segment, dict):
            continue
        segment_key = _segment_id(timed_segment.get("id"))
        source_segment = source_segments.get(segment_key)
        if source_segment is None:
            continue
        legacy_by_target = {
            str(item["target"]): item for item in build_char_proportional_timing(source_segment)
        }
        elements = {
            str(element.get("id")): element
            for element in source_segment.get("elements", []) or []
            if isinstance(element, dict) and str(element.get("id") or "").strip()
        }
        cues_by_id = _sentence_lookup(source_segment, sentence_cues)
        references = dict(elements)
        for animation in timed_segment.get("animations", []) or []:
            if not isinstance(animation, dict):
                continue
            target = str(animation.get("target") or "")
            source = str(animation.get("trigger_source") or "")
            if source not in {"text_match", "semantic", "semantic_match"}:
                excluded.append(
                    {
                        "case_id": case_id,
                        "lesson_id": lesson_id,
                        "segment_id": segment_key,
                        "element_id": target,
                        "reason": "non_semantic_trigger_source",
                        "trigger_source": source or None,
                    }
                )
                continue
            sentence_id = str(animation.get("matched_sentence_id") or "").strip()
            if not sentence_id:
                excluded.append(
                    {
                        "case_id": case_id,
                        "lesson_id": lesson_id,
                        "segment_id": segment_key,
                        "element_id": target,
                        "reason": "missing_matched_sentence_id",
                    }
                )
                continue
            cue = cues_by_id.get(sentence_id)
            sentence_start = animation.get("sentence_start_sec")
            if not _is_number(sentence_start) and cue is not None:
                sentence_start = cue["start_sec"]
            if not _is_number(sentence_start) or not _is_number(animation.get("trigger_at_sec")):
                excluded.append(
                    {
                        "case_id": case_id,
                        "lesson_id": lesson_id,
                        "segment_id": segment_key,
                        "element_id": target,
                        "reason": "missing_sentence_start_or_semantic_trigger",
                        "matched_sentence_id": sentence_id,
                    }
                )
                continue
            element = elements.get(target, {})
            legacy = legacy_by_target.get(target)
            if legacy is None:
                excluded.append(
                    {
                        "case_id": case_id,
                        "lesson_id": lesson_id,
                        "segment_id": segment_key,
                        "element_id": target,
                        "reason": "element_not_in_source_storyboard",
                    }
                )
                continue
            lead = (
                float(animation.get("lead_sec", DEFAULT_LEAD_SEC))
                if _is_number(animation.get("lead_sec", DEFAULT_LEAD_SEC))
                else DEFAULT_LEAD_SEC
            )
            matched_text = str(
                animation.get("matched_sentence_text") or (cue or {}).get("text", "")
            )
            current_text = _current_element_text(element, references=references)
            row = {
                "lesson_id": lesson_id,
                "case_id": case_id,
                "segment_id": segment_key,
                "element_id": target,
                "element_type": str(element.get("type") or element.get("visual_type") or ""),
                "element_text": current_text,
                "legacy_element_text": legacy["baseline_inputs"]["element_text"],
                "trigger_source": source,
                "match_method": animation.get("match_method"),
                "match_score": animation.get("match_score"),
                "matched_sentence_id": sentence_id,
                "matched_sentence_text": matched_text,
                "sentence_start_sec": round(float(sentence_start), 6),
                "lead_sec": round(lead, 6),
                "target_trigger_sec": round(max(0.0, float(sentence_start) - lead), 6),
                "char_proportional_trigger_sec": legacy["trigger_at_sec"],
                "semantic_trigger_sec": round(float(animation["trigger_at_sec"]), 6),
                "char_error_sec": round(
                    abs(float(legacy["trigger_at_sec"]) - max(0.0, float(sentence_start) - lead)), 6
                ),
                "semantic_plan_error_sec": round(
                    abs(
                        float(animation["trigger_at_sec"]) - max(0.0, float(sentence_start) - lead)
                    ),
                    6,
                ),
                "baseline_method": legacy["baseline_method"],
                "baseline_inputs": legacy["baseline_inputs"],
            }
            rows.append(row)
    return rows, excluded


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    weight = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 6)


def aggregate_baseline_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(rows)
    char_errors = [float(row["char_error_sec"]) for row in records]
    semantic_errors = [float(row["semantic_plan_error_sec"]) for row in records]

    def metrics(errors: list[float], prefix: str) -> dict[str, Any]:
        count = len(errors)
        result: dict[str, Any] = {f"{prefix}_evaluated_element_count": count}
        if not errors:
            result.update(
                {
                    f"{prefix}_mae_sec": None,
                    f"{prefix}_median_error_sec": None,
                    f"{prefix}_p95_error_sec": None,
                    f"{prefix}_max_error_sec": None,
                }
            )
            for threshold in (0.5, 1.0, 2.0):
                result[f"{prefix}_error_le_{str(threshold).replace('.', '_')}_ratio"] = None
            return result
        result.update(
            {
                f"{prefix}_mae_sec": round(sum(errors) / count, 6),
                f"{prefix}_median_error_sec": round(float(median(errors)), 6),
                f"{prefix}_p95_error_sec": _percentile(errors, 0.95),
                f"{prefix}_max_error_sec": round(max(errors), 6),
            }
        )
        for threshold in (0.5, 1.0, 2.0):
            key = f"{prefix}_error_le_{str(threshold).replace('.', '_')}_ratio"
            result[key] = round(sum(error <= threshold for error in errors) / count, 6)
        return result

    output = metrics(char_errors, "char")
    output.update(metrics(semantic_errors, "semantic_plan"))
    # Keep the unprefixed count convenient for report consumers while retaining
    # the explicit ``char_*`` and ``semantic_plan_*`` names above.
    output["evaluated_element_count"] = output["char_evaluated_element_count"]
    return output


def build_baseline_report(
    storyboard: dict[str, Any],
    timed_storyboard: dict[str, Any],
    sentence_cues: Any = None,
    *,
    case_id: str | None = None,
    lesson_id: str | None = None,
    source_path: str | Path | None = None,
    timed_storyboard_path: str | Path | None = None,
    sentence_cues_path: str | Path | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    resolved_case_id = case_id or str(
        storyboard.get("metadata", {}).get("case_id") or lesson_id or "unknown"
    )
    resolved_lesson_id = lesson_id or str(
        storyboard.get("metadata", {}).get("lesson_id") or resolved_case_id
    )
    rows, excluded = _production_rows(
        storyboard,
        timed_storyboard,
        sentence_cues,
        case_id=resolved_case_id,
        lesson_id=resolved_lesson_id,
    )
    top = sorted(
        rows, key=lambda row: (-float(row["char_error_sec"]), row["segment_id"], row["element_id"])
    )[: max(0, int(top_n))]
    return {
        "schema_version": "textbookeval-char-proportional-baseline-v0.1",
        "report_type": "char_proportional_baseline",
        "case_id": resolved_case_id,
        "lesson_id": resolved_lesson_id,
        "status": "ok" if rows else "no_evaluable_semantic_elements",
        "algorithm": {
            "historical_commit": HISTORICAL_COMMIT,
            "historical_timing_file": HISTORICAL_TIMING_PATH,
            "historical_subtitle_file": HISTORICAL_SUBTITLE_PATH,
            "cue_allocation": "build_subtitle_cues visible-character proportional durations",
            "max_chars": HISTORICAL_MAX_CHARS,
            "min_cue_sec": HISTORICAL_MIN_CUE_SEC,
            "similarity": "character and bigram Jaccard",
            "similarity_threshold": HISTORICAL_SIMILARITY_THRESHOLD,
            "min_gap_sec": HISTORICAL_MIN_GAP_SEC,
            "element_order": "source storyboard order",
        },
        "comparison_scope": {
            "included_trigger_sources": ["text_match", "semantic", "semantic_match"],
            "excluded_fallbacks": True,
            "semantic_plan_error_interpretation": (
                "implementation consistency only; not semantic correctness"
            ),
        },
        "human_review": {
            "human_reviewed_new_matches": 6,
            "human_review_correct": 6,
            "human_review_incorrect": 0,
            "scope": "six Phase 2B newly matched elements across the three cases; "
            "not all semantic matches",
        },
        "human_reviewed_new_matches": 6,
        "human_review_correct": 6,
        "metrics": aggregate_baseline_rows(rows),
        "evaluated_elements": rows,
        "excluded_elements": excluded,
        "top_char_errors": top,
        "inputs": {
            "source_storyboard": str(source_path) if source_path else None,
            "production_timed_storyboard": str(timed_storyboard_path)
            if timed_storyboard_path
            else None,
            "sentence_cues": str(sentence_cues_path) if sentence_cues_path else None,
        },
    }


def evaluate_char_proportional_baseline(
    storyboard: dict[str, Any],
    sentence_cues: Any = None,
    *,
    timed_storyboard: dict[str, Any] | None = None,
    case_id: str | None = None,
    lesson_id: str | None = None,
    **paths: Any,
) -> dict[str, Any]:
    """Build a report while leaving both input storyboards unchanged."""
    production = (
        timed_storyboard
        if timed_storyboard is not None
        else apply_timing(storyboard, sentence_cues)
    )
    return build_baseline_report(
        storyboard,
        production,
        sentence_cues,
        case_id=case_id,
        lesson_id=lesson_id,
        **paths,
    )


def build_overall_report(
    case_reports: Iterable[dict[str, Any]], *, top_n: int = 10
) -> dict[str, Any]:
    reports = list(case_reports)
    rows = [row for report in reports for row in report.get("evaluated_elements", [])]
    return {
        "schema_version": "textbookeval-char-proportional-baseline-v0.1",
        "report_type": "char_proportional_baseline_overall",
        "status": "ok" if rows else "no_evaluable_semantic_elements",
        "case_ids": [report.get("case_id") for report in reports],
        "metrics": aggregate_baseline_rows(rows),
        "human_review": {
            "human_reviewed_new_matches": 6,
            "human_review_correct": 6,
            "human_review_incorrect": 0,
            "scope": "six Phase 2B newly matched elements across the three cases; "
            "not all semantic matches",
        },
        "human_reviewed_new_matches": 6,
        "human_review_correct": 6,
        "top_char_errors": sorted(
            rows,
            key=lambda row: (
                -float(row["char_error_sec"]),
                row["lesson_id"],
                row["segment_id"],
                row["element_id"],
            ),
        )[: max(0, int(top_n))],
        "cases": [
            {
                "case_id": report.get("case_id"),
                "lesson_id": report.get("lesson_id"),
                "metrics": report.get("metrics", {}),
                "evaluated_element_count": len(report.get("evaluated_elements", [])),
            }
            for report in reports
        ],
    }


def _markdown_report(report: dict[str, Any]) -> str:
    historical_commit = report.get("algorithm", {}).get("historical_commit", HISTORICAL_COMMIT)
    lines = [
        f"# Char-proportional baseline — {report.get('case_id', 'overall')}",
        "",
        f"- Lesson: `{report.get('lesson_id', 'overall')}`",
        f"- Status: **{report.get('status')}**",
        f"- Historical commit: `{historical_commit}`",
        "- Scope: production semantic matches with sentence provenance only; "
        "fallback elements are excluded.",
        "- Semantic plan error is an implementation-consistency check, not a "
        "semantic-accuracy score.",
        "- Human review: 6 newly matched elements reviewed, 6 correct; this is "
        "not 153/153 validation.",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key, value in report.get("metrics", {}).items():
        lines.append(f"| `{key}` | {value if value is not None else 'n/a'} |")
    lines.extend(
        [
            "",
            "## Top char errors",
            "",
            "| Lesson | Segment | Element | Element text | Matched sentence | "
            "Sentence start | Char trigger | Semantic trigger | Error |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("top_char_errors", []):
        element_text = str(row.get("element_text", "")).replace("|", "\\|").replace("\n", " ")
        sentence_text = (
            str(row.get("matched_sentence_text", "")).replace("|", "\\|").replace("\n", " ")
        )
        lines.append(
            f"| {row.get('lesson_id')} | {row.get('segment_id')} | "
            f"{row.get('element_id')} | {element_text} | {sentence_text} | "
            f"{row.get('sentence_start_sec')} | "
            f"{row.get('char_proportional_trigger_sec')} | "
            f"{row.get('semantic_trigger_sec')} | {row.get('char_error_sec')} |"
        )
    lines.extend(["", "## Inputs", ""])
    for key, value in report.get("inputs", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def write_baseline_reports(
    output_dir: str | Path, reports: list[dict[str, Any]], *, top_n: int = 10
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for report in reports:
        stem = str(report["lesson_id"])
        json_path = output / f"{stem}_char_proportional_baseline.json"
        md_path = output / f"{stem}_char_proportional_baseline.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_markdown_report(report), encoding="utf-8")
        paths.extend([json_path, md_path])
    overall = build_overall_report(reports, top_n=top_n)
    overall_json = output / "overall_char_proportional_baseline.json"
    overall_md = output / "overall_char_proportional_baseline.md"
    overall_json.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding="utf-8")
    overall_md.write_text(_markdown_report(overall), encoding="utf-8")
    paths.extend([overall_json, overall_md])
    return paths


def _git_commit(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def generate_pilot3_reports(
    repo_root: str | Path,
    cues_root: str | Path,
    output_dir: str | Path,
    *,
    lesson_ids: Iterable[str] = ("lesson_001", "lesson_002", "lesson_004"),
    top_n: int = 10,
) -> list[Path]:
    root = Path(repo_root).resolve()
    cues_base = Path(cues_root).resolve()
    reports: list[dict[str, Any]] = []
    for lesson_id in lesson_ids:
        source_path = root / "datasets" / "pilot3" / "artifacts" / lesson_id / "storyboard.json"
        cue_path = cues_base / f"{lesson_id}_sentence_cues.json"
        storyboard = json.loads(source_path.read_text(encoding="utf-8"))
        cues = json.loads(cue_path.read_text(encoding="utf-8")) if cue_path.is_file() else None
        timed = apply_timing(storyboard, cues)
        report = build_baseline_report(
            storyboard,
            timed,
            cues,
            case_id=f"pilot3_{lesson_id}",
            lesson_id=lesson_id,
            source_path=source_path,
            sentence_cues_path=cue_path if cue_path.is_file() else None,
            timed_storyboard_path=None,
            top_n=top_n,
        )
        report["production_commit"] = _git_commit(root)
        reports.append(report)
    return write_baseline_reports(output_dir, reports, top_n=top_n)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate historical char-proportional timing baseline reports"
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--cues-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", dest="cases", action="append", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args(argv)
    generate_pilot3_reports(
        args.repo_root,
        args.cues_root,
        args.output,
        lesson_ids=args.cases or ("lesson_001", "lesson_002", "lesson_004"),
        top_n=args.top_n,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
