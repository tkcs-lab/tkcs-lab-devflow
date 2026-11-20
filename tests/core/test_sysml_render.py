"""Tests of tld.sysml.svg and tld.sysml.markdown: allowlists, escaping, golden files, byte stability (3.5)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tld.sysml import layout as L
from tld.sysml.layout import layout
from tld.sysml.markdown import md_escape, to_markdown
from tld.sysml.markdown import layout_number as md_layout_number
from tld.sysml.model import build
from tld.sysml.svg import ATTRIBUTES, ELEMENTS, STAMP, esc, layout_number, to_svg
from tld.sysml.types import Element, ModelError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sysml"
SVG_NS = "{http://www.w3.org/2000/svg}"


def _model(text: str):
    model, findings = build({"m.sysml": text})
    assert findings == []
    return model


def _fixture(name: str):
    return _model((FIXTURES / "valid" / name).read_text(encoding="utf-8"))


def _big(n: int) -> str:
    out = ["package Big {", "    port def L;"]
    for i in range(n):
        out += [f"    part def D{i} {{", "        doc /* d */", "        port p : L;", "    }"]
    out += ["    dependency from D0 to D1;", "}"]
    return "\n".join(out)


def _check_allowlists(svg: str) -> None:
    root = ET.fromstring(svg.split("\n", 1)[1])
    for node in root.iter():
        assert node.tag.startswith(SVG_NS)
        assert node.tag[len(SVG_NS):] in ELEMENTS
        for attr in node.attrib:
            assert attr in ATTRIBUTES or attr == "xmlns"


def test_svg_uses_only_allowlisted_elements_and_attributes() -> None:
    for name in ("connect.sysml", "composition.sysml", "cross_package.sysml", "ports.sysml", "minimal.sysml"):
        _check_allowlists(to_svg(layout(_fixture(name))))
    big = layout(_model(_big(61)))
    assert big.view == "package"
    svg = to_svg(big)
    _check_allowlists(svg)
    for word in ("href", "style", "script", "foreignObject"):
        assert word not in svg


def test_svg_escapes_names_and_never_holds_doc_text() -> None:
    text = 'package P { part def A_1 { doc /* <script>&" */ } }'
    svg = to_svg(layout(_model(text)))
    assert "A_1" in svg
    assert "script" not in svg and "&amp;\"" not in svg and "doc" not in svg
    _check_allowlists(svg)


def test_svg_escapes_raw_greater_than_of_port_lines() -> None:
    svg = to_svg(layout(_fixture("connect.sysml")))
    assert ">&gt; tx : Link<" in svg
    assert "> tx" not in svg


def test_esc() -> None:
    assert esc('<a href="x">&</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;"


def test_svg_ints_only_and_line_form() -> None:
    svg = to_svg(layout(_fixture("cross_package.sysml")))
    assert svg.endswith("</svg>\n") and "\r" not in svg
    assert not re.search(r'="-?\d+\.\d', svg)
    assert svg.splitlines()[0] == STAMP


def test_package_view_label_and_dependency_style() -> None:
    svg = to_svg(layout(_model(_big(61))))
    assert 'stroke-dasharray="6 4"' not in svg  # the one dependency is inside one package: dropped
    assert "61 part defs in 1 packages" in svg
    dep = to_svg(layout(_fixture("cross_package.sysml")))
    assert 'stroke-dasharray="6 4"' in dep


def test_golden_files() -> None:
    lay = layout(_fixture("connect.sysml"))
    model = _fixture("connect.sysml")
    golden = FIXTURES / "golden"
    assert to_svg(lay) == (golden / "connect.svg").read_text(encoding="utf-8")
    assert to_markdown(model, lay) == (golden / "connect.md").read_text(encoding="utf-8")


def test_golden_changes_with_layout_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    before = to_svg(layout(_fixture("connect.sysml")))
    monkeypatch.setattr(L, "GAP_X", 60)
    assert to_svg(layout(_fixture("connect.sysml"))) != before


def test_golden_svg_matches_hand_derived_layout() -> None:
    root = ET.fromstring((FIXTURES / "golden" / "connect.svg").read_text(encoding="utf-8").split("\n", 1)[1])
    rects = [(int(r.get("x")), int(r.get("y")), int(r.get("width")), int(r.get("height")))
             for r in root.iter(f"{SVG_NS}rect")]
    assert rects == [
        (0, 0, 848, 144),  # background
        (24, 24, 800, 96),  # frame
        (40, 52, 224, 52),  # Producer
        (312, 52, 224, 52),  # Consumer
        (584, 52, 224, 36),  # Pipeline
    ]
    assert (root.get("width"), root.get("height")) == ("848", "144")


def test_md_escape_escapes_all_15_characters() -> None:
    out = md_escape("| [x](y) * _ # ! ~ & < > \\ `")
    assert out == "\\| \\[x\\]\\(y\\) \\* \\_ \\# \\! \\~ \\& \\< \\> \\\\ \\`"
    for ch in "\\`*_[]()<>#!|~&":
        assert md_escape(ch) == "\\" + ch
    assert not re.search(r"(?<!\\)\|", out)


def test_md_escape_collapses_whitespace() -> None:
    assert md_escape("  a \n\t b  ") == "a b"


def _doc_md(doc: str) -> str:
    model = _model(f"package P {{ part def A {{ doc /* {doc} */ }} }}")
    return to_markdown(model, layout(model))


def test_doc_with_link_syntax_is_rendered_inert() -> None:
    for doc, want in (
        ("javascript:alert(1)", "javascript:alert\\(1\\)"),
        ("user@example.com", "user@example.com"),
        ("[a](b)", "\\[a\\]\\(b\\)"),
    ):
        row = [ln for ln in _doc_md(doc).splitlines() if ln.startswith("| `A`")][0]
        assert row.endswith(f"|  | {want} |")
        for ch in "()[]<>":
            assert ch not in re.sub(r"\\.", "", row.split("|  | ", 1)[1])


def test_hostile_doc_cannot_break_table_or_inject_html() -> None:
    md = _doc_md("a | b `c` <script>x</script> ![i](j) # h\n\n- item")
    row = [ln for ln in md.splitlines() if ln.startswith("| `A`")][0]
    assert row.count("|") == len(re.findall(r"\\\|", row)) + 4
    assert "<script>" not in md and "`c`" not in md
    assert not [ln for ln in md.splitlines() if ln.startswith(("- ", "#", "!["))
                and ln not in ("![Architecture](architecture.svg)",) and not ln.startswith("## ")
                and ln != "# Architecture"]
    assert "!\\[i\\]" in row
    assert len([ln for ln in md.splitlines() if ln.startswith("| `A`")]) == 1


def test_package_doc_is_escaped_and_headings_hold_names_only() -> None:
    model = _model("package Q_1 { doc /* see [x](y) */ part def A { doc /* d */ } }")
    md = to_markdown(model, layout(model))
    assert "## Q\\_1" in md and "see \\[x\\]\\(y\\)" in md


def test_to_markdown_refuses_a_non_name_in_a_code_span() -> None:
    model = _model("package P { port def L; part def A { doc /* d */ port p : L; } }")
    bad = [Element(e.kind, e.name, e.qname, e.owner, "L`]( )", e.ends, e.doc, e.file, e.line)
           if e.kind == "port" else e for e in model.elements]
    model.elements = tuple(bad)
    model.index = {e.qname: e for e in bad}
    with pytest.raises(ModelError):
        to_markdown(model, layout(model))


def test_summary_lines_and_package_view_note() -> None:
    detail = _fixture("connect.sysml")
    md = to_markdown(detail, layout(detail))
    head = md.split(STAMP)[0].strip().splitlines()
    assert head[0] == "# Architecture" and len(head) == 3
    assert "3 part defs in 1 packages, 0 dependencies and 1 connections" in head[2]
    assert "The diagram shows packages only" not in md
    big = _model(_big(61))
    pv = to_markdown(big, layout(big))
    head = pv.split(STAMP)[0].strip().splitlines()
    assert len(head) == 4 and head[3] == "The diagram shows packages only; the tables list every part def."
    assert "| `D60` |" in pv  # every part def stays in the tables


def test_stamp_positions_and_layout_number() -> None:
    model = _fixture("connect.sysml")
    lay = layout(model)
    svg, md = to_svg(lay), to_markdown(model, lay)
    assert svg.splitlines()[0] == STAMP
    assert md.splitlines().index(STAMP) == 4
    assert layout_number(svg) == md_layout_number(md) == 1
    assert layout_number("no stamp here\n") is None
    assert layout_number("<!-- generated by tld ops sysml render, layout 2; do not edit -->\n") == 2
    assert layout_number("<!-- generated by tld ops sysml render, layout x; do not edit -->") is None


def test_relations_table_is_sorted_and_lists_every_distinct_edge() -> None:
    model = _fixture("cross_package.sysml")
    md = to_markdown(model, layout(model))
    rows = md.split("## Relations")[1].strip().splitlines()[2:]
    assert rows == sorted(rows, key=lambda r: tuple(c.strip() for c in r.split("|")[2:3] + r.split("|")[1:2]))
    assert "| `CrossPackage::Shell::Cli` | dependency | `CrossPackage::Core::Engine` |" in rows
    assert "| `CrossPackage::Core::Inner::Helper` | composition | `CrossPackage::Core::Engine` |" in rows


def test_nested_package_follows_its_owner() -> None:
    model = _fixture("cross_package.sysml")
    heads = [ln for ln in to_markdown(model, layout(model)).splitlines() if ln.startswith("## ")]
    assert heads == [
        "## CrossPackage", "## CrossPackage::Core", "## CrossPackage::Core::Inner", "## CrossPackage::Shell",
        "## Relations"]


def test_two_renders_are_byte_equal() -> None:
    model = _fixture("cross_package.sysml")
    a = (to_svg(layout(model)), to_markdown(model, layout(model)))
    b = (to_svg(layout(model)), to_markdown(model, layout(model)))
    assert a == b
    assert a[1].endswith("\n") and not a[1].endswith("\n\n")


def test_empty_model_renders() -> None:
    model = _model("package P { }")
    lay = layout(model)
    _check_allowlists(to_svg(lay))
    md = to_markdown(model, lay)
    assert "0 part defs in 0 packages" in md and "## Relations" in md
