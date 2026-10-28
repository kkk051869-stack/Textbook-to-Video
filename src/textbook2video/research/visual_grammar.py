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

from textbook2video.research.exact_source_excerpts import exact_evidence
from textbook2video.research.relationship_visuals import _wrap
from textbook2video.research.visual_graph_layout import (
    GRAPH_CONTENT_HEIGHT,
    bridge_route,
    dag_grid_positions,
    intersection,
    label_box,
    layered_positions,
    network_positions,
    overlaps,
    route_edge,
)
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
    exact_evidence(item.get("evidence"), source)


def validate_visual(spec: dict, source: str | None = None) -> None:
    if spec.get("schema_version") != GRAMMAR_VERSION or spec.get("kind") not in KINDS:
        raise ValueError("unsupported visual grammar version or kind")
    _text(spec.get("title"), "title", 64)
    _text(spec.get("teaching_goal"), "teaching_goal", 300)
    kind = spec["kind"]
    direction = spec.get("layout_direction", "horizontal")
    if direction not in {"horizontal", "vertical", "wrapped", "auto"}:
        raise ValueError("layout_direction must be horizontal, vertical, wrapped or auto")
    if "layout_direction" in spec and kind not in {
        "flow", "causal", "timeline", "hierarchy", "part_whole",
    }:
        raise ValueError("layout_direction is only supported by layered graph kinds")
    if "text_scale" in spec and (
        kind not in GRAPH_KINDS | {"comparison"}
        or type(spec["text_scale"]) not in (int, float)
        or spec["text_scale"] not in (1, 1.25, 1.5)
    ):
        raise ValueError("graph text_scale must be 1, 1.25 or 1.5; never shrink type")
    if kind in GRAPH_KINDS or kind == "comparison":
        nodes, edges = spec.get("nodes"), spec.get("edges", [])
        if not isinstance(nodes, list):
            raise ValueError(f"visual {spec.get('id')}: nodes must be a list")
        if len(nodes) < 2:
            raise ValueError(
                f"visual {spec.get('id')}: node count {len(nodes)} is below minimum 2"
            )
        if len(nodes) > 8:
            node_ids = [node.get("id") for node in nodes if isinstance(node, dict)]
            raise ValueError(
                f"visual {spec.get('id')}: node count {len(nodes)} exceeds maximum 8; "
                f"split this panel. node_ids={node_ids}"
            )
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
            raise ValueError(
                "every graph node must participate in an explicit relationship; "
                f"unconnected IDs={sorted(ids - {v for pair in pairs for v in pair})}. "
                "Add only source-supported edges, never invent links to satisfy validation."
            )
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


def render_visual(
    spec: dict,
    *,
    theme_id: str = "dark-blue-academic",
    _auto_layout=None,
    _auto_width=None,
    _equalize=True,
) -> str:
    validate_visual(spec)
    if spec.get("layout_direction") == "auto" and _auto_layout is None:
        errors = []
        four_nodes = len(spec.get("nodes", [])) == 4
        for equalize in ((True, False) if four_nodes else (False,)):
            for width in (310, 360, 420, 480, 600):
                layouts = (("horizontal", "grid2", "grid3", "vertical") if four_nodes
                           else ("horizontal", "grid3", "grid2", "vertical"))
                for layout in layouts:
                    try:
                        return render_visual(
                            spec, theme_id=theme_id, _auto_layout=layout, _auto_width=width,
                            _equalize=equalize,
                        )
                    except ValueError as error:
                        if str(error) not in errors:
                            errors.append(str(error))
        raise ValueError(
            "auto geometry could not fit unchanged nodes/edges at readable type; "
            "split panels or shorten redundant display wording. " + "; ".join(errors[:3])
        )
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
        ranks = (
            _ranks(nodes, edges)
            if kind
            in {
                "flow",
                "causal",
                "timeline",
                "hierarchy",
                "part_whole",
            }
            else None
        )
        chain = (
            kind in {"flow", "causal", "timeline"}
            and ranks is not None
            and len(set(ranks.values())) == len(nodes)
            and len(edges) == len(nodes) - 1
        )
        direction = _auto_layout or spec.get(
            "layout_direction", "wrapped" if chain and len(nodes) > 3 else "horizontal"
        )
        scale = spec.get("text_scale", (1.5 if len(nodes) <= 6 else 1.25) if chain else 1)
        vertical = direction == "vertical"
        label_size, detail_size = 29 * scale, 24 * scale
        padding = 20 * scale
        dimensions = {}
        automatic_height = spec.get("layout_direction") == "auto" and _auto_layout is not None
        height_budget = (GRAPH_CONTENT_HEIGHT if automatic_height
                         else (330 if kind == "comparison" else 165) * scale)
        for node in nodes:
            width = (_auto_width or (600 if kind == "comparison" or vertical else 310)) * scale
            if kind in {"network", "cycle"}:
                width = next(
                    (w * scale for w in (240, 260, 280, 300, 320)
                     if len(_wrap(node["label"], (w - 40) / 30)) <= 1
                     and len(_wrap(node.get("detail", ""), (w - 40) / 24)) <= 1),
                    320 * scale,
                )
            label_lines = _wrap(node["label"], (width - 2 * padding) / (30 * scale))
            detail_lines = _wrap(node.get("detail", ""), (width - 2 * padding) / detail_size)
            height = max(80 * scale, scale * (42 + 38 * len(label_lines)
                                              + 31 * len(detail_lines)))
            if height > height_budget:
                raise ValueError(
                    f"node text needs a separate panel; do not shrink fonts; "
                    f"visual={spec['id']}, node={node['id']}, label={node['label']!r}, "
                    f"detail={node.get('detail', '')!r}; label_lines={len(label_lines)}, "
                    f"detail_lines={len(detail_lines)}, required_height={height:.1f}, "
                    f"maximum_height={height_budget:.1f}. "
                    "Shorten redundant wording or use additional narration-partitioned panels; "
                    "retain all source-supported spoken facts."
                )
            dimensions[node["id"]] = width, height
        if automatic_height and chain and len(nodes) == 4 and _equalize:
            # Equal cards keep a short chain visually aligned without changing
            # its text, font or topology. Candidate capacity is still checked.
            common_height = max(height for _, height in dimensions.values())
            dimensions = {ident: (width, common_height)
                          for ident, (width, _) in dimensions.items()}
        positions = {}
        if kind == "network":
            positions = network_positions(nodes, edges, dimensions=dimensions)
        elif kind == "cycle":
            by_id = {node["id"]: node for node in nodes}
            successor = {edge["source"]: edge["target"] for edge in edges}
            ordered = [nodes[0]]
            while len(ordered) < len(nodes):
                ordered.append(by_id[successor[ordered[-1]["id"]]])
            for i, node in enumerate(ordered):
                angle = -math.pi / 2 + math.tau * i / len(nodes)
                positions[node["id"]] = (800 + 570 * math.cos(angle), 340 + 245 * math.sin(angle))
        elif kind == "comparison":
            positions = {n["id"]: (420 + i * 760, 330) for i, n in enumerate(nodes)}
        elif direction in {'grid2', 'grid3'}:
            positions = dag_grid_positions(nodes, ranks, dimensions, columns=int(direction[-1]))
        else:
            positions = layered_positions(
                nodes, edges, ranks, dimensions=dimensions,
                direction=direction,
                adaptive_height=automatic_height,
            )
        boxes = {}
        for node in nodes:
            width, height = dimensions[node["id"]]
            x, y = positions[node["id"]]
            boxes[node["id"]] = (x - width / 2, y - height / 2, width, height)

        node_boxes = list(boxes.values())
        if any(x < 10 or y < 10 or x + w > 1590 or y + h > 670
               for x, y, w, h in node_boxes):
            raise ValueError("graph presentation exceeds canvas; change direction or split panel")
        if any(overlaps(a, b) for i, a in enumerate(node_boxes) for b in node_boxes[i + 1 :]):
            raise ValueError("node rectangles overlap; split visual or shorten details")
        routes, path_data, previous_lines = [], [], []
        for edge in edges:
            points = route_edge(edge["source"], edge["target"], boxes, previous_lines)
            commands, samples = [], []
            for start, end in zip(points, points[1:]):
                path, segment_samples = bridge_route(start, end, previous_lines)
                commands.append(path if not commands else "L" + path[1:])
                samples.extend(segment_samples if not samples else segment_samples[1:])
            routes.append(list(zip(samples, samples[1:])))
            previous_lines.extend(routes[-1])
            path_data.append(" ".join(commands))
        for index, edge in enumerate(edges):
            arrow = edge.get("directed", kind not in {"network", "part_whole", "hierarchy"})
            marker = ' marker-end="url(#grammar-arrow)"' if arrow else ""
            # A transparent mask cuts the lower edge at the ACTUAL upper curve,
            # rather than painting a fake background or merely moving a crossing.
            crossings = [
                point for lower_start, lower_end in routes[index]
                for upper in routes[index+1:] for upper_start, upper_end in upper
                if (point := intersection(
                    lower_start, lower_end, upper_start, upper_end, inclusive=True))
                is not None
                and not (
                    min(math.dist(point, routes[index][0][0]),
                        math.dist(point, routes[index][-1][1])) < 8
                    and min(math.dist(point, upper[0][0]), math.dist(point, upper[-1][1])) < 8
                )
            ]
            mask = ""
            if crossings:
                ident = f"edge-gap-{index}"
                parts.append(
                    f'<defs><mask id="{ident}" maskUnits="userSpaceOnUse" '
                    'x="0" y="0" width="1600" height="680">'
                    '<rect width="1600" height="680" fill="white"/>'
                    + "".join(f'<circle cx="{x:g}" cy="{y:g}" r="7" fill="black"/>'
                              for x, y in crossings) + '</mask></defs>'
                )
                mask = f' mask="url(#{ident})"'
            parts.append(
                f'<path data-edge="{html.escape(edge["source"])}:{html.escape(edge["target"])}" '
                f'd="{path_data[index]}" fill="none" '
                f'stroke="{secondary}" stroke-width="3"{marker}{mask}/>'
            )
        occupied_labels = []
        for index, edge in enumerate(edges):
            if edge.get("label"):
                start, end = max(routes[index], key=lambda segment: math.dist(*segment))
                label_lines = _wrap(edge["label"], 7)
                label_height = (30 * len(label_lines) + 12) * scale
                label_width = 200 * scale
                free, anchor = label_box(
                    start, end, label_width, label_height,
                    node_boxes=node_boxes, occupied=occupied_labels,
                    other_lines=[segment for i, route in enumerate(routes) if i != index
                                 for segment in route],
                )
                occupied_labels.append(free)
                cx, cy = free[0] + free[2] / 2, free[1] + free[3] / 2
                if math.dist(anchor, (cx, cy)) > 10:
                    parts.append(
                        f'<path d="M{anchor[0]:g},{anchor[1]:g} L{cx:g},{cy:g}" '
                        f'stroke="{secondary}" stroke-width="1" stroke-dasharray="3 4"/>'
                    )
                parts.append(
                    f'<g data-edge-label="{edge["source"]}:{edge["target"]}">'
                )
                rect(*free, card, card)
                text(free[0] + label_width / 2, free[1] + 27 * scale,
                     edge["label"], 23 * scale, accent, "middle", 7)
                parts.append("</g>")
        for node in nodes:
            x, y, w, h = boxes[node["id"]]
            parts.append(f'<g data-node-id="{node["id"]}">')
            rect(x, y, w, h, stroke=accent if node.get("accent") else secondary)
            if node.get("detail"):
                cursor = y + 38 * scale
                cursor += text(x + padding, cursor, node["label"], label_size,
                               max_units=(w - 2 * padding) / (30 * scale))
                text(x + padding, cursor + 5 * scale, node["detail"], detail_size,
                     dim, max_units=(w - 2 * padding) / detail_size)
            else:
                lines = len(_wrap(node["label"], (w - 2 * padding) / (30 * scale)))
                baseline = y + (h - lines * label_size * 1.3) / 2 + label_size
                text(x + w / 2, baseline, node["label"], label_size, anchor="middle",
                     max_units=(w - 2 * padding) / (30 * scale))
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
        f'data-renderer="{GRAMMAR_VERSION}" data-theme="{html.escape(theme_id)}" '
        f'data-auto-layout="{_auto_layout or "not-requested"}">'
        f"<title>{html.escape(spec['title'])}</title>"
        '<defs><marker id="grammar-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        f'<path d="M1,1 L9,5 L1,9" fill="none" stroke="{secondary}" stroke-width="1.5"/>'
        "</marker></defs><style>text{font-family:Microsoft YaHei,PingFang SC,sans-serif;"
        "white-space:pre}</style>" + "".join(parts) + "</svg>"
    )
