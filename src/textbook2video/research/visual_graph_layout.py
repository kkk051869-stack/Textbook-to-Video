"""Topology-preserving placement and label clearance for small teaching graphs."""

from __future__ import annotations

import math


def overlaps(a, b) -> bool:
    return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]


def intersection(a, b, c, d, *, inclusive=False):
    """Return proper segment intersection (never shared endpoints)."""
    dx, dy, ex, ey = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    denominator = dx * ey - dy * ex
    if abs(denominator) < 1e-8:
        return None
    cx, cy = c[0] - a[0], c[1] - a[1]
    t, u = (cx * ey - cy * ex) / denominator, (cx * dy - cy * dx) / denominator
    inside = (
        -1e-6 <= t <= 1 + 1e-6 and -1e-6 <= u <= 1 + 1e-6
        if inclusive
        else 1e-6 < t < 1 - 1e-6 and 1e-6 < u < 1 - 1e-6
    )
    if inside:
        return a[0] + t * dx, a[1] + t * dy
    return None


def line_hits_box(a, b, box) -> bool:
    """Liang-Barsky clipping, including a line entirely inside the box."""
    left, top, width, height = box
    low, high = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in (
        (-dx, a[0] - left),
        (dx, left + width - a[0]),
        (-dy, a[1] - top),
        (dy, top + height - a[1]),
    ):
        if abs(p) < 1e-8:
            if q < 0:
                return False
        elif p < 0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
    return low <= high


def network_positions(nodes: list[dict], edges: list[dict], *, dimensions=None) -> dict:
    """Choose layout by geometry, never infer or add a semantic relationship."""
    ids = [n["id"] for n in nodes]
    degree = {ident: sum(ident in (e["source"], e["target"]) for e in edges) for ident in ids}
    incoming = {
        ident: sum(e["target"] == ident and e.get("directed", False) for e in edges)
        for ident in ids
    }

    def place(order, center):
        positions = {center: (800.0, 340.0)} if center is not None else {}
        for i, ident in enumerate(order):
            angle = -math.pi / 2 + math.tau * i / len(order)
            positions[ident] = (800 + 570 * math.cos(angle), 340 + 245 * math.sin(angle))
        return positions

    def score(positions):
        boxes = {}
        for ident, (x, y) in positions.items():
            width, height = (dimensions or {}).get(ident, (220, 165))
            boxes[ident] = x - width / 2, y - height / 2, width, height
        overlap = sum(overlaps(boxes[a], boxes[b]) for i, a in enumerate(ids) for b in ids[i + 1 :])
        blocked = sum(
            line_hits_box(positions[e["source"]], positions[e["target"]], box)
            for e in edges
            for ident, box in boxes.items()
            if ident not in (e["source"], e["target"])
        )
        crossings = sum(
            intersection(
                positions[e["source"]],
                positions[e["target"]],
                positions[f["source"]],
                positions[f["target"]],
            )
            is not None
            for i, e in enumerate(edges)
            for f in edges[i + 1 :]
            if not {e["source"], e["target"]} & {f["source"], f["target"]}
        )
        length = sum(math.dist(positions[e["source"]], positions[e["target"]]) for e in edges)
        return overlap, blocked, crossings, round(length, 3)

    best_positions, best_score = None, None
    centers = sorted(
        (
            ident
            for ident in ids
            if degree[ident] >= 3
            and (
                incoming[ident] == degree[ident]
                or degree[ident] > max(degree[other] for other in ids if other != ident)
            )
        ),
        key=lambda ident: (-incoming[ident], -degree[ident], ids.index(ident)),
    )
    for center in [None, *centers]:
        order = [ident for ident in ids if ident != center]
        current = place(order, center)
        value = score(current)
        # Bounded deterministic adjacent/local swaps, at most 4*28 per candidate.
        for _ in range(4):
            candidate_order, candidate_positions, candidate_score = order, current, value
            for a in range(len(order)):
                for b in range(a + 1, len(order)):
                    trial = order[:]
                    trial[a], trial[b] = trial[b], trial[a]
                    placed = place(trial, center)
                    trial_score = score(placed)
                    if trial_score < candidate_score:
                        candidate_order = trial
                        candidate_positions, candidate_score = placed, trial_score
            if candidate_score >= value:
                break
            order, current, value = candidate_order, candidate_positions, candidate_score
        if best_score is None or value < best_score:
            best_positions, best_score = current, value
    if best_score[0] or best_score[1]:
        raise ValueError("network edges/nodes cannot fit clearly; split into related panels")
    return best_positions


def layered_positions(
    nodes: list[dict], edges: list[dict], ranks: dict, *, dimensions=None,
    direction="horizontal",
) -> dict:
    """Barycentric sweeps keep explicit parent/child lanes together."""
    depth = max(ranks.values()) + 1
    if direction == "wrapped":
        if depth != len(nodes) or len(edges) != len(nodes) - 1:
            raise ValueError("wrapped layout requires one explicit linear chain")
        ordered = sorted(nodes, key=lambda node: ranks[node["id"]])
        columns = 2 if len(nodes) <= 4 else 3
        rows = math.ceil(len(nodes) / columns)
        widths = [(dimensions or {}).get(node["id"], (310, 165))[0] for node in ordered]
        row_heights = [max((dimensions or {}).get(node["id"], (310, 165))[1]
                           for node in ordered[start:start + columns])
                       for start in range(0, len(nodes), columns)]
        gap = (640 - sum(row_heights)) / max(1, rows - 1)
        width = max(widths)
        if gap < 50 or columns * width + (columns - 1) * 50 > 1520:
            raise ValueError("wrapped graph cannot fit readable nodes; split into panels")
        result, top = {}, 20
        for row, height in enumerate(row_heights):
            for col, node in enumerate(ordered[row * columns:(row + 1) * columns]):
                lane = col if row % 2 == 0 else columns - col - 1
                x = 40 + width / 2 + lane * (1520 - width) / (columns - 1)
                result[node["id"]] = (x, top + height / 2)
            top += height + gap
        return result
    if depth > 4:
        raise ValueError("more than four relationship stages; split into panels")
    layers = [[n["id"] for n in nodes if ranks[n["id"]] == rank] for rank in range(depth)]
    if any(len(layer) > 3 for layer in layers):
        raise ValueError("more than three nodes in a layer; split into panels")
    for _ in range(4):
        for forward in (True, False):
            order = {ident: i for layer in layers for i, ident in enumerate(layer)}
            for rank in range(1, depth) if forward else range(depth - 2, -1, -1):
                original = {ident: i for i, ident in enumerate(layers[rank])}

                def barycenter(ident):
                    neighbors = [
                        e["source"] if forward else e["target"]
                        for e in edges
                        if (e["target"] if forward else e["source"]) == ident
                    ]
                    value = (
                        sum(order[n] for n in neighbors) / len(neighbors)
                        if neighbors
                        else original[ident]
                    )
                    return value, original[ident]

                layers[rank].sort(key=barycenter)
                order.update({ident: i for i, ident in enumerate(layers[rank])})
    if direction == "vertical":
        heights = [max((dimensions or {}).get(ident, (310, 165))[1]
                       for ident in layer) for layer in layers]
        gap = (640 - sum(heights)) / max(1, depth - 1)
        if gap < 50 or (depth == 1 and heights[0] > 640):
            raise ValueError("vertical graph cannot fit readable nodes; split into panels")
        result, top = {}, 20
        for layer, height in zip(layers, heights, strict=True):
            for i, ident in enumerate(layer):
                result[ident] = (1600 * (i + 1) / (len(layer) + 1), top + height / 2)
            top += height + gap
        return result
    max_width = max((dimensions or {}).get(n["id"], (310, 165))[0] for n in nodes)
    left = max(230, 40 + max_width / 2)
    return {
        ident: (left + rank * (1600 - 2 * left) / max(1, depth - 1),
                340 + (i - (len(layer) - 1) / 2) * 190)
        for rank, layer in enumerate(layers)
        for i, ident in enumerate(layer)
    }


def label_box(start, end, width, height, *, node_boxes, occupied, other_lines):
    """Keep label close to its own edge and away from all unrelated edges."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    candidates = []
    for fraction in (0.5, 0.35, 0.65, 0.22, 0.78):
        anchor = start[0] + fraction * dx, start[1] + fraction * dy
        for offset in (0, 36, -36, 65, -65, 95, -95, 140, -140, 190, -190, 245, -245):
            cx, cy = anchor[0] + offset * nx, anchor[1] + offset * ny
            box = cx - width / 2, cy - height / 2, width, height
            if (
                box[0] < 10
                or box[1] < 10
                or box[0] + width > 1590
                or box[1] + height > 670
                or any(overlaps(box, b) for b in [*node_boxes, *occupied])
                or any(
                    line_hits_box(a, b, (box[0] - 1, box[1] - 1, width + 2, height + 2))
                    for a, b in other_lines
                )
            ):
                continue
            candidates.append((abs(offset) + abs(fraction - 0.5) * 160, box, anchor))
    if not candidates:
        raise ValueError("edge labels cannot fit without collisions; split visual")
    _, box, anchor = min(candidates, key=lambda item: item[0])
    return box, anchor


def bridge_route(start, end, previous_lines) -> tuple[str, list]:
    """An unavoidable crossing is an overpass, not a new junction or edge."""
    length = math.dist(start, end)
    ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
    distances = sorted(
        math.dist(start, point)
        for a, b in previous_lines
        if (point := intersection(start, end, a, b)) is not None
    )
    commands = [f"M{start[0]:g},{start[1]:g}"]
    samples = [start]
    last = -100
    for distance in distances:
        if distance < 24 or distance > length - 24 or distance - last < 28:
            continue
        x, y = start[0] + distance * ux, start[1] + distance * uy
        commands.append(
            f"L{x - 10 * ux:g},{y - 10 * uy:g} "
            f"Q{x - 18 * uy:g},{y + 18 * ux:g} {x + 10 * ux:g},{y + 10 * uy:g}"
        )
        before, control, after = (
            (x - 10 * ux, y - 10 * uy),
            (x - 18 * uy, y + 18 * ux),
            (x + 10 * ux, y + 10 * uy),
        )
        samples.append(before)
        for step in range(1, 17):
            t = step / 16
            samples.append(
                tuple(
                    (1 - t) ** 2 * before[i] + 2 * (1 - t) * t * control[i] + t * t * after[i]
                    for i in (0, 1)
                )
            )
        last = distance
    commands.append(f"L{end[0]:g},{end[1]:g}")
    samples.append(end)
    return " ".join(commands), samples


def bridge_path(start, end, previous_lines) -> str:
    return bridge_route(start, end, previous_lines)[0]


def route_edge(source, target, boxes: dict, previous_lines: list) -> list:
    """Keep a clear straight edge, otherwise search bounded exterior lanes."""
    a, b = boxes[source], boxes[target]

    def ports(box):
        x, y, w, h = box
        return [(x + w / 2, y), (x + w / 2, y + h), (x, y + h / 2), (x + w, y + h / 2)]

    ax, ay = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
    dx, dy = bx - ax, by - ay
    t = min(a[2] / 2 / max(abs(dx), 0.001), a[3] / 2 / max(abs(dy), 0.001))
    u = min(b[2] / 2 / max(abs(dx), 0.001), b[3] / 2 / max(abs(dy), 0.001))
    straight = [(ax + dx * t, ay + dy * t), (bx - dx * u, by - dy * u)]
    obstacles = [(x + 0.5, y + 0.5, w - 1, h - 1) for x, y, w, h in boxes.values()]

    def clear(points):
        return all(
            not line_hits_box(s, e, box) for s, e in zip(points, points[1:]) for box in obstacles
        )

    if clear(straight):
        return straight
    y_lanes = {
        22.0,
        658.0,
        *(y - 24 for x, y, w, h in boxes.values()),
        *(y + h + 24 for x, y, w, h in boxes.values()),
    }
    x_lanes = {
        22.0,
        1578.0,
        *(x - 24 for x, y, w, h in boxes.values()),
        *(x + w + 24 for x, y, w, h in boxes.values()),
    }
    candidates = []
    for start in ports(a):
        for end in ports(b):
            trials = [[start, (start[0], y), (end[0], y), end] for y in y_lanes if 12 < y < 668]
            trials += [[start, (x, start[1]), (x, end[1]), end] for x in x_lanes if 12 < x < 1588]
            for points in trials:
                points = [p for i, p in enumerate(points) if not i or p != points[i - 1]]
                if not clear(points):
                    continue
                crossings = sum(
                    intersection(s, e, p, q) is not None
                    for s, e in zip(points, points[1:])
                    for p, q in previous_lines
                )
                cost = sum(math.dist(s, e) for s, e in zip(points, points[1:]))
                candidates.append((crossings * 500 + cost + len(points) * 40, points))
    if not candidates:
        raise ValueError("edge cannot avoid unrelated nodes; split visual")
    return min(candidates, key=lambda candidate: (candidate[0], candidate[1]))[1]
