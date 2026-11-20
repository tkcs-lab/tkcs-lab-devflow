"""Tests of the SysML subset parser (tld.sysml.parse)."""
from __future__ import annotations

import pytest

from tld.sysml.parse import parse_file
from tld.sysml.types import RESERVED, Finding

F = "sysml/model/x.sysml"


def one(text: str) -> list[Finding]:
    elements, findings = parse_file(text, F)
    assert elements == []
    assert len(findings) == 1
    return findings


def ok(text: str):
    elements, findings = parse_file(text, F)
    assert findings == []
    return elements


def err(line: int, message: str) -> list[Finding]:
    return [Finding(F, line, message)]


# -- happy path ---------------------------------------------------------------------------------

def test_empty_file_has_no_elements():
    assert ok("") == []
    assert ok("// only a comment\n") == []


def test_package_part_def_ports_and_composition_elements():
    text = (
        "package Pkg {\n"
        "  doc /* the package */\n"
        "  port def P;\n"
        "  part def A {\n"
        "    doc /* an a */\n"
        "    port outp : P;\n"
        "    part inner : B;\n"
        "  }\n"
        "  part def B { doc /* a b */ }\n"
        "}\n"
    )
    els = ok(text)
    assert [(e.kind, e.qname, e.owner, e.type_ref, e.doc, e.line) for e in els] == [
        ("package", "Pkg", "", None, "the package", 1),
        ("port def", "Pkg::P", "Pkg", None, "", 3),
        ("part def", "Pkg::A", "Pkg", None, "an a", 4),
        ("port", "Pkg::A::outp", "Pkg::A", "P", "", 6),
        ("part", "Pkg::A::inner", "Pkg::A", "B", "", 7),
        ("part def", "Pkg::B", "Pkg", None, "a b", 9),
    ]
    assert all(e.file == F for e in els)
    assert [e.name for e in els] == ["Pkg", "P", "A", "outp", "inner", "B"]


def test_nested_package_qname_and_qualified_type():
    els = ok("package A { package B { part def C { part x : A::Y::Z; } } }")
    assert [e.qname for e in els] == ["A", "A::B", "A::B::C", "A::B::C::x"]
    assert els[3].type_ref == "A::Y::Z"


def test_connect_and_dependency_qnames_and_repeat_suffix():
    text = (
        "package P {\n"
        "  dependency from A to Q::B;\n"
        "  dependency from A to Q::B;\n"
        "  dependency from A to Q::B;\n"
        "  part def D {\n"
        "    connect a.p to b.q;\n"
        "    connect a.p to b.q;\n"
        "  }\n"
        "}\n"
    )
    els = {e.qname: e for e in ok(text) if e.kind in ("connect", "dependency")}
    assert list(els) == [
        "P::dependency(A->Q::B)",
        "P::dependency(A->Q::B)#2",
        "P::dependency(A->Q::B)#3",
        "P::D::connect(a.p-b.q)",
        "P::D::connect(a.p-b.q)#2",
    ]
    assert els["P::dependency(A->Q::B)"].ends == ("A", "Q::B")
    assert els["P::D::connect(a.p-b.q)"].ends == ("a", "p", "b", "q")
    assert els["P::D::connect(a.p-b.q)"].owner == "P::D"
    assert els["P::dependency(A->Q::B)#2"].line == 3


def test_line_comments_are_skipped_anywhere():
    text = "// a\npackage // b\n P // c\n { // d\n part def X { doc /* x */ } // e\n}"
    assert [e.qname for e in ok(text)] == ["P", "P::X"]


def test_doc_normalisation():
    els = ok("package P { part def X { doc /* \n * a\n *   b */ } }")
    assert els[1].doc == "a b"
    els = ok("package P { doc /**  one\n\ttwo   three  */ }")
    assert els[0].doc == "one two three"


def test_port_def_forms():
    els = ok("package P { port def A; port def B { doc /* x */ } port def C { } }")
    assert [(e.qname, e.doc) for e in els[1:]] == [("P::A", ""), ("P::B", "x"), ("P::C", "")]


def test_crlf_file_parses_and_counts_lines_by_newline():
    assert [e.qname for e in ok("package P {\r\n part def X { doc /* x */ }\r\n}\r\n")] == ["P", "P::X"]
    assert one("package P {\r\n\r\n  part x : T;\r\n}") == err(3, "unexpected 'x' (expected 'def')")


def test_multiple_top_level_packages():
    assert [e.qname for e in ok("package A { } package B { }")] == ["A", "B"]


def test_non_ascii_allowed_in_comments_and_docs():
    els = ok("// café\npackage P { doc /* café */ }")
    assert els[0].doc == "café"


# -- characters ---------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,line,label",
    [
        ("package P {\0}", 1, "U+0000"),
        ("package P {\x7f}", 1, "U+007F"),
        ("package P {\x0b}", 1, "U+000B"),
        ("package P { ‮ }", 1, "U+202E"),
        ("\n// bad ‮\npackage P { }", 2, "U+202E"),
        ("package P { doc /* a\n ‮ */ }", 2, "U+202E"),
        ("package P { doc /* ​ */ }", 1, "U+200B"),
        ("package P { doc /*   */ }", 1, "U+2028"),
        ("package P { doc /*   */ }", 1, "U+2029"),
        ("﻿package P { }", 1, "U+FEFF"),
        ("package P {  }", 1, "U+E000"),
        ("package P { ͸ }", 1, "U+0378"),
        ("package Pé { }", 1, "U+00E9"),
        ("package P { é }", 1, "U+00E9"),
        ("package P { \U0001f600 }", 1, "U+1F600"),
    ],
)
def test_unexpected_character_u_labels(text, line, label):
    assert one(text) == err(line, f"unexpected character '{label}'")


@pytest.mark.parametrize("c", list("'\"@#$%^&*()+-=[]|\\<>?!~`,/"))
def test_printable_ascii_non_token_characters(c):
    assert one(f"package P {{ {c} }}") == err(1, f"unexpected character '{c}'")


def test_quoted_name_gives_the_quote_character():
    assert one("package 'a b' { }") == err(1, "unexpected character '''")


def test_digit_at_start_of_word_is_refused_but_digits_inside_are_fine():
    assert one("package 1a { }") == err(1, "unexpected character '1'")
    assert [e.qname for e in ok("package a1_2 { }")] == ["a1_2"]


def test_character_finding_wins_over_earlier_syntax_finding():
    assert one("package P { part x : T; }\n‮") == err(2, "unexpected character 'U+202E'")


def test_unterminated_comment():
    assert one("package P { doc /* open") == err(1, "unterminated comment")
    assert one("package P {\n doc /* open\n\n") == err(2, "unterminated comment")


def test_block_comment_only_after_doc():
    assert one("/* x */ package P { }") == err(1, "block comment only allowed after doc")
    assert one("package P {\n /* x */ part def X { } }") == err(2, "block comment only allowed after doc")
    assert one("package P { doc /* a */ /* b */ }") == err(1, "block comment only allowed after doc")


# -- syntax -------------------------------------------------------------------------------------

def test_every_reserved_word_is_refused_as_a_name():
    for word in sorted(RESERVED):
        assert one(f"package {word} {{ }}") == err(1, f"name '{word}' is reserved")


def test_reserved_word_as_part_usage_and_type_name():
    assert one("package P { part def X { part to : T; } }") == err(1, "name 'to' is reserved")
    assert one("package P { part def X { part a : state; } }") == err(1, "name 'state' is reserved")


def test_name_length_limit():
    assert [e.name for e in ok(f"package {'a' * 64} {{ }}")] == ["a" * 64]
    assert one(f"package {'a' * 65} {{ }}") == err(1, f"name '{'a' * 65}' is longer than 64 characters")


def test_nesting_limit_counts_before_descending():
    six = "".join(f"package P{i} {{ " for i in range(6)) + "}" * 6
    assert len(ok(six)) == 6
    seven = "".join(f"package P{i} {{\n" for i in range(7)) + "}" * 7
    assert one(seven) == err(7, "nesting deeper than 6")


def test_part_def_counts_as_a_level():
    six_pkgs = "".join(f"package P{i} {{\n" for i in range(6))
    assert one(six_pkgs + "part def X { }" + "}" * 6) == err(7, "nesting deeper than 6")
    five_pkgs = "".join(f"package P{i} {{\n" for i in range(5))
    assert len(ok(five_pkgs + "part def X { }" + "}" * 5)) == 6


def test_duplicate_doc():
    assert one("package P { doc /* a */\n doc /* b */ }") == err(2, "duplicate doc")
    assert one("package P { part def X { doc /* a */ doc /* b */ } }") == err(1, "duplicate doc")
    assert one("package P { port def X { doc /* a */ doc /* b */ } }") == err(1, "duplicate doc")


def test_doc_without_comment():
    assert one("package P { doc x }") == err(1, "unexpected 'x' (expected a /* */ comment)")
    assert one("package P { doc; }") == err(1, "unexpected ';' (expected a /* */ comment)")


def test_unsupported_elements():
    assert one("import X;") == err(1, "unsupported element 'import'")
    assert one("import X::*;") == err(1, "unexpected character '*'")  # a character finding wins over a syntax one
    assert one("part def X { }") == err(1, "unsupported element 'part'")
    assert one("package P { attribute a; }") == err(1, "unsupported element 'attribute'")
    assert one("package P { import X; }") == err(1, "unsupported element 'import'")
    assert one("package P { connect a.p to b.q; }") == err(1, "unsupported element 'connect'")
    assert one("package P { part def D { dependency from A to B; } }") == err(1, "unsupported element 'dependency'")
    assert one("package P { part def D { package Q { } } }") == err(1, "unsupported element 'package'")
    assert one("doc /* x */") == err(1, "unsupported element 'doc'")


def test_part_usage_in_a_package_needs_def():
    assert one("package P { part x : T; }") == err(1, "unexpected 'x' (expected 'def')")
    assert one("package P { port x : T; }") == err(1, "unexpected 'x' (expected 'def')")


def test_package_expectations():
    assert one("package { }") == err(1, "unexpected '{' (expected a name)")
    assert one("package P ;") == err(1, "unexpected ';' (expected '{')")
    assert one("package P") == err(1, "unexpected 'end of file' (expected '{')")
    assert one("package P {") == err(1, "unexpected 'end of file' (expected '}')")
    assert one("package P {\n") == err(2, "unexpected 'end of file' (expected '}')")


def test_punctuation_where_a_statement_must_start():
    assert one("package P { ; }") == err(1, "unexpected ';' (expected a statement or '}')")
    assert one("package P { part def X { : } }") == err(1, "unexpected ':' (expected a statement or '}')")
    assert one("}") == err(1, "unexpected '}' (expected 'package')")
    assert one("; package P { }") == err(1, "unexpected ';' (expected 'package')")


def test_part_def_expectations():
    assert one("package P { part def X ; }") == err(1, "unexpected ';' (expected '{')")
    assert one("package P { part def X {") == err(1, "unexpected 'end of file' (expected '}')")
    assert one("package P { part def { } }") == err(1, "unexpected '{' (expected a name)")


def test_port_def_expectations():
    assert one("package P { port def X x }") == err(1, "unexpected 'x' (expected ';' or '{')")
    assert one("package P { port def X { port a : T; } }") == err(1, "unexpected 'port' (expected 'doc' or '}')")
    assert one("package P { port def X { ; } }") == err(1, "unexpected ';' (expected 'doc' or '}')")
    assert one("package P { port def X {") == err(1, "unexpected 'end of file' (expected 'doc' or '}')")


def test_usage_expectations():
    assert one("package P { part def X { port a T; } }") == err(1, "unexpected 'T' (expected ':')")
    assert one("package P { part def X { port a : ; } }") == err(1, "unexpected ';' (expected a name)")
    assert one("package P { part def X { port a : T } }") == err(1, "unexpected '}' (expected ';')")
    assert one("package P { part def X { part a : T::; } }") == err(1, "unexpected ';' (expected a name)")


def test_connect_expectations():
    base = "package P { part def X { %s } }"
    assert one(base % "connect ;") == err(1, "unexpected ';' (expected a name)")
    assert one(base % "connect a to b.q;") == err(1, "unexpected 'to' (expected '.')")
    assert one(base % "connect a. to b.q;") == err(1, "name 'to' is reserved")
    assert one(base % "connect a.p b.q;") == err(1, "unexpected 'b' (expected 'to')")
    assert one(base % "connect a.p to ;") == err(1, "unexpected ';' (expected a name)")
    assert one(base % "connect a.p to b;") == err(1, "unexpected ';' (expected '.')")
    assert one(base % "connect a.p to b.;") == err(1, "unexpected ';' (expected a name)")
    assert one(base % "connect a.p to b.q }") == err(1, "unexpected '}' (expected ';')")


def test_dependency_expectations():
    base = "package P { %s }"
    assert one(base % "dependency A to B;") == err(1, "unexpected 'A' (expected 'from')")
    assert one(base % "dependency from ;") == err(1, "unexpected ';' (expected a name)")
    assert one(base % "dependency from A B;") == err(1, "unexpected 'B' (expected 'to')")
    assert one(base % "dependency from A to ;") == err(1, "unexpected ';' (expected a name)")
    assert one(base % "dependency from A to B }") == err(1, "unexpected '}' (expected ';')")


def test_only_the_first_finding_is_returned_with_no_elements():
    elements, findings = parse_file("package P {\n part def { }\n part def Y { port a T; }\n}", F)
    assert elements == []
    assert findings == err(2, "unexpected '{' (expected a name)")


# -- doc text -----------------------------------------------------------------------------------

def test_doc_length_limit():
    assert len(ok(f"package P {{ doc /* {'a' * 1000} */ }}")[0].doc) == 1000
    assert one(f"package P {{ doc /* {'a' * 1001} */ }}") == err(1, "doc is longer than 1000 characters")


def test_doc_length_is_measured_after_normalisation():
    padded = " " * 3000 + "a" + " " * 3000
    assert ok(f"package P {{ doc /* {padded} */ }}")[0].doc == "a"


@pytest.mark.parametrize(
    "bad",
    [
        "http://x", "HTTP://x", "www.x", "WWW.x", "password: x", "passwd=x", "secret : x", "token=x",
        "API-KEY: x", "api_key=x", "-----BEGIN", "ghp_abcdefgh1", "gho_abcdefgh", "ghs_abcdefgh",
        "AKIA12345678", "sk-abcdefgh",
        "github_pat_" + "a1_" * 8, "ghu_abcdefgh1", "ghr_abcdefgh1", "ghp_abcdefgh1",
        "sk-" + "a-" * 12, "AKIA" + "A1" * 8, "xoxb-1", "xoxa-1", "xoxp-1", "xoxo-1", "xoxs-1", "xoxr-1",
        "AIza" + "a_-" * 8,
    ],
)
def test_doc_secret_or_link_rejected(bad):
    assert one(f"package P {{\n doc /* see {bad} */ }}") == err(2, "doc contains a link or a secret-like text")


@pytest.mark.parametrize("fine", ["the token bucket", "skeleton", "a www b", "e.g. this"])
def test_doc_benign_text_passes(fine):
    assert ok(f"package P {{ doc /* {fine} */ }}")[0].doc == fine


def test_doc_check_runs_on_part_def_and_port_def_docs():
    msg = "doc contains a link or a secret-like text"
    assert one("package P { part def X { doc /* http://a */ } }") == err(1, msg)
    assert one("package P { port def X { doc /* http://a */ } }") == err(1, msg)


def test_parse_never_raises_on_odd_input():
    for text in ["{", "}", "::", ":::", "package", "package P { doc", "\\", "\r", "\n\n\n", "a" * 100000]:
        elements, findings = parse_file(text, F)
        assert (elements, bool(findings)) in (([], True),) or findings == []


@pytest.mark.parametrize(
    "text,line",
    [
        ("package P {\r }", 1),
        ("package P { }\r", 1),
        ("// a\rb\npackage P { }", 1),
        ("\n\npackage P { doc /* a\rb */ }", 3),
        ("package P { }\r\n\r", 2),
    ],
)
def test_lone_carriage_return_is_refused_everywhere(text, line):
    assert one(text) == err(line, "unexpected character 'U+000D'")


def test_crlf_in_comments_and_docs_is_fine():
    els = ok("// a\r\npackage P { doc /* a\r\n b */ }\r\n")
    assert els[0].doc == "a b"


def test_stray_comment_then_bidi_reports_the_character_finding():
    assert one("/* x */\npackage P { }\n\u202e") == err(3, "unexpected character 'U+202E'")
