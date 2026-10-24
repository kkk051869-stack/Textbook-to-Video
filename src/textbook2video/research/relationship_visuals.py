"""Theme-aware relationship diagrams: model supplies semantics, code lays out.

This is an additive VisualSpec dialect. Existing flat SVG specifications retain
their original renderer. Output is an asset without a duplicate page heading.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from textbook2video.themes import load_theme

RELATIONSHIP_VERSION = "teaching-relationship-v1"
LAYOUTS = {"peer_network", "split_merge", "one_way"}

PLANNER_RULES = """For a precise relationship use kind=relationship with a diagram object.
diagram={version:"teaching-relationship-v1",layout:"peer_network|split_merge|one_way",
columns:["short heading","short heading","short heading"],
nodes:[{id:"safe-id",column:0,label:"short label",detail:"optional short explanation",
value:"optional displayed amount with unit",accent:false,evidence:"exact source excerpt"}],
edges:[{source:"node-id",target:"node-id",label:"optional short label",
evidence:"exact source excerpt supporting THIS relationship"}],
constraint:"optional limitation or example assumption",
constraint_evidence:"exact source excerpt"}.
Use exactly three columns. one_way has EXACTLY ONE node per column (3 nodes total).
split_merge has exactly one middle node and 1-3 inputs/outputs. peer_network has 1-3 per column.
No duplicate IDs or duplicate edges.
Every node needs an exact nonempty evidence excerpt from source text. Do not add facts.
Every edge also needs its own exact evidence (or source_ref when source_units are supplied).
Edges MUST go from column 0 to 1 or 1 to 2, never backwards or skipping columns.
peer_network may also have same-column edges
between peers in column 1, drawn without arrowheads. Explicitly supply every intended edge.
split_merge shows inputs, process, outputs: preserve payment AND change as separate outputs.
one_way shows input, transformation, output; use constraint for a supported reverse limitation.
peer_network shows input, participating peers, synchronized copies.
Never invent a central controller.
constraint itself must be an exact source excerpt, or be empty with empty constraint_evidence.
Never add fees, equations, assumptions or external facts absent from source_text.
Focus on teaching_goal's main relationship; do not combine it with adjacent subtopics.
For irreversibility, choose one_way and show data, hash computation, hash value.
Do not attribute a field stored in a block to a participant or give peers invented roles.
Put amounts only in value, not repeated in label; labels describe roles.
Keep labels under 18 Chinese characters and details under 28. Do not write SVG, CSS or HTML.
If the source cannot support such a diagram, do not invent relationships to fill the template.
For backwards edges, other same-column edges, or a process with more than three stages,
choose a general flow/network kind with top-level nodes/edges instead of forcing this component.
"""


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _field(value: Any, name: str, limit: int, *, optional: bool = False) -> str:
    if value is None and optional:
        return ""
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise ValueError(f"relationship {name} must be text")
    if len(value) > limit:
        raise ValueError(f"relationship {name} exceeds content budget; split the visual")
    return value.strip()


def validate_relationship(spec: dict[str, Any], source_text: str | None = None) -> None:
    """Reject missing relationships, unsafe IDs and excess content, not truncate."""
    diagram = spec.get("diagram")
    if not isinstance(diagram, dict) or diagram.get("version") != RELATIONSHIP_VERSION:
        raise ValueError("relationship requires a versioned diagram")
    if diagram.get("layout") not in LAYOUTS:
        raise ValueError("unsupported relationship layout")
    if spec.get("title") is not None:
        _field(spec["title"], "title", 32)
    columns, nodes, edges = (diagram.get(k) for k in ("columns", "nodes", "edges"))
    if not isinstance(columns, list) or len(columns) != 3:
        raise ValueError("relationship requires exactly three columns")
    for label in columns:
        _field(label, "column heading", 20)
    if not isinstance(nodes, list) or not 3 <= len(nodes) <= 9:
        raise ValueError("relationship requires 3-9 nodes")
    counts = [0, 0, 0]
    ids: dict[str, int] = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("relationship node must be an object")
        node_id, column = node.get("id"), node.get("column")
        if not isinstance(node_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", node_id):
            raise ValueError("relationship node id must be a safe identifier")
        if node_id in ids:
            raise ValueError("duplicate relationship node id")
        if type(column) is not int or column not in range(3):
            raise ValueError("relationship node column must be 0, 1 or 2")
        ids[node_id] = column
        counts[column] += 1
        _field(node.get("label"), "label", 36)
        _field(node.get("detail"), "detail", 56, optional=True)
        _field(node.get("value"), "value", 18, optional=True)
        quote = _field(node.get("evidence"), "evidence", 1000)
        if source_text is not None and quote not in source_text:
            raise ValueError("relationship evidence must be an exact source excerpt")
        if "accent" in node and type(node["accent"]) is not bool:
            raise ValueError("relationship accent must be boolean")
    if any(count < 1 or count > 3 for count in counts):
        raise ValueError("relationship allows 1-3 nodes per column; split the visual")
    if diagram["layout"] in {"split_merge", "one_way"} and counts[1] != 1:
        raise ValueError("transformation layout requires one middle node")
    if diagram["layout"] == "one_way" and counts != [1, 1, 1]:
        raise ValueError("one_way requires one node per column")
    if not isinstance(edges, list) or not 2 <= len(edges) <= 18:
        raise ValueError("relationship requires 2-18 explicit edges")
    seen: set[tuple[str, str]] = set()
    connected: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("relationship edge must be an object")
        a, b = edge.get("source"), edge.get("target")
        if not isinstance(a, str) or not isinstance(b, str) or a not in ids or b not in ids:
            raise ValueError("relationship edge target is missing")
        same = ids[a] == ids[b] == 1 and diagram["layout"] == "peer_network"
        if a == b or (not same and ids[b] - ids[a] != 1):
            raise ValueError("relationship edge must connect adjacent columns or peers")
        pair = tuple(sorted((a, b))) if same else (a, b)
        if pair in seen:
            raise ValueError("duplicate relationship edge")
        seen.add(pair)
        connected.update((a, b))
        _field(edge.get("label"), "edge label", 12, optional=True)
    if connected != set(ids):
        raise ValueError("relationship contains an unconnected node")
    constraint = _field(diagram.get("constraint"), "constraint", 60, optional=True)
    if constraint:
        quote = _field(diagram.get("constraint_evidence"), "constraint evidence", 1000)
        if source_text is not None and quote not in source_text:
            raise ValueError("relationship constraint evidence must be an exact source excerpt")
        if source_text is not None and constraint not in source_text:
            raise ValueError("relationship constraint must be an exact source excerpt")


def _wrap(value: str, max_units: float) -> list[str]:
    """Conservative CJK-aware wrapping without shrinking the font."""
    lines, current, width = [], "", 0.0
    for char in value:
        # Only known narrow ASCII characters receive the compact estimate.
        # W/M and arbitrary fallback glyphs must not be treated like digits.
        narrow = char.isascii() and (
            char.isdigit() or char in " abcdefghijklnopqrstuvxyz.,:;+-/()"
        )
        units = 0.62 if narrow and unicodedata.east_asian_width(char) not in "WF" else 1.0
        if char == "\n" or (current and width + units > max_units):
            lines.append(current)
            current, width = "", 0.0
        if char != "\n":
            current += char
            width += units
    if current:
        lines.append(current)
    return lines


def render_relationship(spec: dict[str, Any], *, theme_id: str = "dark-blue-academic") -> str:
    """Render a reusable 1600x650 diagram, including measurable text nodes."""
    validate_relationship(spec)
    diagram = spec["diagram"]
    visual = load_theme(theme_id)["visual"]
    fg, dim, cyan, gold = (visual[k] for k in ("text_color", "text_dim", "secondary", "accent"))
    body: list[str] = []

    def text(x: float, y: float, value: str, size: int, color: str, *, weight: int = 400) -> str:
        return (
            f'<text x="{x:g}" y="{y:g}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}">{_escape(value)}</text>'
        )

    boxes: dict[str, tuple[float, float, float, float]] = {}
    node_content: dict[str, tuple[list[str], list[str], list[str]]] = {}
    groups = [[n for n in diagram["nodes"] if n["column"] == col] for col in range(3)]
    # The usable canvas ends at y=540, before the constraint footer at y=565.
    # Two amount cards can need more than 380px without any actual overflow.
    available_height = (
        420 if diagram["layout"] == "one_way" and diagram.get("constraint") else 460
    )
    for column, nodes in enumerate(groups):
        x = 80 + column * 540
        body.append(text(x, 44, f"0{column + 1}", 23, gold, weight=700))
        for row, heading in enumerate(_wrap(diagram["columns"][column], 12)):
            body.append(text(x + 45, 44 + row * 29, heading, 25, dim))
        heights = []
        for node in nodes:
            labels = _wrap(node["label"], 10)
            details = _wrap(node.get("detail") or "", 13)
            values = _wrap(node.get("value") or "", 6)
            if len(labels) > 3 or len(details) > 3:
                raise ValueError("relationship text exceeds node budget; split the visual")
            height = max(128, 42 + len(labels) * 32 + len(details) * 27 + 60 * len(values))
            if len(nodes) == 1:
                height = max(220, height)
            heights.append(height)
            node_content[node["id"]] = labels, details, values
        gap = 24
        total = sum(heights) + gap * (len(nodes) - 1)
        if total > available_height:
            raise ValueError(
                f"relationship column exceeds height budget; split the visual: "
                f"column={column}, nodes={[node['id'] for node in nodes]}, "
                f"required={total}, available={available_height}. "
                "Shorten repeated value units or split panels without dropping facts."
            )
        y = 80 + (available_height - total) / 2
        for node, height in zip(nodes, heights, strict=True):
            boxes[node["id"]] = (x, y, 360, height)
            y += height + gap

    # Draw connectors before cards; edges terminate at card boundaries.
    occupied_labels: list[tuple[float, float, float, float]] = []
    for edge in diagram["edges"]:
        a, b = (boxes[edge[k]] for k in ("source", "target"))
        same = a[0] == b[0]
        if same:
            # Explicit peer links use a left-side lane, never run through cards.
            sx, sy, tx, ty = a[0], a[1] + a[3] / 2, b[0], b[1] + b[3] / 2
            mid = sx - 30
            marker = ""
        else:
            sx, sy, tx, ty = a[0] + a[2], a[1] + a[3] / 2, b[0] - 8, b[1] + b[3] / 2
            mid = (sx + tx) / 2
            marker = ' marker-end="url(#relation-arrow)"'
        body.append(
            f'<path d="M{sx:g} {sy:g} H{mid:g} V{ty:g} H{tx:g}" '
            f'fill="none" stroke="{cyan}" stroke-width="3" '
            f'stroke-linejoin="round"{marker}/>'
        )
        if edge.get("label"):
            label_lines = _wrap(edge["label"], 4)
            label_x = a[0] - 145 if same else mid - 44
            label_height = 23 * len(label_lines)
            # Reserve a text rectangle in the connector corridor. Candidate
            # positions must avoid every card and earlier edge label.
            for baseline in (ty - 20, sy - 20, (sy + ty) / 2 - 20, ty + 32, sy + 32):
                candidate = (label_x, baseline - 21, 90, label_height)
                x, y, w, h = candidate
                if all(
                    x + w <= bx or x >= bx + bw or y + h <= by or y >= by + bh
                    for bx, by, bw, bh in [*boxes.values(), *occupied_labels]
                ):
                    occupied_labels.append(candidate)
                    body.append('<g data-edge-label="true">')
                    for row, line in enumerate(label_lines):
                        body.append(text(label_x, baseline + row * 23, line, 20, gold))
                    body.append("</g>")
                    break
            else:
                raise ValueError("relationship edge labels exceed layout budget")
    for node in diagram["nodes"]:
        x, y, width, height = boxes[node["id"]]
        accent = gold if node.get("accent") else cyan
        body.append(
            f'<g data-node-id="{_escape(node["id"])}">'
            f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" '
            f'rx="18" fill="{visual["card_bg"]}" stroke="{accent}" '
            'stroke-opacity=".65" stroke-width="1.5"/>'
        )
        labels, details, values = node_content[node["id"]]
        cursor = y + 39
        for line in labels:
            body.append(text(x + 26, cursor, line, 27, fg, weight=600))
            cursor += 32
        if values:
            cursor += 17
            for line in values:
                body.append(text(x + 26, cursor, line, 44, accent, weight=700))
                cursor += 52
        for line in details:
            body.append(text(x + 26, cursor, line, 23, dim))
            cursor += 27
        body.append("</g>")
    if diagram.get("constraint"):
        body.append('<g data-visual-object="constraint">')
        if diagram["layout"] == "one_way":
            left = boxes[groups[0][0]["id"]]
            right = boxes[groups[2][0]["id"]]
            body.append(
                f'<path d="M{right[0] + 180:g} {right[1] + right[3] + 14:g} '
                f'V520 H{left[0] + 180:g} V{left[1] + left[3] + 14:g}" '
                f'fill="none" stroke="{gold}" stroke-width="2.5" stroke-dasharray="8 8"/>'
                f'<path d="M788 508 L812 532 M812 508 L788 532" '
                f'fill="none" stroke="{gold}" stroke-width="4"/>'
            )
        body.append(
            f'<rect x="80" y="565" width="1440" height="64" rx="12" '
            f'fill="{visual["card_bg"]}" stroke="{gold}" stroke-opacity=".45"/>'
        )
        for index, line in enumerate(_wrap(diagram["constraint"], 52)):
            body.append(text(107, 591 + 27 * index, line, 24, gold, weight=600))
        body.append("</g>")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="650" '
        f'viewBox="0 0 1600 650" role="img" data-renderer="{RELATIONSHIP_VERSION}" '
        f'data-theme="{_escape(theme_id)}">'
        f"<title>{_escape(spec.get('title') or '教学关系图')}</title>"
        '<defs><marker id="relation-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="8" markerHeight="8" orient="auto"><path d="M1 1 L9 5 L1 9" '
        f'fill="none" stroke="{cyan}" stroke-width="1.5"/></marker></defs>'
        "<style>text{font-family:Microsoft YaHei,PingFang SC,sans-serif}</style>"
        + "".join(body)
        + "</svg>"
    )


def plan_relationship(
    source_text: str,
    *,
    model: str = "ecnu-plus",
    response_path: Path | None = None,
    teaching_goal: str = "",
    layout_hint: str | None = None,
) -> tuple[dict[str, Any], str]:
    """One bounded real model call; return raw response for provenance."""
    from textbook2video.llm.client import chat_with_system

    if layout_hint is not None and layout_hint not in LAYOUTS:
        raise ValueError("unsupported requested relationship layout")
    raw = chat_with_system(
        json.dumps(
            {
                "source_text": source_text,
                "teaching_goal": teaching_goal,
                "required_layout": layout_hint,
                "output": {
                    "kind": "relationship",
                    "title": "简短标题",
                    "diagram": "object as specified",
                },
            },
            ensure_ascii=False,
        ),
        system_prompt="You are an instructional relationship planner. Output one JSON object.\n"
        + PLANNER_RULES,
        model=model,
        temperature=0,
        max_tokens=4096,
        timeout=60,
    )
    if response_path is not None:
        with response_path.open("x", encoding="utf-8") as stream:
            stream.write(raw)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    spec = json.loads(cleaned)
    if not isinstance(spec, dict) or spec.get("kind") != "relationship":
        raise ValueError("planner did not return a relationship spec")
    validate_relationship(spec, source_text)
    if layout_hint and spec["diagram"]["layout"] != layout_hint:
        raise ValueError("planner did not follow the requested relationship layout")
    return spec, raw
