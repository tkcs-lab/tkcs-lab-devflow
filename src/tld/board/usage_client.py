#!/usr/bin/env python3
"""Send the newest rate-limit reading to the board's Usage page.

    tld board usage FILE|- [--source final|scheduled]

The input is JSON in one of three shapes: the whole `rate_limit_info`, its `unifiedWindows`, or an object
holding `five_hour` / `seven_day` directly. A window spells its time `resetsAt` or `resets_at`. A window whose
time is not in the future is dropped. Exit codes: 0 sent (stdout `{"stored":n}`) or nothing current to send;
1 the board refused it or the input is not understood; 2 usage error; 3 no board configured.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable

from tld.board import client as board_client

KINDS = ("five_hour", "seven_day")


def _find_windows(doc: object) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("the reading is not a JSON object")
    if isinstance(doc.get("unifiedWindows"), dict):
        return doc["unifiedWindows"]
    info = doc.get("rate_limit_info")
    if isinstance(info, dict) and isinstance(info.get("unifiedWindows"), dict):
        return info["unifiedWindows"]
    return doc


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_body(doc: object, source: str, now: float) -> dict:
    """The POST body of the reading; windows that ended are left out. Raises ValueError when not understood."""
    windows = _find_windows(doc)
    body: dict[str, object] = {}
    seen = False
    for kind in KINDS:
        if kind not in windows:
            continue
        seen = True
        win = windows[kind]
        if not isinstance(win, dict):
            raise ValueError(f"{kind} is not an object")
        resets = win.get("resetsAt", win.get("resets_at"))
        if "utilization" not in win or not _number(resets):
            raise ValueError(f"{kind} needs utilization and resetsAt")
        if resets <= now:
            continue
        if isinstance(resets, float) and resets.is_integer():
            resets = int(resets)
        body[kind] = {"utilization": win["utilization"], "resets_at": resets}
    if not seen:
        raise ValueError("no five_hour or seven_day window in the reading")
    body["source"] = source
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tld board usage", description="Send a rate-limit reading to the board.")
    parser.add_argument("file", help="JSON reading, or - for stdin")
    parser.add_argument("--source", choices=("final", "scheduled"), default="final")
    return parser


def main(argv: list[str] | None = None, clock: Callable[[], float] = time.time) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = board_client.load_config()
    except board_client.ConfigError as exc:
        print(f"board_usage: {exc}", file=sys.stderr)
        return 1
    if config is None:
        print("board_usage: no board configured", file=sys.stderr)
        return 3
    try:
        text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
        body = build_body(json.loads(text), args.source, clock())
    except (OSError, ValueError) as exc:
        print(f"board_usage: cannot read the reading ({exc})", file=sys.stderr)
        return 1
    if len(body) == 1:
        print("usage: no current window in the reading", file=sys.stderr)
        return 0
    try:
        status, payload = board_client.call(config, "POST", "/api/usage", body)
    except OSError as exc:
        print(f"board_usage: cannot reach the board ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    if status == 200:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    if status == 409:
        print("usage: the board has usage off: set TLD_BOARD_PLAN on the board host", file=sys.stderr)
    else:
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        print(f"board_usage: the server answered HTTP {status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
