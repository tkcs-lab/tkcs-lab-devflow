#!/usr/bin/env python3
"""The gate of a research hand-off: check a prompt before it is posted, take the report out of the reply.

    tld research check-prompt FILE [--forbid TEXT]...
    tld research report --id ID --reply FILE|- [--rest FILE]

`check-prompt` exit 0 prints `research prompt: OK (<n> characters)`; exit 1 prints one line per problem
(too long, first line, sections, character, secret, forbidden, report format); exit 2 an unreadable file.

`report` prints the marked report block of ID from the owner's reply. A block starts at `RESEARCH-REPORT <id>`
and ends at the last `END RESEARCH-REPORT <id>` after it, so a forged end line inside web text cannot end it
early. With --rest FILE only the lines before the first start line are written there (on every exit code
except 2): whatever follows may be web text, so it can never answer an ask. Exit 0 the body; 1 the report is for another id, too long
or has no `Answer:` line; 2 an unreadable reply, a bad --id; 3 no complete report for ID.
Python 3.11+, stdlib + the toolkit.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

from tld.board.ask import BAD_CHARS
from tld.guard.secret_scan import ALLOW_MARK, scan_text

ID_RE = re.compile(r"r-[0-9]{8}-[0-9]{1,2}")
MAX_PROMPT = 1800
MAX_REPORT = 3500
SECTIONS = ("Question:", "Public context:", "Constraints:", "What would settle it:",
            "Rules for the researcher:", "Report format")
SECRET_ENV = ("TLD_BOARD_URL", "TLD_BOARD_TOKEN")
# C1 controls, line separators, variation selectors, combining grapheme joiner and blank fillers; the rest of
# what is hidden is found by category (Cf, Co, Cn, Cs)
INVISIBLE = re.compile("[\x80-\x9f\u2028\u2029\u034f\u115f\u17b4\u17b5\u180b-\u180f\u1160\u2800\u3164\uffa0\ufe00-\ufe0f\U000e0100-\U000e01ef]")
HIDDEN_CATEGORIES = ("Cf", "Co", "Cn", "Cs")
START = "RESEARCH-REPORT "
END = "END RESEARCH-REPORT "


def _err(text: str) -> None:
    print(f"tld research: {text}", file=sys.stderr)


def _hidden(ch: str) -> bool:
    return unicodedata.category(ch) in HIDDEN_CATEGORIES or bool(INVISIBLE.match(ch))


def _squash(text: str) -> str:
    return "".join(_plain(text).lower().split())


def _plain(text: str) -> str:
    """The text as a reader or a scanner sees it: no invisible character, compatibility forms folded."""
    return unicodedata.normalize("NFKC", "".join(ch for ch in text if not _hidden(ch)))


def _first_id(lines: list[str]) -> str | None:
    head = lines[0].strip() if lines else ""
    rid = head[len("Research "):] if head.startswith("Research ") else ""
    return rid if ID_RE.fullmatch(rid) else None


def check_prompt(text: str, forbid: list[str], env: dict[str, str]) -> list[str]:
    """The problems of a research prompt, empty when fine. Never contains a secret or a forbidden value."""
    problems: list[str] = []
    lines = text.splitlines()
    if len(text) > MAX_PROMPT:
        problems.append(f"too long: {len(text)} characters, at most {MAX_PROMPT}")
    rid = _first_id(lines)
    if rid is None:
        problems.append("first line: must be `Research <id>` with an id like r-20261112-1")
    at = [next((i for i, line in enumerate(lines) if line.startswith(name)), -1) for name in SECTIONS]
    if -1 in at or at != sorted(at):
        problems.append("sections: need these lines once, in this order: " + ", ".join(SECTIONS))
    if BAD_CHARS.search(text) or any(_hidden(ch) for ch in text):
        problems.append("character: a control, invisible or bidirectional character")
    plain = _plain(text)
    for n, name, _ in scan_text(plain):
        problems.append(f"secret: line {n} looks like a credential ({name})")
    for n, line in enumerate(plain.splitlines(), 1):
        if ALLOW_MARK in line:
            problems.append(f"secret: line {n} has `{ALLOW_MARK}`, which lets a token past the scan")
    low = plain.lower()
    squashed = _squash(plain)
    for i, value in enumerate(forbid, 1):
        want = _squash(value)  # a value with nothing visible left in it matches nothing
        if want and (_plain(value).lower() in low or want in squashed):
            problems.append(f"forbidden: --forbid {i} appears in the prompt")
    for name in SECRET_ENV:
        value = _plain(env.get(name, "")).strip()
        try:
            host = urlsplit(value).hostname or ""
        except ValueError:  # a malformed URL has no host to compare, the value itself still counts
            host = ""
        needles = {value, value.rstrip("/"), host if len(host) >= 4 else ""}
        if any(len(n) >= 4 and (n.lower() in low or _squash(n) in squashed) for n in needles):
            problems.append(f"forbidden: the value of {name} appears in the prompt")
    if rid is not None:
        stripped = {line.strip() for line in lines}
        if START + rid not in stripped or END + rid not in stripped:
            problems.append(f"report format: need the lines `{START}{rid}` and `{END}{rid}`")
    return problems


def split_reply(text: str, rid: str) -> tuple[str, str, str]:
    """(status, body, rest) of the reply: the report block of `rid`, and the reply without any block."""
    lines = text.splitlines()
    blocks: list[tuple[str, list[str], bool]] = []
    rest: list[str] = []  # the lines before the first block; what follows is never the owner's
    i = 0
    while i < len(lines):
        head = _plain(lines[i]).strip()
        bid = head[len(START):] if head.startswith(START) else ""
        if not ID_RE.fullmatch(bid):
            if not blocks:
                rest.append(lines[i])
            i += 1
            continue
        end = max((j for j in range(i + 1, len(lines)) if _plain(lines[j]).strip() == END + bid), default=-1)
        if end < 0:
            blocks.append((bid, lines[i + 1:], False))
            break
        blocks.append((bid, lines[i + 1:end], True))
        i = end + 1
    rest_text = "\n".join(rest)
    mine = [b for b in blocks if b[0] == rid]
    if not mine:
        status = f"other:{blocks[0][0]}" if blocks else "incomplete"
        return status, "", rest_text
    if not mine[0][2]:
        return "incomplete", "", rest_text
    body = "".join(ch for ch in "\n".join(mine[0][1]) if not BAD_CHARS.match(ch) and not _hidden(ch)).rstrip()
    if len(body) > MAX_REPORT:
        return f"too long:{len(body)}", body, rest_text
    if not any(line.strip().startswith("Answer:") for line in body.splitlines()):
        return "no answer", body, rest_text
    return "ok", body, rest_text


def _read(path: str) -> str:
    return sys.stdin.buffer.read().decode("utf-8") if path == "-" else Path(path).read_bytes().decode("utf-8")


def _check_prompt(args: argparse.Namespace) -> int:
    try:
        text = Path(args.file).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        _err("cannot read the prompt file")
        return 2
    if "" in args.forbid:
        _err("--forbid needs a non-empty text")
        return 2
    problems = check_prompt(text, args.forbid, dict(os.environ))
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"research prompt: OK ({len(text)} characters)")
    return 0


def _report(args: argparse.Namespace) -> int:
    if not ID_RE.fullmatch(args.id):
        _err("--id is not an id like r-20261112-1")
        return 2
    try:
        reply = _read(args.reply)
    except (OSError, UnicodeDecodeError):
        _err("cannot read the reply")
        return 2
    status, body, rest = split_reply(reply, args.id)
    if args.rest:
        try:
            Path(args.rest).write_text(rest + "\n" if rest else "", encoding="utf-8")
        except OSError:
            _err("cannot write --rest")
            return 2
    if status == "ok":
        print(body)
        return 0
    if status == "incomplete":
        _err(f"no complete report for {args.id}")
        return 3
    if status.startswith("other:"):
        _err(f"report is for {status[len('other:'):]}")
    elif status.startswith("too long:"):
        _err(f"report is {status[len('too long:'):]} characters, at most {MAX_REPORT}")
    else:
        _err("report has no Answer: line")
    return 1


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # a fixed text: the message may quote a --forbid value
        _err("bad arguments (see --help)")
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="tld research", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True, parser_class=_Parser)
    check = sub.add_parser("check-prompt", help="check a research prompt before it is posted")
    check.add_argument("file", help="the filled prompt")
    check.add_argument("--forbid", action="append", default=[], metavar="TEXT",
                       help="a text that must not appear (repeatable, case-insensitive)")
    rep = sub.add_parser("report", help="the marked report of the owner's reply")
    rep.add_argument("--id", required=True, help="the research id, e.g. r-20261112-1")
    rep.add_argument("--reply", required=True, help="the reply file, or - for stdin")
    rep.add_argument("--rest", help="write the reply without any report block to this file")
    args = parser.parse_args(argv)
    return {"check-prompt": _check_prompt, "report": _report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
