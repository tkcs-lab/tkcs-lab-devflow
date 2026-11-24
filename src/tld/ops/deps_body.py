#!/usr/bin/env python3
"""Render the combined dependency pull request body from validated entries.

  tld ops deps-body FILE

FILE is at most 1000000 bytes of JSON `{"entries": [...]}` (1 to 100 entries, one per Dependabot group or audit
fix): ecosystem, directory, pr, security, updates, moves, files, state (`included` or `left_out`), reason, file.
Every value is checked against a fixed form and written in a code span, so text from a pull request, a changelog
or an audit report cannot mention a user, close an issue or add markup. Prints the body (a `## Summary` that
passes `tld plan summary-check --kind pr`, the Updates table, the action moves and what was left out) and exits 0;
on a bad input prints `deps: entry <i>: <key>: <problem>` (or `deps: no included entry`) to stderr, nothing to
stdout, and exits 1. Reads one file, runs nothing. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from tld.ops.deps_checks import FILE_REASONS, is_workflow

MAX_BYTES = 1000000
MAX_ENTRIES = 100
MAX_UPDATES = 50
MAX_MOVES = 50
MAX_FILES = 200
MAX_PR = 10 ** 9
LISTED = 5  # items a list in the Summary names before `and <m> more`
MAX_PACKAGES_FOCUS = 3

ECOSYSTEM = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
DIRECTORY = re.compile(r"/[A-Za-z0-9._/-]{0,199}")
PACKAGE = re.compile(r"[A-Za-z0-9@][A-Za-z0-9@._/+-]{0,99}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,49}")
ACTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]{1,99}")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
PATH = re.compile(r"[A-Za-z0-9._@+-][A-Za-z0-9._/@+-]{0,199}")

KEYS = {"ecosystem", "directory", "pr", "security", "updates", "moves", "files", "state", "reason", "file"}
REQUIRED = ("ecosystem", "directory", "pr", "security", "updates", "state")

REASONS = {
    "verify-red": "red after two fix attempts",
    "does-not-apply": "its changes do not apply on the main branch",
    "no-change": "the update is already on the main branch",
    "lock-uncovered": "no lock command covers {file}",
    "lockfile-only": "it changes only lockfiles, which a lock command cannot reproduce",
    "lock-other-files": "its lock command changed files outside its lockfiles",
    "not-bot-authored": "its branch has commits not made by the dependency bot",
    "protected-path": "it changes the protected path {file}",
    "unexpected-change": "it adds a link or a submodule or changes a file mode ({file})",
    "workflow-not-a-bump": "it changes {file} beyond action versions",
    "conflicts-with-others": "red only together with the other updates",
    "push-refused": "the push of its workflow files was refused",
    "time-budget": "not combined: time budget used",
}


class BodyError(Exception):
    """Printed as `deps: <message>`."""


def fail(i: int, key: str, problem: str):
    raise BodyError(f"entry {i}: {key}: {problem}")


def text(value, pattern: re.Pattern, no_dots: bool = False) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None and not (no_dots and ".." in value)


def check_list(i: int, key: str, value, limit: int) -> list:
    if not isinstance(value, list):
        fail(i, key, "must be a list")
    if len(value) > limit:
        fail(i, key, f"more than {limit} items")
    return value


def check_item(i: int, key: str, item, fields: dict) -> None:
    if not isinstance(item, dict) or set(item) != set(fields):
        fail(i, key, "an item must have exactly the keys " + ", ".join(fields))
    for name, ok in fields.items():
        if not ok(item[name]):
            fail(i, f"{key}.{name}", "not an allowed value")


def check_entry(i: int, e) -> dict:
    if not isinstance(e, dict):
        fail(i, "entry", "must be an object")
    for key in e:
        if key not in KEYS:
            fail(i, "keys", "unknown key")
    for key in REQUIRED:
        if key not in e:
            fail(i, key, "missing")
    if not text(e["ecosystem"], ECOSYSTEM):
        fail(i, "ecosystem", "not an allowed value")
    if not text(e["directory"], DIRECTORY, no_dots=True):
        fail(i, "directory", "not an allowed value")
    pr = e["pr"]
    if pr is not None and not (type(pr) is int and 0 < pr <= MAX_PR):
        fail(i, "pr", "must be a positive integer or null")
    if type(e["security"]) is not bool:
        fail(i, "security", "must be true or false")
    version = lambda v: text(v, VERSION)  # noqa: E731
    optional = lambda v: v is None or text(v, VERSION)  # noqa: E731
    for item in check_list(i, "updates", e["updates"], MAX_UPDATES):
        check_item(i, "updates", item, {"package": lambda v: text(v, PACKAGE), "from": optional, "to": version})
    if not e["updates"] and pr is None:
        fail(i, "updates", "empty without a pull request number")
    moves = check_list(i, "moves", e.get("moves", []), MAX_MOVES)
    for item in moves:
        check_item(i, "moves", item, {"action": lambda v: text(v, ACTION, True), "from": lambda v: text(v, REF),
                                      "to": lambda v: text(v, REF)})
    for path in check_list(i, "files", e.get("files", []), MAX_FILES):
        if not text(path, PATH, True):
            fail(i, "files", "not an allowed path")
    state, reason, file = e["state"], e.get("reason"), e.get("file")
    if state not in ("included", "left_out") or not isinstance(state, str):
        fail(i, "state", "must be included or left_out")
    if state == "included" and reason is not None:
        fail(i, "reason", "must be null for an included entry")
    if state == "left_out" and not (isinstance(reason, str) and reason in REASONS):
        fail(i, "reason", "not a known reason")
    if file is not None and not text(file, PATH, True):
        fail(i, "file", "not an allowed path")
    if file is not None and reason not in FILE_REASONS:
        fail(i, "file", "only with a reason that names a file")
    return {"ecosystem": e["ecosystem"], "directory": e["directory"], "pr": pr, "security": e["security"],
            "updates": e["updates"], "moves": moves, "files": e.get("files", []), "state": state,
            "reason": reason, "file": file}


def parse(data: bytes) -> list[dict]:
    if len(data) > MAX_BYTES:
        raise BodyError(f"the input is larger than {MAX_BYTES} bytes")
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise BodyError("the input is not valid JSON") from None
    if not isinstance(doc, dict) or set(doc) != {"entries"} or not isinstance(doc["entries"], list):
        raise BodyError('the input must be {"entries": [...]}')
    if not 1 <= len(doc["entries"]) <= MAX_ENTRIES:
        raise BodyError(f"entries: 1 to {MAX_ENTRIES} entries are allowed")
    entries = [check_entry(i, e) for i, e in enumerate(doc["entries"])]
    if not any(e["state"] == "included" for e in entries):
        raise BodyError("no included entry")
    return entries


def order(entry: dict):
    first = entry["updates"][0]["package"] if entry["updates"] else ""
    return (not entry["security"], entry["ecosystem"], entry["directory"], entry["pr"] or 0, first)


def code(value) -> str:
    return f"`{value}`"


def label(e: dict) -> str:
    return code(f"{e['ecosystem']} {e['directory']}")


def pr_ref(e: dict) -> str:
    return code(f"#{e['pr']}" if e["pr"] else "audit")


def listed(items: list[str]) -> str:
    """At most LISTED items, then `and <m> more`; the items are already formatted."""
    shown = ", ".join(items[:LISTED])
    return shown + (f" and {len(items) - LISTED} more" if len(items) > LISTED else "")


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def major(old, new: str) -> bool:
    if old is None:
        return False
    old, new = old.removeprefix("v"), new.removeprefix("v")
    return old[:1].isdigit() and new[:1].isdigit() and old.split(".")[0] != new.split(".")[0]


def reason_text(e: dict) -> str:
    return REASONS[e["reason"]].replace("{file}", code(e["file"]) if e["file"] else "a file")


def move_text(m: dict) -> str:
    return f"{code(m['action'])} {code(m['from'])} to {code(m['to'])}"


def render(entries: list[dict]) -> str:
    entries = sorted(entries, key=order)
    inc = [e for e in entries if e["state"] == "included"]
    out = [e for e in entries if e["state"] == "left_out"]
    updates = [(e, u) for e in inc for u in e["updates"]]
    moves = [(e, m) for e in inc for m in e["moves"]]
    wf_files = unique([f for e in inc for f in e["files"] if is_workflow(f)])
    secure = [e for e in inc if e["security"]]

    if out:
        names = [f"{label(e)} ({pr_ref(e)})" for e in out]
        noun = "update" if len(out) == 1 else "updates"
        deviations = f"Left out {len(out)} {noun}: {listed(names)}; see Left out."
    else:
        deviations = "None."
    ecosystems = listed(sorted({e["ecosystem"] for e in inc}))
    scope = (f"{len(updates)} package update{'' if len(updates) == 1 else 's'} in {len(inc)} "
             f"group{'' if len(inc) == 1 else 's'} ({ecosystems}); lockfiles come from the profile's lock commands.")

    lines = ["## Summary", "", f"**Deviations:** {deviations}", f"**Scope:** {scope}"]
    if secure or wf_files or moves:
        parts = []
        if secure:
            packages = unique([code(u["package"]) for e in secure for u in e["updates"]])
            parts.append(f"Audit fixes: {listed(packages)}." if packages else "Audit fixes: see the Updates table.")
        if wf_files:
            parts.append(f"Workflow files changed: {listed([code(f) for f in wf_files])}.")
        if moves:
            parts.append(f"Action moves: {listed([move_text(m) for _, m in moves])}.")
        lines.append(f"**Security:** {' '.join(parts)}")
    focus = []
    if secure:
        names = unique([code(u["package"]) for e in secure for u in e["updates"]]) or unique(
            [pr_ref(e) for e in secure])
        focus.append(f"Security updates first: {', '.join(names[:MAX_PACKAGES_FOCUS])}.")
    jumps = [f"{code(u['package'])} {code(u['from'])} to {code(u['to'])}" for _, u in updates
             if major(u["from"], u["to"])]
    if jumps:
        focus.append(f"Major version jumps: {', '.join(jumps[:MAX_PACKAGES_FOCUS])}.")
    lines.append(f"**Review focus:** {' '.join(focus) or 'The version changes in the Updates table.'}")

    lines += ["", "## Updates", "", "| Group | Dependabot PR | Package | From | To | Security |",
              "|---|---|---|---|---|---|"]
    for e in inc:
        sec = "yes" if e["security"] else "no"
        rows = e["updates"] or [None]
        for u in rows:
            if u is None:
                cells = [code(f"see #{e['pr']}"), "-", "-"]
            else:
                cells = [code(u["package"]), "new" if u["from"] is None else code(u["from"]), code(u["to"])]
            lines.append(f"| {label(e)} | {pr_ref(e)} | " + " | ".join(cells) + f" | {sec} |")
    if moves:
        lines += ["", "## Action moves", ""]
        lines += [f"- {label(e)} ({pr_ref(e)}): {move_text(m)}" for e, m in moves]
    if out:
        lines += ["", "## Left out", ""]
        for e in out:
            tail = ("Its Dependabot pull request stays open." if e["pr"] else "It has no Dependabot pull request.")
            lines.append(f"- {label(e)} ({pr_ref(e)}): {reason_text(e)}. {tail}")
    lines += ["", "The Dependabot pull requests of the included updates stay open; Dependabot closes each one once "
                  "its update is on the main branch.", ""]
    return "\n".join(lines)


def read(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(MAX_BYTES + 1)
    except OSError as exc:
        raise BodyError(f"cannot read the input file: {exc.strerror or type(exc).__name__}") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld ops deps-body", description=__doc__.split("\n\n")[0])
    ap.add_argument("file", metavar="FILE", help='JSON {"entries": [...]}, at most 1000000 bytes')
    args = ap.parse_args(argv)
    try:
        body = render(parse(read(args.file)))
    except BodyError as exc:
        print(f"deps: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
