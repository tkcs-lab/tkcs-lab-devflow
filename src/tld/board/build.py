#!/usr/bin/env python3
"""Build the board page: fill the title and the shared rules into board.html.

    tld board build --title TITLE --out FILE [--fixture FILE] [--now ISO] [--session-url URL]

Replaces the title marker with the escaped title and the rules marker with src/tld/board/web/rules.js.
With --fixture the page reads that JSON list of {"id", "data"} documents instead of the database (and shows
no login); with --now (YYYY-MM-DDTHH:MM:SSZ) it uses that instant instead of the clock. --session-url (the
server takes it from TLD_BOARD_SESSION_URL) is the https base a session id is appended to for a session
link; without it the page shows no session links. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BOARD = Path(__file__).resolve().parent / "web"
MARKERS = ("<!--TLD:TITLE-->", "/*TLD:RULES*/", "/*TLD:FIXTURE*/null", "/*TLD:NOW*/null",
           "/*TLD:SESSION_URL*/null")


def script_safe(text: str) -> str:
    """Make text safe to put inside an inline script element."""
    return text.replace("</", "<\\/").replace("<!--", "<\\!--")


def build(title: str, fixture: str | None, now: str | None, session_url: str | None = None) -> str:
    page = (BOARD / "board.html").read_text(encoding="utf-8")
    for marker in MARKERS:
        if page.count(marker) != 1:
            raise ValueError(f"board.html must contain {marker} exactly once")
    rules = (BOARD / "rules.js").read_text(encoding="utf-8")
    page = page.replace("<!--TLD:TITLE-->", html.escape(title))
    page = page.replace("/*TLD:RULES*/", script_safe(rules))
    if fixture is not None:
        docs = json.loads(Path(fixture).read_text(encoding="utf-8"))
        if not isinstance(docs, list):
            raise ValueError("the fixture must be a JSON list of {id, data} documents")
        page = page.replace("/*TLD:FIXTURE*/null", script_safe(json.dumps(docs)))
    if session_url is not None:
        if not session_url.startswith("https://") or not session_url.endswith("/"):
            raise ValueError("the session URL must be an https:// URL that ends with '/'")
        page = page.replace("/*TLD:SESSION_URL*/null", script_safe(json.dumps(session_url)))
    if now is not None:
        instant = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        page = page.replace("/*TLD:NOW*/null", str(int(instant.timestamp() * 1000)))
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the tld board page.")
    parser.add_argument("--title", required=True, help="page title")
    parser.add_argument("--out", required=True, help="file to write")
    parser.add_argument("--fixture", help="JSON list of {id, data} documents to show instead of the database")
    parser.add_argument("--now", help="the instant to use instead of the clock, YYYY-MM-DDTHH:MM:SSZ")
    parser.add_argument("--session-url", dest="session_url",
                        help="https base URL of a session link, ending with '/' (e.g. the runtime's session URL)")
    args = parser.parse_args(argv)
    try:
        page = build(args.title, args.fixture, args.now, args.session_url)
        Path(args.out).write_text(page, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"build_board: {exc}", file=sys.stderr)
        return 1
    print(f"build_board: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
