#!/usr/bin/env python3
"""Self-hosted board: the owner's inbox for status records and asks. SQLite store, JSON API, MCP, page.

    TLD_BOARD_TOKEN=<24+ chars> TLD_BOARD_OWNER_PASSPHRASE=<16+ chars> tld board server
        [--host H] [--port N] [--db FILE] [--title T] [--allow-origin URL] [--public-origin URL]
        [--insecure-cookie] [--session-hours N] [--trust-proxy]

Environment: TLD_BOARD_TOKEN, TLD_BOARD_OWNER_PASSPHRASE, TLD_BOARD_SECRET, TLD_BOARD_DB (--db),
TLD_BOARD_PUBLIC_ORIGIN (--public-origin), TLD_BOARD_SESSION_URL (the https base of a session link),
TLD_BOARD_PLAN (standard or max: turns the usage readings on), TLD_BOARD_MAX_FACTOR (Max = this many times Standard).

Two principals. A **session** sends `Authorization: Bearer $TLD_BOARD_TOKEN`: it writes status records,
creates, reads and cancels asks, and calls `POST /mcp`; it can never answer an ask. The **owner** logs in on
the page with TLD_BOARD_OWNER_PASSPHRASE and gets a signed session cookie: it reads records and asks, answers
and cancels asks, and can never write a record. Without a passphrase the owner UI is off (API only); a
passphrase under 16 characters stops the server. The cookie is signed with TLD_BOARD_SECRET or with a secret
generated once into `<db>.secret`. Secrets come from the environment only. The server speaks plain HTTP: put a
TLS proxy in front (docs/guides/board-server.md). Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import sys
import threading
import time
from collections import deque
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from tld.board import build as build_board
from tld.board import mcp as board_mcp
from tld.board import usage
from tld.board.record import TIMESTAMP
from tld.board.store import Conflict, Invalid, NotFound, Store

MAX_BODY = 1048576
MAX_LOGIN_BODY = 4096
MIN_TOKEN = 24
MIN_PASSPHRASE = 16
MIN_SECRET = 32
SOCKET_TIMEOUT = 15      # seconds a connection may sit idle (headers, body, keep-alive) before it is closed
BODY_DEADLINE = 30       # seconds a request body may take in total, however slowly it trickles in
MAX_CONNECTIONS = 64     # connections served at once; one more is answered 503 and closed

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

# (path pattern, route name, allowed methods). The id group is URL-decoded.
ROUTES = (
    (re.compile(r"^/(?:index\.html)?$"), "page", ("GET",)),
    (re.compile(r"^/login$"), "login", ("POST",)),
    (re.compile(r"^/logout$"), "logout", ("POST",)),
    (re.compile(r"^/api/session$"), "session", ("GET",)),
    (re.compile(r"^/api/records$"), "records", ("GET",)),
    (re.compile(r"^/api/records/([^/]+)$"), "record", ("GET", "PUT", "DELETE")),
    (re.compile(r"^/api/records/([^/]+)/dismiss$"), "dismiss", ("POST",)),
    (re.compile(r"^/api/records/([^/]+)/restore$"), "restore", ("POST",)),
    (re.compile(r"^/api/asks$"), "asks", ("GET", "POST")),
    (re.compile(r"^/api/asks/([^/]+)$"), "ask", ("GET",)),
    (re.compile(r"^/api/asks/([^/]+)/answer$"), "answer", ("POST",)),
    (re.compile(r"^/api/asks/([^/]+)/cancel$"), "cancel", ("POST",)),
    (re.compile(r"^/mcp$"), "mcp", ("POST",)),
    (re.compile(r"^/api/usage$"), "usage", ("GET", "POST")),
)
ANY, SESSION, OWNER = "any", "session", "owner"
# Who may call a route with a method. "any" needs no credentials.
POLICY: dict[tuple[str, str], frozenset[str]] = {
    ("page", "GET"): frozenset({ANY}),
    ("login", "POST"): frozenset({ANY}),
    ("session", "GET"): frozenset({ANY}),
    ("logout", "POST"): frozenset({OWNER}),
    ("records", "GET"): frozenset({SESSION, OWNER}),
    ("record", "GET"): frozenset({SESSION, OWNER}),
    ("record", "PUT"): frozenset({SESSION}),
    ("record", "DELETE"): frozenset({SESSION}),
    ("dismiss", "POST"): frozenset({OWNER}),
    ("restore", "POST"): frozenset({OWNER}),
    ("asks", "GET"): frozenset({SESSION, OWNER}),
    ("asks", "POST"): frozenset({SESSION}),
    ("ask", "GET"): frozenset({SESSION, OWNER}),
    ("answer", "POST"): frozenset({OWNER}),
    ("cancel", "POST"): frozenset({SESSION, OWNER}),
    ("mcp", "POST"): frozenset({SESSION}),
    ("usage", "POST"): frozenset({SESSION}),
    ("usage", "GET"): frozenset({OWNER}),
}
OWNER_UI = ("page", "login", "logout", "session")


class Tokens:
    """The session token. Only `Authorization: Bearer <token>` is accepted."""

    def __init__(self, write: str) -> None:
        self.write = hashlib.sha256(write.encode("utf-8")).digest()

    def valid(self, authorization: str | None) -> bool:
        if not authorization:
            return False
        scheme, _, rest = authorization.strip().partition(" ")
        if scheme.lower() != "bearer":
            return False
        candidate = hashlib.sha256(rest.strip().encode("utf-8")).digest()
        return hmac.compare_digest(candidate, self.write)


class LoginLimiter:
    """In-memory brake on wrong passphrases. Per client key, after FREE failures, a lockout that doubles up to
    MAX_LOCK seconds; a successful login clears that key. For everybody together, more than GLOBAL_MAX failures
    per WINDOW seconds only slow every login attempt down (at most MAX_DELAY seconds); they never lock anybody
    out, so a flood of wrong passphrases from many addresses cannot keep the owner from logging in."""

    FREE = 5
    MAX_LOCK = 900
    WINDOW = 60
    GLOBAL_MAX = 30
    MAX_DELAY = 2.0
    MAX_KEYS = 10000

    def __init__(self, clock=time.monotonic, sleep=time.sleep) -> None:
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}  # key -> [count, locked_until]
        self._recent: deque[float] = deque()

    def retry_after(self, key: str) -> int:
        """Seconds this client must wait before the next attempt, 0 when it may try now."""
        now = self._clock()
        with self._lock:
            entry = self._fails.get(key)
            wait = entry[1] - now if entry and entry[1] > now else 0.0
            return math.ceil(wait) if wait > 0 else 0

    def delay(self) -> float:
        """The global slow-down in seconds (0 unless more than GLOBAL_MAX failures fell in the last WINDOW)."""
        now = self._clock()
        with self._lock:
            while self._recent and self._recent[0] <= now - self.WINDOW:
                self._recent.popleft()
            over = len(self._recent) - self.GLOBAL_MAX
            return min(self.MAX_DELAY, 0.1 * (over + 1)) if over >= 0 else 0.0

    def slow_down(self) -> None:
        wait = self.delay()
        if wait:
            self._sleep(wait)

    def failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            if len(self._fails) >= self.MAX_KEYS and key not in self._fails:
                self._fails.pop(next(iter(self._fails)))
            entry = self._fails.setdefault(key, [0, 0.0])
            entry[0] += 1
            if entry[0] >= self.FREE:
                entry[1] = now + min(self.MAX_LOCK, 2 ** (entry[0] - self.FREE + 1))
            self._recent.append(now)
            if len(self._recent) > 4 * self.GLOBAL_MAX:
                self._recent.popleft()

    def success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


def client_key(address: str) -> str:
    """The limiter key of a client address: an IPv4 address as is, an IPv6 address by its /64 network (one host
    usually holds a whole /64), anything else as given (cut to 64 characters)."""
    try:
        ip = ipaddress.ip_address(address.strip().strip("[]"))
    except ValueError:
        return address.strip()[:64]
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class OwnerAuth:
    """The owner's passphrase and the signed session cookie."""

    def __init__(self, passphrase: str, secret: bytes, secure: bool = True, max_age: int = 12 * 3600,
                 clock=time.time, revocations=None) -> None:
        self._digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
        # The signing key depends on the passphrase too: a new passphrase ends every session.
        self._key = hmac.new(secret, b"tld-owner-session\0" + self._digest, hashlib.sha256).digest()
        self.secure = secure
        self.max_age = max_age
        self.cookie_name = "__Host-tld_owner" if secure else "tld_owner"
        self._clock = clock
        self._revoked: dict[str, int] = {}
        self._lock = threading.Lock()
        # Where logouts are kept across restarts (the Store: revoke_session / session_revoked); make_server sets it.
        self.revocations = revocations

    def check(self, candidate: object) -> bool:
        if not isinstance(candidate, str):
            return False
        return hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8")).digest(), self._digest)

    def _sign(self, text: str) -> str:
        return hmac.new(self._key, text.encode("ascii"), hashlib.sha256).hexdigest()

    def issue(self) -> tuple[str, str]:
        """(cookie value, CSRF token) of a new session."""
        expires = int(self._clock()) + self.max_age
        nonce = secrets.token_hex(16)
        payload = f"{expires}.{nonce}"
        return f"{payload}.{self._sign(payload)}", self.csrf(nonce)

    def csrf(self, nonce: str) -> str:
        return self._sign("csrf." + nonce)[:40]

    def verify(self, value: str | None) -> str | None:
        """The session nonce of a valid, unexpired, not logged-out cookie value, else None."""
        if not value or value.count(".") != 2:
            return None
        expires, nonce, sig = value.split(".")
        if not (expires.isdigit() and re.fullmatch(r"[0-9a-f]{32}", nonce)):
            return None
        if not hmac.compare_digest(sig, self._sign(f"{expires}.{nonce}")):
            return None
        now = int(self._clock())
        if int(expires) <= now:
            return None
        with self._lock:
            if nonce in self._revoked:
                return None
        if self.revocations is not None and self.revocations.session_revoked(nonce):
            return None
        return nonce

    def revoke(self, value: str) -> None:
        nonce = self.verify(value)
        if nonce is None:
            return
        now = int(self._clock())
        expires = int(value.split(".")[0])
        with self._lock:
            self._revoked = {n: e for n, e in self._revoked.items() if e > now}
            self._revoked[nonce] = expires
        if self.revocations is not None:
            self.revocations.revoke_session(nonce, expires, now)

    def set_cookie(self, value: str) -> str:
        parts = [f"{self.cookie_name}={value}", "Path=/", f"Max-Age={self.max_age}", "HttpOnly",
                 "SameSite=Strict"]
        if self.secure:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_cookie(self) -> str:
        parts = [f"{self.cookie_name}=", "Path=/", "Max-Age=0", "HttpOnly", "SameSite=Strict"]
        if self.secure:
            parts.append("Secure")
        return "; ".join(parts)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tld-board"
    sys_version = ""
    timeout = SOCKET_TIMEOUT  # StreamRequestHandler sets it on the socket: a silent client is dropped

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

    # -- requests -------------------------------------------------------------------------------

    def _route(self) -> tuple[str, str | None, tuple[str, ...]] | None:
        path = urlsplit(self.path).path
        for pattern, name, methods in ROUTES:
            match = pattern.match(path)
            if match:
                return name, unquote(match.group(1)) if match.groups() else None, methods
        return None

    def _cookie(self) -> str | None:
        owner = self.server.owner
        header = self.headers.get("Cookie")
        if owner is None or not header:
            return None
        try:
            jar = SimpleCookie()
            jar.load(header)
        except CookieError:
            return None
        morsel = jar.get(owner.cookie_name)
        return morsel.value if morsel else None

    def _principal(self) -> str | None:
        """SESSION for a valid bearer token, OWNER for a valid cookie, "bad" for a wrong token, else None."""
        if self.headers.get("Authorization") is not None:
            return SESSION if self.server.tokens.valid(self.headers.get("Authorization")) else "bad"
        if self.server.owner is not None and self.server.owner.verify(self._cookie()):
            return OWNER
        return None

    def _same_origin(self) -> bool:
        """The request comes from the board's own page: Origin (required) is the board's origin."""
        origin = self.headers.get("Origin")
        if not origin:
            return False
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site != "same-origin":
            return False
        if self.server.public_origin:
            return origin == self.server.public_origin
        parts = urlsplit(origin)
        schemes = ("https",) if self.server.owner.secure else ("https", "http")
        return parts.scheme in schemes and parts.netloc != "" and parts.netloc == (self.headers.get("Host") or "")

    def _client_key(self) -> str:
        """The client's limiter key. With --trust-proxy, the rightmost X-Forwarded-For entry: the one the single
        trusted proxy in front of the board appended (entries to its left are whatever the client sent)."""
        if self.server.trust_proxy:
            forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()
            if forwarded:
                return client_key(forwarded)
        return client_key(self.client_address[0])

    def _dispatch(self, method: str) -> None:
        self._body_read = False
        if method == "GET" and urlsplit(self.path).path == "/healthz":
            self._json(200, {"ok": True})
            return
        route = self._route()
        if route is None:
            self._error(404, "not_found")
            return
        name, item_id, methods = route
        if method not in methods:
            self._error(405, "method_not_allowed", {"Allow": ", ".join(methods)})
            return
        if name in OWNER_UI and self.server.owner is None:
            self._error(404, "owner_ui_disabled")
            return
        principal = self._principal()
        if principal == "bad":
            self._error(401, "unauthorized", {"WWW-Authenticate": 'Bearer realm="tld board"'})
            return
        allowed = POLICY[(name, method)]
        if ANY not in allowed:
            if principal is None:
                self._error(401, "unauthorized", {"WWW-Authenticate": 'Bearer realm="tld board"'})
                return
            if principal not in allowed:
                self._error(403, "forbidden")
                return
        if method == "POST" and (principal == OWNER or name == "login"):
            if not self._same_origin():
                self._error(403, "origin_not_allowed")
                return
            if principal == OWNER and name != "login":
                nonce = self.server.owner.verify(self._cookie())
                sent = self.headers.get("X-CSRF-Token") or ""
                if not hmac.compare_digest(sent, self.server.owner.csrf(nonce or "")):
                    self._error(403, "csrf")
                    return
        getattr(self, "_do_" + name)(method, item_id, principal)

    def _read_body(self, limit: int = MAX_BODY) -> bytes | None:
        """The request body, or None after an error response has been sent."""
        header = self.headers.get("Content-Length")
        if header is None or not header.strip().isdigit():
            self.close_connection = True
            self._error(400, "bad_request")
            return None
        length = int(header.strip())
        if length > limit:
            self.close_connection = True
            self._error(413, "payload_too_large")
            return None
        chunks, left = [], length
        deadline = time.monotonic() + BODY_DEADLINE
        try:
            while left > 0:
                chunk = self.rfile.read1(min(left, 65536))
                if not chunk or time.monotonic() > deadline:
                    break
                chunks.append(chunk)
                left -= len(chunk)
        except (TimeoutError, OSError):
            pass
        if left > 0:
            self.close_connection = True
            self._body_read = True
            self._error(408, "request_timeout")
            return None
        self._body_read = True
        return b"".join(chunks)

    def _read_json(self, limit: int = MAX_BODY) -> tuple[bool, object]:
        body = self._read_body(limit)
        if body is None:
            return False, None
        try:
            return True, json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._error(400, "bad_request")
            return False, None

    # -- owner UI -------------------------------------------------------------------------------

    def _do_page(self, method, item_id, principal) -> None:
        self._send(200, self.server.page, "text/html; charset=utf-8",
                   {"X-Frame-Options": "DENY", "Content-Security-Policy": CSP})

    def _do_session(self, method, item_id, principal) -> None:
        if principal == OWNER:
            nonce = self.server.owner.verify(self._cookie())
            self._json(200, {"owner": True, "csrf": self.server.owner.csrf(nonce or "")})
        else:
            self._json(200, {"owner": False, "csrf": None})

    def _do_login(self, method, item_id, principal) -> None:
        owner, limiter = self.server.owner, self.server.limiter
        key = self._client_key()
        wait = limiter.retry_after(key)
        if wait:
            self._error(429, "too_many_attempts", {"Retry-After": str(wait)}, retry_after=wait)
            return
        ok, payload = self._read_json(MAX_LOGIN_BODY)
        if not ok:
            return
        limiter.slow_down()  # many failures from everywhere: every attempt waits a little, nobody is locked out
        candidate = payload.get("passphrase") if isinstance(payload, dict) else None
        if not owner.check(candidate):
            limiter.failure(key)
            self._error(401, "wrong_passphrase")
            return
        limiter.success(key)
        value, csrf = owner.issue()
        self._json(200, {"owner": True, "csrf": csrf}, {"Set-Cookie": owner.set_cookie(value)})

    def _do_logout(self, method, item_id, principal) -> None:
        self.server.owner.revoke(self._cookie() or "")
        self._json(200, {"owner": False}, {"Set-Cookie": self.server.owner.clear_cookie()})

    # -- records --------------------------------------------------------------------------------

    def _do_records(self, method, item_id, principal) -> None:
        self._json(200, {"records": self.server.store.list()})

    def _do_record(self, method, doc_id, principal) -> None:
        store = self.server.store
        if method == "GET":
            record = store.get(doc_id or "")
            if record is None:
                self._error(404, "not_found")
            else:
                self._json(200, record)
        elif method == "PUT":
            self._put(doc_id or "")
        elif store.delete(doc_id or ""):
            self._json(200, {"deleted": True})
        else:
            self._error(404, "not_found")

    def _put(self, doc_id: str) -> None:
        ok, payload = self._read_json()
        if not ok:
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

    def _do_dismiss(self, method, doc_id, principal) -> None:
        ok, payload = self._read_json()
        if not ok:
            return
        version = payload.get("version") if isinstance(payload, dict) else None
        if (not isinstance(payload, dict) or set(payload) != {"version"} or isinstance(version, bool)
                or not isinstance(version, int) or version < 1):
            self._error(400, "bad_request")
            return
        try:
            result = self.server.store.dismiss(doc_id or "", version)
        except NotFound:
            self._error(404, "not_found")
        except Conflict as exc:
            self._error(409, "version_conflict", current=exc.current)
        else:
            self._json(200, result)

    def _do_restore(self, method, doc_id, principal) -> None:
        if self.headers.get("Content-Length", "0").strip() not in ("", "0"):
            if self._read_body() is None:
                return
        try:
            result = self.server.store.restore(doc_id or "")
        except NotFound:
            self._error(404, "not_found")
        else:
            self._json(200, result)

    # -- asks -----------------------------------------------------------------------------------

    def _do_asks(self, method, item_id, principal) -> None:
        store = self.server.store
        if method == "GET":
            query = parse_qs(urlsplit(self.path).query)
            state = (query.get("state") or [None])[0]
            since = (query.get("since") or [None])[0]
            limit = (query.get("limit") or ["200"])[0]
            order = (query.get("order") or ["desc"])[0]
            if (state not in (None, "open", "answered", "cancelled")
                    or (since is not None and not TIMESTAMP.fullmatch(since))
                    or not (limit.isascii() and limit.isdigit() and 1 <= int(limit) <= 1000)
                    or order not in ("asc", "desc")):
                self._error(400, "bad_request")
                return
            self._json(200, {"asks": store.list_asks(state, int(limit), since, order == "asc")})
            return
        ok, payload = self._read_json()
        if not ok:
            return
        try:
            ask = store.create_ask(payload)
        except Invalid as exc:
            self._error(422, "invalid", errors=exc.errors)
        else:
            self._json(201, ask)

    def _do_ask(self, method, ask_id, principal) -> None:
        ask = self.server.store.get_ask(ask_id or "")
        if ask is None:
            self._error(404, "not_found")
        else:
            self._json(200, ask)

    def _do_answer(self, method, ask_id, principal) -> None:
        ok, payload = self._read_json()
        if not ok:
            return
        if not isinstance(payload, dict) or set(payload) != {"answers"}:
            self._error(400, "bad_request")
            return
        try:
            ask = self.server.store.answer_ask(ask_id or "", payload["answers"])
        except NotFound:
            self._error(404, "not_found")
        except Conflict as exc:
            self._error(409, "not_open", current=exc.current)
        except Invalid as exc:
            self._error(422, "invalid", errors=exc.errors)
        else:
            self._json(200, ask)

    def _do_cancel(self, method, ask_id, principal) -> None:
        if self.headers.get("Content-Length", "0").strip() not in ("", "0"):
            if self._read_body() is None:
                return
        try:
            ask = self.server.store.cancel_ask(ask_id or "")
        except NotFound:
            self._error(404, "not_found")
        except Conflict as exc:
            self._error(409, "not_open", current=exc.current)
        else:
            self._json(200, ask)

    # -- usage ----------------------------------------------------------------------------------

    def _do_usage(self, method, item_id, principal) -> None:
        plan, factor = self.server.usage_plan
        now = int(self.server.clock())
        if method == "GET":
            rows = self.server.store.list_usage()
            self._json(200, {"now": now, "plan": plan, "factor": factor,
                             "windows": usage.windows(rows, factor, now)})
            return
        if plan is None:
            self._error(409, "usage_off")
            return
        ok, payload = self._read_json(usage.MAX_BODY)
        if not ok:
            return
        samples, source, errors = usage.validate(payload, now)
        if errors:
            self._error(422, "invalid", errors=errors)
            return
        self._json(200, {"stored": self.server.store.add_usage(samples, source, plan, factor, now)})

    # -- MCP ------------------------------------------------------------------------------------

    def _rpc_error(self, status: int, code: int, message: str) -> None:
        self._json(status, {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}})

    def _do_mcp(self, method, item_id, principal) -> None:
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

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_POST(self) -> None:
        self._dispatch("POST")


class BoardServer(ThreadingHTTPServer):
    """A threading HTTP server that serves at most `max_connections` connections at once."""

    daemon_threads = True
    BUSY = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 16\r\n"
            b"Retry-After: 1\r\nConnection: close\r\n\r\n" + b'{"error":"busy"}')

    def __init__(self, address, handler, max_connections: int = MAX_CONNECTIONS) -> None:
        super().__init__(address, handler)
        self.max_connections = max_connections
        self._slots = threading.BoundedSemaphore(max_connections)

    def process_request(self, request, client_address) -> None:
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(self.BUSY)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(store: Store, tokens: Tokens, title: str, host: str, port: int,
                allow_origins: tuple[str, ...] = (), owner: OwnerAuth | None = None,
                session_url: str | None = None, public_origin: str | None = None,
                trust_proxy: bool = False, limiter: LoginLimiter | None = None,
                max_connections: int = MAX_CONNECTIONS, usage_plan: tuple[str | None, float] = (None, 5.0),
                clock=time.time) -> ThreadingHTTPServer:
    server = BoardServer((host, port), Handler, max_connections)
    if owner is not None and owner.revocations is None:
        owner.revocations = store  # logouts survive a restart
    server.store = store  # type: ignore[attr-defined]
    server.tokens = tokens  # type: ignore[attr-defined]
    server.owner = owner  # type: ignore[attr-defined]
    server.limiter = limiter or LoginLimiter()  # type: ignore[attr-defined]
    server.page = build_board.build(title, None, None, session_url).encode("utf-8")  # type: ignore[attr-defined]
    server.allow_origins = allow_origins  # type: ignore[attr-defined]
    server.public_origin = public_origin  # type: ignore[attr-defined]
    server.trust_proxy = trust_proxy  # type: ignore[attr-defined]
    server.usage_plan = usage_plan  # type: ignore[attr-defined]
    server.clock = clock  # type: ignore[attr-defined]
    return server


def load_secret(db: str, env=os.environ) -> bytes:
    """TLD_BOARD_SECRET, else the secret file next to the database (created once, mode 0600)."""
    value = env.get("TLD_BOARD_SECRET") or ""
    if value:
        if len(value) < MIN_SECRET:
            raise ValueError(f"TLD_BOARD_SECRET must have at least {MIN_SECRET} characters")
        return value.encode("utf-8")
    path = Path(db).with_name(Path(db).name + ".secret")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        text = path.read_text(encoding="ascii").strip()
        if len(text) < MIN_SECRET:
            raise ValueError(f"{path} holds fewer than {MIN_SECRET} characters; delete it to make a new one")
        return text.encode("ascii")
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        text = secrets.token_hex(32)
        handle.write(text + "\n")
    return text.encode("ascii")


def check_session_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment or not url.endswith("/"):
        raise ValueError("TLD_BOARD_SESSION_URL must be an https:// URL that ends with '/'")
    return url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the tld board.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="0 picks a free port")
    parser.add_argument("--db", default=os.environ.get("TLD_BOARD_DB") or "board.sqlite3")
    parser.add_argument("--title", default="tld Board")
    parser.add_argument("--allow-origin", action="append", default=[], dest="allow_origin",
                        help="an Origin that may call POST /mcp; repeatable")
    parser.add_argument("--public-origin", dest="public_origin",
                        default=os.environ.get("TLD_BOARD_PUBLIC_ORIGIN") or None,
                        help="the board's public origin (https://board.example.org) the owner's POSTs must come from;"
                             " default: the request's Host")
    parser.add_argument("--insecure-cookie", action="store_true", dest="insecure_cookie",
                        help="local development over plain http: the session cookie without Secure")
    parser.add_argument("--session-hours", type=int, default=12, dest="session_hours")
    parser.add_argument("--trust-proxy", action="store_true", dest="trust_proxy",
                        help="rate-limit logins by the last X-Forwarded-For entry (behind exactly one reverse proxy)")
    args = parser.parse_args(argv)
    write = os.environ.get("TLD_BOARD_TOKEN", "")
    passphrase = os.environ.get("TLD_BOARD_OWNER_PASSPHRASE", "")
    if len(write) < MIN_TOKEN:
        print("board_server: TLD_BOARD_TOKEN must be set to at least 24 characters", file=sys.stderr)
        return 2
    if passphrase and len(passphrase) < MIN_PASSPHRASE:
        print(f"board_server: TLD_BOARD_OWNER_PASSPHRASE must have at least {MIN_PASSPHRASE} characters",
              file=sys.stderr)
        return 2
    if passphrase and hmac.compare_digest(passphrase.encode(), write.encode()):
        print("board_server: TLD_BOARD_OWNER_PASSPHRASE must differ from TLD_BOARD_TOKEN", file=sys.stderr)
        return 2
    try:
        usage_plan = usage.parse_plan(os.environ)
    except ValueError as exc:
        print(f"board_server: {exc}", file=sys.stderr)
        return 2
    if not 1 <= args.session_hours <= 24 * 30:
        print("board_server: --session-hours must be between 1 and 720", file=sys.stderr)
        return 2
    try:
        session_url = check_session_url(os.environ.get("TLD_BOARD_SESSION_URL"))
        if args.public_origin:
            parts = urlsplit(args.public_origin)
            if parts.scheme not in ("https", "http") or not parts.netloc or parts.path not in ("", "/"):
                raise ValueError("--public-origin must be scheme://host[:port]")
            args.public_origin = f"{parts.scheme}://{parts.netloc}"
        owner = None
        if passphrase:
            owner = OwnerAuth(passphrase, load_secret(args.db), secure=not args.insecure_cookie,
                              max_age=args.session_hours * 3600)
        store = Store(args.db)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"board_server: {exc}", file=sys.stderr)
        return 2
    server = make_server(store, Tokens(write), args.title, args.host, args.port, tuple(args.allow_origin),
                         owner, session_url, args.public_origin, args.trust_proxy, usage_plan=usage_plan)
    print(f"board_server: listening on http://{args.host}:{server.server_address[1]}",
          file=sys.stderr, flush=True)
    if owner is None:
        print("board_server: TLD_BOARD_OWNER_PASSPHRASE is not set: the owner UI is off (API only)",
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
