"""Tests of tld.sysml.model: name resolution, the model checks and the fixture corpus."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tld.sysml.model import build
from tld.sysml.types import Finding, ModelError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sysml"
VALID = sorted((FIXTURES / "valid").glob("*.sysml"))
INVALID = sorted((FIXTURES / "invalid").glob("*.sysml"))
LIMIT_FILE = "sysml/model"


def _f(rel: str, line: int, message: str) -> Finding:
    return Finding(f"sysml/model/{rel}", line, message)


def _build_one(text: str, rel: str = "m.sysml"):
    return build({rel: text})


def test_fixture_corpus_counts() -> None:
    assert [p.name for p in VALID] == [
        "composition.sysml", "connect.sysml", "cross_package.sysml", "minimal.sysml", "ports.sysml"]
    assert len(VALID) == 5
    assert len(INVALID) == 7


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_fixture_builds_alone(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "/*" not in text.replace("doc /*", "")  # only doc block comments
    _, findings = build({path.name: text})
    assert findings == []


def test_valid_fixtures_build_together() -> None:
    model, findings = build({p.name: p.read_text(encoding="utf-8") for p in VALID})
    assert findings == []
    tops = [e.name for e in model.elements if e.kind == "package" and not e.owner]
    assert sorted(tops) == ["Composition", "Connect", "CrossPackage", "Minimal", "Ports"]


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_invalid_fixture_gives_exactly_its_expectation(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"// expect: (\d+): (.*)\n", text)
    assert m
    _, findings = build({path.name: text})
    assert findings == [Finding(f"sysml/model/{path.name}", int(m.group(1)), m.group(2))]


def test_connect_fixture_model() -> None:
    text = (FIXTURES / "valid" / "connect.sysml").read_text(encoding="utf-8")
    model, findings = build({"connect.sysml": text})
    assert findings == []
    assert {k: v.kind for k, v in model.index.items()} == {
        "Connect": "package",
        "Connect::Link": "port def",
        "Connect::Producer": "part def",
        "Connect::Producer::tx": "port",
        "Connect::Consumer": "part def",
        "Connect::Consumer::inp": "port",
        "Connect::Pipeline": "part def",
        "Connect::Pipeline::src": "part",
        "Connect::Pipeline::dst": "part",
        "Connect::Pipeline::connect(src.tx-dst.inp)": "connect",
    }
    assert model.types == {
        "Connect::Producer::tx": "Connect::Link",
        "Connect::Consumer::inp": "Connect::Link",
        "Connect::Pipeline::src": "Connect::Producer",
        "Connect::Pipeline::dst": "Connect::Consumer",
    }
    assert model.targets == {
        "Connect::Pipeline::connect(src.tx-dst.inp)": ("Connect::Producer", "Connect::Consumer")}


def test_cross_package_fixture_model() -> None:
    text = (FIXTURES / "valid" / "cross_package.sysml").read_text(encoding="utf-8")
    model, findings = build({"cross_package.sysml": text})
    assert findings == []
    assert {k: v.kind for k, v in model.index.items()} == {
        "CrossPackage": "package",
        "CrossPackage::Core": "package",
        "CrossPackage::Core::Engine": "part def",
        "CrossPackage::Core::Inner": "package",
        "CrossPackage::Core::Inner::Helper": "part def",
        "CrossPackage::Core::Inner::Helper::owner": "part",
        "CrossPackage::Shell": "package",
        "CrossPackage::Shell::Cli": "part def",
        "CrossPackage::Shell::Cli::engine": "part",
        "CrossPackage::Shell::dependency(Cli->Core::Engine)": "dependency",
        "CrossPackage::Shell::dependency(Core::Inner::Helper->Core::Engine)": "dependency",
    }
    assert model.types == {
        "CrossPackage::Core::Inner::Helper::owner": "CrossPackage::Core::Engine",
        "CrossPackage::Shell::Cli::engine": "CrossPackage::Core::Engine",
    }
    assert model.targets == {
        "CrossPackage::Shell::dependency(Cli->Core::Engine)": (
            "CrossPackage::Shell::Cli", "CrossPackage::Core::Engine"),
        "CrossPackage::Shell::dependency(Core::Inner::Helper->Core::Engine)": (
            "CrossPackage::Core::Inner::Helper", "CrossPackage::Core::Engine"),
    }


# -- tests written as text instead of files --------------------------------------------------------

def test_connect_no_port() -> None:
    text = (
        "package C {\n"            # 1
        "    port def L;\n"        # 2
        "    part def A {\n"       # 3
        "        doc /* A. */\n"   # 4
        "        port o : L;\n"    # 5
        "    }\n"                  # 6
        "    part def D {\n"       # 7
        "        doc /* D. */\n"   # 8
        "        part a : A;\n"    # 9
        "        part b : A;\n"    # 10
        "        connect a.o to b.zz;\n"  # 11
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert findings == [_f("m.sysml", 11, "connect: 'b' has no port 'zz'")]


def test_connect_ends_must_be_parts_of_the_owner_not_ports_or_outsiders() -> None:
    text = (
        "package C {\n"
        "    port def L;\n"
        "    part def A {\n"
        "        doc /* A. */\n"
        "        port o : L;\n"
        "    }\n"
        "    part def D {\n"
        "        doc /* D. */\n"
        "        part a : A;\n"
        "        connect a.o to o.o;\n"   # 10: `o` is not a part of D
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert findings == [_f("m.sysml", 10, "connect: 'o' is not a part of 'C::D'")]


def test_sibling_unqualified() -> None:
    text = (
        "package A {\n"
        "    part def X {\n"
        "        doc /* X. */\n"
        "    }\n"
        "}\n"
        "package B {\n"
        "    part def Y {\n"
        "        doc /* Y. */\n"
        "        part x : X;\n"       # 9
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert findings == [_f("m.sysml", 9, "unknown name 'X'")]


def test_qualified_reference_with_missing_later_segment_does_not_fall_back() -> None:
    text = (
        "package A {\n"
        "    part def X {\n"
        "        doc /* X. */\n"
        "    }\n"
        "}\n"
        "package B {\n"
        "    package A {\n"
        "    }\n"
        "    part def Y {\n"
        "        doc /* Y. */\n"
        "        part x : A::X;\n"    # B::A is found first, B::A::X does not exist
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert findings == [_f("m.sysml", 11, "unknown name 'A::X'")]


def test_inner_name_wins_over_outer_name() -> None:
    text = (
        "package Outer {\n"
        "    part def X {\n"
        "        doc /* Outer X. */\n"
        "    }\n"
        "    package In {\n"
        "        part def X {\n"
        "            doc /* Inner X. */\n"
        "        }\n"
        "        part def U {\n"
        "            doc /* U. */\n"
        "            part x : X;\n"
        "        }\n"
        "    }\n"
        "    part def V {\n"
        "        doc /* V. */\n"
        "        part x : X;\n"
        "    }\n"
        "}\n"
    )
    model, findings = _build_one(text)
    assert findings == []
    assert model.types == {
        "Outer::In::U::x": "Outer::In::X",
        "Outer::V::x": "Outer::X",
    }


def test_wrong_kind_names_every_kind() -> None:
    text = (
        "package P {\n"
        "    part def A {\n"
        "        doc /* A. */\n"
        "        part self : A;\n"
        "        part bad1 : P;\n"            # 5 package
        "        part bad2 : self;\n"         # 6 part
        "        port bad3 : A;\n"            # 7 part def
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert findings == [
        _f("m.sysml", 5, "'P' is a package; a part def is needed"),
        _f("m.sysml", 6, "'self' is a part; a part def is needed"),
        _f("m.sysml", 7, "'A' is a part def; a port def is needed"),
    ]


def test_port_reference_kind_message() -> None:
    text = (
        "package P {\n"
        "    port def L;\n"
        "    part def A {\n"
        "        doc /* A. */\n"
        "        port o : L;\n"
        "        part x : o;\n"      # 6: a port is not a part def
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert findings == [_f("m.sysml", 6, "'o' is a port; a part def is needed")]


def test_too_many_elements() -> None:
    body = "".join(f"    part def P{i} {{ doc /* d. */ }}\n" for i in range(299))
    text = "package Big {\n" + body + "}\n"
    # `doc /* d. */` on one line with braces: part def P0 { doc /* d. */ }
    model, findings = _build_one(text)
    assert findings == []
    assert len(model.elements) == 300
    body = "".join(f"    part def P{i} {{ doc /* d. */ }}\n" for i in range(300))
    model, findings = _build_one("package Big {\n" + body + "}\n")
    assert findings == [Finding(LIMIT_FILE, 0, "too many elements (limit 300)")]
    assert len(model.elements) == 301


def _relations_text(count: int, parts: int = 2) -> str:
    defs = "".join(f"    part def P{i} {{ doc /* d. */ }}\n" for i in range(parts))
    deps = "".join("    dependency from P0 to P1;\n" for _ in range(count))
    return "package R {\n" + defs + deps + "}\n"


def test_relation_limit() -> None:
    model, findings = _build_one(_relations_text(600))
    assert findings == []
    assert len(model.targets) == 600
    _, findings = _build_one(_relations_text(601))
    assert findings == [Finding(LIMIT_FILE, 0, "too many relations (limit 600)")]


def test_element_limit_wins_over_relation_limit() -> None:
    _, findings = _build_one(_relations_text(601, parts=300))
    assert findings == [Finding(LIMIT_FILE, 0, "too many elements (limit 300)")]


def test_limit_finding_hides_other_model_findings() -> None:
    text = _relations_text(601, parts=2) + "package Q {\n    part def NoDoc {\n    }\n}\n"
    _, findings = _build_one(text)
    assert findings == [Finding(LIMIT_FILE, 0, "too many relations (limit 600)")]


def test_duplicate_across_files_is_reported_on_the_second() -> None:
    one = "package Same {\n    part def A {\n        doc /* A. */\n    }\n}\n"
    two = "package Same {\n    part def B {\n        doc /* B. */\n    }\n}\n"
    model, findings = build({"a.sysml": one, "b.sysml": two})
    assert findings == [_f("b.sysml", 1, "duplicate name 'Same'")]
    assert model.index["Same"].file == "sysml/model/a.sysml"


def test_duplicate_usage_names() -> None:
    text = (
        "package P {\n"
        "    part def A {\n"
        "        doc /* A. */\n"
        "    }\n"
        "    part def B {\n"
        "        doc /* B. */\n"
        "        part x : A;\n"
        "        part x : A;\n"      # 8
        "    }\n"
        "}\n"
    )
    model, findings = _build_one(text)
    assert findings == [_f("m.sysml", 8, "duplicate name 'P::B::x'")]
    assert list(model.types) == ["P::B::x"]


def test_syntax_error_in_one_file_hides_model_checks_of_the_others() -> None:
    bad = "package Bad {\n    part def A {\n"
    nodoc = "package NoDoc {\n    part def A {\n    }\n}\n"
    model, findings = build({"a.sysml": bad, "b.sysml": nodoc})
    assert findings == [_f("a.sysml", 3, "unexpected 'end of file' (expected '}')")]
    assert "NoDoc::A" in model.index  # elements of the clean file are still returned
    assert model.types == {} and model.targets == {}


def test_findings_are_sorted_by_file_line_message() -> None:
    one = (
        "package A {\n"
        "    part def X {\n"
        "        doc /* X. */\n"
        "        part u : Zed;\n"      # 4
        "        part t : Alpha;\n"    # 5
        "    }\n"
        "}\n"
    )
    two = "package B {\n    part def Y {\n    }\n}\n"
    _, findings = build({"z.sysml": two, "a.sysml": one})
    assert findings == [
        _f("a.sysml", 4, "unknown name 'Zed'"),
        _f("a.sysml", 5, "unknown name 'Alpha'"),
        _f("z.sysml", 2, "part def 'B::Y' needs a doc"),
    ]
    # Same line: ordered by message.
    same = "package S {\n    part def X {\n        doc /* X. */\n        part q : Q; part p : P;\n    }\n}\n"
    _, findings = build({"s.sysml": same})
    assert findings == [
        _f("s.sysml", 4, "unknown name 'P'"),
        _f("s.sysml", 4, "unknown name 'Q'"),
    ]


def test_names_argument_gives_the_file_names() -> None:
    text = "package N {\n    part def A {\n    }\n}\n"
    _, findings = build({"a.sysml": text, "b.sysml": text.replace("package N", "package M")},
                        {"a.sysml": "sysml/changes/x/model/a.sysml"})
    assert findings == [
        Finding("sysml/changes/x/model/a.sysml", 2, "part def 'N::A' needs a doc"),
        Finding("sysml/model/b.sysml", 2, "part def 'M::A' needs a doc"),
    ]


def test_files_are_parsed_in_sorted_order_whatever_the_dict_order() -> None:
    a = "package A {\n    part def X {\n        doc /* X. */\n    }\n}\n"
    b = "package B {\n    part def Y {\n        doc /* Y. */\n    }\n}\n"
    m1, _ = build({"a.sysml": a, "b.sysml": b})
    m2, _ = build({"b.sysml": b, "a.sysml": a})
    assert m1.elements == m2.elements
    assert list(m1.index) == list(m2.index)


def test_dependency_to_unknown_and_wrong_kind_ends() -> None:
    text = (
        "package P {\n"
        "    part def A {\n"
        "        doc /* A. */\n"
        "    }\n"
        "    dependency from A to Nope;\n"    # 5
        "    dependency from P to A;\n"       # 6
        "}\n"
    )
    model, findings = _build_one(text)
    assert findings == [
        _f("m.sysml", 5, "unknown name 'Nope'"),
        _f("m.sysml", 6, "'P' is a package; a part def is needed"),
    ]
    assert model.targets == {}


def test_empty_model() -> None:
    model, findings = build({})
    assert findings == []
    assert model.elements == () and model.index == {}


# -- hostile input -----------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", ["A.sysml", "a/../b.sysml", "/a.sysml", "a.txt", "a\n.sysml", "a b.sysml"])
def test_invalid_relpath_is_a_model_error(rel: str) -> None:
    with pytest.raises(ModelError, match="invalid file"):
        build({rel: "package P {\n}\n"})


def test_too_many_files_and_too_large_input_are_model_errors() -> None:
    with pytest.raises(ModelError, match="more than 50 model files"):
        build({f"f{i}.sysml": "" for i in range(51)})
    with pytest.raises(ModelError, match=r"sysml/model/big.sysml is longer than 100000 bytes"):
        build({"big.sysml": "// " + "x" * 100000})
    chunk = "// " + "x" * 90000 + "\n"
    with pytest.raises(ModelError, match="the model is larger than 1000000 bytes"):
        build({f"f{i}.sysml": chunk for i in range(12)})


def test_long_reference_is_bounded_in_the_message() -> None:
    ref = "::".join(["Seg"] * 120)  # 119 * 2 + 360 characters
    text = (
        "package P {\n"
        "    part def A {\n"
        "        doc /* A. */\n"
        f"        part x : {ref};\n"
        "    }\n"
        "}\n"
    )
    _, findings = _build_one(text)
    assert len(findings) == 1
    assert findings[0].message == "unknown name '" + ref[:197] + "...'"


def test_hostile_text_returns_findings_not_exceptions() -> None:
    for text in ["\x00", "package", "package P {", "part def", "}" * 500, "package P {\n" * 50,
                 "package ‮ {}", "/* x */", "package P { part def A { connect a.b to c.d; } }"]:
        _, findings = build({"m.sysml": text})
        assert len(findings) >= 1
        assert all(isinstance(f, Finding) for f in findings)
