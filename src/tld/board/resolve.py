#!/usr/bin/env python3
"""Clear the "needs you" of a status record whose pull requests are all merged or closed.

    board_resolve.py FILE|- --now ISO --reason TEXT

FILE (or stdin for -) is a bare status record or a board entry {"id", "version", "data"}; an entry is
recognised by its `data` key. Prints the cleared record as JSON: needs_you false, needs_you_reason "",
needs_you_since null, status done, finished_at and updated_at --now, next_check_at null, last_event
--reason (at most 200 characters). Exit 1 with a `board_resolve: ` line when the record does not need
you, the reason is empty or too long, or the result fails the record validator. Never reads the network.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys

from tld.board import record

MAX_REASON = 200


def resolve(rec: dict, now: str, reason: str) -> dict:
    """The cleared copy of `rec`; raises ValueError with the message when it cannot be cleared."""
    if not isinstance(rec, dict):
        raise ValueError("the record must be a JSON object")
    if rec.get("needs_you") is not True:
        raise ValueError("the record does not need you")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("--reason must not be empty")
    if len(reason) > MAX_REASON:
        raise ValueError(f"--reason must be at most {MAX_REASON} characters")
    out = copy.deepcopy(rec)
    out.update({
        "needs_you": False, "needs_you_reason": "", "needs_you_since": None, "status": "done",
        "finished_at": now, "next_check_at": None, "updated_at": now, "last_event": reason,
    })
    errors = record.validate(out)
    if errors:
        raise ValueError("the cleared record is not valid: " + "; ".join(errors))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear needs_you of a status record.")
    parser.add_argument("file", help="a status record or a board entry as JSON, or - for stdin")
    parser.add_argument("--now", required=True, help="the instant, YYYY-MM-DDTHH:MM:SSZ")
    parser.add_argument("--reason", required=True, help="the last_event text, at most 200 characters")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        doc = json.loads(text)
        rec = doc["data"] if isinstance(doc, dict) and "data" in doc else doc
        out = resolve(rec, args.now, args.reason)
    except (OSError, ValueError) as exc:
        print(f"board_resolve: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
