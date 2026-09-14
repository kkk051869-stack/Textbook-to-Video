"""Adapters that invoke the repository's real Storyboard and Layout repairs.

The orchestrator owns candidate isolation and acceptance.  This module only
bridges its ``Path`` callback to the existing production functions, while
keeping model behavior injectable for local deterministic runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from textbook2video.animation_gen import (
    generate_batch,
    repair_single_slides,
    split_slides_html,
)

from .orchestrator import RepairOrchestrator, RepairResult

StoryboardReviewFn = Callable[
    [dict[str, Any], dict[str, Any] | None, str | None], dict[str, Any]
]
StoryboardRepairFn = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any] | None, str | None], dict[str, Any]
]
GenerateFn = Callable[..., str]
LayoutReEvalFn = Callable[[Path, list[str], Path], dict[str, Any]]


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def repair_storyboard_candidate(
    candidate_artifact: str | Path,
    *,
    lesson_plan: dict[str, Any] | None = None,
    model: str | None = None,
    max_rounds: int = 2,
    review_fn: StoryboardReviewFn | None = None,
    repair_fn: StoryboardRepairFn | None = None,
) -> Path:
    """Run the existing ``run_storyboard_agent_review`` on a candidate file.

    Supplying ``review_fn`` and ``repair_fn`` is mandatory for local offline
    demos.  Omitting them deliberately keeps the normal production model
    boundary available to callers that explicitly opt into it.
    """

    path = Path(candidate_artifact).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("candidate storyboard must be a JSON object")

    from textbook2video.pipeline.storyboard import run_storyboard_agent_review

    repaired = run_storyboard_agent_review(
        value,
        lesson_plan=lesson_plan,
        model=model,
        max_rounds=max_rounds,
        strict=True,
        review_fn=review_fn,
        repair_fn=repair_fn,
    )
    if not isinstance(repaired, dict):
        raise TypeError("Storyboard repair returned a non-object")
    _write_json_atomic(path, repaired)
    return path


def _replace_slide_blocks(html: str, before: list[str], after: list[str]) -> str:
    if len(before) != len(after):
        raise ValueError("layout repair must preserve slide count")
    cursor = 0
    pieces: list[str] = []
    for old, new in zip(before, after):
        start = html.find(old, cursor)
        if start < 0:
            raise ValueError("cannot locate extracted slide in candidate HTML")
        pieces.append(html[cursor:start])
        pieces.append(new)
        cursor = start + len(old)
    pieces.append(html[cursor:])
    return "".join(pieces)


def repair_layout_candidate(
    candidate_artifact: str | Path,
    *,
    segments: list[dict[str, Any]],
    layout_report: dict[str, Any],
    title: str = "Local Layout Repair",
    lesson_description: str = "",
    theme_prompt: str = "",
    layout_prompt: str = "",
    model: str = "local-deterministic",
    max_tokens: int = 16000,
    generate_fn: GenerateFn | None = None,
    browser_channel: str = "msedge",
) -> Path:
    """Invoke the existing CSS-hotfix → single-slide repair chain.

    CSS hotfix is attempted first exactly as ``animation_gen.generate`` does.
    If the local browser is unavailable or CSS cannot resolve the issue, the
    existing ``repair_single_slides`` production function is invoked with the
    supplied deterministic generator.  The candidate file is the only file
    ever mutated.
    """

    path = Path(candidate_artifact).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    html = path.read_text(encoding="utf-8")

    try:
        from textbook2video.css_hotfix import apply_css_hotfixes

        css_fix_count = apply_css_hotfixes(
            path,
            layout_report,
            browser_channel=browser_channel,
        )
    except Exception as exc:  # noqa: BLE001 - existing generate() falls through to LLM repair
        css_fix_count = 0
        css_error = f"{type(exc).__name__}: {exc}"
    else:
        css_error = None

    if css_fix_count > 0:
        return path

    before_slides = split_slides_html(html)
    if not before_slides:
        raise ValueError("candidate HTML contains no .slide blocks")
    if not segments:
        raise ValueError("layout repair requires storyboard segments")

    # ``repair_single_slides`` mutates the supplied batch list in place; keep
    # an immutable snapshot for exact block replacement below.
    batch_slide_lists = [list(before_slides)]
    custom_css: list[str] = []
    repaired = repair_single_slides(
        segments=segments,
        batch_slide_lists=batch_slide_lists,
        all_custom_css=custom_css,
        report=layout_report,
        title=title,
        lesson_description=lesson_description,
        theme_prompt=theme_prompt,
        layout_prompt=layout_prompt,
        model=model,
        max_tokens=max_tokens,
        generate_fn=generate_fn or generate_batch,
    )
    if not repaired:
        detail = "single-slide repair returned no replacement"
        if css_error:
            detail = f"CSS hotfix unavailable ({css_error}); {detail}"
        raise RuntimeError(detail)

    after_slides = batch_slide_lists[0]
    updated = _replace_slide_blocks(html, before_slides, after_slides)
    if custom_css:
        updated = updated.replace("</head>", "<style>\n" + "\n".join(custom_css) + "\n</style></head>", 1)
    path.write_text(updated, encoding="utf-8")
    return path


def execute_layout_repair(
    *,
    canonical_root: str | Path,
    work_root: str | Path,
    case_id: str,
    run_id: str,
    issue: dict[str, Any],
    artifact: str | Path,
    before_report: dict[str, Any],
    segments: list[dict[str, Any]],
    layout_report: dict[str, Any],
    re_evaluate: LayoutReEvalFn,
    title: str = "Local Layout Repair",
    lesson_description: str = "",
    theme_prompt: str = "",
    layout_prompt: str = "",
    model: str = "local-deterministic",
    max_tokens: int = 16000,
    generate_fn: GenerateFn | None = None,
    browser_channel: str = "msedge",
    max_rounds: int = 3,
) -> RepairResult:
    """Run the real Layout repair chain through candidate gating and lineage."""
    orchestrator = RepairOrchestrator(
        canonical_root=canonical_root,
        work_root=work_root,
        case_id=case_id,
        run_id=run_id,
        max_rounds=max_rounds,
    )

    def repair(candidate: Path) -> Path:
        return repair_layout_candidate(
            candidate,
            segments=segments,
            layout_report=layout_report,
            title=title,
            lesson_description=lesson_description,
            theme_prompt=theme_prompt,
            layout_prompt=layout_prompt,
            model=model,
            max_tokens=max_tokens,
            generate_fn=generate_fn,
            browser_channel=browser_channel,
        )

    return orchestrator.execute(
        issue,
        artifact=artifact,
        before_report=before_report,
        repair_fn=repair,
        re_evaluate=re_evaluate,
        model=model,
    )


__all__ = [
    "execute_layout_repair",
    "repair_layout_candidate",
    "repair_storyboard_candidate",
]
