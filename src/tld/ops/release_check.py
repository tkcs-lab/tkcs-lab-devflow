#!/usr/bin/env python3
"""Is a commit green? The one definition of green for a release, shared with the tld-release workflow template.

Usage: release_check.py [--checks FILE|-] [--status FILE] [--self NAME]... [--sha SHA]

`--checks` holds the check runs of the commit: the JSON of the check-runs API (an object with `check_runs`), a JSON
list, or JSON objects one after another (`gh api --paginate --jq '.check_runs[]'`), each with `name`, `status` and
`conclusion`. `--status` holds the combined commit status (`state`, `total_count`); without it the status is not
checked. A run named by `--self` is left out. A check run is green when it is completed with the conclusion success,
skipped or neutral. The combined status is green unless it is failure or error, or pending while at least one status
exists (a commit without statuses reports pending with a total of 0).

Exit 0 green (`release-check: green ...`); 3 nothing is red but a check or the status is still running
(`release-check: waiting`); 1 something is red (`release-check: red`); 2 a usage error or unreadable input.
After the first line come the lines `red: <name>: <status> <conclusion>` and `waiting: <...>`.

The part between BEGIN GREEN RULE and END GREEN RULE is copied verbatim into the template
src/tld/templates/tld-release.yml; tests/core/test_release_workflow.py fails when the two differ.
"""
from __future__ import annotations

import argparse
import json
import sys

# BEGIN GREEN RULE
GOOD = ("success", "skipped", "neutral")


def load_runs(text):
    """The check runs: a check-runs API answer, a JSON list, or JSON values one after another (gh api --paginate)."""
    runs, pos, decoder = [], 0, json.JSONDecoder()
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return runs
        data, pos = decoder.raw_decode(text, pos)
        if isinstance(data, dict) and "check_runs" in data:
            if not isinstance(data["check_runs"], list):
                raise ValueError("check_runs is not a list")
            runs += data["check_runs"]
        elif isinstance(data, list):
            runs += data
        else:
            runs.append(data)


def judge(runs, state, total, skip=()):
    """(red, waiting): the lines that stop a release, from the check runs and the combined status."""
    red, waiting = [], []
    for run in runs:
        if run.get("name") in skip:
            continue
        line = f"{run.get('name')}: {run.get('status')} {run.get('conclusion') or ''}".rstrip()
        if run.get("status") != "completed":
            waiting.append(line)
        elif run.get("conclusion") not in GOOD:
            red.append(line)
    if state in ("failure", "error"):
        red.append(f"commit status: {state}")
    elif state == "pending" and total != 0:
        waiting.append("commit status: pending")
    return red, waiting
# END GREEN RULE


def read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="release_check.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--checks", default="-", help="check runs: a file, or - for stdin")
    ap.add_argument("--status", help="combined commit status JSON; without it the status is not checked")
    ap.add_argument("--self", dest="skip", action="append", default=[], help="name of a check run to leave out")
    ap.add_argument("--sha", default="", help="the commit, echoed in the first line")
    args = ap.parse_args(argv)
    try:
        text = read(args.checks)
        if not text.strip():
            raise ValueError("no check runs given (write [] when there are none)")
        runs = load_runs(text)
        status = json.loads(read(args.status)) if args.status else None
        if not all(isinstance(r, dict) for r in runs):
            raise ValueError("the check runs are not a list of objects")
        if status is not None and not isinstance(status, dict):
            raise ValueError("the status is not an object")
    except (OSError, ValueError) as exc:
        print(f"release-check: {exc}", file=sys.stderr)
        return 2
    state, total = (status.get("state"), status.get("total_count")) if status else (None, None)
    red, waiting = judge(runs, state, total, tuple(args.skip))
    where = f" {args.sha}" if args.sha else ""
    counted = len([r for r in runs if r.get("name") not in args.skip])
    if red:
        print(f"release-check: red{where}")
    elif waiting:
        print(f"release-check: waiting{where}")
    else:
        note = "" if status else ", commit status not checked"
        print(f"release-check: green{where} ({counted} check(s){note})")
    for line in red:
        print(f"red: {line}")
    for line in waiting:
        print(f"waiting: {line}")
    return 1 if red else 3 if waiting else 0


if __name__ == "__main__":
    sys.exit(main())
