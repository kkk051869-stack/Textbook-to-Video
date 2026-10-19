# ruff: noqa: E501
"""Compile teaching visual specifications into auditable SVG or image assets.

The module is deliberately independent from one lesson and from the storyboard
format.  A planner supplies a small, declarative visual specification; this
module routes it to deterministic SVG when the relationship can be expressed
precisely, or to the configured image generator for genuinely figurative
content.  Every emitted asset is accompanied by its input and SHA-256.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from textbook2video.llm.image_gen import generate_image
from textbook2video.pipeline.config import IMAGE_MODEL

VISUAL_SYNTHESIS_VERSION = "teaching-visual-synthesis-v1"
SVG_KINDS = frozenset(
    {
        "flow",
        "hierarchy",
        "network",
        "timeline",
        "cycle",
        "comparison",
        "causal",
        "part_whole",
        "proportion",
        "table",
        "chart",
        "formula",
        "code",
    }
)
IMAGE_KINDS = frozenset({"scene", "object", "historical", "person", "photo", "texture"})


def route_visual(spec: dict[str, Any]) -> str:
    """Return ``svg``, ``image`` or ``none`` for one declarative visual spec."""
    kind = str(spec.get("kind") or "").strip().lower()
    if kind in SVG_KINDS:
        return "svg"
    if kind in IMAGE_KINDS:
        return "image"
    if kind in {"none", "text"}:
        return "none"
    raise ValueError(f"unsupported teaching visual kind: {kind!r}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _svg_document(
    body: str, title: str, *, view_box: tuple[int, int, int, int]
) -> str:
    """Return a tight SVG whose title is accessibility metadata only."""
    x, y, width, height = view_box
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="{x} {y} {width} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
        f"<title>{_escape(title)}</title>"
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">'
        '<path d="M0,0 L0,6 L9,3 z" fill="#3b82f6"/></marker></defs>'
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#f8fafc"/>'
        f"{body}</svg>"
    )


def _box(
    x: int, y: int, label: Any, *, width: int = 190, height: int = 76, color: str = "#dbeafe"
) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="{color}" stroke="#2563eb" stroke-width="2"/>'
        f'<text x="{x + width // 2}" y="{y + height // 2 + 7}" text-anchor="middle" font-family="Arial,Microsoft YaHei,sans-serif" font-size="21" fill="#172554">{_escape(label)}</text>'
    )


def _items(spec: dict[str, Any]) -> list[Any]:
    values = spec.get("items") or spec.get("nodes") or []
    if not isinstance(values, list) or not values:
        raise ValueError("visual spec requires a non-empty items/nodes list")
    return values


def render_svg(spec: dict[str, Any]) -> str:
    """Render any supported deterministic teaching visual to standalone SVG."""
    kind = str(spec.get("kind") or "").lower()
    if kind not in SVG_KINDS:
        raise ValueError(f"SVG rendering does not support {kind!r}")
    title = str(spec.get("title") or spec.get("description") or kind)
    values = _items(spec)
    body: list[str] = []
    canvas_width = 1280
    bounds = (60, 270, 1160, 136)

    if kind in {"flow", "timeline", "causal"}:
        count = len(values)
        gap = max(18, (1120 - count * 190) // max(1, count - 1))
        # Seven-node flows used to place the last node at x=1328 while the
        # fixed 1280px viewBox clipped it. Grow only this layout's canvas so
        # smaller diagrams retain the original readable scale.
        if count > 5:
            gap = 18
            canvas_width = 160 + count * 190 + (count - 1) * gap
        y = 300
        for index, value in enumerate(values):
            x = 80 + index * (190 + gap)
            body.append(_box(x, y, value, color="#dcfce7" if kind == "causal" else "#dbeafe"))
            if index:
                body.append(
                    f'<line x1="{x - gap + 5}" y1="338" x2="{x - 10}" y2="338" stroke="#3b82f6" stroke-width="4" marker-end="url(#arrow)"/>'
                )
        if kind == "timeline":
            body.append(
                f'<line x1="90" y1="430" x2="{canvas_width - 90}" y2="430" stroke="#64748b" stroke-width="4"/>'
            )
            bounds = (60, 270, canvas_width - 120, 190)
        else:
            bounds = (60, 270, canvas_width - 120, 136)

    elif kind == "comparison":
        if len(values) != 2:
            raise ValueError("comparison visuals require exactly two items")
        body.extend(
            [
                _box(180, 230, values[0], width=380, height=280, color="#dbeafe"),
                _box(720, 230, values[1], width=380, height=280, color="#fee2e2"),
            ]
        )
        body.append(
            '<text x="640" y="380" text-anchor="middle" font-size="42" font-family="Arial" font-weight="700" fill="#475569">VS</text>'
        )
        bounds = (150, 200, 980, 340)

    elif kind in {"hierarchy", "part_whole"}:
        root = values[0]
        body.append(_box(545, 160, root, width=190, color="#fde68a"))
        children = values[1:]
        for index, value in enumerate(children):
            x = 80 + index * (1120 // max(1, len(children)))
            body.append(
                f'<line x1="640" y1="236" x2="{x + 95}" y2="390" stroke="#3b82f6" stroke-width="3" marker-end="url(#arrow)"/>'
            )
            body.append(_box(x, 400, value, color="#e0e7ff"))
        bounds = (55, 130, 1170, 380)

    elif kind == "network":
        positions = [(640, 260), (310, 430), (970, 430), (470, 570), (810, 570)]
        for index, value in enumerate(values):
            x, y = positions[index % len(positions)]
            if index:
                px, py = positions[(index - 1) % len(positions)]
                body.append(
                    f'<line x1="{px}" y1="{py}" x2="{x}" y2="{y}" stroke="#60a5fa" stroke-width="4"/>'
                )
            body.append(
                f'<circle cx="{x}" cy="{y}" r="58" fill="#dbeafe" stroke="#2563eb" stroke-width="3"/>'
            )
            body.append(
                f'<text x="{x}" y="{y + 7}" text-anchor="middle" font-size="19" font-family="Arial,Microsoft YaHei,sans-serif" fill="#172554">{_escape(value)}</text>'
            )
        bounds = (220, 180, 840, 470)

    elif kind == "cycle":
        positions = [(640, 190), (940, 360), (760, 570), (420, 570), (250, 360)]
        for index, value in enumerate(values):
            x, y = positions[index % len(positions)]
            nx, ny = positions[(index + 1) % len(positions)]
            body.append(_box(x - 95, y - 38, value, color="#f3e8ff"))
            body.append(
                f'<path d="M{x},{y} Q{(x + nx) // 2},{(y + ny) // 2 - 70} {nx - 25},{ny}" fill="none" stroke="#7c3aed" stroke-width="3" marker-end="url(#arrow)"/>'
            )
        bounds = (120, 120, 1040, 510)

    elif kind in {"proportion", "chart"}:
        numeric = spec.get("values") or values
        if not all(isinstance(value, (int, float)) for value in numeric):
            raise ValueError("proportion/chart visuals require numeric values")
        maximum = max(numeric) or 1
        labels = spec.get("labels") or [str(index + 1) for index in range(len(numeric))]
        for index, value in enumerate(numeric):
            height = int(360 * float(value) / maximum)
            x = 180 + index * 210
            body.append(
                f'<rect x="{x}" y="{580 - height}" width="120" height="{height}" fill="#60a5fa" rx="8"/>'
            )
            body.append(
                f'<text x="{x + 60}" y="615" text-anchor="middle" font-size="20" font-family="Arial,Microsoft YaHei,sans-serif">{_escape(labels[index])}</text>'
            )
            body.append(
                f'<text x="{x + 60}" y="{565 - height}" text-anchor="middle" font-size="18" font-family="Arial">{_escape(value)}</text>'
            )
        chart_right = 180 + (len(numeric) - 1) * 210 + 150
        bounds = (145, 175, max(210, chart_right - 145), 470)

    elif kind == "table":
        rows = spec.get("rows") or values
        if not all(isinstance(row, list) for row in rows):
            raise ValueError("table visuals require rows as a list of lists")
        columns = max(len(row) for row in rows)
        width, height = 1050 // columns, 440 // len(rows)
        for row_index, row in enumerate(rows):
            for col_index in range(columns):
                x, y = 110 + col_index * width, 160 + row_index * height
                fill = "#bfdbfe" if row_index == 0 else "#ffffff"
                body.append(
                    f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" stroke="#64748b"/>'
                )
                body.append(
                    f'<text x="{x + width // 2}" y="{y + height // 2 + 7}" text-anchor="middle" font-size="18" font-family="Arial,Microsoft YaHei,sans-serif">{_escape(row[col_index] if col_index < len(row) else "")}</text>'
                )
        bounds = (85, 135, 1100, 490)

    elif kind in {"formula", "code"}:
        text = str(spec.get("content") or values[0])
        body.append('<rect x="130" y="180" width="1020" height="350" rx="18" fill="#0f172a"/>')
        body.append(
            f'<text x="190" y="360" font-size="30" font-family="Consolas,monospace" fill="#e2e8f0">{_escape(text)}</text>'
        )
        bounds = (105, 155, 1070, 405)

    else:  # Exhaustive fallback for type checkers; kinds handled above.
        raise ValueError(f"no renderer for {kind!r}")
    return _svg_document("".join(body), title, view_box=bounds)


def compile_visuals(
    specs: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    image_generator: Callable[..., str | None] = generate_image,
    image_model: str = IMAGE_MODEL,
    revision_of: str | Path | None = None,
) -> Path:
    """Compile visual specs into a new, traceable visual-asset revision.

    Existing manifests are never replaced.  A planner (including an AI agent)
    revises a graphic by submitting a changed spec to a fresh output directory
    and may identify the prior manifest through ``revision_of``.
    """
    output = Path(output_dir)
    destination = output / "visual_assets.json"
    if destination.exists():
        raise FileExistsError(
            f"visual output already exists: {destination}; use a new output directory for a revision"
        )
    assets_dir = output / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ordinal, spec in enumerate(specs, start=1):
        if not isinstance(spec, dict):
            raise ValueError("visual specifications must be objects")
        visual_id = str(spec.get("id") or f"visual-{ordinal:03d}")
        if visual_id in seen_ids:
            raise ValueError(f"duplicate visual id: {visual_id}")
        seen_ids.add(visual_id)
        route = route_visual(spec)
        record: dict[str, Any] = {"id": visual_id, "route": route, "spec": spec}
        if route == "svg":
            data = render_svg(spec).encode("utf-8")
            filename = f"{visual_id}.svg"
            (assets_dir / filename).write_bytes(data)
            record.update(
                {"filename": filename, "sha256": _sha256(data), "status": "DETERMINISTIC_SVG"}
            )
        elif route == "image":
            prompt = str(spec.get("prompt") or spec.get("description") or "").strip()
            if not prompt:
                raise ValueError(f"image visual {visual_id} requires prompt or description")
            encoded = image_generator(prompt, model=image_model)
            if not encoded:
                record.update(
                    {"status": "IMAGE_GENERATION_FAILED", "prompt": prompt, "model": image_model}
                )
            else:
                data = base64.b64decode(encoded)
                filename = f"{visual_id}.png"
                (assets_dir / filename).write_bytes(data)
                record.update(
                    {
                        "filename": filename,
                        "sha256": _sha256(data),
                        "status": "GENERATED_PENDING_REVIEW",
                        "prompt": prompt,
                        "model": image_model,
                    }
                )
        else:
            record["status"] = "NO_VISUAL"
        records.append(record)
    manifest = {
        "schema_version": VISUAL_SYNTHESIS_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "image_model": image_model,
        "assets": records,
    }
    if revision_of is not None:
        prior = Path(revision_of)
        if not prior.is_file():
            raise FileNotFoundError(f"revision manifest does not exist: {prior}")
        manifest["revision_of"] = str(prior.resolve())
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def main(argv: list[str] | None = None) -> int:
    """Provide a JSON-in/manifest-out command interface for agent tool calls."""
    parser = argparse.ArgumentParser(description="Compile declarative teaching visuals")
    parser.add_argument("--specs", required=True, type=Path, help="JSON file containing a list or {visuals: [...]} ")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--image-model", default=IMAGE_MODEL)
    parser.add_argument("--revision-of", type=Path)
    args = parser.parse_args(argv)

    payload = json.loads(args.specs.read_text(encoding="utf-8"))
    specs = payload.get("visuals") if isinstance(payload, dict) else payload
    if not isinstance(specs, list):
        raise ValueError("spec JSON must be a list or an object with a visuals list")
    manifest_path = compile_visuals(
        specs,
        args.output_dir,
        image_model=args.image_model,
        revision_of=args.revision_of,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "manifest": str(manifest_path.resolve()),
                "schema_version": manifest["schema_version"],
                "assets": [
                    {key: asset[key] for key in ("id", "route", "status", "filename") if key in asset}
                    for asset in manifest["assets"]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


__all__ = [
    "IMAGE_KINDS",
    "SVG_KINDS",
    "VISUAL_SYNTHESIS_VERSION",
    "compile_visuals",
    "render_svg",
    "route_visual",
]


if __name__ == "__main__":
    raise SystemExit(main())
