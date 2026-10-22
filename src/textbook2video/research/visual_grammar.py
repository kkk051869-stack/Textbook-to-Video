"""Source-grounded, theme-aware visual grammar for new course generation.

The old flat VisualSpec remains readable. New plans use explicit relationships,
fixed readable type sizes and bounded panels rather than inventing edges or
shrinking a growing canvas to fit a slide.
"""

from __future__ import annotations

import html
import math
import re
from typing import Any

from textbook2video.research.relationship_visuals import _wrap
from textbook2video.themes import load_theme

GRAMMAR_VERSION = "teaching-visual-v2"
GRAPH_KINDS = {"flow", "hierarchy", "network", "timeline", "cycle", "causal", "part_whole"}
KINDS = GRAPH_KINDS | {"comparison", "proportion", "chart", "table", "formula", "code"}
CATALOG = {
    "flow": "Ordered steps; explicit directed edges; split long processes into panels.",
    "hierarchy": "A rooted tree with explicit parent-child edges, not a flat word list.",
    "network": "Peer relationships; explicit edges and directed flags; no invented hub.",
    "timeline": "Chronological events; dates in labels; arrows indicate order, not causality.",
    "cycle": "A closed process; explicitly provide every edge including return edge.",
    "causal": "Only source-supported cause-effect edges; association is not causation.",
    "part_whole": "Explicit containment tree; parent edges mean membership, not sequence.",
    "comparison": "Two alternatives with the same comparison dimensions, no implicit steps.",
    "proportion": "Nonnegative numeric parts and units; preserve the source denominator.",
    "chart": "Numeric series, explicit labels/units; bar or line; no invented measurements.",
    "table": "A header row and source-supported cells; split dense matrices.",
    "formula": "Exact mathematical expression and explanation; keep line breaks.",
    "code": "Exact code with preserved indentation; no arbitrary truncation.",
    "relationship": "Existing peer_network / split_merge / one_way components.",
    "scene": "ecnu-image only when a concrete scene explains the teaching goal.",
    "none": "No explanatory visual is needed; decorative pictures are rejected.",
}


def _text(value: Any, name: str, limit: int = 160) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text within {limit} characters; split content")
    return value


def _quote(item: dict, source: str | None) -> None:
    quote = _text(item.get("evidence"), "evidence", 4000)
    if source is not None and quote not in source:
        raise ValueError("visual evidence must be an exact source excerpt")


def validate_visual(spec: dict, source: str | None = None) -> None:
    if spec.get("schema_version") != GRAMMAR_VERSION or spec.get("kind") not in KINDS:
        raise ValueError("unsupported visual grammar version or kind")
    _text(spec.get("title"), "title", 64)
    _text(spec.get("teaching_goal"), "teaching_goal", 300)
    kind = spec["kind"]
    if kind in GRAPH_KINDS or kind == "comparison":
        nodes, edges = spec.get("nodes"), spec.get("edges", [])
        if not isinstance(nodes, list) or not 2 <= len(nodes) <= 8:
            raise ValueError("a graph panel needs 2-8 nodes; split larger visuals")
        ids = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("node must be an object")
            ident = node.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ident):
                raise ValueError("node id must be a safe stable identifier")
            if ident in ids:
                raise ValueError("duplicate node id")
            ids.add(ident)
            _text(node.get("label"), "node label", 48)
            if node.get("detail"):
                _text(node["detail"], "node detail", 96)
            _quote(node, source)
        if not isinstance(edges, list) or len(edges) > 16:
            raise ValueError("too many edges; split graph")
        pairs = set()
        for edge in edges:
            a, b = edge.get("source"), edge.get("target")
            if a not in ids or b not in ids or a == b or (a, b) in pairs:
                raise ValueError("invalid or duplicate graph edge")
            pairs.add((a, b))
            if edge.get("label"):
                _text(edge["label"], "edge label", 20)
            if "directed" in edge and type(edge["directed"]) is not bool:
                raise ValueError("edge directed must be boolean")
            _quote(edge, source)
        if kind == "comparison":
            if len(nodes) != 2 or edges:
                raise ValueError("comparison requires two alternatives and no sequence edges")
        elif {v for pair in pairs for v in pair} != ids:
            raise ValueError("every graph node must participate in an explicit relationship")
        if kind in {"hierarchy", "part_whole"}:
            incoming = {i: sum(b == i for _, b in pairs) for i in ids}
            if len(pairs) != len(ids) - 1 or sum(n == 0 for n in incoming.values()) != 1:
                raise ValueError("hierarchy requires a rooted tree")
            if any(n > 1 for n in incoming.values()):
                raise ValueError("tree nodes cannot have multiple parents")
            _ranks(nodes, edges)  # Also reject disconnected cyclic components.
        if kind in {"flow", "causal", "timeline"}:
            _ranks(nodes, edges)
        if kind == "cycle":
            if len(pairs) != len(ids) or any(
                sum(a == i for a, _ in pairs) != 1 or sum(b == i for _, b in pairs) != 1
                for i in ids
            ):
                raise ValueError("cycle needs one incoming and outgoing edge per node")
            current, visited = nodes[0]["id"], set()
            while current not in visited:
                visited.add(current)
                current = next(b for a, b in pairs if a == current)
            if visited != ids:
                raise ValueError("cycle must be one connected loop")
    elif kind in {"chart", "proportion"}:
        series = spec.get("series")
        if not isinstance(series, list) or not 1 <= len(series) <= 8:
            raise ValueError("numeric panels need 1-8 source-supported values")
        _text(spec.get("unit"), "numeric unit", 32)
        if spec.get("chart_type", "bar") not in {"bar", "line"}:
            raise ValueError("chart_type must be bar or line")
        for point in series:
            _text(point.get("label"), "series label", 32)
            value = point.get("value")
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("numeric values must be finite numbers")
            if kind == "proportion" and value < 0:
                raise ValueError("parts cannot be negative")
            _quote(point, source)
        if kind == "proportion" and sum(p["value"] for p in series) <= 0:
            raise ValueError("proportion total must be positive")
    elif kind == "table":
        rows = spec.get("rows")
        if not isinstance(rows, list) or not 2 <= len(rows) <= 7:
            raise ValueError("table needs 2-7 rows including header; split larger tables")
        if not isinstance(rows[0], list) or not 1 <= len(rows[0]) <= 5:
            raise ValueError("table needs 1-5 columns")
        for row in rows:
            if not isinstance(row, list) or len(row) != len(rows[0]):
                raise ValueError("table rows must have the same column count")
            for cell in row:
                _text(cell, "table cell", 64)
        _quote(spec, source)
    else:
        _text(spec.get("content"), "content", 1800)
        _quote(spec, source)


def _ranks(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    pending = {n["id"] for n in nodes}
    ranks: dict[str, int] = {}
    while pending:
        ready = sorted(
            i for i in pending if all(e["source"] in ranks for e in edges if e["target"] == i)
        )
        if not ready:
            raise ValueError("directed layout contains a cycle")
        for i in ready:
            ranks[i] = max((ranks[e["source"]] + 1 for e in edges if e["target"] == i), default=0)
            pending.remove(i)
    return ranks


def render_visual(spec: dict, *, theme_id: str = "dark-blue-academic") -> str:
    validate_visual(spec)
    colors = load_theme(theme_id)["visual"]
    fg, dim, accent, secondary, card = (
        colors[k] for k in ("text_color", "text_dim", "accent", "secondary", "card_bg")
    )
    parts: list[str] = []

    def text(x, y, value, size=28, color=fg, anchor="start", max_units=20):
        lines = _wrap(str(value), max_units)
        for row, line in enumerate(lines):
            parts.append(
                f'<text x="{x:g}" y="{y + row * size * 1.3:g}" font-size="{size}" '
                f'text-anchor="{anchor}" fill="{color}">{html.escape(line)}</text>'
            )
        return len(lines) * size * 1.3

    def rect(x, y, w, h, fill=card, stroke=secondary):
        parts.append(
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'rx="16" fill="{fill}" stroke="{stroke}" stroke-opacity=".5"/>'
        )

    kind = spec["kind"]
    if kind in GRAPH_KINDS or kind == "comparison":
        nodes, edges = spec["nodes"], spec.get("edges", [])
        positions = {}
        if kind in {"cycle", "network"}:
            for i, node in enumerate(nodes):
                angle = -math.pi / 2 + math.tau * i / len(nodes)
                positions[node["id"]] = (800 + 570 * math.cos(angle), 340 + 245 * math.sin(angle))
        elif kind == "comparison":
            positions = {n["id"]: (420 + i * 760, 330) for i, n in enumerate(nodes)}
        else:
            ranks = _ranks(nodes, edges)
            depth = max(ranks.values()) + 1
            if depth > 4:
                raise ValueError("more than four relationship stages; split into panels")
            for rank in range(depth):
                group = [n for n in nodes if ranks[n["id"]] == rank]
                if len(group) > 3:
                    raise ValueError("more than three nodes in a layer; split into panels")
                for i, node in enumerate(group):
                    positions[node["id"]] = (
                        230 + rank * 1140 / max(1, depth - 1),
                        340 + (i - (len(group) - 1) / 2) * 190,
                    )
        boxes = {}
        for node in nodes:
            width = 600 if kind == "comparison" else (220 if kind in {"network", "cycle"} else 310)
            label_lines = _wrap(node["label"], (width - 40) / 30)
            detail_lines = _wrap(node.get("detail", ""), (width - 40) / 24)
            height = max(110, 42 + 38 * len(label_lines) + 31 * len(detail_lines))
            if height > (330 if kind == "comparison" else 165):
                raise ValueError("node text needs a separate panel; do not shrink fonts")
            x, y = positions[node["id"]]
            boxes[node["id"]] = (x - width / 2, y - height / 2, width, height)

        def intersects(a, b):
            return (
                a[0] < b[0] + b[2]
                and a[0] + a[2] > b[0]
                and a[1] < b[1] + b[3]
                and a[1] + a[3] > b[1]
            )

        node_boxes = list(boxes.values())
        if any(intersects(a, b) for i, a in enumerate(node_boxes) for b in node_boxes[i + 1 :]):
            raise ValueError("node rectangles overlap; split visual or shorten details")
        occupied_labels = []
        for edge in edges:
            a, b = boxes[edge["source"]], boxes[edge["target"]]
            ax, ay = positions[edge["source"]]
            bx, by = positions[edge["target"]]
            dx, dy = bx - ax, by - ay

            def boundary(box):
                return min(box[2] / 2 / max(abs(dx), 0.001), box[3] / 2 / max(abs(dy), 0.001))

            t, u = boundary(a), boundary(b)
            sx, sy, tx, ty = ax + dx * t, ay + dy * t, bx - dx * u, by - dy * u
            arrow = edge.get("directed", kind not in {"network", "part_whole", "hierarchy"})
            marker = ' marker-end="url(#grammar-arrow)"' if arrow else ""
            parts.append(
                f'<path data-edge="{html.escape(edge["source"])}:{html.escape(edge["target"])}" '
                f'd="M{sx:g},{sy:g} L{tx:g},{ty:g}" fill="none" '
                f'stroke="{secondary}" stroke-width="3"{marker}/>'
            )
            if edge.get("label"):
                mx, my = (sx + tx) / 2, (sy + ty) / 2
                label_lines = _wrap(edge["label"], 7)
                label_height = 30 * len(label_lines) + 12
                candidates = [
                    (mx - 100, baseline, 200, label_height)
                    for baseline in (
                        my - 32,
                        min(sy, ty) - label_height - 12,
                        max(sy, ty) + 12,
                        my - 100,
                        my + 65,
                    )
                ]
                free = next(
                    (
                        r
                        for r in candidates
                        if r[0] >= 0
                        and r[1] >= 0
                        and r[0] + r[2] <= 1600
                        and r[1] + r[3] <= 680
                        and not any(intersects(r, b) for b in node_boxes + occupied_labels)
                    ),
                    None,
                )
                if free is None:
                    raise ValueError("edge labels cannot fit without covering nodes; split visual")
                occupied_labels.append(free)
                rect(*free, card, card)
                text(free[0] + 100, free[1] + 27, edge["label"], 23, accent, "middle", 7)
        for node in nodes:
            x, y, w, h = boxes[node["id"]]
            parts.append(f'<g data-node-id="{node["id"]}">')
            rect(x, y, w, h, stroke=accent if node.get("accent") else secondary)
            cursor = y + 38
            cursor += text(x + 20, cursor, node["label"], 29, max_units=(w - 40) / 30)
            if node.get("detail"):
                text(x + 20, cursor + 5, node["detail"], 24, dim, max_units=(w - 40) / 24)
            parts.append("</g>")
    elif kind == "table":
        rows = spec["rows"]
        w, h = 1480 / len(rows[0]), 570 / len(rows)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                lines = _wrap(cell, (w - 28) / 26)
                if len(lines) * 34 > h - 20:
                    raise ValueError("table cell over budget; split table")
                rect(60 + c * w, 45 + r * h, w, h, stroke=dim)
                text(
                    74 + c * w,
                    78 + r * h,
                    cell,
                    26,
                    accent if r == 0 else fg,
                    max_units=(w - 28) / 26,
                )
    elif kind in {"chart", "proportion"}:
        series = spec["series"]
        minimum = min(0, min(p["value"] for p in series))
        maximum = max(0, max(p["value"] for p in series))
        span = maximum - minimum or 1
        zero = 530 + minimum / span * 420
        previous = None
        total = sum(p["value"] for p in series)
        for i, point in enumerate(series):
            x = 130 + i * 1360 / len(series)
            y = 530 - (point["value"] - minimum) / span * 420
            if spec.get("chart_type", "bar") == "line":
                if previous:
                    parts.append(
                        f'<path d="M{previous[0]:g},{previous[1]:g} L{x:g},{y:g}" '
                        f'stroke="{secondary}" stroke-width="4" fill="none"/>'
                    )
                parts.append(f'<circle cx="{x:g}" cy="{y:g}" r="7" fill="{accent}"/>')
                previous = x, y
            else:
                rect(x, min(zero, y), min(100, 1000 / len(series)), max(2, abs(zero - y)))
            label = f"{point['value']:g}"
            if kind == "proportion":
                label += f" ({point['value'] / total:.0%})"
            text(x, max(40, y - 18), label, 24, accent, max_units=14)
            text(x, 580, point["label"], 25, max_units=1360 / len(series) / 26)
        text(60, 650, spec["unit"], 24, dim)
    else:
        lines = spec["content"].splitlines()
        wrapped = [line for raw in lines for line in _wrap(raw, 45)]
        if len(wrapped) > 14:
            raise ValueError("code/formula needs multiple panels")
        rect(55, 35, 1490, 610)
        for i, line in enumerate(wrapped):
            text(90, 85 + i * 38, line or " ", 28, max_units=45)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="680" '
        'viewBox="0 0 1600 680" role="img" '
        f'data-renderer="{GRAMMAR_VERSION}" data-theme="{html.escape(theme_id)}">'
        f"<title>{html.escape(spec['title'])}</title>"
        '<defs><marker id="grammar-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        f'<path d="M1,1 L9,5 L1,9" fill="none" stroke="{secondary}" stroke-width="1.5"/>'
        "</marker></defs><style>text{font-family:Microsoft YaHei,PingFang SC,sans-serif;"
        "white-space:pre}</style>" + "".join(parts) + "</svg>"
    )
