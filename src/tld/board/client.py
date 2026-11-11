#!/usr/bin/env python3
"""Command-line client for the tld status board server.

    board_client.py health | list | get ID | set ID FILE|- [--if-version N] | delete ID [ID ...]

Reads TLD_BOARD_URL and TLD_BOARD_TOKEN (and TLD_BOARD_ALLOW_HTTP) from the environment.
Prints one line of compact JSON on stdout (`health` prints `ok`). Exit codes: 0 success; 1 the server
answered with an error status, a network error or a bad configuration; 2 usage error; 3 no board
configured. Redirects keep the Authorization header only on the same scheme, host and port (S18). The asks
have their own commands: `tld board ask`, `tld board answers`, `tld board cancel` (tld.board.inbox).
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import NamedTuple

from tld.net import opener as _opener

LOOPBACK = ("localhost", "127.0.0.1", "::1")
OPENER = _opener()


class ConfigError(Exception):
    pass


class Config(NamedTuple):
    url: str
    token: str


def load_url(env: Mapping[str, str] = os.environ) -> str | None:
    """The board URL without a trailing slash, or None when unset or empty."""
    url = (env.get("TLD_BOARD_URL") or "").strip()
    if not url:
        return None
    if url.endswith("/"):
        url = url[:-1]
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("TLD_BOARD_URL must be an http(s) URL")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ConfigError("TLD_BOARD_URL must not contain user info")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise ConfigError("TLD_BOARD_URL must not contain a query or a fragment")
    if parts.scheme == "http" and parts.hostname not in LOOPBACK and env.get("TLD_BOARD_ALLOW_HTTP") != "1":
        raise ConfigError("TLD_BOARD_URL must be https (set TLD_BOARD_ALLOW_HTTP=1 to allow plain http)")
    return url


def load_config(env: Mapping[str, str] = os.environ) -> Config | None:
    url = load_url(env)
    token = (env.get("TLD_BOARD_TOKEN") or "").strip()
    if url is None or not token:
        return None
    return Config(url, token)


def call(config: Config, method: str, path: str, body: object | None = None, timeout: float = 20.0,
         auth: bool = True) -> tuple[int, object | None]:
    """Send one request; return (status, parsed JSON or None). HTTP errors are returned, not raised."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(config.url + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", f"Bearer {config.token}")
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None
    return status, parsed


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _fail(status: int, payload: object | None) -> int:
    if payload is not None:
        _emit(payload)
    print(f"board_client: the server answered HTTP {status}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="board_client.py", description="Client for the tld status board.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="GET /healthz (needs only the URL)")
    sub.add_parser("list", help="list every record")
    get = sub.add_parser("get", help="read one record")
    get.add_argument("id")
    put = sub.add_parser("set", help="write one record")
    put.add_argument("id")
    put.add_argument("file", help="JSON document file, or - for stdin")
    put.add_argument("--if-version", type=int, dest="if_version", help="the version last read")
    rm = sub.add_parser("delete", help="delete records")
    rm.add_argument("ids", nargs="+", metavar="ID")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "health":
            url = load_url()
            config = Config(url, "") if url else None
        else:
            config = load_config()
    except ConfigError as exc:
        print(f"board_client: {exc}", file=sys.stderr)
        return 1
    if config is None:
        print("board_client: no board configured", file=sys.stderr)
        return 3
    try:
        return run(args, config)
    except OSError as exc:
        print(f"board_client: cannot reach the board ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1


def run(args: argparse.Namespace, config: Config) -> int:
    quote = urllib.parse.quote
    if args.cmd == "health":
        status, payload = call(config, "GET", "/healthz", auth=False)
        if status != 200:
            return _fail(status, payload)
        print("ok")
        return 0
    if args.cmd == "list":
        status, payload = call(config, "GET", "/api/records")
    elif args.cmd == "get":
        status, payload = call(config, "GET", f"/api/records/{quote(args.id, safe='')}")
    elif args.cmd == "set":
        try:
            text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
            doc = json.loads(text)
        except (OSError, ValueError) as exc:
            print(f"board_client: cannot read the document ({exc})", file=sys.stderr)
            return 1
        body: dict[str, object] = {"data": doc}
        if args.if_version is not None:
            body["if_version"] = args.if_version
        status, payload = call(config, "PUT", f"/api/records/{quote(args.id, safe='')}", body)
    else:
        deleted: list[str] = []
        missing: list[str] = []
        for doc_id in args.ids:
            status, payload = call(config, "DELETE", f"/api/records/{quote(doc_id, safe='')}")
            if status == 200:
                deleted.append(doc_id)
            elif status == 404:
                missing.append(doc_id)
            else:
                return _fail(status, payload)
        _emit({"deleted": deleted, "missing": missing})
        return 0
    if status != 200:
        return _fail(status, payload)
    _emit(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
