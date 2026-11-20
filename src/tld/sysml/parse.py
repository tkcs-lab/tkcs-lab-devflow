"""Parser of tld's documented subset of the SysML v2 textual notation (subset 1).

The subset is intended to parse in SysML v2 tools; tld does not check it against one.
Model text is untrusted input: the lexer is a single bounded pass, nesting is capped, and the only
things this module returns are `Element` lists and `Finding`s; it raises nothing else.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from tld.sysml.types import MAX_DEPTH, MAX_DOC, MAX_NAME, RESERVED, Element, Finding

_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_PUNCT = "{};:."
_SECRET_PATTERNS = (
    re.compile(r"(?i)[a-z][a-z0-9+.-]*://"),
    re.compile(r"(?i)\bwww\."),
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]"),
    re.compile(r"-----BEGIN"),
    re.compile(r"\b(AKIA|ghp_|gho_|ghs_|sk-)[A-Za-z0-9_-]{8,}"),
)


@dataclass(frozen=True)
class _Tok:
    kind: str  # "word", "punct", "comment" or "eof"
    text: str
    line: int


class _Stop(Exception):
    """Internal: the first finding of the file."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.line = line
        self.message = message


def _char_label(c: str) -> str:
    o = ord(c)
    return c if 0x20 <= o <= 0x7E else f"U+{o:04X}"


def _refused(c: str) -> bool:
    """A character that is refused everywhere, comments and doc text included."""
    if c in "\t\n\r":
        return False
    return unicodedata.category(c) in _BAD_CATEGORIES


def _scan_region(text: str, start: int, end: int, line: int) -> None:
    """Refuse bad characters in a comment region; `line` is the line of `start`."""
    for k in range(start, end):
        c = text[k]
        if c == "\n":
            line += 1
        elif _refused(c):
            raise _Stop(line, f"unexpected character '{_char_label(c)}'")


def _prescan(text: str) -> None:
    """One pass over the whole text, comments and docs included: refused characters win over syntax findings.

    A carriage return is only allowed directly before a line feed (CRLF); a lone one would let a terminal
    overwrite the line and show a different text than the parser reads.
    """
    line = 1
    n = len(text)
    for k, c in enumerate(text):
        if c == "\n":
            line += 1
        elif c == "\r":
            if k + 1 >= n or text[k + 1] != "\n":
                raise _Stop(line, "unexpected character 'U+000D'")
        elif _refused(c):
            raise _Stop(line, f"unexpected character '{_char_label(c)}'")


def _lex(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    i = 0
    n = len(text)
    line = 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if _refused(c):
            raise _Stop(line, f"unexpected character '{_char_label(c)}'")
        if text.startswith("//", i):
            end = text.find("\n", i)
            if end == -1:
                end = n
            _scan_region(text, i, end, line)
            i = end
            continue
        if text.startswith("/*", i):
            after_doc = bool(tokens) and tokens[-1].kind == "word" and tokens[-1].text == "doc"
            if not after_doc:
                raise _Stop(line, "block comment only allowed after doc")
            end = text.find("*/", i + 2)
            stop = n if end == -1 else end
            _scan_region(text, i + 2, stop, line)
            if end == -1:
                raise _Stop(line, "unterminated comment")
            body = text[i + 2 : end]
            tokens.append(_Tok("comment", body, line))
            line += body.count("\n")
            i = end + 2
            continue
        if c.isascii() and (c.isalpha() or c == "_"):
            j = i + 1
            while j < n and text[j].isascii() and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(_Tok("word", text[i:j], line))
            i = j
            continue
        if c in _PUNCT:
            if c == ":" and text.startswith("::", i):
                tokens.append(_Tok("punct", "::", line))
                i += 2
            else:
                tokens.append(_Tok("punct", c, line))
                i += 1
            continue
        raise _Stop(line, f"unexpected character '{_char_label(c)}'")
    tokens.append(_Tok("eof", "end of file", line))
    return tokens


def _normalise_doc(body: str) -> str:
    lines = []
    for raw in body.split("\n"):
        s = raw.lstrip()
        if s.startswith("*"):
            s = s[1:]
        lines.append(s)
    return " ".join(" ".join(lines).split())


class _Parser:
    def __init__(self, tokens: list[_Tok], file: str) -> None:
        self.toks = tokens
        self.pos = 0
        self.file = file
        self.elements: list[Element | None] = []
        self.repeats: dict[str, int] = {}

    # -- token helpers -------------------------------------------------
    def peek(self) -> _Tok:
        return self.toks[self.pos]

    def next(self) -> _Tok:
        tok = self.toks[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    @staticmethod
    def shown(tok: _Tok) -> str:
        return "/* */" if tok.kind == "comment" else tok.text

    def unexpected(self, tok: _Tok, what: str) -> _Stop:
        return _Stop(tok.line, f"unexpected '{self.shown(tok)}' (expected {what})")

    def punct(self, text: str) -> _Tok:
        tok = self.next()
        if tok.kind != "punct" or tok.text != text:
            raise self.unexpected(tok, f"'{text}'")
        return tok

    def word(self, text: str) -> _Tok:
        tok = self.next()
        if tok.kind != "word" or tok.text != text:
            raise self.unexpected(tok, f"'{text}'")
        return tok

    def name(self) -> str:
        tok = self.next()
        if tok.kind != "word":
            raise self.unexpected(tok, "a name")
        if tok.text in RESERVED:
            raise _Stop(tok.line, f"name '{tok.text}' is reserved")
        if len(tok.text) > MAX_NAME:
            raise _Stop(tok.line, f"name '{tok.text}' is longer than {MAX_NAME} characters")
        return tok.text

    def qname(self) -> str:
        parts = [self.name()]
        while self.peek().kind == "punct" and self.peek().text == "::":
            self.next()
            parts.append(self.name())
        return "::".join(parts)

    def doc(self, have_doc: bool, kw: _Tok) -> str:
        if have_doc:
            raise _Stop(kw.line, "duplicate doc")
        tok = self.next()
        if tok.kind != "comment":
            raise self.unexpected(tok, "a /* */ comment")
        text = _normalise_doc(tok.text)
        if len(text) > MAX_DOC:
            raise _Stop(kw.line, f"doc is longer than {MAX_DOC} characters")
        if any(p.search(text) for p in _SECRET_PATTERNS):
            raise _Stop(kw.line, "doc contains a link or a secret-like text")
        return text

    # -- elements ------------------------------------------------------
    def add(self, kind: str, name: str, qname: str, owner: str, type_ref: str | None,
            ends: tuple[str, ...], line: int) -> int:
        self.elements.append(Element(kind, name, qname, owner, type_ref, ends, "", self.file, line))
        return len(self.elements) - 1

    def set_doc(self, index: int, doc: str) -> None:
        el = self.elements[index]
        assert el is not None
        self.elements[index] = Element(el.kind, el.name, el.qname, el.owner, el.type_ref, el.ends,
                                       doc, el.file, el.line)

    def unique(self, qname: str) -> str:
        count = self.repeats.get(qname, 0) + 1
        self.repeats[qname] = count
        return qname if count == 1 else f"{qname}#{count}"

    @staticmethod
    def join(owner: str, name: str) -> str:
        return f"{owner}::{name}" if owner else name

    def top(self) -> None:
        while True:
            tok = self.peek()
            if tok.kind == "eof":
                return
            if tok.kind == "word" and tok.text == "package":
                self.next()
                self.package("", 1, tok)
            elif tok.kind == "word":
                raise _Stop(tok.line, f"unsupported element '{tok.text}'")
            else:
                raise self.unexpected(tok, "'package'")

    def package(self, owner: str, depth: int, kw: _Tok) -> None:
        if depth > MAX_DEPTH:
            raise _Stop(kw.line, f"nesting deeper than {MAX_DEPTH}")
        name = self.name()
        qname = self.join(owner, name)
        index = self.add("package", name, qname, owner, None, (), kw.line)
        self.punct("{")
        have_doc = False
        while True:
            tok = self.peek()
            if tok.kind == "punct" and tok.text == "}":
                self.next()
                return
            if tok.kind == "eof":
                raise self.unexpected(tok, "'}'")
            if tok.kind != "word":
                raise self.unexpected(tok, "a statement or '}'")
            w = tok.text
            if w == "package":
                self.next()
                self.package(qname, depth + 1, tok)
            elif w == "part":
                self.next()
                self.word("def")
                self.part_def(qname, depth + 1, tok)
            elif w == "port":
                self.next()
                self.word("def")
                self.port_def(qname, tok)
            elif w == "dependency":
                self.next()
                self.word("from")
                src = self.qname()
                self.word("to")
                dst = self.qname()
                self.punct(";")
                key = self.unique(f"{qname}::dependency({src}->{dst})")
                self.add("dependency", "", key, qname, None, (src, dst), tok.line)
            elif w == "doc":
                self.next()
                self.set_doc(index, self.doc(have_doc, tok))
                have_doc = True
            else:
                raise _Stop(tok.line, f"unsupported element '{w}'")

    def part_def(self, owner: str, depth: int, kw: _Tok) -> None:
        if depth > MAX_DEPTH:
            raise _Stop(kw.line, f"nesting deeper than {MAX_DEPTH}")
        name = self.name()
        qname = self.join(owner, name)
        index = self.add("part def", name, qname, owner, None, (), kw.line)
        self.punct("{")
        have_doc = False
        while True:
            tok = self.peek()
            if tok.kind == "punct" and tok.text == "}":
                self.next()
                return
            if tok.kind == "eof":
                raise self.unexpected(tok, "'}'")
            if tok.kind != "word":
                raise self.unexpected(tok, "a statement or '}'")
            w = tok.text
            if w in ("port", "part"):
                self.next()
                usage = self.name()
                self.punct(":")
                type_ref = self.qname()
                self.punct(";")
                self.add(w, usage, f"{qname}::{usage}", qname, type_ref, (), tok.line)
            elif w == "connect":
                self.next()
                a = self.name()
                self.punct(".")
                p = self.name()
                self.word("to")
                b = self.name()
                self.punct(".")
                q = self.name()
                self.punct(";")
                key = self.unique(f"{qname}::connect({a}.{p}-{b}.{q})")
                self.add("connect", "", key, qname, None, (a, p, b, q), tok.line)
            elif w == "doc":
                self.next()
                self.set_doc(index, self.doc(have_doc, tok))
                have_doc = True
            else:
                raise _Stop(tok.line, f"unsupported element '{w}'")

    def port_def(self, owner: str, kw: _Tok) -> None:
        name = self.name()
        qname = self.join(owner, name)
        index = self.add("port def", name, qname, owner, None, (), kw.line)
        tok = self.next()
        if tok.kind == "punct" and tok.text == ";":
            return
        if tok.kind != "punct" or tok.text != "{":
            raise self.unexpected(tok, "';' or '{'")
        have_doc = False
        while True:
            tok = self.next()
            if tok.kind == "punct" and tok.text == "}":
                return
            if tok.kind == "word" and tok.text == "doc":
                self.set_doc(index, self.doc(have_doc, tok))
                have_doc = True
                continue
            raise self.unexpected(tok, "'doc' or '}'")


def parse_file(text: str, file: str) -> tuple[list[Element], list[Finding]]:
    """Parse one model file. Callers must read the text through files.load_tree or files.read_text (size limits).

    Stops at the first finding and then returns just that one, with no elements."""
    try:
        _prescan(text)
        parser = _Parser(_lex(text), file)
        parser.top()
    except _Stop as stop:
        return [], [Finding(file, stop.line, stop.message)]
    return [e for e in parser.elements if e is not None], []
