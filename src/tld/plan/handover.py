#!/usr/bin/env python3
"""The board hand-over of a finished plan: its Summary word for word, the slug, the links and the next command.

    tld plan handover FILE --kind plan|issue --repo OWNER/NAME --plan-slug SLUG
                      [--issue-url URL] [--plan-url URL] [--spec-url URL] [--command-prefix PREFIX]

Reads the plan or the tracking-issue body FILE, checks its `## Summary` like `tld plan summary-check`, refuses a
Summary with an unsafe character, more than 4000 characters, a secret-like value or the `secret-scan:allow` marker, scans every other field too, builds the `handover` object of
a done make-plan status record and checks it with the status-record rules. Prints the object as JSON (exit 0), or
`handover: <problem>` lines on stderr and nothing on stdout (exit 1). Writes nothing and runs nothing.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata

from tld.board import record
from tld.guard import secret_scan
from tld.plan import summary

KINDS = ("plan", "issue")
ALLOW_MARK = "secret-scan:allow"  # scan_text skips a line that ends with it; nothing here may opt out
UNSAFE_MESSAGE = "'handover.summary' holds a control, format, surrogate, private-use or separator character"


def fail(problems: list[str]) -> int:
    for problem in problems:
        print(f"handover: {problem}", file=sys.stderr)
    return 1


def section_of(text: str) -> str:
    """The Summary section without its heading and without leading and trailing blank lines."""
    lines = summary.normalise(text).split("\n")
    kinds = summary.scan(lines)
    start = next(i for i, k in enumerate(kinds) if k == "heading" and lines[i][3:].strip() == "Summary")
    end = next((i for i in range(start + 1, len(lines)) if kinds[i] == "heading"), len(lines))
    body = lines[start + 1:end]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def unsafe(section: str) -> bool:
    return any(c != "\n" and unicodedata.category(c) in record.HANDOVER_UNSAFE for c in section)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld plan handover", description=__doc__.split("\n")[0])
    ap.add_argument("file", metavar="FILE", help="the plan or the tracking-issue body")
    ap.add_argument("--kind", required=True, choices=KINDS, help="what the file is")
    ap.add_argument("--repo", required=True, metavar="OWNER/NAME", help="the repository the links belong to")
    ap.add_argument("--plan-slug", required=True, metavar="SLUG", help="the plan slug")
    ap.add_argument("--issue-url", metavar="URL", help="the tracking issue")
    ap.add_argument("--plan-url", metavar="URL", help="the plan on its branch")
    ap.add_argument("--spec-url", metavar="URL", help="the spec change on its branch")
    ap.add_argument("--command-prefix", metavar="PREFIX", help="/tld:implement or implement; needs --plan-url")
    args = ap.parse_args(argv)
    try:
        text = summary.read(args.file)
    except summary.ReadError as exc:
        return fail([str(exc)])
    problems, _ = summary.check(text, args.kind)
    if problems:
        return fail([f"summary: {p}" for p in problems])
    section = section_of(text)
    if unsafe(section):
        return fail([UNSAFE_MESSAGE])
    if len(section) > record.HANDOVER_MAX_CHARS:
        return fail([f"'handover.summary' has {len(section)} characters, at most {record.HANDOVER_MAX_CHARS} are allowed"])
    if ALLOW_MARK in section:
        return fail([f"the Summary must not contain '{ALLOW_MARK}'"])
    hits = secret_scan.scan_text(section)
    if hits:
        return fail([f"a secret-like value on line {n} of the Summary" for n, _, _ in hits])
    if args.command_prefix is not None and args.plan_url is None:
        return fail(["--command-prefix needs --plan-url"])
    obj = {
        "summary": section,
        "plan_slug": args.plan_slug,
        "issue_url": args.issue_url,
        "plan_url": args.plan_url,
        "spec_url": args.spec_url,
        "next_command": f"{args.command_prefix} {args.plan_url}" if args.command_prefix is not None else None,
    }
    errors = record.handover_errors(obj, args.repo)
    if errors:
        return fail(errors)
    flagged = [k for k, v in obj.items() if k != "summary" and isinstance(v, str)
               and (ALLOW_MARK in v or secret_scan.scan_text(v))]
    if flagged:
        return fail([f"'{k}' holds a secret-like value" for k in flagged])
    print(json.dumps(obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
