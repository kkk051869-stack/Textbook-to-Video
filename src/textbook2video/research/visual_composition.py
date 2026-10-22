"""Render validated panel groups without shrinking labels below readable size."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import mimetypes
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path


def execution_assets(directory: Path) -> list[dict]:
    composed = directory / "composition_assets.json"
    path = composed if composed.exists() else directory / "compiled/visual_assets.json"
    return json.loads(path.read_text(encoding="utf-8"))["assets"]


def render_composition(directory: Path, plan: dict, *, page_plan: dict | None) -> list[dict]:
    """Create self-contained SVGs for pairs; keep original assets for single pages."""
    assets = json.loads(
        (directory / "compiled/visual_assets.json").read_text(encoding="utf-8")
    )["assets"]
    failed = [a["id"] for a in assets if not a.get("filename") and a["spec"]["kind"] != "none"]
    if failed:
        raise ValueError(
            f"visual generation failed for panels {failed}; cannot omit planned panels"
        )
    lookup = {asset["id"]: asset for asset in assets}
    ordered = [lookup[ident] for group in plan["pages"] for ident in group]
    if len(ordered) != len(assets) or len({a["id"] for a in ordered}) != len(assets):
        raise ValueError("composition must include every generated asset exactly once")
    if plan["axis"] == "single":
        if ordered != assets:
            with (directory / "composition_assets.json").open("x", encoding="utf-8") as stream:
                json.dump({"assets": ordered}, stream, ensure_ascii=False, indent=2)
        return ordered
    # The current full-width production primary cannot share an axis with body
    # supports. Never trust an LLM's free-space boolean over the actual plan.
    if page_plan and page_plan.get("support_element_ids"):
        raise ValueError(
            "paired visuals require an empty body axis; split pages or remove supports"
        )
    selected = ordered
    if len(selected) != len(assets) or any(not a.get("filename") for a in selected):
        raise ValueError("composition must include every generated asset, with no absent images")
    width, height, gap = 1600, 680, 24
    horizontal = plan["axis"] == "horizontal"
    box_w = (width - gap) / 2 if horizontal else width
    box_h = height if horizontal else (height - gap) / 2
    pieces, members = [], []
    for index, asset in enumerate(selected):
        path = directory / "compiled/assets" / asset["filename"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise ValueError("composition input asset hash drift")
        x, y = (index * (box_w + gap), 0) if horizontal else (0, index * (box_h + gap))
        if path.suffix.lower() == ".svg":
            root = ET.fromstring(data)
            view = [float(v) for v in root.attrib["viewBox"].replace(",", " ").split()]
            scale = min(box_w / view[2], box_h / view[3])
            # 1200x510 is the actual primary surface in the narrow course viewport.
            for text in root.iter("{http://www.w3.org/2000/svg}text"):
                size = text.get("font-size")
                if size is None:
                    match = re.search(r"font-size\s*:\s*([\d.]+)", text.get("style", ""))
                    size = match[1] if match else None
                if size is None or float(size.removesuffix("px")) * scale * 0.74 < 16:
                    raise ValueError("paired diagram labels would be too small; use separate pages")
        else:
            import fitz

            try:
                image = fitz.Pixmap(data)
                native_w, native_h = image.width, image.height
            except Exception as exc:
                raise ValueError("composition image cannot be decoded") from exc
            scale = min(box_w / native_w, box_h / native_h)
            actual = sorted((native_w * scale * 0.74, native_h * scale * 0.74))
            if actual[0] < 220 or actual[1] < 440:
                raise ValueError("paired image would become a thumbnail; use separate pages")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        pieces.append(
            f'<image data-visual-id="{html.escape(asset["id"], quote=True)}" '
            f'x="{x}" y="{y}" width="{box_w}" height="{box_h}" '
            f'preserveAspectRatio="xMidYMid meet" href="data:{mime};base64,{encoded}"/>'
        )
        members.append({"id": asset["id"], "sha256": asset["sha256"]})
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'role="img"><title>组合教学视觉</title>' + "".join(pieces) + "</svg>"
    ).encode("utf-8")
    ident = "composed-" + hashlib.sha256(svg).hexdigest()[:16]
    filename = f"{ident}.svg"
    with (directory / "compiled/assets" / filename).open("xb") as stream:
        stream.write(svg)
    spec = deepcopy(selected[0]["spec"])
    spec.update(
        id=ident,
        kind="composition",
        member_visual_ids=[a["id"] for a in selected],
        title=" / ".join(a["spec"]["title"] for a in selected),
        narration_span="".join(a["spec"].get("narration_span", "") for a in selected),
    )
    record = {
        "id": ident,
        "filename": filename,
        "sha256": hashlib.sha256(svg).hexdigest(),
        "spec": spec,
        "members": members,
        "axis": plan["axis"],
        "status": "COMPOSED_PENDING_REVIEW",
    }
    with (directory / "composition_assets.json").open("x", encoding="utf-8") as stream:
        json.dump({"assets": [record]}, stream, ensure_ascii=False, indent=2)
    return [record]
