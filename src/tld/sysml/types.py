"""Shared types and limits of tld's documented subset of the SysML v2 textual notation.

The subset is intended to parse in SysML v2 tools; tld does not check it against one. Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_FILE_BYTES = 100000
MAX_FILES = 50
MAX_TOTAL_BYTES = 1000000
MAX_NAME = 64
MAX_DEPTH = 6
MAX_DOC = 1000
MAX_ELEMENTS = 300
MAX_RELATIONS = 600

# A name equal to one of these is an error; deliberately wider than the SysML keyword list.
RESERVED = frozenset(
    ["about", "accept", "action", "actor", "alias", "all", "allocate", "allocation", "analysis", "and", "as", "assert", "assign", "assume", "at", "attribute", "bind", "binding", "by", "calc", "case", "comment", "concern", "connect", "connection", "constant", "constraint", "decide", "def", "dependency", "derived", "do", "doc", "else", "end", "entry", "enum", "event", "exhibit", "exit", "expose", "false", "filter", "first", "flow", "for", "fork", "frame", "from", "hastype", "if", "import", "in", "include", "individual", "inout", "interface", "istype", "item", "join", "language", "library", "loop", "merge", "message", "meta", "metadata", "new", "not", "null", "objective", "occurrence", "of", "or", "ordered", "out", "package", "parallel", "part", "perform", "port", "private", "protected", "public", "readonly", "redefines", "ref", "references", "render", "rendering", "rep", "require", "requirement", "return", "satisfy", "send", "snapshot", "specializes", "stakeholder", "standard", "state", "subject", "subsets", "succession", "then", "timeslice", "to", "transition", "true", "until", "use", "variant", "variation", "verification", "verify", "via", "view", "viewpoint", "while", "xor"]
)


@dataclass(frozen=True)
class Finding:
    """One problem: `<file>:<line>: <message>`."""

    file: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.message}"


class ModelError(Exception):
    """A problem that stops the command (exit 2); the message is the stderr line without the prefix."""


@dataclass(frozen=True)
class Element:
    """A model element. `kind` is package, part def, port def, part, port, connect or dependency."""

    kind: str
    name: str
    qname: str
    owner: str
    type_ref: str | None
    ends: tuple[str, ...]
    doc: str
    file: str
    line: int
