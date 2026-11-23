"""The semantic diff of two models of tld's documented subset of the SysML v2 textual notation.

Elements are compared by qualified name. The subset is intended to parse in SysML v2 tools; tld does not check
it against one. Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass

from tld.sysml.model import Model


@dataclass(frozen=True)
class Change:
    """One element that was added, removed or changed: printed as `<op> <kind> <qname>`."""

    op: str
    kind: str
    qname: str

    def __str__(self) -> str:
        return f"{self.op} {self.kind} {self.qname}"


def diff(old: Model, new: Model) -> list[Change]:
    """Compare two models by `qname`, sorted by `(qname, op)`.

    `changed` means `(kind, type_ref, doc)` differs. An owner move, or a different end of a connect or a
    dependency, is a different `qname`: one `removed` and one `added`."""
    changes: list[Change] = []
    for qname, el in old.index.items():
        other = new.index.get(qname)
        if other is None:
            changes.append(Change("removed", el.kind, qname))
        elif (el.kind, el.type_ref, el.doc) != (other.kind, other.type_ref, other.doc):
            changes.append(Change("changed", other.kind, qname))
    for qname, el in new.index.items():
        if qname not in old.index:
            changes.append(Change("added", el.kind, qname))
    return sorted(changes, key=lambda c: (c.qname, c.op))
