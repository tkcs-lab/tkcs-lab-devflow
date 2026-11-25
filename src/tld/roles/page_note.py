#!/usr/bin/env python3
"""Say that the HTML change report page was not stored, and print it ahead of the change-report block.

    tld roles page-note --stage role|check|board|send [--stderr FILE] [--sent]
    tld roles change-report --report FILE [--note FILE]

`page-note` prints exactly one line and exits 0. The line is built only from fixed text, a reason that
`tld.roles.reflektor.known_reason` accepts, and a three-digit board status. FILE (`--stderr`) is read as bytes,
at most 20000, decoded with replacement; an unreadable file counts as empty. `--sent` (board only) adds that the
page went to the owner as a file. A missing stage, or `--sent` with another stage, exits 2.

`change-report` prints the note, a blank line and the cleaned block of the report, produced by the functions of
`tld.roles.section` exactly as `tld roles section --report FILE` does. With no note (not given, missing or
empty) its output and exit codes are those of `section --report`. A note must pass `valid_note`, else the
command exits 1 with `tld roles: the page note is not a page-note line`. A valid note with no usable block
prints the note alone and exits 0. The note comes first because this command prints it: text inside the role's
own block cannot forge or move it. Python 3.11+, standard library and the tld modules.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata

from tld.plan.summary import UNSAFE, scrub
from tld.roles.reflektor import known_reason
from tld.roles.section import _read, _suspect, clean, extract

NOTE = "HTML page not stored: "
SENT = " It was sent to the owner as a file instead."
READ_LIMIT = 20000
REFLEKTOR = "tld roles: reflektor: "
CHECK_OPEN = "the page check refused it ("

_STATUS = re.compile(r"the server answered HTTP ([0-9]{3})(?![0-9])")
_FIXED = (
    "the reflektor role built no checked page.",
    "the page check refused it.",
    "the page could not be sent as a file.",
)
_BOARD_FIXED = (
    "the page is too large to upload.",
    "the board cannot be reached.",
    "the board did not accept it.",
)
_BOARD_STATUS = re.compile(r"the board answered HTTP [0-9]{3}\.")


def _read_stderr(path: str | None) -> str:
    if not path:
        return ""
    try:
        with open(path, "rb") as handle:
            return handle.read(READ_LIMIT).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _check_line(stderr_text: str) -> str:
    for line in stderr_text.split("\n"):
        line = line.rstrip()
        if line.startswith(REFLEKTOR):
            reason = line[len(REFLEKTOR):]
            if known_reason(reason):
                return f"{NOTE}{CHECK_OPEN}{reason})."
            break
    return f"{NOTE}the page check refused it."


def _board_text(stderr_text: str) -> str:
    status = _STATUS.search(stderr_text)
    if status:
        return f"the board answered HTTP {status.group(1)}."
    if "cannot read the report (larger than" in stderr_text:
        return "the page is too large to upload."
    if "cannot reach the board" in stderr_text:
        return "the board cannot be reached."
    return "the board did not accept it."


def note_line(stage: str, stderr_text: str, sent: bool) -> str:
    """The one page-note line of a stage (plan section 3.3)."""
    if stage == "role":
        return f"{NOTE}the reflektor role built no checked page."
    if stage == "check":
        return _check_line(stderr_text)
    if stage == "board":
        return NOTE + _board_text(stderr_text) + (SENT if sent else "")
    return f"{NOTE}the page could not be sent as a file."


def _plain(line: str) -> bool:
    return all(unicodedata.category(c) not in UNSAFE for c in line)


def valid_note(line: str) -> bool:
    """True only for a line that `note_line` can print: one line, the prefix, and a fixed or known text."""
    line = line.strip()
    if not line or not _plain(line):
        return False
    if not line.startswith(NOTE):
        return False
    rest = line[len(NOTE):]
    if rest in _FIXED:
        return True
    if rest.startswith(CHECK_OPEN) and rest.endswith(")."):
        return known_reason(rest[len(CHECK_OPEN):-2])
    if rest.endswith(SENT):
        rest = rest[:-len(SENT)]
    return rest in _BOARD_FIXED or _BOARD_STATUS.fullmatch(rest) is not None


def _usable(report: str) -> tuple[str | None, str]:
    """The cleaned block, or None and the reason `tld roles section` gives."""
    block = extract(report)
    cleaned = clean(block).strip() if block is not None else ""
    if not cleaned:
        return None, "tld roles: no change-report block"
    if _suspect(block) or _suspect(cleaned):
        return None, "tld roles: the change-report block looks like it holds a secret"
    return cleaned, ""


def _read_note(path: str | None) -> str | None:
    """The stripped note text, None when there is none; text that is not UTF-8 is returned as a bad note."""
    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace").strip()
    return text or None


def _report(args: argparse.Namespace) -> int:
    try:
        report = _read(args.report)
    except (OSError, UnicodeDecodeError):
        print(f"tld roles: cannot read '{scrub(args.report)}'", file=sys.stderr)
        return 1
    cleaned, problem = _usable(report)
    note = _read_note(args.note)
    if note is None:
        if cleaned is None:
            print(problem, file=sys.stderr)
            return 3
        print(cleaned)
        return 0
    if not valid_note(note):
        print("tld roles: the page note is not a page-note line", file=sys.stderr)
        return 1
    if cleaned is None:
        print(note)
        return 0
    print(f"{note}\n\n{cleaned}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld roles", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    np = sub.add_parser("note", help="print the page-note line of a stage")
    np.add_argument("--stage", required=True, choices=("role", "check", "board", "send"))
    np.add_argument("--stderr", metavar="FILE", help="the stderr of the failed step")
    np.add_argument("--sent", action="store_true", help="board only: the page was sent as a file")
    rp = sub.add_parser("report", help="print the change-report block with the note first")
    rp.add_argument("--report", required=True, metavar="FILE", help="the reflektor subsection of the dod report")
    rp.add_argument("--note", metavar="FILE", help="a file holding the page-note line")
    args = ap.parse_args(argv)
    if args.cmd == "report":
        return _report(args)
    if args.sent and args.stage != "board":
        np.error("--sent goes with --stage board")
    print(note_line(args.stage, _read_stderr(args.stderr), args.sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
