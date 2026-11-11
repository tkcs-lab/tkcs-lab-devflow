#!/usr/bin/env python3
"""The session side of the board inbox: post an ask, read its answers, cancel it, and the issue fallback.

    tld board ask FILE|- [--fallback-issue OWNER/REPO[#N]] [--mention LOGIN] [--profile FILE]
    tld board answers ID [--wait SECONDS] [--interval SECONDS]
    tld board answers --from-issue COMMENTS.json --ask FILE --self LOGIN [--owner LOGIN]... [--repo O/R] [--profile F]
    tld board cancel ID

`ask` validates the ask (src/tld/schema/ask.schema.json), posts it and prints its id. Exit 0 posted; 1 the ask
is invalid or the board refused it; 3 no board configured (and no --fallback-issue); 5 the board is not
configured or cannot be reached and --fallback-issue was given: stdout is then the exact comment body for that
issue (for OWNER/REPO without a number: the body of a new issue titled with the ask's title). This command
never writes to GitHub: the session posts the body with its own GitHub tool. The body mentions
--mention, else the profile's `git.owner_login`, else the repository owner.

`answers ID` prints the answers as one JSON object (question id -> answer) once the owner answered. Exit 0
answered; 3 still open (after --wait seconds of polling every --interval seconds); 4 cancelled; 1 not found,
no board, or the board cannot be reached.

`answers --from-issue` reads the replies to a fallback comment. COMMENTS.json is a JSON list of
{"author": LOGIN, "permission": admin|maintain|write|read|none, "body": TEXT}, oldest first, as the session
read them with its GitHub tools (the permission is the author's permission on the repository). Only comments
by the owner (every --owner, else the profile's `git.owner_login`, else the owner of --repo or of the ask's
`fallback_issue`) or by an author with `admin` permission count; `write` and `maintain` do not, since the agent
account itself has write. `--self` (also spelled `--ignore-author`), the session's own login, is required and
never counts, whatever its permission; nor does the fallback comment itself. In a counted comment every plain
line `<question id>: <answer>` that fits the question is an answer (a choice: an option value; a confirm: yes
or no; a text: the rest of the line); a later answer overrides an earlier one. Text a reader may not see, or
that quotes someone else, never counts: fenced (```` ``` ```` or `~~~`) and indented code blocks, `>` quotes,
HTML comments and `<blockquote>` / `<details>` blocks. Exit 0 with the answers JSON when every required question
has an answer, else 3 (stderr names the missing ones); 2 without --self or with no owner to count.

`cancel ID` cancels an open ask and prints {"id", "state"}. Exit 0 cancelled (or already cancelled); 1 not
found, already answered, or no board. Python 3.11+, stdlib + PyYAML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from tld.board import ask as ask_model
from tld.board import client as board_client

MARKER = "<!-- tld-ask -->"
COUNTED = ("admin",)  # besides the owner login(s); never write or maintain (the agent account has write)
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
ANSWER_LINE = re.compile(r"^`?([A-Za-z0-9][A-Za-z0-9_.-]{0,39})`?\s*:\s*(.*?)\s*$")
YES = ("yes", "y", "true")
NO = ("no", "n", "false")
EXIT_OPEN, EXIT_CANCELLED, EXIT_FALLBACK = 3, 4, 5


def _err(text: str) -> None:
    print(f"tld board: {text}", file=sys.stderr)


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _read_json(path: str) -> object:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def _quiet(text: str) -> str:
    """Text for a GitHub comment that cannot mention anyone (a zero-width space after every @)."""
    return text.replace("@", "@​")


# -- the fallback comment ------------------------------------------------------------------------

def owner_login(repo: str, mention: str | None, profile: str | None) -> str:
    """The login the fallback mentions: --mention, the profile's git.owner_login, the repository owner."""
    if mention:
        return mention
    path = Path(profile) if profile else Path(".tld/toolkit.yaml")
    if path.is_file():
        import yaml
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        login = ((data.get("git") or {}) if isinstance(data, dict) else {}).get("owner_login")
        if isinstance(login, str) and LOGIN_RE.match(login):
            return login
    return repo.split("/", 1)[0]


def fallback_comment(ask: dict, mention: str) -> str:
    """The comment body that asks the owner on GitHub; `answers_from_comments` reads the replies."""
    lines = [MARKER, f"@{mention} a tld session ({_quiet(ask['created_by'])}) needs your answers: "
                     f"**{_quiet(ask['title'])}**", ""]
    if ask.get("context_url"):
        lines += [f"Context: {ask['context_url']}", ""]
    example: list[str] = []
    for n, q in enumerate(ask["questions"], 1):
        need = "required" if ask_model.is_required(q) else "optional"
        text = _quiet(q["text"]).replace("\n", "\n   ")
        lines.append(f"{n}. `{q['id']}` ({q['kind']}, {need}): {text}")
        if q["kind"] == "choice":
            opts = ", ".join(f"`{o['value']}`" + (f" ({_quiet(o['label'])})" if o.get("label") else "")
                             for o in q["options"])
            lines.append(f"   Options: {opts}")
            example.append(f"{q['id']}: {q['options'][0]['value']}")
        elif q["kind"] == "confirm":
            lines.append("   Answer `yes` or `no`.")
            example.append(f"{q['id']}: yes")
        else:
            lines.append("   Answer on one line.")
            example.append(f"{q['id']}: your answer on one line")
    lines += ["", "Reply with one line per question, each at the start of its own line and not in a code block or a "
                  "quote. Example reply (copy the lines between the markers and change the answers):", "",
              "-- example reply --", "", *example, "", "-- end of example --",
              "", "Only replies by the repository owner or an admin count; the session's own account never does."]
    return "\n".join(lines) + "\n"


def _fits(question: dict, raw: str) -> object | None:
    if question["kind"] == "confirm":
        word = raw.strip().lower()
        return True if word in YES else False if word in NO else None
    return ask_model.check_value(question, raw)


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
BLOCK_OPEN = re.compile(r"<(blockquote|details)\b[^>]*>", re.I)
BLOCK_CLOSE = re.compile(r"</(blockquote|details)\s*>", re.I)


def visible_lines(body: str) -> list[str]:
    """The lines of a comment that are plain, visible text by its author: no code block, quote, HTML comment,
    <blockquote> or <details> block (S10)."""
    body = re.sub(r"<!--.*?(-->|$)", "", body, flags=re.S)  # an unclosed comment hides the rest
    out: list[str] = []
    fence: str | None = None
    depth = 0
    for line in body.splitlines():
        m = FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):].strip():
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        opened, closed = len(BLOCK_OPEN.findall(line)), len(BLOCK_CLOSE.findall(line))
        was = depth
        depth = max(0, depth + opened - closed)
        if was or opened:
            continue
        if line.startswith(("    ", "\t")) or line.strip().startswith(">"):
            continue
        out.append(line.strip())
    return out


def answers_from_comments(ask: dict, comments: list, ignore: str | None = None,
                          owners: list[str] | tuple[str, ...] = ()) -> dict:
    """The answers in the counted comments (the owners' and admins', never `ignore`'s), the later overriding."""
    questions = {q["id"]: q for q in ask["questions"]}
    owner_set = {o.lower() for o in owners}
    found: dict[str, object] = {}
    for c in comments:
        if not isinstance(c, dict):
            continue
        author, permission, body = c.get("author"), c.get("permission"), c.get("body")
        if not (isinstance(author, str) and isinstance(body, str)):
            continue
        if ignore and author.lower() == ignore.lower():
            continue
        if author.lower() not in owner_set and permission not in COUNTED:
            continue
        if MARKER in body:
            continue
        for stripped in visible_lines(body):
            m = ANSWER_LINE.match(stripped)
            if not m or m.group(1) not in questions:
                continue
            value = _fits(questions[m.group(1)], m.group(2))
            if value is not None:
                found[m.group(1)] = value
    return found


# -- commands ------------------------------------------------------------------------------------

def _config() -> board_client.Config | None:
    return board_client.load_config()


def cmd_ask(args: argparse.Namespace) -> int:
    try:
        ask = _read_json(args.file)
    except (OSError, ValueError) as exc:
        _err(f"cannot read the ask ({exc})")
        return 1
    if args.fallback_issue:
        if not ask_model.ISSUE_RE.match(args.fallback_issue):
            _err("--fallback-issue must be OWNER/REPO or OWNER/REPO#N")
            return 2
        if isinstance(ask, dict) and ask.get("fallback_issue") is None:
            ask["fallback_issue"] = args.fallback_issue
    if args.mention and not LOGIN_RE.match(args.mention):
        _err("--mention must be a GitHub login")
        return 2
    errors = ask_model.validate_new(ask)
    if errors:
        for e in errors:
            print(f"ask: {e}", file=sys.stderr)
        return 1
    assert isinstance(ask, dict)

    def fallback(reason: str) -> int:
        if not args.fallback_issue:
            _err(reason)
            return 3 if reason == "no board configured" else 1
        repo = args.fallback_issue.split("#", 1)[0]
        _err(f"{reason}: post the body below on {args.fallback_issue} (exit {EXIT_FALLBACK})")
        sys.stdout.write(fallback_comment(ask, owner_login(repo, args.mention, args.profile)))
        return EXIT_FALLBACK

    try:
        config = _config()
    except board_client.ConfigError as exc:
        return fallback(str(exc))
    if config is None:
        return fallback("no board configured")
    try:
        status, payload = board_client.call(config, "POST", "/api/asks", ask)
    except OSError as exc:
        return fallback(f"cannot reach the board ({type(exc).__name__})")
    if status >= 500:
        return fallback(f"the board answered HTTP {status}")
    if status != 201 or not isinstance(payload, dict) or "id" not in payload:
        if payload is not None:
            _emit(payload)
        _err(f"the board answered HTTP {status}")
        return 1
    print(payload["id"])
    return 0


def _get(config: board_client.Config, ask_id: str) -> tuple[int, object]:
    return board_client.call(config, "GET", "/api/asks/" + urllib.parse.quote(ask_id, safe=""))


def cmd_answers(args: argparse.Namespace) -> int:
    if args.from_issue:
        return answers_from_issue(args)
    if not args.id:
        _err("give an ask id, or --from-issue with --ask")
        return 2
    try:
        config = _config()
    except board_client.ConfigError as exc:
        _err(str(exc))
        return 1
    if config is None:
        _err("no board configured")
        return 1
    deadline = time.monotonic() + max(0, args.wait)
    interval = max(1.0, args.interval)
    while True:
        try:
            status, payload = _get(config, args.id)
        except OSError as exc:
            _err(f"cannot reach the board ({type(exc).__name__})")
            return 1
        if status != 200 or not isinstance(payload, dict):
            _err("no such ask" if status == 404 else f"the board answered HTTP {status}")
            return 1
        state = payload.get("state")
        if state == "answered":
            _emit(payload.get("answers") or {})
            return 0
        if state == "cancelled":
            _err(f"ask {args.id} was cancelled")
            return EXIT_CANCELLED
        left = deadline - time.monotonic()
        if left <= 0:
            _err(f"ask {args.id} is still open")
            return EXIT_OPEN
        time.sleep(min(interval, left))


def answers_from_issue(args: argparse.Namespace) -> int:
    if not args.ask:
        _err("--from-issue needs --ask FILE (the ask that was posted)")
        return 2
    if not args.ignore_author or not LOGIN_RE.match(args.ignore_author):
        _err("--from-issue needs --self LOGIN: the session's own login, whose comments never count")
        return 2
    for login in args.owner:
        if not LOGIN_RE.match(login):
            _err(f"--owner {login!r} is not a GitHub login")
            return 2
    try:
        ask = _read_json(args.ask)
        comments = _read_json(args.from_issue)
    except (OSError, ValueError) as exc:
        _err(f"cannot read the input ({exc})")
        return 1
    errors = ask_model.validate_new(ask)
    if errors or not isinstance(comments, list):
        for e in errors:
            print(f"ask: {e}", file=sys.stderr)
        if not isinstance(comments, list):
            _err("COMMENTS.json must be a JSON list of {author, permission, body}")
        return 1
    owners = list(args.owner)
    if not owners:
        issue = args.repo or (ask.get("fallback_issue") if isinstance(ask.get("fallback_issue"), str) else "")
        repo = issue.split("#", 1)[0] if ask_model.ISSUE_RE.match(issue) else ""
        login = owner_login(repo or "/", None, args.profile)
        if not LOGIN_RE.match(login):
            _err("no owner to count: pass --owner LOGIN, set git.owner_login, or post the ask with --fallback-issue")
            return 2
        owners = [login]
    found = answers_from_comments(ask, comments, args.ignore_author, owners)
    missing = [q["id"] for q in ask["questions"] if ask_model.is_required(q) and q["id"] not in found]
    if missing:
        _err("no answer yet for: " + ", ".join(missing))
        return EXIT_OPEN
    _emit(found)
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    try:
        config = _config()
    except board_client.ConfigError as exc:
        _err(str(exc))
        return 1
    if config is None:
        _err("no board configured")
        return 1
    try:
        status, payload = board_client.call(
            config, "POST", "/api/asks/" + urllib.parse.quote(args.id, safe="") + "/cancel")
    except OSError as exc:
        _err(f"cannot reach the board ({type(exc).__name__})")
        return 1
    if status == 200 and isinstance(payload, dict):
        _emit({"id": payload["id"], "state": payload["state"]})
        return 0
    _err({404: "no such ask", 409: "the ask is already answered"}.get(status, f"the board answered HTTP {status}"))
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tld board", description="The session side of the board inbox.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", prog="tld board ask", help="post an ask; prints its id")
    ask.add_argument("file", help="the ask as JSON, or - for stdin")
    ask.add_argument("--fallback-issue", dest="fallback_issue", metavar="OWNER/REPO[#N]",
                     help="without a reachable board, print the issue comment body and exit 5")
    ask.add_argument("--mention", help="the login the fallback comment mentions")
    ask.add_argument("--profile", help="the profile to read git.owner_login from (default .tld/toolkit.yaml)")
    answers = sub.add_parser("answers", prog="tld board answers", help="print the answers of an ask")
    answers.add_argument("id", nargs="?", help="the ask id")
    answers.add_argument("--wait", type=float, default=0, help="poll up to this many seconds while open")
    answers.add_argument("--interval", type=float, default=10, help="seconds between polls (at least 1)")
    answers.add_argument("--from-issue", dest="from_issue", metavar="COMMENTS.json",
                         help="read the answers from the replies to a fallback comment")
    answers.add_argument("--ask", help="with --from-issue: the ask file that was posted")
    answers.add_argument("--self", "--ignore-author", dest="ignore_author", metavar="LOGIN",
                         help="with --from-issue (required): the session's own login, never an answer")
    answers.add_argument("--owner", action="append", default=[], metavar="LOGIN",
                         help="with --from-issue: a login whose replies count (default: git.owner_login, else "
                              "the repository owner); admins count too")
    answers.add_argument("--repo", metavar="OWNER/REPO", help="with --from-issue: the repository whose owner counts "
                                                              "when the profile has no git.owner_login")
    answers.add_argument("--profile", help="with --from-issue: the profile to read git.owner_login from")
    cancel = sub.add_parser("cancel", prog="tld board cancel", help="cancel an open ask")
    cancel.add_argument("id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"ask": cmd_ask, "answers": cmd_answers, "cancel": cmd_cancel}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
