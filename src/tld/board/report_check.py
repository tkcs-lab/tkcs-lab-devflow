#!/usr/bin/env python3
"""The page check for a Reflektor report: the same rules on the client (`tld roles reflektor-html`) and on the board.

`check(text)` returns the reasons a page is not acceptable (an empty list when it is). A page is acceptable only
when it is exactly: part 1 of the pinned viewer (up to and including `<head>`), `CSP_META`, part 2, `<title>`, a
plain title, `</title>`, part 3, a one-line JSON payload without `<`, part 4 (the end of the pinned viewer). The
four parts are compared by length and sha256, so the application code of the page is the pinned code; the data may
hold no link target (the viewer would turn those into links). The secret scan is not here: the board image has no
`tld.guard`, so only the client adds it.

Standard library only; imports nothing from `tld`. `VIEWER_PARTS` and `CSP_META` are read inside the functions so
tests can replace them.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata

# (length in characters, sha256 of the UTF-8 text) of the four parts of the pinned assets/viewer.html around the
# three fixed places: up to and including <head>; between <head> and <title>PR report</title>; between that
# title tag and __REFLEKTOR_DATA__; after __REFLEKTOR_DATA__.
VIEWER_PARTS = (
    (41, "913938b754ef88f878978136f45d0ef208700dc2f4da19a4549a7ab7a13a22d8"),
    (111, "86241ba83dbe1edf99781d5b00834970db6258d667920e776fa9ca6d899f139d"),
    (12064403, "8441767dcecfb6bc4f0e6f4488f0eb95a059df3b96e5c50f57a02967227acb47"),
    (28, "e0c8de22a9bf475d6dd3b74e254705709728ccf8a58bb6d52bf4df2657fcae24"),
)

CSP_META = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    "script-src 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'\">"
)

TITLE_OPEN = "<title>"
TITLE_CLOSE = "</title>"
MAX_TITLE = 200

# every value under one of these keys, at any depth, must be null: the viewer makes links or embeds from them
NULL_KEYS = ("url", "ownerUrl", "href", "notesUrl", "web", "screenshots", "projectChecks", "coverage", "agent")
# (parent key, key): `pr` under `branch`, `image` under `avatar`
NULL_UNDER = (("branch", "pr"), ("avatar", "image"))
MAX_DEPTH = 200


class _Reject(ValueError):
    """A payload that is refused for a stated reason."""


def _no_constant(name):
    raise _Reject("invalid payload (NaN or Infinity)")


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _Reject("invalid payload (duplicate key)")
        out[key] = value
    return out


def _sha(part: str) -> str:
    return hashlib.sha256(part.encode("utf8")).hexdigest()


def _same(part: str, expected) -> bool:
    return len(part) == expected[0] and _sha(part) == expected[1]


def split(text: str):
    """(title, payload) of a page whose fixed parts all match, else a list with one reason."""
    parts = VIEWER_PARTS
    csp = CSP_META
    n1, n2, n3, n4 = (p[0] for p in parts)
    if not _same(text[:n1], parts[0]):
        return ["page part 1 differs from the pinned viewer"]
    pos = n1
    if text[pos:pos + len(csp)] != csp:
        return ["the Content-Security-Policy meta tag is missing or changed"]
    pos += len(csp)
    if not _same(text[pos:pos + n2], parts[1]):
        return ["page part 2 differs from the pinned viewer"]
    pos += n2
    if not text.startswith(TITLE_OPEN, pos):
        return ["the title tag is missing"]
    start = pos + len(TITLE_OPEN)
    end = text.find(TITLE_CLOSE, start)
    if end < 0:
        return ["the title tag is not closed"]
    title = text[start:end]
    if (len(title) > MAX_TITLE or "<" in title or "&" in title
            or any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in title)):
        return ["the title is not plain one-line text"]
    pos = end + len(TITLE_CLOSE)
    if not _same(text[pos:pos + n3], parts[2]):
        return ["page part 3 differs from the pinned viewer"]
    pos += n3
    if len(text) - pos < n4:
        return ["page part 4 differs from the pinned viewer"]
    if not _same(text[len(text) - n4:], parts[3]):
        return ["page part 4 differs from the pinned viewer"]
    return title, text[pos:len(text) - n4]


def parse_payload(payload: str):
    """The parsed JSON of a payload; raises `_Reject` or another exception when it is not acceptable."""
    if "\n" in payload or "\r" in payload:
        raise _Reject("invalid payload (not one line)")
    if "<" in payload:
        raise _Reject("invalid payload (contains '<')")
    try:
        return json.loads(payload, parse_constant=_no_constant, object_pairs_hook=_no_duplicates)
    except _Reject:
        raise
    except RecursionError as exc:
        raise _Reject("invalid payload (nested too deeply)") from exc
    except ValueError as exc:
        raise _Reject("invalid payload (not JSON)") from exc


def link_targets(value) -> list[str]:
    """The keys of non-null values that must be null (iterative; no recursion)."""
    found: list[str] = []
    stack = [(value, None, 0)]
    while stack:
        item, parent, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise _Reject("invalid payload (nested too deeply)")
        if isinstance(item, dict):
            for key, child in item.items():
                if child is not None and (key in NULL_KEYS or (parent, key) in NULL_UNDER):
                    label = f"{parent}.{key}" if (parent, key) in NULL_UNDER else key
                    if label not in found:
                        found.append(label)
                stack.append((child, key, depth + 1))
        elif isinstance(item, list):
            for child in item:
                stack.append((child, parent, depth + 1))
    return found


def check(text: str) -> list[str]:
    """The reasons `text` is not an acceptable page (empty when it is)."""
    try:
        if not isinstance(text, str):
            return ["the page is not text"]
        got = split(text)
        if isinstance(got, list):
            return got
        _title, payload = got
        value = parse_payload(payload)
        return [f"the data has a link target under '{k}'" for k in link_targets(value)]
    except _Reject as exc:
        return [str(exc)]
    except Exception:  # noqa: BLE001 - any failure is a refusal, never a crash of the board
        return ["invalid payload"]
