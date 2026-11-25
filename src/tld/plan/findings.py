#!/usr/bin/env python3
"""The rows of the `## Non-blocking findings` section of a pull-request body.

    findings.check(lines, n) -> list of problems

`lines` is the section body (the lines after the heading, up to the next `## ` heading). Each row is
`- F<k> · <source> · <location> · <text> · <status>` where the status is `fixed <sha>` or `declined: <reason>`;
the single line `None.` stands for no findings. `n` is the number of findings counted, or None. Prints nothing
and runs nothing; the problems carry no prefix. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import re
import unicodedata

SEP = " · "
MIN_VALUE_WORDS = 3
PLACEHOLDERS = ("tbd", "todo", "n/a", "see below", "...")
HIDDEN = ("<!--", "<details")
UNSAFE = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")
WORD = re.compile(r"\w")
MENTION = re.compile(r"(?<![\w.-])@[A-Za-z]")
ID = re.compile(r"F[0-9]+")
SOURCE = re.compile(r"final-review|[a-z-]+@(implement_final|dod)")
FIXED = re.compile(r"fixed [0-9a-fA-F]{7,40}")


def count_words(text: str) -> int:
    return sum(1 for token in text.split() if WORD.search(token))


def is_none(value: str) -> bool:
    low = value.strip().lower()
    return (low[:-1] if low.endswith(".") else low) == "none"


def is_placeholder(value: str) -> bool:
    low = value.strip().lower()
    bare = low[:-1] if low.endswith(".") else low
    single = (len(low) >= 2 and low[0] == "<" and low[-1] == ">" and low.count("<") == 1 and low.count(">") == 1)
    return low in PLACEHOLDERS or bare in PLACEHOLDERS or single


def row_problem(line: str) -> str | None:
    """What is wrong with the grammar of one row, or None."""
    if not line.startswith("- "):
        return "a row starts with '- '"
    fields = line[2:].split(SEP)
    if len(fields) < 5:
        return f"{len(fields)} fields, expected at least 5 separated by ' · '"
    ident, source, location, status = fields[0], fields[1], fields[2], fields[-1]
    text = SEP.join(fields[3:-1])
    if not ID.fullmatch(ident):
        return "the id must be F<digits>"
    if not SOURCE.fullmatch(source):
        return "the source must be final-review, <role>@implement_final or <role>@dod"
    if not location or re.search(r"\s", location):
        return "the location must not be empty or hold a space"
    if count_words(text) < MIN_VALUE_WORDS:
        return f"the text needs at least {MIN_VALUE_WORDS} words"
    if FIXED.fullmatch(status):
        return None
    if status.startswith("declined: "):
        reason = status[len("declined: "):]
        if is_placeholder(reason) or is_none(reason):
            return "the declined reason is a placeholder or none"
        if count_words(reason) < MIN_VALUE_WORDS:
            return f"the declined reason needs at least {MIN_VALUE_WORDS} words"
        return None
    return "the status must be 'fixed <7-40 hex characters>' or 'declined: <reason>'"


def check(lines: list[str], n: int | None) -> list[str]:
    """The problems of a findings section body; `n` is the number of findings counted, or None."""
    rows = [ln for ln in lines if ln.strip()]
    if not rows:
        return ["the section is empty (write None. or one row per finding)"]
    if len(rows) == 1 and rows[0].strip() == "None.":
        if n is not None and n != 0:
            return [f"says None. but {n} findings were counted"]
        return []
    problems: list[str] = []
    for k, line in enumerate(rows, 1):
        bad = row_problem(line)
        if bad:
            problems.append(f"row {k}: {bad}")
    ids = [ln[2:].split(SEP)[0] for ln in rows]
    if ids != [f"F{k}" for k in range(1, len(rows) + 1)]:
        problems.append(f"ids must run F1..F{len(rows)} in order")
    if n is not None:
        if n > 0 and len(rows) != n:
            problems.append(f"{len(rows)} rows, expected {n}")
        if n == 0:
            problems.append("rows but no findings were counted")
    for k, line in enumerate(rows, 1):
        low = line.lower()
        if (any(mark in low for mark in HIDDEN) or any(unicodedata.category(c) in UNSAFE for c in line)
                or MENTION.search(line)):
            problems.append(f"row {k}: hidden markup, control characters or a mention")
    return problems
