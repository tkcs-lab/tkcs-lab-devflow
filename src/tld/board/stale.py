#!/usr/bin/env python3
"""Print the ids of the status records the board hides, and of the ones the owner dismissed (the ones /board prune may delete).

    board_stale.py [FILE|-] [--now ISO]

Reads a JSON list of {"id", "data"} documents (FILE, or stdin for - or no argument) and prints one
id per line for every record whose board section is `hidden`. The rule is the one in
src/tld/board/web/rules.js, re-implemented here; a record the owner dismissed
(the entry's `dismissed_at` is a string) is printed whatever its state. A record still under a legacy id
(`legacy_ids`) is also printed once it is more than 24 hours old, even with needs_you true.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from tld.board.record import legacy_ids

WEEK = timedelta(days=7)
LEGACY_HIDE = timedelta(hours=24)


def parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def section(rec: dict, now: datetime, dismissed: bool = False) -> str:
    if dismissed:
        return "hidden"
    if rec.get("needs_you") is True:
        return "needs_you"
    if now - parse(rec["updated_at"]) > WEEK:
        return "hidden"
    if rec.get("status") == "pr_open":
        return "pr_open"
    if rec.get("finished_at") and now - parse(rec["finished_at"]) <= WEEK:
        return "done"
    if rec.get("status") in ("done", "failed"):
        return "hidden"
    return "running"


def legacy_stale(doc: dict, now: datetime) -> bool:
    """A record under a legacy document id that has not been updated for more than 24 hours."""
    try:
        return doc["id"] in legacy_ids(doc["data"]) and now - parse(doc["data"]["updated_at"]) > LEGACY_HIDE
    except (ValueError, KeyError, TypeError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the ids of hidden status records.")
    parser.add_argument("file", nargs="?", default="-", help="JSON list of {id, data}, or - for stdin")
    parser.add_argument("--now", help="the instant to use instead of the clock, YYYY-MM-DDTHH:MM:SSZ")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        docs = json.loads(text)
        now = parse(args.now) if args.now else datetime.now(timezone.utc)
        hidden = [doc["id"] for doc in docs
                  if section(doc["data"], now, isinstance(doc.get("dismissed_at"), str)) == "hidden" or legacy_stale(doc, now)]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"board_stale: cannot read the records ({exc})", file=sys.stderr)
        return 1
    for doc_id in hidden:
        print(doc_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
