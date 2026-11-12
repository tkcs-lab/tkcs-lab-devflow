#!/usr/bin/env python3
"""Is another run of make-plan or implement already going on the same issue or plan.

    tld plan active-run --kind make-plan|implement --comments FILE --bot LOGIN
                        [--record FILE --plan-slug SLUG] [--self SESSION] [--now ISO] [--max-age-minutes N]

A hook sees one session's tool call, not another session, so the state lives in the tracking issue's comments
and on the status board. FILE is a JSON list of the issue's comments, oldest first, each
`{"author", "created_at", "body"}` (strings; `created_at` is `YYYY-MM-DDTHH:MM:SSZ`). Only comments by `--bot`
(the agent's own login, compared case-insensitively and exactly) are believed: a comment by anyone else is
neither a marker nor a sign of life. `--record` is the output of `tld board client get` (`{"id", "version",
"data"}`) or just its `data`; implement uses it with `--plan-slug`, make-plan ignores both.

A comment is a marker when its first line (after stripping the body) starts with one of these:

    kind        start                        final (any of)
    make-plan   Planning started.            Plan ready:, Planning stopped:
    implement   Implementation started on    PR opened:, Implementation stopped:

A start comment names its session as `Session: <id>.` at the end of its first line; no such token, or the
token `unknown`, `make-plan` or `implement`, means session `null`, which is never this run's own.

A run is open from a start marker to the next final marker. Its last sign of life is the newest later comment
by the bot or, for implement, the `updated_at` of a usable board record (the plan's `run` record, not
finished, newer than the last final comment). It prints one line of JSON: `{"state": "none"}`, or `state`
(`own`: the start carries `--self`; `active`: the last sign of life is at most `--max-age-minutes`, default
120, old; `stale`), `kind`, `session`, `started_at`, `last_seen`, `age_minutes` and `source` (`comment` or
`record`).

Exit codes: 4 for `active`; 0 for `none`, `own` and `stale`; 1 for bad input (`plan: <message>` on stderr).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

DEFAULT_MAX_AGE = timedelta(minutes=120)
MARKERS = {
    "make-plan": ("Planning started.", ("Plan ready:", "Planning stopped:")),
    "implement": ("Implementation started on ", ("PR opened:", "Implementation stopped:")),
}
SESSION = re.compile(r"Session: ([A-Za-z0-9_:-]{1,100})\.?$")
NOT_A_SESSION = {"unknown", "make-plan", "implement"}
FINISHED = {"done", "failed", "pr_open"}


class PlanError(Exception):
    pass


def parse(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def stamp(moment: datetime | None) -> str | None:
    return None if moment is None else moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def first_line(body: str) -> str:
    lines = body.strip().splitlines()
    return lines[0] if lines else ""


def session_of(line: str) -> str | None:
    m = SESSION.search(line)
    return None if m is None or m.group(1) in NOT_A_SESSION else m.group(1)


def record_data(record: dict) -> dict:
    data = record["data"] if "data" in record else record
    if not isinstance(data, dict):
        raise PlanError("the record's data is not an object")
    return data


def evaluate(kind: str, comments: list, bot: str, now: datetime, self_id: str | None = None,
             record: dict | None = None, plan_slug: str | None = None,
             max_age: timedelta = DEFAULT_MAX_AGE) -> dict:
    start, finals = MARKERS[kind]
    mine = []
    for comment in comments:
        if comment["author"].casefold() == bot.casefold():
            mine.append((parse(comment["created_at"]), comment["body"]))
    mine.sort(key=lambda item: item[0])

    run: dict | None = None
    last_final_at: datetime | None = None
    source = "comment"
    for created, body in mine:
        line = first_line(body)
        if line.startswith(finals):
            run, last_final_at = None, created
        elif line.startswith(start):
            run = {"started_at": created, "last_seen": created, "session": session_of(line)}
        elif run is not None:
            run["last_seen"] = created

    if kind == "implement" and record is not None and plan_slug is not None:
        data = record_data(record)
        try:
            updated = parse(data["updated_at"])
        except (KeyError, TypeError, ValueError):
            updated = None
        usable = (updated is not None and data.get("kind") == "run" and data.get("plan_slug") == plan_slug
                  and data.get("status") not in FINISHED
                  and (last_final_at is None or updated > last_final_at))
        if usable and run is not None:
            if updated > run["last_seen"]:
                run["last_seen"], source = updated, "record"
        elif usable:
            owner = data.get("orchestrator_session")
            run = {"started_at": None, "last_seen": updated, "session": owner if isinstance(owner, str) else None}
            source = "record"

    if run is None:
        return {"state": "none"}
    age = now - run["last_seen"]
    if run["session"] is not None and run["session"] == self_id:
        state = "own"
    elif age <= max_age:
        state = "active"
    else:
        state = "stale"
    return {"state": state, "kind": kind, "session": run["session"], "started_at": stamp(run["started_at"]),
            "last_seen": stamp(run["last_seen"]), "age_minutes": max(0, int(age / timedelta(minutes=1))),
            "source": source}


def load_json(path: str, what: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise PlanError(f"cannot read the {what} file {path}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise PlanError(f"the {what} file {path} is not valid JSON: {exc}") from exc


def load_comments(path: str) -> list:
    data = load_json(path, "comments")
    if isinstance(data, dict):
        data = data.get("comments")
    if not isinstance(data, list):
        raise PlanError("the comments file must hold a list of comments (or an object with a 'comments' list)")
    for i, comment in enumerate(data):
        if not isinstance(comment, dict):
            raise PlanError(f"comment {i} is not an object")
        for key in ("author", "created_at", "body"):
            if not isinstance(comment.get(key), str):
                raise PlanError(f"comment {i} has no string '{key}'")
        try:
            parse(comment["created_at"])
        except ValueError as exc:
            raise PlanError(f"comment {i} has a bad created_at {comment['created_at']!r} "
                            f"(want YYYY-MM-DDTHH:MM:SSZ)") from exc
    return data


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tld plan active-run", description="is another run of make-plan or "
                                "implement already going (exit 4: active)")
    p.add_argument("--kind", required=True, choices=["make-plan", "implement"])
    p.add_argument("--comments", required=True, metavar="FILE", help="JSON list of {author, created_at, body}")
    p.add_argument("--bot", required=True, metavar="LOGIN", help="the login whose comments count")
    p.add_argument("--record", metavar="FILE", help="output of `tld board client get` (implement)")
    p.add_argument("--plan-slug", metavar="SLUG", help="the plan the record must belong to (with --record)")
    p.add_argument("--self", dest="self_id", metavar="SESSION", help="this session's id")
    p.add_argument("--now", metavar="ISO", help="the instant to measure from (tests)")
    p.add_argument("--max-age-minutes", default="120", metavar="N", help="longest silence of a live run (120)")
    return p


def run(args: argparse.Namespace) -> dict:
    try:
        minutes = int(args.max_age_minutes)
    except ValueError:
        minutes = 0
    if minutes < 1:
        raise PlanError("--max-age-minutes must be an integer of at least 1")
    try:
        now = parse(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as exc:
        raise PlanError(f"--now must be YYYY-MM-DDTHH:MM:SSZ: {exc}") from exc
    comments = load_comments(args.comments)
    record = None
    if args.kind == "implement" and args.record:
        if not args.plan_slug:
            raise PlanError("--record needs --plan-slug")
        record = load_json(args.record, "record")
        if not isinstance(record, dict):
            raise PlanError("the record file must hold a JSON object")
        record_data(record)
    return evaluate(args.kind, comments, args.bot, now, args.self_id, record, args.plan_slug,
                    timedelta(minutes=minutes))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except (PlanError, ValueError, OSError, TypeError, KeyError) as exc:
        print(f"plan: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 4 if result["state"] == "active" else 0


if __name__ == "__main__":
    sys.exit(main())
