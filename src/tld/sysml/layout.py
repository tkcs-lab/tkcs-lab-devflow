"""Layout 1 of the architecture picture: integer geometry for a checked model of tld's SysML subset.

Pure and deterministic: no clock, no sets in the iteration order, integer coordinates only, no recursion (a model
with cycles or self-references is laid out like any other; an edge from a box to itself is dropped). The input
is a `tld.sysml.model.Model`, bounded to 300 elements and 600 relations by the checks that built it.
The drawing itself is `tld.sysml.svg`; this module only decides where things go (docs/guides/sysml.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from tld.sysml.model import Model

LAYOUT_VERSION = 1
BOX_W = 224
HEAD_H = 28
LINE_H = 16
PAD = 8
GAP_X = 48
GAP_Y = 40
COLS = 3
FRAME_PAD = 16
FRAME_HEAD = 28
MARGIN = 24
CHAR_W = 7
MAX_DETAIL_BOXES = 60
MAX_DETAIL_EDGES = 150
MAX_PORT_LINES = 6
FIT_MAX = 30
FIT_KEEP = 27
PACKAGE_BOX_H = HEAD_H + LINE_H + PAD
FRAME_W = 2 * FRAME_PAD + COLS * BOX_W + (COLS - 1) * GAP_X
CANVAS_W = FRAME_W + 2 * MARGIN


@dataclass(frozen=True)
class Text:
    x: int
    y: int
    value: str


@dataclass(frozen=True)
class Box:
    """A rectangle with its texts: the header first, then the lines."""

    x: int
    y: int
    w: int
    h: int
    texts: tuple[Text, ...]


@dataclass(frozen=True)
class Frame:
    x: int
    y: int
    w: int
    h: int
    title: str


@dataclass(frozen=True)
class Edge:
    """A line from (x1, y1) to (x2, y2); `label` is "" or `x<n>`; `head` is the polygon of the arrowhead or
    the diamond as x, y, x, y ... (empty for a connect)."""

    kind: str
    x1: int
    y1: int
    x2: int
    y2: int
    label: str
    head: tuple[int, ...]


@dataclass(frozen=True)
class Layout:
    """`counts` is (part defs, packages that own a part def, dependency statements, connect statements)."""

    view: str
    width: int
    height: int
    frames: tuple[Frame, ...]
    boxes: tuple[Box, ...]
    edges: tuple[Edge, ...]
    counts: tuple[int, int, int, int]


def fit(text: str) -> str:
    """The text, or its first 27 characters plus `...` when it is longer than 30."""
    return text if len(text) <= FIT_MAX else text[:FIT_KEEP] + "..."


def _box_text_height(lines: int) -> int:
    return HEAD_H + LINE_H * lines + PAD


def _rect_cut(cx: float, cy: float, hw: float, hh: float, dx: float, dy: float) -> tuple[float, float]:
    """The point where the ray from the centre (cx, cy) in direction (dx, dy) leaves the rectangle."""
    ts = []
    if dx:
        ts.append(hw / abs(dx))
    if dy:
        ts.append(hh / abs(dy))
    t = min(ts) if ts else 0.0
    return cx + dx * t, cy + dy * t


def _edge(kind: str, count: int, src: tuple[int, int, int, int], dst: tuple[int, int, int, int]) -> Edge:
    sx, sy = src[0] + src[2] / 2, src[1] + src[3] / 2
    tx, ty = dst[0] + dst[2] / 2, dst[1] + dst[3] / 2
    dx, dy = tx - sx, ty - sy
    length = (dx * dx + dy * dy) ** 0.5
    ux, uy = (dx / length, dy / length) if length else (1.0, 0.0)
    nx, ny = -uy, ux
    p1 = _rect_cut(sx, sy, src[2] / 2, src[3] / 2, dx, dy)
    p2 = _rect_cut(tx, ty, dst[2] / 2, dst[3] / 2, -dx, -dy)
    head: tuple[int, ...] = ()
    if kind == "dependency":
        bx, by = p2[0] - 10 * ux, p2[1] - 10 * uy
        pts = [p2, (bx + 5 * nx, by + 5 * ny), (bx - 5 * nx, by - 5 * ny)]
        head = tuple(round(v) for p in pts for v in p)
    elif kind == "composition":
        x, y = p1
        pts = [p1, (x + 5 * ux + 5 * nx, y + 5 * uy + 5 * ny), (x + 10 * ux, y + 10 * uy),
               (x + 5 * ux - 5 * nx, y + 5 * uy - 5 * ny)]
        head = tuple(round(v) for p in pts for v in p)
    return Edge(kind, round(p1[0]), round(p1[1]), round(p2[0]), round(p2[1]),
                f"x{count}" if count > 1 else "", head)


def _relations(model: Model, part_defs: set[str]) -> list[tuple[str, str, str]]:
    """Every dependency, connect and composition between part defs as (kind, source, target), one per
    statement, a connect's pair sorted. Elements the checks did not record (findings) are skipped."""
    rels: list[tuple[str, str, str]] = []
    for el in model.elements:
        if model.index.get(el.qname) is not el:
            continue
        if el.kind in ("dependency", "connect"):
            ends = model.targets.get(el.qname)
            if ends is None or len(ends) != 2 or ends[0] not in part_defs or ends[1] not in part_defs:
                continue
            if el.kind == "dependency":
                rels.append(("dependency", ends[0], ends[1]))
            else:
                a, b = sorted(ends)
                rels.append(("connect", a, b))
        elif el.kind == "part":
            target = model.types.get(el.qname)
            if target is not None and target in part_defs and el.owner in part_defs:
                rels.append(("composition", el.owner, target))
    return rels


def _aggregate(rels: list[tuple[str, str, str]]) -> list[tuple[str, str, str, int]]:
    counts: dict[tuple[str, str, str], int] = {}
    for rel in rels:
        if rel[1] != rel[2]:
            counts[rel] = counts.get(rel, 0) + 1
    return [(k, s, t, n) for (k, s, t), n in sorted(counts.items())]


def layout(model: Model) -> Layout:
    """Layout 1 of `model` (3.5 of the plan): detail view up to 60 part defs and 150 aggregated edges, else
    the package view."""
    part_def_els = [e for e in model.elements if e.kind == "part def" and model.index.get(e.qname) is e]
    part_defs = {e.qname for e in part_def_els}
    ports: dict[str, list[tuple[str, str]]] = {}
    for el in model.elements:
        if el.kind == "port" and model.index.get(el.qname) is el:
            ports.setdefault(el.owner, []).append((el.name, el.type_ref or ""))
    packages: list[str] = []
    for el in part_def_els:
        if el.owner not in packages:
            packages.append(el.owner)
    rels = _relations(model, part_defs)
    edges = _aggregate(rels)
    counts = (len(part_def_els), len(packages),
              sum(1 for e in model.elements if e.kind == "dependency"),
              sum(1 for e in model.elements if e.kind == "connect"))
    if len(part_def_els) <= MAX_DETAIL_BOXES and len(edges) <= MAX_DETAIL_EDGES:
        return _detail(part_def_els, packages, ports, edges, counts)
    return _package_view(part_def_els, packages, rels, counts)


def _detail(part_def_els, packages, ports, edges, counts) -> Layout:
    frames: list[Frame] = []
    boxes: list[Box] = []
    rects: dict[str, tuple[int, int, int, int]] = {}
    y = MARGIN
    for pkg in packages:
        members = [e for e in part_def_els if e.owner == pkg]
        heights: list[int] = []
        rows = [members[i:i + COLS] for i in range(0, len(members), COLS)]
        shaped = []
        for row in rows:
            row_boxes = []
            for el in row:
                plist = ports.get(el.qname, [])
                lines = [fit(f"> {n} : {t}") for n, t in plist[:MAX_PORT_LINES]]
                if len(plist) > MAX_PORT_LINES:
                    lines.append(f"+{len(plist) - MAX_PORT_LINES} more")
                row_boxes.append((el, lines))
            shaped.append(row_boxes)
            heights.append(max(_box_text_height(len(lines)) for _, lines in row_boxes))
        frame_h = FRAME_HEAD + sum(heights) + (len(rows) - 1) * GAP_Y + FRAME_PAD
        frames.append(Frame(MARGIN, y, FRAME_W, frame_h, fit(pkg)))
        row_y = y + FRAME_HEAD
        for row_boxes, row_h in zip(shaped, heights):
            for col, (el, lines) in enumerate(row_boxes):
                bx = MARGIN + FRAME_PAD + col * (BOX_W + GAP_X)
                texts = [Text(bx + PAD, row_y + 19, fit(el.name))]
                texts += [Text(bx + PAD, row_y + HEAD_H + LINE_H * i + 12, line) for i, line in enumerate(lines)]
                bh = _box_text_height(len(lines))
                boxes.append(Box(bx, row_y, BOX_W, bh, tuple(texts)))
                rects[el.qname] = (bx, row_y, BOX_W, bh)
            row_y += row_h + GAP_Y
        y += frame_h + GAP_Y
    height = 2 * MARGIN + (y - GAP_Y - MARGIN if frames else 0)
    out = tuple(_edge(k, n, rects[s], rects[t]) for k, s, t, n in edges)
    return Layout("detail", CANVAS_W, height, tuple(frames), tuple(boxes), out, counts)


def _package_view(part_def_els, packages, rels, counts) -> Layout:
    owner = {e.qname: e.owner for e in part_def_els}
    sizes = {p: sum(1 for e in part_def_els if e.owner == p) for p in packages}
    rects: dict[str, tuple[int, int, int, int]] = {}
    boxes: list[Box] = []
    for i, pkg in enumerate(packages):
        col, row = i % COLS, i // COLS
        bx = MARGIN + FRAME_PAD + col * (BOX_W + GAP_X)
        by = MARGIN + row * (PACKAGE_BOX_H + GAP_Y)
        texts = (Text(bx + PAD, by + 19, fit(pkg)), Text(bx + PAD, by + HEAD_H + 12, f"{sizes[pkg]} part defs"))
        boxes.append(Box(bx, by, BOX_W, PACKAGE_BOX_H, texts))
        rects[pkg] = (bx, by, BOX_W, PACKAGE_BOX_H)
    mapped = []
    for kind, s, t in rels:
        ps, pt = owner[s], owner[t]
        if kind == "connect":
            ps, pt = sorted((ps, pt))
        mapped.append((kind, ps, pt))
    rows = (len(packages) + COLS - 1) // COLS
    height = 2 * MARGIN + rows * PACKAGE_BOX_H + max(rows - 1, 0) * GAP_Y
    out = tuple(_edge(k, n, rects[s], rects[t]) for k, s, t, n in _aggregate(mapped))
    return Layout("package", CANVAS_W, height, (), tuple(boxes), out, counts)
