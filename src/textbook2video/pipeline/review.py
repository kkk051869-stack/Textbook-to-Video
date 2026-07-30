"""Human review gate for storyboard-based video production."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from textbook2video.pipeline.checks import validate_storyboard
from textbook2video.pipeline.preview import preview_path_for, write_preview

__all__ = [
    "approve_storyboard",
    "ensure_review_approved",
    "review_path_for",
    "write_review_packet",
]


def _read_storyboard(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("storyboard JSON must be an object")
    if not isinstance(data.get("segments"), list):
        raise ValueError("storyboard JSON must contain a segments list")
    return data


def _default_script_path(storyboard_path: Path) -> Path:
    stem = storyboard_path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]
    return storyboard_path.parent / f"{stem}_script.txt"


def review_path_for(storyboard_path: str | Path) -> Path:
    path = Path(storyboard_path)
    stem = path.stem
    if stem.endswith("_storyboard"):
        stem = stem[: -len("_storyboard")]
    return path.with_name(f"{stem}_review.md")


def _review_status(storyboard: dict[str, Any]) -> dict[str, Any]:
    meta = storyboard.get("metadata")
    if not isinstance(meta, dict):
        return {}
    status = meta.get("human_review")
    return status if isinstance(status, dict) else {}


def ensure_review_approved(storyboard_path: str | Path) -> None:
    """Raise if storyboard has not been explicitly approved by a human."""
    storyboard = _read_storyboard(storyboard_path)
    status = _review_status(storyboard)
    if status.get("status") == "approved":
        return
    raise RuntimeError(
        "storyboard has not been human-approved. Run "
        f"`t2v review {Path(storyboard_path)} --approve` after checking it, "
        "or omit --require-review."
    )


def approve_storyboard(
    storyboard_path: str | Path,
    *,
    reviewer: str = "human",
    note: str = "",
) -> Path:
    """Mark a storyboard JSON as approved after human review."""
    path = Path(storyboard_path)
    storyboard = _read_storyboard(path)
    metadata = storyboard.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        storyboard["metadata"] = metadata
    metadata["human_review"] = {
        "status": "approved",
        "reviewer": reviewer,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }
    path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_review_packet(
    storyboard_path: str | Path,
    *,
    output_path: str | Path | None = None,
    script_path: str | Path | None = None,
    open_preview: bool = False,
) -> Path:
    """Write a Markdown review checklist and a sibling preview HTML."""
    path = Path(storyboard_path)
    storyboard = _read_storyboard(path)
    preview_path = write_preview(path)
    report = validate_storyboard(
        storyboard,
        base_dir=path.parent,
        script_path=Path(script_path) if script_path else _default_script_path(path),
    )
    out = Path(output_path) if output_path else review_path_for(path)
    status = _review_status(storyboard)
    approved = status.get("status") == "approved"

    lines = [
        f"# Storyboard Review: {path.name}",
        "",
        f"- Storyboard: `{path}`",
        f"- Preview: `{preview_path}`",
        f"- Slides: {len(storyboard.get('segments', []) or [])}",
        f"- Validation: {'PASS' if report.ok else 'FAIL'}",
        f"- Human review: {'approved' if approved else 'pending'}",
    ]
    if approved:
        lines.append(f"- Reviewer: {status.get('reviewer', '')}")
        lines.append(f"- Approved at: {status.get('approved_at', '')}")
    lines.extend([
        "",
        "## Checklist",
        "",
        "- [ ] 标题和正文没有明显重复。",
        "- [ ] 每页有清楚的主视觉或结构化元素。",
        "- [ ] 讲稿、画面、检测题和小结逻辑连贯。",
        "- [ ] 图片没有空缺、错配或明显幻觉。",
        "- [ ] 检测题有题干、答案和解析。",
        "- [ ] 预览 HTML 中没有文字重叠或溢出。",
        "",
        "## Validation Warnings",
        "",
    ])
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Validation Errors", ""])
    if report.errors:
        lines.extend(f"- {error}" for error in report.errors)
    else:
        lines.append("- None")
    lines.extend([
        "",
        "## Next Commands",
        "",
        "```powershell",
        f"t2v preview \"{path}\" --edit --open",
        f"t2v review \"{path}\" --approve",
        f"t2v produce <textbook.pdf/docx> --from-storyboard \"{path}\" --require-review",
        "```",
    ])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if open_preview:
        import webbrowser

        webbrowser.open(preview_path.resolve().as_uri())
    return out
