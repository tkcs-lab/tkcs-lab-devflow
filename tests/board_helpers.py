"""Shared helpers of the board tests: a running server with the owner UI, requests, the owner's login."""
from __future__ import annotations

import contextlib
import json
import threading
import urllib.error
import urllib.request

from tld.board import server as board_server
from tld.board.store import Store

WRITE = "w" * 24
PASSPHRASE = "correct horse battery staple"
SECRET = b"s" * 32


def ask_doc(**changes) -> dict:
    """A valid ask as a session posts it."""
    doc = {
        "schema": 1, "kind": "ask", "project": "example-project", "repo": "example/example-project",
        "title": "Review all: 2 decisions", "created_by": "session_example",
        "context_url": "https://example.com/review.md",
        "questions": [
            {"id": "SEC-1", "text": "Token in logs.\nFix it?", "kind": "choice",
             "options": [{"value": "plan", "label": "plan (recommended)"}, {"value": "issue"}, {"value": "drop"}]},
            {"id": "go", "text": "Run the commands?", "kind": "confirm"},
            {"id": "notes", "text": "Anything else?", "kind": "text", "required": False},
        ],
    }
    doc.update(changes)
    return doc


@contextlib.contextmanager
def running(tmp_path, owner=True, insecure=True, **kwargs):
    """A board server on a free loopback port; yields the server object."""
    auth = board_server.OwnerAuth(PASSPHRASE, SECRET, secure=not insecure) if owner else None
    srv = board_server.make_server(Store(str(tmp_path / "b.sqlite3")), board_server.Tokens(WRITE), "T",
                                   "127.0.0.1", 0, owner=auth, **kwargs)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(5)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def base(srv) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}"


def call(srv, method, path, token=None, body=None, headers=None, raw=None, cookie=None, csrf=None,
         origin=None):
    """(status, headers, parsed JSON or raw bytes). `origin=True` sends the server's own Origin."""
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base(srv) + path, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    if csrf:
        req.add_header("X-CSRF-Token", csrf)
    if origin is True:
        req.add_header("Origin", base(srv))
    elif origin:
        req.add_header("Origin", origin)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with _OPENER.open(req, timeout=10) as resp:
            status, hdrs, raw_body = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        status, hdrs, raw_body = err.code, err.headers, err.read()
    try:
        parsed = json.loads(raw_body) if raw_body else None
    except ValueError:
        parsed = raw_body
    return status, hdrs, parsed


def login(srv, passphrase=PASSPHRASE) -> tuple[str, str]:
    """(Cookie header value, CSRF token) of a fresh owner session."""
    status, headers, body = call(srv, "POST", "/login", body={"passphrase": passphrase}, origin=True)
    assert status == 200, body
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    return cookie, body["csrf"]
