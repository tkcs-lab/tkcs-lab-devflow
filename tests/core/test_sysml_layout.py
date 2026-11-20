"""Tests of tld.sysml.layout: layout 1, with literal values derived by hand from the formulas of the plan (3.5)."""
from __future__ import annotations

from pathlib import Path

from tld.sysml import layout as L
from tld.sysml.layout import Box, Edge, Frame, Layout, Text, fit, layout
from tld.sysml.model import build

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sysml" / "valid"


def _model(text: str):
    model, findings = build({"m.sysml": text})
    assert findings == []
    return model


def _fixture(name: str):
    return _model((FIXTURES / name).read_text(encoding="utf-8"))


def _defs(names: list[str], ports: dict[str, int] | None = None, pkg: str = "P") -> str:
    ports = ports or {}
    out = [f"package {pkg} {{", "    port def L;"]
    for n in names:
        out.append(f"    part def {n} {{")
        out.append("        doc /* d */")
        out += [f"        port p{i} : L;" for i in range(ports.get(n, 0))]
        out.append("    }")
    out.append("}")
    return "\n".join(out)


def test_constants() -> None:
    assert (L.LAYOUT_VERSION, L.BOX_W, L.HEAD_H, L.LINE_H, L.PAD, L.GAP_X, L.GAP_Y) == (1, 224, 28, 16, 8, 48, 40)
    assert (L.COLS, L.FRAME_PAD, L.FRAME_HEAD, L.MARGIN, L.CHAR_W) == (3, 16, 28, 24, 7)
    assert (L.MAX_DETAIL_BOXES, L.MAX_DETAIL_EDGES) == (60, 150)


def test_empty_model() -> None:
    lay = layout(_model("package P { }"))
    assert (lay.view, lay.width, lay.height) == ("detail", 848, 48)
    assert lay.frames == lay.boxes == lay.edges == ()
    assert lay.counts == (0, 0, 0, 0)


def test_fit() -> None:
    assert fit("a" * 30) == "a" * 30
    assert fit("a" * 31) == "a" * 27 + "..."
    assert fit("") == ""


def test_first_frame_and_box_geometry() -> None:
    lay = layout(_model(_defs(["A", "B", "C"], {"A": 3})))
    f = lay.frames[0]
    assert (f.x, f.y, f.w) == (24, 24, 800)
    assert f.h == 28 + 84 + 0 + 16  # one row, tallest box has 3 ports
    assert lay.height == 48 + f.h
    assert lay.width == 848
    assert [(b.x, b.y, b.w) for b in lay.boxes] == [(40, 52, 224), (312, 52, 224), (584, 52, 224)]
    assert [b.h for b in lay.boxes] == [28 + 16 * 3 + 8, 36, 36]
    assert lay.boxes[0].h == 84
    assert lay.boxes[0].texts == (
        Text(48, 71, "A"), Text(48, 92, "> p0 : L"), Text(48, 108, "> p1 : L"), Text(48, 124, "> p2 : L"))
    assert lay.boxes[1].texts == (Text(320, 71, "B"),)


def test_eight_ports_show_six_and_more() -> None:
    lay = layout(_model(_defs(["A"], {"A": 8})))
    box = lay.boxes[0]
    assert box.h == 28 + 16 * 7 + 8 == 148
    assert [t.value for t in box.texts][-2:] == ["> p5 : L", "+2 more"]
    assert len(box.texts) == 1 + 7
    assert box.texts[-1] == Text(48, 52 + 28 + 16 * 6 + 12, "+2 more")


def test_second_row_and_frame_height() -> None:
    lay = layout(_model(_defs(["A", "B", "C", "D"], {"A": 3})))
    d = lay.boxes[3]
    assert (d.x, d.y, d.h) == (40, 52 + 84 + 40, 36)
    assert lay.frames[0].h == 28 + (84 + 36) + 40 + 16 == 204
    assert lay.height == 48 + 204


def test_two_frames_stack_in_declaration_order() -> None:
    text = _defs(["A"], pkg="One") + "\n" + _defs(["B"], pkg="Two")
    lay = layout(_model(text))
    assert [(f.title, f.y, f.h) for f in lay.frames] == [("One", 24, 80), ("Two", 24 + 80 + 40, 80)]
    assert lay.boxes[1].y == 24 + 80 + 40 + 28
    assert lay.height == 48 + 80 + 80 + 40


def test_package_without_part_def_has_no_frame() -> None:
    lay = layout(_model("package Outer { package Empty { } package In { port def L; part def X { doc /* d */ } } }"))
    assert [f.title for f in lay.frames] == ["Outer::In"]
    assert lay.counts == (1, 1, 0, 0)


def test_long_names_are_fitted() -> None:
    name = "N" * 40
    lay = layout(_model(_defs([name], {name: 1}, pkg="Q" * 31)))
    assert lay.frames[0].title == "Q" * 27 + "..."
    assert lay.boxes[0].texts[0].value == "N" * 27 + "..."


def test_connect_fixture_literal_layout() -> None:
    lay = layout(_fixture("connect.sysml"))
    assert lay == Layout(
        view="detail", width=848, height=144,
        frames=(Frame(24, 24, 800, 96, "Connect"),),
        boxes=(
            Box(40, 52, 224, 52, (Text(48, 71, "Producer"), Text(48, 92, "> tx : Link"))),
            Box(312, 52, 224, 52, (Text(320, 71, "Consumer"), Text(320, 92, "> inp : Link"))),
            Box(584, 52, 224, 36, (Text(592, 71, "Pipeline"),)),
        ),
        edges=(
            Edge("composition", 584, 73, 536, 75, "", (584, 73, 579, 68, 574, 74, 579, 78)),
            Edge("composition", 584, 72, 264, 76, "", (584, 72, 579, 67, 574, 72, 579, 77)),
            Edge("connect", 312, 78, 264, 78, "", ()),
        ),
        counts=(3, 1, 0, 1),
    )


def test_composition_fixture_literal_layout() -> None:
    lay = layout(_fixture("composition.sysml"))
    assert lay == Layout(
        view="detail", width=848, height=128,
        frames=(Frame(24, 24, 800, 80, "Composition"),),
        boxes=(
            Box(40, 52, 224, 36, (Text(48, 71, "Wheel"),)),
            Box(312, 52, 224, 36, (Text(320, 71, "Axle"),)),
            Box(584, 52, 224, 36, (Text(592, 71, "Car"),)),
        ),
        edges=(
            Edge("composition", 312, 70, 264, 70, "x2", (312, 70, 307, 65, 302, 70, 307, 75)),
            Edge("composition", 584, 70, 536, 70, "x2", (584, 70, 579, 65, 574, 70, 579, 75)),
        ),
        counts=(3, 1, 0, 0),
    )


def test_dependency_arrowhead_literal() -> None:
    text = _defs(["A", "B"]).rstrip("}") + "    dependency from A to B;\n}"
    lay = layout(_model(text))
    assert lay.edges == (Edge("dependency", 264, 70, 312, 70, "", (312, 70, 302, 75, 302, 65)),)
    assert lay.counts == (2, 1, 1, 0)


def test_connect_is_symmetric() -> None:
    base = (FIXTURES / "connect.sysml").read_text(encoding="utf-8")
    flipped = base.replace("connect src.tx to dst.inp;", "connect dst.inp to src.tx;")
    assert flipped != base
    assert layout(_model(base)) == layout(_model(flipped))


def test_no_self_edges_and_cycles_are_safe() -> None:
    text = """package P {
    part def A { doc /* a */ part me : A; part b : B; }
    part def B { doc /* b */ part a : A; }
    dependency from A to A;
    dependency from A to B;
    dependency from B to A;
}"""
    lay = layout(_model(text))
    kinds = [e.kind for e in lay.edges]
    assert kinds == ["composition", "composition", "dependency", "dependency"]
    assert len(lay.edges) == 4  # A->A (part and dependency) dropped
    assert lay.counts == (2, 1, 3, 0)


def test_edge_aggregation_counts_statements() -> None:
    text = _defs(["A", "B"]).rstrip("}") + "    dependency from A to B;\n    dependency from A to B;\n    dependency from A to B;\n}"
    lay = layout(_model(text))
    assert [(e.kind, e.label) for e in lay.edges] == [("dependency", "x3")]


def test_dependency_end_lies_on_target_border() -> None:
    text = _defs(["A", "B", "C", "D"]).rstrip("}") + "    dependency from A to D;\n}"
    lay = layout(_model(text))
    (edge,) = lay.edges
    t = lay.boxes[3]
    assert t.x - 1 <= edge.x2 <= t.x + t.w + 1 and t.y - 1 <= edge.y2 <= t.y + t.h + 1
    on_border = (abs(edge.x2 - t.x) <= 1 or abs(edge.x2 - (t.x + t.w)) <= 1
                 or abs(edge.y2 - t.y) <= 1 or abs(edge.y2 - (t.y + t.h)) <= 1)
    assert on_border
    s = lay.boxes[0]
    assert s.x - 1 <= edge.x1 <= s.x + s.w + 1 and s.y - 1 <= edge.y1 <= s.y + s.h + 1
    assert len(edge.head) == 6


def _two_packages(n_a: int, n_b: int, deps: list[tuple[str, str]]) -> str:
    a = _defs([f"A{i}" for i in range(n_a)], pkg="P1")
    b = _defs([f"B{i}" for i in range(n_b)], pkg="P2")
    rel = "\n".join(f"    dependency from {s} to {t};" for s, t in deps)
    return f"{a}\n{b}\npackage R {{\n{rel}\n}}\n"


def test_package_view_boxes_and_aggregated_edges() -> None:
    deps = [("P1::A0", "P2::B0"), ("P1::A1", "P2::B1"), ("P1::A2", "P2::B0"), ("P1::A0", "P1::A1")]
    lay = layout(_model(_two_packages(31, 30, deps)))
    assert lay.view == "package"
    assert lay.frames == ()
    assert (lay.width, lay.height) == (848, 48 + 52)
    assert lay.boxes == (
        Box(40, 24, 224, 52, (Text(48, 43, "P1"), Text(48, 24 + 28 + 12, "31 part defs"))),
        Box(312, 24, 224, 52, (Text(320, 43, "P2"), Text(320, 64, "30 part defs"))),
    )
    assert lay.edges == (Edge("dependency", 264, 50, 312, 50, "x3", (312, 50, 302, 55, 302, 45)),)
    assert lay.counts == (61, 2, 4, 0)


def _many_deps(n_edges: int, n_defs: int = 60) -> str:
    half = n_defs // 2
    names = [f"A{i}" for i in range(half)] + [f"B{i}" for i in range(n_defs - half)]
    pairs = [(s, t) for s in names for t in names if s != t][:n_edges]
    def q(n: str) -> str:
        return ("P1::" if n[0] == "A" else "P2::") + n
    deps = [(q(s), q(t)) for s, t in pairs]
    return _two_packages(half, n_defs - half, deps)


def test_detail_view_at_exactly_60_part_defs_and_150_edges() -> None:
    lay = layout(_model(_many_deps(150)))
    assert lay.view == "detail"
    assert len(lay.boxes) == 60 and len(lay.edges) == 150
    assert len(lay.frames) == 2


def test_package_view_at_60_part_defs_and_151_edges() -> None:
    lay = layout(_model(_many_deps(151)))
    assert lay.view == "package"
    assert len(lay.boxes) == 2
    # sources A0, A1 (30 B targets each) and A2 (its 33 pairs end with B0..B3): 30 + 30 + 4 package-crossing ones
    assert [(e.kind, e.label) for e in lay.edges] == [("dependency", "x64")]


def test_maximum_model_is_bounded_and_deterministic() -> None:
    # 3 packages + 2 port defs + 295 part defs = 300 elements, 600 distinct dependencies: the limits of the checks.
    names = [f"A{i}" for i in range(148)] + [f"B{i}" for i in range(147)]

    def q(x: str) -> str:
        return ("P1::" if x[0] == "A" else "P2::") + x

    pairs = [(s, t) for s in names[:3] for t in names if s != t][:600]
    assert len(pairs) == 600
    model = _model(_two_packages(148, 147, [(q(s), q(t)) for s, t in pairs]))
    first = layout(model)
    assert first.view == "package"
    assert first == layout(model)
    assert first.counts == (295, 2, 600, 0)
    assert first.width == 848


def test_determinism_and_file_order() -> None:
    one = _defs(["A", "B"], pkg="One")
    two = _defs(["C"], pkg="Two")
    m1, f1 = build({"a.sysml": one, "b.sysml": two})
    m2, f2 = build({"b.sysml": two, "a.sysml": one})
    assert f1 == f2 == []
    assert layout(m1) == layout(m1)
    assert layout(m1) == layout(m2)
