#!/usr/bin/env python3
"""Print the cleaned `change-report` block of a role report, ready for a pull request body.

    tld roles section --report FILE [--report-line]

FILE is the reflektor subsection of the dod report. The command takes the last complete pair of bare lines
`BEGIN change-report` / `END change-report` (a leading `>`, spaces or backticks are tolerated, as in the
`AGENT-REPORT` grammar; an unclosed BEGIN is ignored) and prints the text between them after `clean`: no
mention, issue reference, link, image, HTML, heading above `###`, forged report line or control character
can pass, and the text is cut to 60 lines and 6000 characters. With `--report-line` it prints instead the
last non-blank line of FILE when that line is a complete `AGENT-REPORT reflektor at=dod ...` line.

Exit 0 with output; exit 3 with `tld roles: no change-report block` (none, or empty after cleaning), with
`tld roles: the change-report block looks like it holds a secret`, or with `tld roles: no reflektor report line`;
exit 1 when FILE cannot be read or is not UTF-8. Python 3.11+, standard library and the tld modules.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata

from tld.guard.secret_scan import ALLOW_MARK, scan_text
from tld.plan.summary import UNSAFE, scrub
from tld.roles.dispatch import REPORT_LINE

BEGIN = "BEGIN change-report"
END = "END change-report"

MAX_LINES = 60
MAX_LINE = 500
MAX_TOTAL = 5988
TRUNCATED = "(truncated)"

_MARK = r"^[>\s`]*{}[\s`]*$"
_BEGIN_LINE = re.compile(_MARK.format(re.escape(BEGIN)), re.MULTILINE)
_END_LINE = re.compile(_MARK.format(re.escape(END)), re.MULTILINE)
_REF_DEF = re.compile(r"^\[[^\]]+\]:")
_SETEXT = re.compile(r"^(=+|-+)$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPEN_COMMENT = re.compile(r"<!--[^\n]*")
_TAG = re.compile(r"</?[A-Za-z][^>\n]*>")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_TEXT = r"((?:[^\[\]\n]|\[[^\[\]\n]*\])*)"
_LINK = re.compile(r"\[" + _TEXT + r"\]\([^)\n]*\)")
_REF_LINK = re.compile(r"\[" + _TEXT + r"\]\[[^\]\n]*\]")
_URL = re.compile(r"https?://\S+|www\.\S+|(?<!\w)//\S+", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s")
_WRAP = re.compile(
    r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+#[0-9]+|@[A-Za-z0-9][A-Za-z0-9/_-]*(?:#[0-9]+)?|GH-[0-9]+|#[0-9]+")
_CLOSING = re.compile(r"\b(?:closes?|closed|fix(?:es|ed)?|resolves?|resolved)\b(?=:?[ \t]*`)", re.IGNORECASE)


def block_re() -> re.Pattern[str]:
    """One BEGIN..END block: the marker lines and, in group `body`, the text between them. The body never
    holds a BEGIN marker line, so an unclosed BEGIN before a pair is not part of it."""
    begin = _MARK.format(re.escape(BEGIN))
    end = _MARK.format(re.escape(END))
    return re.compile(
        f"{begin}(?P<body>(?:(?!{begin}).)*?){end}", re.MULTILINE | re.DOTALL)


def _forged(line: str) -> bool:
    return bool(REPORT_LINE.match(line) or line.startswith("REPORT-HTML")
                or _BEGIN_LINE.match(line) or _END_LINE.match(line))


def _drop_forged(lines: list[str]) -> list[str]:
    return [line for line in lines if not _forged(line)]


def _cut(lines: list[str]) -> list[str]:
    kept: list[str] = []
    size = 0
    for line in lines[:MAX_LINES]:
        add = len(line) + (1 if kept else 0)
        if size + add > MAX_TOTAL:
            break
        kept.append(line)
        size += add
    if len(kept) < len(lines):
        kept.append(TRUNCATED)
    return kept


def _demote(match: re.Match[str]) -> int:
    return min(max(len(match.group(1)) + 1, 3), 6)


def clean(text: str) -> str:
    """The text of a change-report block, made safe for a pull request body (plan section 3.5, eight steps)."""
    # 1. one unescape, control and format characters, forged report lines and markers
    text = html.unescape(text)
    text = "".join(c for c in text if c in "\t\n" or unicodedata.category(c) not in UNSAFE)
    lines = _drop_forged(text.split("\n"))
    # 2. backticks and backslashes
    text = "\n".join(lines).replace("`", "").replace("\\", "")
    # 3. HTML comments, tags, `&` and `<`
    text = _COMMENT.sub("", text)
    text = _OPEN_COMMENT.sub("", text)
    text = _TAG.sub("", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    # 4. quote and indent markers, fences, reference definitions, setext underlines
    lines = [line.lstrip(" >") for line in text.split("\n")]
    lines = [line for line in lines
             if not (line.startswith("~~~") or _REF_DEF.match(line) or _SETEXT.match(line.rstrip()))]
    lines = _drop_forged(lines)
    # 5. images, links, URLs
    text = "\n".join(lines)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _REF_LINK.sub(r"\1", text)
    text = text.replace("](", "] (")
    text = _URL.sub("(link removed)", text)
    # 6. headings
    lines = []
    for line in text.split("\n"):
        m = _HEADING.match(line)
        lines.append("#" * _demote(m) + line[len(m.group(1)):] if m else line)
    # 7. cut, wrap mentions and references, drop closing keywords
    out = []
    for line in lines:
        wrapped = _WRAP.sub(lambda m: f"`{m.group(0)}`", line[:MAX_LINE])
        out.append(_CLOSING.sub("[removed]", wrapped))
    # a link, an image or the cut can leave a line that is a report line again
    out = _drop_forged(out)
    # 8. whole lines only
    return "\n".join(_cut(out))


def extract(report: str) -> str | None:
    """The text between the last complete BEGIN/END pair, or None."""
    found = None
    for m in block_re().finditer(report):
        found = m.group("body")
    return found


def _suspect(text: str) -> bool:
    """A credential-looking line, or the mark that would make the scan skip a line."""
    return ALLOW_MARK in text or bool(scan_text(text))


def _last_line(report: str) -> str | None:
    """The last non-blank line, split at newlines only (as `tld roles verify` does)."""
    for line in reversed(report.split("\n")):
        line = line[:-1] if line.endswith("\r") else line
        if line.strip(" \t"):
            return line
    return None


def _read(path: str) -> str:
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tld roles section", description=__doc__.split("\n")[0])
    ap.add_argument("--report", required=True, metavar="FILE", help="the reflektor subsection of the dod report")
    ap.add_argument("--report-line", action="store_true", help="print the AGENT-REPORT reflektor line instead")
    args = ap.parse_args(argv)
    try:
        report = _read(args.report)
    except (OSError, UnicodeDecodeError):
        print(f"tld roles: cannot read '{scrub(args.report)}'", file=sys.stderr)
        return 1
    if args.report_line:
        last = _last_line(report)
        unsafe = last is not None and any(unicodedata.category(c) in UNSAFE for c in last)
        m = REPORT_LINE.fullmatch(last) if last is not None and not unsafe else None
        if m is None or m["agent"] != "reflektor" or m["at"] != "dod":
            print("tld roles: no reflektor report line", file=sys.stderr)
            return 3
        print(last.strip())
        return 0
    block = extract(report)
    cleaned = clean(block).strip() if block is not None else ""
    if not cleaned:
        print("tld roles: no change-report block", file=sys.stderr)
        return 3
    if _suspect(block) or _suspect(cleaned):
        print("tld roles: the change-report block looks like it holds a secret", file=sys.stderr)
        return 3
    print(cleaned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
