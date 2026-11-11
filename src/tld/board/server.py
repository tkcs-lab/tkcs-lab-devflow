#!/usr/bin/env python3
"""Self-hosted status board: SQLite store, JSON API and the board page over HTTP.

    TLD_BOARD_TOKEN=<24+ chars> board_server.py [--host H] [--port N] [--db FILE] [--title T] [--allow-origin URL]

Tokens come from the environment only: TLD_BOARD_TOKEN (write) and the optional
TLD_BOARD_READ_TOKEN (read only). The server speaks plain HTTP; put a TLS proxy in front.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tld.board import mcp as board_mcp  # noqa: E402
from tld.board import build as build_board  # noqa: E402
from tld.board.store import Conflict, Invalid, Store  # noqa: E402

MAX_BODY = 1048576
MIN_TOKEN = 24

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
RECORD_PATH = re.compile(r"^/api/records/([^/]+)$")


class Tokens:
    def __init__(self, write: str, read: str | None = None) -> None:
        self.write = write.encode("utf-8")
        self.read = read.encode("utf-8") if read else None

    def role(self, authorization: str | None) -> str | None:
        """"write", "read" or None for an Authorization header value."""
        if not authorization:
            return None
        scheme, _, rest = authorization.strip().partition(" ")
        rest = rest.strip()
        scheme = scheme.lower()
        if scheme == "bearer":
            candidate = rest
        elif scheme == "basic":
            try:
                decoded = base64.b64decode(rest, validate=True).decode("utf-8")
            except (binascii.Error, ValueError):
                return None
            candidate = decoded.partition(":")[2]
        else:
            return None
        raw = candidate.encode("utf-8")
        if hmac.compare_digest(raw, self.write):
            return "write"
        if self.read is not None and hmac.compare_digest(raw, self.read):
            return "read"
        return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tld-board"
    sys_version = ""

    # -- output ---------------------------------------------------------------------------------

    def log_request(self, code: object = "-", size: object = "-") -> None:
        path = urlsplit(self.path).path
        print(f"board_server: {self.command} {path} {code}", file=sys.stderr, flush=True)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print("board_server: " + (format % args), file=sys.stderr, flush=True)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        if not self._body_read and (self.headers.get("Content-Length") or "0").strip() not in ("", "0"):
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: object, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, code: str, extra: dict[str, str] | None = None, **fields: object) -> None:
        self._json(status, {"error": code, **fields}, extra)

    def _unauthorized(self) -> None:
        self._error(401, "unauthorized",
                    {"WWW-Authenticate": 'Basic realm="tld board", charset="UTF-8"'})

    def _not_allowed(self, allow: str) -> None:
        self._error(405, "method_not_allowed", {"Allow": allow})

    # -- routing --------------------------------------------------------------------------------

    def _route(self) -> tuple[str, str | None, str] | None:
        """(route name, document id, allowed methods) of the path, or None for an unknown path."""
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            return "page", None, "GET"
        if path == "/api/records":
            return "list", None, "GET"
        if path == "/mcp":
            return "mcp", None, "POST"
        match = RECORD_PATH.match(path)
        if match:
            return "record", unquote(match.group(1)), "GET, PUT, DELETE"
        return None

    def _dispatch(self, method: str) -> None:
        self._body_read = False
        if method == "GET" and urlsplit(self.path).path == "/healthz":
            self._json(200, {"ok": True})
            return
        role = self.server.tokens.role(self.headers.get("Authorization"))
        if role is None:
            self._unauthorized()
            return
        route = self._route()
        if route is None:
            self._error(404, "not_found")
            return
        name, doc_id, allow = route
        if method not in allow.split(", "):
            self._not_allowed(allow)
            return
        if method != "GET" and role != "write":
            self._error(403, "forbidden")
            return
        if name == "mcp":
            self._mcp()
        elif name == "page":
            self._send(200, self.server.page, "text/html; charset=utf-8",
                       {"X-Frame-Options": "DENY", "Content-Security-Policy": CSP})
        elif name == "list":
            self._json(200, {"records": self.server.store.list()})
        elif method == "GET":
            record = self.server.store.get(doc_id or "")
            if record is None:
                self._error(404, "not_found")
            else:
                self._json(200, record)
        elif method == "PUT":
            self._put(doc_id or "")
        else:
            if self.server.store.delete(doc_id or ""):
                self._json(200, {"deleted": True})
            else:
                self._error(404, "not_found")

    def _read_body(self) -> bytes | None:
        """The request body, or None after an error response has been sent."""
        header = self.headers.get("Content-Length")
        if header is None or not header.strip().isdigit():
            self.close_connection = True
            self._error(400, "bad_request")
            return None
        length = int(header.strip())
        if length > MAX_BODY:
            self.close_connection = True
            self._error(413, "payload_too_large")
            return None
        body = self.rfile.read(length)
        self._body_read = True
        return body

    def _rpc_error(self, status: int, code: int, message: str) -> None:
        self._json(status, {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}})

    def _mcp(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.allow_origins:
            self._error(403, "origin_not_allowed")
            return
        body = self._read_body()
        if body is None:
            return
        try:
            message = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._rpc_error(400, -32700, "Parse error")
            return
        if isinstance(message, list):
            self._rpc_error(400, -32600, "Batch requests are not supported")
            return
        reply = board_mcp.handle(self.server.store, message)
        if reply is None:
            self._send(202, b"", "application/json")
        else:
            self._json(200, reply)

    def _put(self, doc_id: str) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._error(400, "bad_request")
            return
        if not isinstance(payload, dict) or "data" not in payload:
            self._error(400, "bad_request")
            return
        if_version = payload.get("if_version")
        if if_version is not None and (
                isinstance(if_version, bool) or not isinstance(if_version, int) or if_version < 1):
            self._error(400, "bad_request")
            return
        try:
            result = self.server.store.set(doc_id, payload["data"], if_version)
        except Conflict as exc:
            self._error(409, "version_conflict", current=exc.current)
        except Invalid as exc:
            self._error(422, "invalid", errors=exc.errors)
        else:
            self._json(200, result)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_POST(self) -> None:
        self._dispatch("POST")


def make_server(store: Store, tokens: Tokens, title: str, host: str, port: int,
                allow_origins: tuple[str, ...] = ()) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.store = store  # type: ignore[attr-defined]
    server.tokens = tokens  # type: ignore[attr-defined]
    server.page = build_board.build(title, None, None).encode("utf-8")  # type: ignore[attr-defined]
    server.allow_origins = allow_origins  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the tld status board.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="0 picks a free port")
    parser.add_argument("--db", default=os.environ.get("TLD_BOARD_DB") or "board.sqlite3")
    parser.add_argument("--title", default="tld Board")
    parser.add_argument("--allow-origin", action="append", default=[], dest="allow_origin")
    args = parser.parse_args(argv)
    write = os.environ.get("TLD_BOARD_TOKEN", "")
    read = os.environ.get("TLD_BOARD_READ_TOKEN") or None
    if len(write) < MIN_TOKEN:
        print("board_server: TLD_BOARD_TOKEN must be set to at least 24 characters", file=sys.stderr)
        return 2
    if read is not None and (len(read) < MIN_TOKEN or read == write):
        print("board_server: TLD_BOARD_READ_TOKEN must differ from TLD_BOARD_TOKEN "
              "and have at least 24 characters", file=sys.stderr)
        return 2
    server = make_server(Store(args.db), Tokens(write, read), args.title, args.host, args.port,
                         tuple(args.allow_origin))
    print(f"board_server: listening on http://{args.host}:{server.server_address[1]}",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
