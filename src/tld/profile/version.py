"""The `tld.version` check: does the running tld satisfy the profile's version specifier?

A specifier is a comma-separated list of clauses `<op><version>`, `op` one of `==`, `!=`, `>=`, `<=`,
`>`, `<`, and `version` dotted integers (`>=1.0,<2`). Versions compare as integer tuples padded with
zeros, so `1.0` equals `1.0.0`. A development or pre-release build (`1.0.0.dev0`, `1.0.0rc1`) counts as
the release it leads to: a checkout of the next release satisfies the profiles written for it.
"""
from __future__ import annotations

import re

CLAUSE = re.compile(r"^\s*(==|!=|>=|<=|>|<)\s*(\d+(?:\.\d+)*)\s*$")
RELEASE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


class SpecifierError(ValueError):
    """The specifier text cannot be parsed."""


def release(version: str) -> tuple[int, ...]:
    """The release part of a version string as an integer tuple (`1.0.0.dev0` -> (1, 0, 0))."""
    m = RELEASE.match(version)
    if not m:
        raise SpecifierError(f"not a version: {version!r}")
    return tuple(int(x) for x in m.group(1).split("."))


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def parse(spec: str) -> list[tuple[str, tuple[int, ...]]]:
    if not isinstance(spec, str) or not spec.strip():
        raise SpecifierError("empty version specifier")
    out = []
    for part in spec.split(","):
        m = CLAUSE.match(part)
        if not m:
            raise SpecifierError(f"cannot read clause {part.strip()!r} (use e.g. '>=1.0,<2')")
        out.append((m.group(1), release(m.group(2))))
    return out


def satisfies(version: str, spec: str) -> bool:
    have = release(version)
    for op, want in parse(spec):
        c = _cmp(have, want)
        ok = {"==": c == 0, "!=": c != 0, ">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0}[op]
        if not ok:
            return False
    return True
