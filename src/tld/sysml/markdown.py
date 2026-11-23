"""The text of docs/architecture.md, written from a checked model and its layout (3.5 of the plan).

Pure and byte-stable. Model text is untrusted: doc text goes through `md_escape` (whitespace collapsed, the 15
characters that can start a link, markup, HTML or a table cell escaped with a backslash); names and types are
set in code spans only after they are checked to hold nothing but name characters and `::`, otherwise this module
raises `ModelError`. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import re

from tld.sysml.layout import Layout, _relations
from tld.sysml.model import Model
from tld.sysml.svg import STAMP, layout_number
from tld.sysml.types import ModelError

__all__ = ["STAMP", "layout_number", "md_escape", "to_markdown"]

_SPECIAL = frozenset("\\`*_[]()<>#!|~&")
_EXTRA = {"$": "\\$", "@": "&#64;"}  # beyond the 15: math spans, and e-mail autolinks
_LEAD = re.compile(r"^(?:[-+=]|[0-9]+(?=[.]))")
_CODE_OK = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(::[A-Za-z_][A-Za-z0-9_]*)*")
_SUMMARY = "{n} part defs in {m} packages, {k} dependencies and {c} connections, generated from sysml/model/. " \
          "Change it with a plan, never by hand."
_PACKAGE_VIEW_NOTE = "The diagram shows packages only; the tables list every part def."


def md_escape(text: str) -> str:
    """Collapse whitespace runs to one space, trim, and put a backslash before each of the 15 characters
    `\\ ` * _ [ ] ( ) < > # ! | ~ &`. Also escaped: `$` (math), `@` (written `&#64;`, so no e-mail autolink),
    and a leading `-`, `+`, `=` or `<digits>.` (a list item, rule or ordered list)."""
    collapsed = " ".join(text.split())
    out = "".join("\\" + c if c in _SPECIAL else _EXTRA.get(c, c) for c in collapsed)
    m = _LEAD.match(out)
    if m:
        out = out[: m.end()] + "\\" + out[m.end():] if out[0].isdigit() else "\\" + out
    return out


def _code(text: str) -> str:
    if not _CODE_OK.fullmatch(text):
        raise ModelError(f"cannot write '{md_escape(text)[:80]}' to docs/architecture.md: not a name")
    return f"`{text}`"


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def to_markdown(model: Model, lay: Layout) -> str:
    """docs/architecture.md for `model`, laid out as `lay`; ends with one newline."""
    n, m, k, c = lay.counts
    lines = ["# Architecture", "", _SUMMARY.format(n=n, m=m, k=k, c=c)]
    if lay.view == "package":
        lines.append(_PACKAGE_VIEW_NOTE)
    lines += ["", STAMP, "", "![Architecture](architecture.svg)", ""]

    recorded = [e for e in model.elements if model.index.get(e.qname) is e]
    part_defs = [e for e in recorded if e.kind == "part def"]
    ports: dict[str, list[str]] = {}
    for e in recorded:
        if e.kind == "port":
            ports.setdefault(e.owner, []).append(f"{_code(e.name)} : {_code(e.type_ref or '')}")
    owning = {e.owner for e in recorded if e.kind in ("part def", "port def", "package") and e.owner}
    for pkg in (e for e in recorded if e.kind == "package"):
        if not (pkg.doc or pkg.qname in owning):
            continue
        lines += [f"## {md_escape(pkg.qname)}", ""]
        if pkg.doc:
            lines += [md_escape(pkg.doc), ""]
        members = [d for d in part_defs if d.owner == pkg.qname]
        if members:
            lines += [_row("Part def", "Ports", "Description"), _row("---", "---", "---")]
            for d in members:
                lines.append(_row(_code(d.name), ", ".join(ports.get(d.qname, [])), md_escape(d.doc)))
            lines.append("")

    names = {d.qname for d in part_defs}
    rels = sorted({r for r in _relations(model, names) if r[1] != r[2]})
    lines += ["## Relations", ""]
    lines += [_row("From", "Kind", "To"), _row("---", "---", "---")]
    for kind, src, dst in sorted(rels, key=lambda r: (r[0], r[1], r[2])):
        lines.append(_row(_code(src), kind, _code(dst)))
    return "\n".join(lines) + "\n"
