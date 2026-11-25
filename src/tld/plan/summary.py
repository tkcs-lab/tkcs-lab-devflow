#!/usr/bin/env python3
"""The `## Summary` section of a plan, a tracking-issue body or a pull-request body.

    summary.py FILE --kind plan|issue|pr [--deviations FILE] [--findings N] [--changed FILE]

Checks where the Summary stands, its labels and their order, hidden markup and the word limit (350 for a plan
and an issue, 175 for a pull request). With `--deviations` it also checks that `None.` is not claimed over a
non-empty deviations file. For a pull request it checks the rows of a `## Non-blocking findings` section when
there is one; with `--findings N` that section must exist and hold exactly N rows. With `--changed FILE` (one repository-relative
path per line, only for a pull request) the `**Security:**` label must name every workflow and profile file the list
holds. Prints one `summary: <problem>` line per problem and exits 1, or prints
`summary: OK (<n> words)`. Reads one file of at most 1000000 bytes, runs nothing. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata

from tld.plan import findings as findings_check

KINDS = ("plan", "issue", "pr")
MAX_WORDS = {"plan": 350, "issue": 350, "pr": 175}
_SHARED = ("Use it", "Scope", "Security", "Performance", "Review focus")
ORDER = {
    "plan": _SHARED,
    "issue": _SHARED,
    "pr": ("Deviations", "Scope", "Security", "Performance", "Review focus"),
}
REQUIRED = {
    "plan": ("Use it", "Scope", "Review focus"),
    "issue": ("Use it", "Scope", "Review focus"),
    "pr": ("Deviations", "Review focus"),
}
NONE_OK = ("Deviations", "Security", "Performance")
TEXT_MAX = 80
FINDINGS_HEADING = "Non-blocking findings"
MAX_BYTES = 1000000
MIN_VALUE_WORDS = 3
PLACEHOLDERS = ("tbd", "todo", "n/a", "see below", "...")
HIDDEN = ("<!--", "<details")
UNSAFE = ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")
CLOSES = re.compile(r"(closes|fixes|resolves) #[0-9]+\.?", re.IGNORECASE)
WORD = re.compile(r"\w")
LINKISH = re.compile(r"\]\(|\]\[|!\[|<|^[\s>*+\-]*\[[^\]]*\]:", re.MULTILINE)
SECURITY_PATHS = (".github/workflows/", ".tld/toolkit.yaml")


class ReadError(Exception):
    """Printed as `summary: <message>`."""


def scrub(text: str) -> str:
    return "".join("?" if unicodedata.category(c) in UNSAFE else c for c in text)


def clean(text: str) -> str:
    """An echoed fragment: unsafe characters become `?`, then it is cut to TEXT_MAX characters."""
    return scrub(text[:TEXT_MAX])


def normalise(text: str) -> str:
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n")


def fence_run(line: str) -> tuple[str, int] | None:
    """(character, length) when the line opens or closes a fenced block."""
    body = line.lstrip(" ")
    if len(line) - len(body) > 3 or body[:1] not in ("`", "~"):
        return None
    length = len(body) - len(body.lstrip(body[0]))
    return (body[0], length) if length >= 3 else None


def closes(line: str, fence: tuple[str, int]) -> bool:
    run = fence_run(line)
    return run is not None and run[0] == fence[0] and run[1] >= fence[1] and line.strip().strip(fence[0]) == ""


def is_quote(line: str) -> bool:
    body = line.lstrip(" ")
    return len(line) - len(body) <= 3 and body.startswith(">")


def scan(lines: list[str]) -> list[str]:
    """The kind of every line: fence, quote, heading or text."""
    kinds: list[str] = []
    fence = None
    for line in lines:
        if fence is not None:
            kinds.append("fence")
            if closes(line, fence):
                fence = None
            continue
        opened = fence_run(line)
        if opened is not None:
            fence = opened
            kinds.append("fence")
        elif is_quote(line):
            kinds.append("quote")
        elif line.startswith("## "):
            kinds.append("heading")
        else:
            kinds.append("text")
    return kinds


def parse_label(line: str) -> tuple[str, str] | None:
    """(name, rest of the line) when the line is `**Name:** value` or `- **Name:** value`."""
    rest = line[2:] if line.startswith("- ") else line
    if not rest.startswith("**"):
        return None
    end = rest.find(":**", 2)
    name = rest[2:end]
    if end < 3 or "*" in name or not name.strip():
        return None
    return name, rest[end + 3:]


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


def placement(lines: list[str], kinds: list[str], heads: list[tuple[int, str]], start: int, kind: str) -> list[str]:
    pos = [h[0] for h in heads].index(start)
    if kind == "issue":
        ok = pos == 1 and heads[0][1] == "Request"
        wrong = "'## Summary' must come right after '## Request'"
    else:
        ok = pos == 0
        wrong = "'## Summary' must be the first '## ' section"
    if not ok:
        return [wrong]
    title = False
    for i in range(heads[0][0]):
        line = lines[i].strip()
        if not line:
            continue
        if kind == "plan" and kinds[i] == "quote":
            continue
        if kind == "plan" and kinds[i] == "text" and lines[i].startswith("# ") and not title:
            title = True
            continue
        if kind == "pr" and kinds[i] == "text" and CLOSES.fullmatch(line):
            continue
        return [f"text before '## Summary' is not allowed: '{clean(lines[i])}'"]
    return []


def findings_problems(lines: list[str], heads: list[tuple[int, str]], n: int | None) -> list[str]:
    """The problems of the `## Non-blocking findings` section; `n` is the count from --findings, or None."""
    found = [h for h in heads if h[1] == FINDINGS_HEADING]
    if len(found) > 1:
        return [f"{len(found)} '## {FINDINGS_HEADING}' sections"]
    if not found:
        return [f"no '## {FINDINGS_HEADING}' section"] if n is not None else []
    top = found[0][0]
    below = [h[0] for h in heads if h[0] > top]
    body = lines[top + 1:below[0] if below else len(lines)]
    return [f"findings: {p}" for p in findings_check.check(body, n)]


def security_paths(changed: list[str]) -> list[str]:
    """The workflow and profile files of a changed-path list, once each, in list order."""
    hits = [p for p in changed if p.startswith(SECURITY_PATHS[0]) or p == SECURITY_PATHS[1]]
    return list(dict.fromkeys(hits))


def names(path: str, text: str) -> bool:
    """Whether the Security text names the path by its full path or by its file name as a whole word."""
    for cand in (path, path.rsplit("/", 1)[-1]):
        if re.search(r"(?<![\w.\-/])" + re.escape(cand) + r"(?![\w\-]|\.\w)", text):
            return True
    return False


def security_problems(values: dict[str, str], changed: list[str]) -> list[str]:
    """The problems of the Security label against the workflow and profile files a pull request changes."""
    hits = security_paths(changed)
    if not hits:
        return []
    value = values.get("Security", "")
    if LINKISH.search(value):
        return ["**Security:** must name the files in plain text: it holds a link, an image, a reference definition "
                "or an HTML tag, which can hide a file name"]
    if not value or is_none(value):
        return [f"**Security:** is missing or None. but the pull request changes {', '.join(clean(p) for p in hits)}"]
    missing = [p for p in hits if not names(p, value)]
    if missing:
        return ["**Security:** must name every workflow and profile file this pull request changes; "
                f"not named: {', '.join(clean(p) for p in missing)}"]
    return []


def check(text: str, kind: str, deviations_text: str | None = None,
          findings: int | None = None, changed: list[str] | None = None) -> tuple[list[str], int]:
    """(problems, word count of the Summary section) for the text of a document."""
    lines = normalise(text).split("\n")
    kinds = scan(lines)
    heads = [(i, lines[i][3:].strip()) for i, k in enumerate(kinds) if k == "heading"]
    exact = [h for h in heads if h[1] == "Summary"]
    near = [h for h in heads if h[1] != "Summary" and "summary" in h[1].lower()]
    problems = [f"the heading must be exactly '## Summary' (found '{clean(h[1])}')" for h in near]
    if not exact:
        return problems or ["no '## Summary' section"], 0
    if len(exact) > 1:
        problems.append(f"{len(exact)} '## Summary' sections")
    start = exact[0][0]
    after = [h for h in heads if h[0] > start]
    end = after[0][0] if after else len(lines)
    problems += placement(lines, kinds, heads, start, kind)

    labels: list[tuple[str, list[str]]] = []
    stray = False
    for i in range(start + 1, end):
        found = parse_label(lines[i]) if kinds[i] == "text" else None
        if found:
            labels.append((found[0], [found[1]]))
        elif labels:
            labels[-1][1].append(lines[i])
        elif lines[i].strip():
            stray = True
    order = ORDER[kind]
    names = [name for name, _ in labels]
    known = [name for name in names if name in order]
    for name in dict.fromkeys(names):
        if name not in order:
            problems.append(f"unknown label '{clean(name)}'")
    for name in dict.fromkeys(known):
        if known.count(name) > 1:
            problems.append(f"duplicate label '{name}'")
    for name in REQUIRED[kind]:
        if name not in known:
            problems.append(f"missing label '{name}'")
    top = -1
    for name in dict.fromkeys(known):
        if order.index(name) < top:
            problems.append(f"label '{name}' is out of order")
        top = max(top, order.index(name))

    if stray:
        problems.append("text before the first label")
    values: dict[str, str] = {}
    for name, parts in labels:
        if name in order and name not in values:
            values[name] = "\n".join(parts).strip()
    for name, value in values.items():
        if is_none(value) and name in NONE_OK:
            continue
        if is_placeholder(value):
            problems.append(f"label '{name}' is a placeholder")
            continue
        if count_words(value) < MIN_VALUE_WORDS:
            problems.append(f"label '{name}' needs at least {MIN_VALUE_WORDS} words")
        if is_none(value):
            problems.append(f"label '{name}' cannot be 'None.'")
    sect = lines[start:end]
    blob = "\n".join(sect).lower()
    if any(mark in blob for mark in HIDDEN):
        problems.append("the Summary holds hidden markup (an HTML comment or a details block)")

    words = count_words("\n".join(sect))
    if words > MAX_WORDS[kind]:
        problems.append(f"{words} words, the limit for {kind} is {MAX_WORDS[kind]}")
    if deviations_text is not None and is_none(values.get("Deviations", "")):
        recorded = [ln[2:].strip() for ln in normalise(deviations_text).split("\n") if ln.startswith("- ")]
        count = sum(1 for item in recorded if item not in ("None.", "pending"))
        if count:
            problems.append(f"Deviations says None. but the deviations file records {count} deviations")
    if changed is not None:
        problems += security_problems(values, changed)
    if kind == "pr":
        problems += findings_problems(lines, heads, findings)
    return problems, words


def read(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ReadError(f"cannot read '{scrub(path)}': {exc.strerror or type(exc).__name__}") from None
    if len(data) > MAX_BYTES:
        raise ReadError(f"cannot read '{scrub(path)}': larger than {MAX_BYTES} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ReadError(f"cannot read '{scrub(path)}': not valid UTF-8") from None


def changed_paths(text: str) -> list[str]:
    """The paths of a --changed file: one per line, blank lines and carriage returns ignored."""
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]
    # git quotes a path with special characters ("..."): the quotes must not hide a workflow path
    return [ln[1:-1] if len(ln) > 1 and ln[0] == ln[-1] == '"' else ln for ln in lines]


def report(problems: list[str]) -> int:
    for problem in problems:
        print(f"summary: {problem}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld plan summary-check", description=__doc__.split("\n")[0])
    ap.add_argument("file", metavar="FILE", help="the plan, issue body or pull request body")
    ap.add_argument("--kind", required=True, choices=KINDS, help="what the file is")
    ap.add_argument("--deviations", metavar="FILE", help="the deviations file (only with --kind pr)")
    ap.add_argument("--findings", type=int, metavar="N", help="the number of findings (only with --kind pr)")
    ap.add_argument("--changed", metavar="FILE",
                    help="the changed paths, one per line (only with --kind pr); workflow and profile files must be named under Security")
    args = ap.parse_args(argv)
    if args.changed is not None and args.kind != "pr":
        ap.error("--changed is only for --kind pr")
    if args.findings is not None and args.kind != "pr":
        ap.error("--findings is only for --kind pr")
    if args.findings is not None and args.findings < 0:
        ap.error("--findings must be 0 or more")
    if args.deviations is not None and args.kind != "pr":
        ap.error("--deviations is only for --kind pr")
    try:
        text = read(args.file)
        deviations = read(args.deviations) if args.deviations is not None else None
        changed = changed_paths(read(args.changed)) if args.changed is not None else None
    except ReadError as exc:
        return report([str(exc)])
    problems, words = check(text, args.kind, deviations, args.findings, changed)
    if problems:
        return report(problems)
    print(f"summary: OK ({words} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
