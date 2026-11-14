"""The board server: records API, asks API, the owner's login and the auth matrix of every endpoint."""
import copy
import http.client
import itertools
import json
import os
import stat
import subprocess
import time

import pytest

from board_helpers import PASSPHRASE, SECRET, WRITE, ask_doc, base, call, login, running
from conftest import FIXTURES, tld_cmd

from tld.board import server as board_server

SCRIPT_CMD = tld_cmd("board", "server")


def record(doc_id="f-running-ok--run--plan-f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if doc_id in (d["id"], d["data"]["project"])))


@pytest.fixture
def server(tmp_path):
    with running(tmp_path) as srv:
        yield srv


@pytest.fixture
def owner(server):
    return login(server)


def new_ask(server, **changes):
    status, _, body = call(server, "POST", "/api/asks", token=WRITE, body=ask_doc(**changes))
    assert status == 201, body
    return body


# ---- the auth matrix ------------------------------------------------------------------------------
# (method, path template, body, expected status for: no credentials, session token, owner cookie)
MATRIX = [
    ("GET", "/healthz", None, (200, 200, 200)),
    ("GET", "/", None, (200, 200, 200)),
    ("GET", "/api/session", None, (200, 200, 200)),
    ("GET", "/api/records", None, (401, 200, 200)),
    ("GET", "/api/records/{rec}", None, (401, 200, 200)),
    ("PUT", "/api/records/{rec}", "record", (401, 200, 403)),
    ("DELETE", "/api/records/{rec}", None, (401, 200, 403)),
    ("GET", "/api/asks", None, (401, 200, 200)),
    ("POST", "/api/asks", "ask", (401, 201, 403)),
    ("GET", "/api/asks/{ask}", None, (401, 200, 200)),
    ("POST", "/api/asks/{ask}/answer", "answers", (401, 403, 200)),
    ("POST", "/api/asks/{ask}/cancel", None, (401, 200, 200)),
    ("POST", "/api/records/{rec}/dismiss", "dismiss", (401, 403, 200)),
    ("POST", "/api/records/{rec}/restore", None, (401, 403, 200)),
    ("POST", "/mcp", "rpc", (401, 200, 403)),
    ("GET", "/api/usage", None, (401, 403, 200)),
    ("POST", "/api/usage", "usage", (401, 200, 403)),
    ("POST", "/logout", None, (401, 403, 200)),
]


def _matrix_id(slug):
    return f"{slug}--run--x"


def _matrix_record(slug):
    data = record()
    data.update(project=slug, repo=f"example-org/{slug}", plan_slug="x", needs_you=True, needs_you_reason="Answer the ask",
                needs_you_since="2026-11-09T11:00:00Z", status="waiting_user", next_check_at=None)
    return data


def _body(kind, server, slug="f-running-ok"):
    return {"record": {"data": _matrix_record(slug), "if_version": 1}, "ask": ask_doc(),
            "dismiss": {"version": 1}, "answers": {"answers": {"SEC-1": "plan", "go": True}},
            "rpc": {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            "usage": {"five_hour": {"utilization": 0.3, "resets_at": int(time.time()) + 3600}, "source": "final"},
            None: None}[kind]


_MATRIX_IDS = itertools.count(1)


@pytest.fixture(scope="module")
def matrix_server(tmp_path_factory):
    """One server for the whole matrix: each case brings its own record id, ask and owner session, so a case
    that deletes, cancels or logs out changes nothing another case reads."""
    with running(tmp_path_factory.mktemp("matrix"), usage_plan=("max", 5.0)) as srv:
        yield srv


@pytest.mark.parametrize("who", ["none", "session", "owner"])
@pytest.mark.parametrize("method,path,body,expected", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_auth_matrix(matrix_server, who, method, path, body, expected):
    srv = matrix_server
    slug = f"matrix-{next(_MATRIX_IDS)}"
    rec = _matrix_id(slug)
    srv.store.set(rec, _matrix_record(slug), None)
    ask = srv.store.create_ask(ask_doc())
    cookie, csrf = login(srv)
    url = path.format(rec=rec, ask=ask["id"])
    kwargs = {"body": _body(body, srv, slug)}
    if who == "session":
        kwargs["token"] = WRITE
    elif who == "owner":
        kwargs.update(cookie=cookie, csrf=csrf, origin=True)
    status, _, payload = call(srv, method, url, **kwargs)
    assert status == expected[["none", "session", "owner"].index(who)], payload


def test_a_wrong_token_is_401_even_with_an_owner_cookie(server, owner):
    cookie, csrf = owner
    status, headers, _ = call(server, "GET", "/api/records", token="x" * 24, cookie=cookie)
    assert status == 401 and headers["WWW-Authenticate"].startswith("Bearer")


def test_basic_auth_is_not_accepted(server):
    import base64
    basic = base64.b64encode(f"anyone:{WRITE}".encode()).decode()
    assert call(server, "GET", "/api/records", headers={"Authorization": f"Basic {basic}"})[0] == 401


def test_session_endpoint_reports_the_owner(server, owner):
    cookie, csrf = owner
    assert call(server, "GET", "/api/session")[2] == {"owner": False, "csrf": None}
    assert call(server, "GET", "/api/session", cookie=cookie)[2] == {"owner": True, "csrf": csrf}


# ---- login ----------------------------------------------------------------------------------------

def test_login_sets_a_strict_http_only_cookie(tmp_path):
    with running(tmp_path, insecure=False) as srv:
        status, headers, body = call(srv, "POST", "/login", body={"passphrase": PASSPHRASE},
                                     origin=base(srv).replace("http:", "https:"))
        assert status == 200 and body["owner"] is True and len(body["csrf"]) == 40
        cookie = headers["Set-Cookie"]
        assert cookie.startswith("__Host-tld_owner=")
        for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=43200"):
            assert flag in cookie.split("; ")
        assert "Domain" not in cookie
        # A secure board does not take an Origin over plain http.
        assert call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)[0] == 403


def test_insecure_cookie_has_no_secure_flag(server):
    status, headers, _ = call(server, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)
    assert status == 200
    cookie = headers["Set-Cookie"]
    assert cookie.startswith("tld_owner=") and "Secure" not in cookie and "HttpOnly" in cookie


def test_wrong_passphrase_is_401_and_sets_no_cookie(server):
    status, headers, body = call(server, "POST", "/login", body={"passphrase": "nope" * 5}, origin=True)
    assert (status, body) == (401, {"error": "wrong_passphrase"}) and "Set-Cookie" not in headers
    assert call(server, "POST", "/login", body={"passphrase": 5}, origin=True)[0] == 401
    assert call(server, "POST", "/login", body=["x"], origin=True)[0] == 401
    assert call(server, "POST", "/login", raw=b"nope", origin=True)[0] == 400


def test_login_rate_limit_locks_out_with_backoff(tmp_path):
    clock = [1000.0]
    limiter = board_server.LoginLimiter(clock=lambda: clock[0])
    with running(tmp_path, limiter=limiter) as srv:
        for _ in range(board_server.LoginLimiter.FREE):
            assert call(srv, "POST", "/login", body={"passphrase": "w" * 20}, origin=True)[0] == 401
        status, headers, body = call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)
        assert status == 429 and body["error"] == "too_many_attempts" and int(headers["Retry-After"]) == 2
        clock[0] += 3
        assert call(srv, "POST", "/login", body={"passphrase": "w" * 20}, origin=True)[0] == 401
        status, headers, _ = call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)
        assert status == 429 and int(headers["Retry-After"]) == 4  # doubled
        clock[0] += 5
        assert call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)[0] == 200
        assert limiter.retry_after("127.0.0.1") == 0  # a success clears the client


def test_login_limiter_caps_the_lockout_and_only_slows_down_globally():
    clock = [0.0]
    limiter = board_server.LoginLimiter(clock=lambda: clock[0])
    for _ in range(40):
        limiter.failure("a")
    assert limiter.retry_after("a") == board_server.LoginLimiter.MAX_LOCK
    slept = []
    other = board_server.LoginLimiter(clock=lambda: clock[0], sleep=slept.append)
    for n in range(board_server.LoginLimiter.GLOBAL_MAX * 3):
        other.failure(f"ip{n}")  # one failure each: no client is locked
    assert other.retry_after("fresh") == 0  # nobody is locked out by the others' failures
    assert other.delay() == board_server.LoginLimiter.MAX_DELAY  # but every attempt waits, at most 2 s
    other.slow_down()
    assert slept == [board_server.LoginLimiter.MAX_DELAY]
    clock[0] += board_server.LoginLimiter.WINDOW + 1
    assert other.delay() == 0


def test_a_flood_of_wrong_passphrases_does_not_lock_the_owner_out(tmp_path):
    slept = []
    limiter = board_server.LoginLimiter(sleep=slept.append)
    with running(tmp_path, limiter=limiter, trust_proxy=True) as srv:
        for n in range(board_server.LoginLimiter.GLOBAL_MAX + 5):
            assert call(srv, "POST", "/login", body={"passphrase": "w" * 20}, origin=True,
                        headers={"X-Forwarded-For": f"203.0.113.{n}"})[0] == 401
        status, _, _ = call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True,
                            headers={"X-Forwarded-For": "198.51.100.1"})
        assert status == 200 and slept and max(slept) <= board_server.LoginLimiter.MAX_DELAY


def test_limiter_keys_ipv6_by_its_64_and_unwraps_mapped_ipv4():
    assert board_server.client_key("2001:db8:1:2:aaaa::1") == board_server.client_key("2001:db8:1:2:bbbb::9")
    assert board_server.client_key("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert board_server.client_key("2001:db8:1:3::1") != board_server.client_key("2001:db8:1:2::1")
    assert board_server.client_key("::ffff:203.0.113.9") == "203.0.113.9"
    assert board_server.client_key("203.0.113.9") == "203.0.113.9"
    assert board_server.client_key("not an ip" + "x" * 100) == ("not an ip" + "x" * 100)[:64]


def test_passphrase_compare_is_constant_time_on_digests():
    auth = board_server.OwnerAuth(PASSPHRASE, SECRET)
    assert auth.check(PASSPHRASE) and not auth.check(PASSPHRASE + "x") and not auth.check(None)
    import inspect
    assert "compare_digest" in inspect.getsource(board_server.OwnerAuth.check)


# ---- cookies, CSRF and Origin -----------------------------------------------------------------------

def _owner_post_cases(server):
    ask = new_ask(server)
    call(server, "PUT", f"/api/records/{_matrix_id('csrf-rec')}", token=WRITE, body={"data": _matrix_record("csrf-rec")})
    return [("answer", f"/api/asks/{ask['id']}/answer", {"answers": {"SEC-1": "plan", "go": True}}),
            ("cancel", f"/api/asks/{ask['id']}/cancel", None),
            ("dismiss", f"/api/records/{_matrix_id('csrf-rec')}/dismiss", {"version": 1}),
            ("restore", f"/api/records/{_matrix_id('csrf-rec')}/restore", None),
            ("logout", "/logout", None)]


@pytest.mark.parametrize("name", ["answer", "cancel", "dismiss", "restore", "logout"])
def test_owner_post_needs_the_csrf_token_and_the_origin(server, owner, name):
    cookie, csrf = owner
    path, body = next((p, b) for n, p, b in _owner_post_cases(server) if n == name)
    assert call(server, "POST", path, body=body, cookie=cookie, origin=True)[2] == {"error": "csrf"}
    assert call(server, "POST", path, body=body, cookie=cookie, csrf="0" * 40, origin=True)[0] == 403
    assert call(server, "POST", path, body=body, cookie=cookie, csrf=csrf)[2] == {"error": "origin_not_allowed"}
    assert call(server, "POST", path, body=body, cookie=cookie, csrf=csrf,
                origin="https://evil.example.org")[0] == 403
    assert call(server, "POST", path, body=body, cookie=cookie, csrf=csrf, origin=True,
                headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert call(server, "POST", path, body=body, cookie=cookie, csrf=csrf, origin=True)[0] == 200


def test_login_needs_the_origin(server):
    assert call(server, "POST", "/login", body={"passphrase": PASSPHRASE})[2] == {"error": "origin_not_allowed"}
    assert call(server, "POST", "/login", body={"passphrase": PASSPHRASE}, origin="http://evil.example.org")[0] == 403


def test_public_origin_is_the_only_origin_accepted(tmp_path):
    with running(tmp_path, public_origin="https://board.example.org") as srv:
        assert call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)[0] == 403
        assert call(srv, "POST", "/login", body={"passphrase": PASSPHRASE},
                    origin="https://board.example.org")[0] == 200


def test_a_tampered_or_expired_cookie_is_refused(tmp_path):
    now = [10_000.0]
    auth = board_server.OwnerAuth(PASSPHRASE, SECRET, secure=False, max_age=60, clock=lambda: now[0])
    value, csrf = auth.issue()
    assert auth.verify(value)
    expires, nonce, sig = value.split(".")
    assert auth.verify(f"{int(expires) + 1000}.{nonce}.{sig}") is None
    assert auth.verify(f"{expires}.{nonce}.{'0' * 64}") is None
    assert auth.verify("garbage") is None and auth.verify(None) is None
    now[0] += 61
    assert auth.verify(value) is None
    # Another passphrase (a rotation) signs with another key: old cookies stop working.
    later = board_server.OwnerAuth(PASSPHRASE + "!", SECRET, clock=lambda: 10_000.0)
    assert later.verify(value) is None


def test_logout_revokes_the_session(server, owner):
    cookie, csrf = owner
    status, headers, _ = call(server, "POST", "/logout", cookie=cookie, csrf=csrf, origin=True)
    assert status == 200 and "Max-Age=0" in headers["Set-Cookie"]
    assert call(server, "GET", "/api/records", cookie=cookie)[0] == 401
    assert call(server, "GET", "/api/session", cookie=cookie)[2]["owner"] is False


def test_logout_survives_a_restart_and_login_works_after_it(tmp_path):
    with running(tmp_path) as srv:
        cookie, csrf = login(srv)
        assert call(srv, "POST", "/logout", cookie=cookie, csrf=csrf, origin=True)[0] == 200
    with running(tmp_path) as srv:  # a new process: same database, a fresh OwnerAuth
        assert call(srv, "GET", "/api/records", cookie=cookie)[0] == 401
        fresh, _ = login(srv)  # board login after a restart
        assert call(srv, "GET", "/api/records", cookie=fresh)[0] == 200


def test_a_silent_or_trickling_client_is_dropped(tmp_path, monkeypatch):
    import socket
    import time
    assert board_server.Handler.timeout == board_server.SOCKET_TIMEOUT == 15
    monkeypatch.setattr(board_server.Handler, "timeout", 0.5)
    monkeypatch.setattr(board_server, "BODY_DEADLINE", 0.6)
    with running(tmp_path) as srv:
        port = srv.server_address[1]
        idle = socket.create_connection(("127.0.0.1", port), timeout=5)
        idle.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n")  # headers never finish
        start = time.monotonic()
        assert idle.recv(1024) == b"" and time.monotonic() - start < 4  # closed by the server
        slow = socket.create_connection(("127.0.0.1", port), timeout=5)
        slow.sendall(b"POST /login HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Length: 50\r\n"
                     b"Origin: http://127.0.0.1:%d\r\n\r\n" % (port, port))
        reply = b""
        for _ in range(8):  # one byte at a time, each in time for the socket timeout, never the whole body
            try:
                slow.sendall(b"{")
            except OSError:
                break
            time.sleep(0.2)
            slow.settimeout(0.01)
            try:
                reply += slow.recv(4096)
            except (TimeoutError, BlockingIOError, socket.timeout):
                pass
            slow.settimeout(5)
            if reply:
                break
        assert b" 408 " in reply.split(b"\r\n", 1)[0]
        idle.close()
        slow.close()


def test_connections_beyond_the_cap_get_503(tmp_path):
    import socket
    with running(tmp_path, max_connections=2) as srv:
        port = srv.server_address[1]
        held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(2)]
        for h in held:
            h.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")  # keep-alive: the slot stays taken
            assert b"200" in h.recv(4096)
        extra = socket.create_connection(("127.0.0.1", port), timeout=5)
        assert extra.recv(4096).startswith(b"HTTP/1.1 503")
        extra.close()
        for h in held:
            h.close()
        import time
        for _ in range(50):  # the slots come back once the held connections close
            if call(srv, "GET", "/healthz")[0] == 200:
                break
            time.sleep(0.05)
        assert call(srv, "GET", "/healthz")[0] == 200


def test_without_a_passphrase_the_owner_ui_is_off(tmp_path):
    with running(tmp_path, owner=False) as srv:
        assert call(srv, "GET", "/")[2] == {"error": "owner_ui_disabled"}
        assert call(srv, "POST", "/login", body={"passphrase": PASSPHRASE}, origin=True)[0] == 404
        assert call(srv, "GET", "/api/session")[0] == 404
        assert call(srv, "GET", "/api/records", token=WRITE)[0] == 200
        assert call(srv, "GET", "/api/records", cookie="tld_owner=1.2.3")[0] == 401


# ---- records --------------------------------------------------------------------------------------

def test_put_get_list_delete_roundtrip(server, owner):
    cookie, _ = owner
    status, _, body = call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body={"data": record()})
    assert (status, body) == (200, {"id": "f-running-ok--run--plan-f-running-ok", "version": 1})
    _, _, body = call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE,
                      body={"data": record(), "if_version": 1})
    assert body == {"id": "f-running-ok--run--plan-f-running-ok", "version": 2}
    status, _, body = call(server, "GET", "/api/records/f-running-ok--run--plan-f-running-ok", cookie=cookie)
    assert status == 200 and body["version"] == 2 and body["data"] == record()
    _, _, body = call(server, "GET", "/api/records", cookie=cookie)
    assert [r["id"] for r in body["records"]] == ["f-running-ok--run--plan-f-running-ok"]
    assert call(server, "DELETE", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE)[2] == {"deleted": True}
    assert call(server, "DELETE", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE)[:3:2] == (404, {"error": "not_found"})


def test_put_conflict_returns_409_with_the_current_record(server):
    call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body={"data": record()})
    status, _, body = call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body={"data": record()})
    assert status == 409 and body["error"] == "version_conflict" and body["current"]["version"] == 1
    status, _, body = call(server, "PUT", "/api/records/f-starting--run--plan-f-starting", token=WRITE,
                           body={"data": record("f-starting--run--plan-f-starting"), "if_version": 4})
    assert status == 409 and body["current"] is None


def test_put_invalid_returns_422_with_errors(server):
    bad = record()
    bad["surprise"] = 1
    status, _, body = call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body={"data": bad})
    assert status == 422 and body["error"] == "invalid" and body["errors"]
    assert call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, raw=b"nope")[0] == 400
    assert call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body=[1])[0] == 400
    assert call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body={"if_version": 1})[0] == 400


def test_if_version_true_is_400(server):
    for bad in (True, "1", 0, 1.5):
        status, _, body = call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE,
                               body={"data": record(), "if_version": bad})
        assert (status, body) == (400, {"error": "bad_request"})
    assert call(server, "PUT", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE,
                body={"data": record(), "if_version": None})[0] == 200


# ---- asks -----------------------------------------------------------------------------------------

def test_get_asks_since_limit_and_order(server):
    ids = [new_ask(server)["id"] for _ in range(3)]
    _, _, everything = call(server, "GET", "/api/asks?order=asc&limit=1000", token=WRITE)
    assert [a["id"] for a in everything["asks"]] == sorted(ids, key=lambda i: next(
        (a["created_at"], a["id"]) for a in everything["asks"] if a["id"] == i))
    _, _, one = call(server, "GET", "/api/asks?order=asc&limit=1", token=WRITE)
    assert [a["id"] for a in one["asks"]] == [everything["asks"][0]["id"]]
    _, _, none = call(server, "GET", "/api/asks?since=2999-01-01T00:00:00Z", token=WRITE)
    assert none == {"asks": []}
    _, _, all_ = call(server, "GET", "/api/asks?since=2000-01-01T00:00:00Z&order=desc", token=WRITE)
    assert len(all_["asks"]) == 3
    assert call(server, "GET", "/api/asks?since=", token=WRITE)[0] == 200


@pytest.mark.parametrize("query", ["since=2026-01-01", "since=x", "limit=0", "limit=1001", "limit=-1", "limit=1.5",
                                   "limit=abc", "limit=" + "9" * 5000, "order=ASC", "order=up"])
def test_get_asks_rejects_bad_since_limit_and_order(server, query):
    status, _, body = call(server, "GET", f"/api/asks?{query}", token=WRITE)
    assert (status, body) == (400, {"error": "bad_request"})


def test_ask_lifecycle(server, owner):
    cookie, csrf = owner
    ask = new_ask(server)
    assert ask["state"] == "open" and ask["answers"] == {} and ask["id"].startswith("a-")
    _, _, listing = call(server, "GET", "/api/asks?state=open", cookie=cookie)
    assert [a["id"] for a in listing["asks"]] == [ask["id"]]
    path = f"/api/asks/{ask['id']}/answer"
    status, _, body = call(server, "POST", path, body={"answers": {"SEC-1": "nope", "go": True}},
                           cookie=cookie, csrf=csrf, origin=True)
    assert status == 422 and any("SEC-1" in e for e in body["errors"])
    status, _, body = call(server, "POST", path, body={"answers": {"SEC-1": "issue", "go": False}},
                           cookie=cookie, csrf=csrf, origin=True)
    assert status == 200 and body["state"] == "answered" and body["answers"] == {"SEC-1": "issue", "go": False}
    assert body["answered_at"]
    status, _, body = call(server, "POST", path, body={"answers": {"SEC-1": "plan", "go": True}},
                           cookie=cookie, csrf=csrf, origin=True)
    assert status == 409 and body["error"] == "not_open"
    assert call(server, "POST", f"/api/asks/{ask['id']}/cancel", token=WRITE)[0] == 409
    _, _, read = call(server, "GET", f"/api/asks/{ask['id']}", token=WRITE)
    assert read["answers"] == {"SEC-1": "issue", "go": False}


def test_ask_create_is_validated_and_ids_are_server_assigned(server):
    status, _, body = call(server, "POST", "/api/asks", token=WRITE, body=ask_doc(id="a-0000000000000000"))
    assert status == 422 and any("set by the board" in e for e in body["errors"])
    status, _, body = call(server, "POST", "/api/asks", token=WRITE, body=ask_doc(questions=[]))
    assert status == 422
    assert call(server, "POST", "/api/asks", token=WRITE, raw=b"{")[0] == 400


def test_cancel_by_the_session_and_unknown_asks(server):
    ask = new_ask(server)
    status, _, body = call(server, "POST", f"/api/asks/{ask['id']}/cancel", token=WRITE)
    assert status == 200 and body["state"] == "cancelled"
    assert call(server, "POST", f"/api/asks/{ask['id']}/cancel", token=WRITE)[0] == 200  # idempotent
    assert call(server, "GET", "/api/asks/a-ffffffffffffffff", token=WRITE)[0] == 404
    assert call(server, "GET", "/api/asks/../etc", token=WRITE)[0] == 404
    assert call(server, "POST", "/api/asks/a-ffffffffffffffff/cancel", token=WRITE)[0] == 404
    assert call(server, "GET", "/api/asks?state=bogus", token=WRITE)[0] == 400


def test_answer_body_must_be_exactly_answers(server, owner):
    cookie, csrf = owner
    ask = new_ask(server)
    status, _, _ = call(server, "POST", f"/api/asks/{ask['id']}/answer",
                        body={"answers": {"SEC-1": "plan", "go": True}, "state": "open"},
                        cookie=cookie, csrf=csrf, origin=True)
    assert status == 400


# ---- the page and the protocol ----------------------------------------------------------------------

def test_page_is_served_with_security_headers(server):
    for path in ("/", "/index.html"):
        status, headers, body = call(server, "GET", path)
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert b"<title>T</title>" in body
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "connect-src 'self'" in headers["Content-Security-Policy"]
    _, headers, _ = call(server, "GET", "/api/records", token=WRITE)
    assert "Content-Security-Policy" not in headers and headers["Cache-Control"] == "no-store"


def test_page_carries_the_session_url(tmp_path):
    with running(tmp_path, session_url="https://sessions.example.org/") as srv:
        assert b'var SESSION_URL = "https://sessions.example.org/";' in call(srv, "GET", "/")[2]


def test_unknown_route_is_404(server):
    assert call(server, "GET", "/nope")[2] == {"error": "not_found"}
    assert call(server, "GET", "/nope", token=WRITE)[0] == 404


def test_wrong_method_is_405(server):
    status, headers, body = call(server, "POST", "/api/records", token=WRITE, body={})
    assert status == 405 and headers["Allow"] == "GET" and body == {"error": "method_not_allowed"}
    assert call(server, "POST", "/", token=WRITE, body={})[0] == 405
    assert call(server, "DELETE", "/", token=WRITE)[0] == 405
    assert call(server, "GET", "/login")[0] == 405
    status, headers, _ = call(server, "POST", "/api/records/f-running-ok--run--plan-f-running-ok", token=WRITE, body={})
    assert status == 405 and headers["Allow"] == "GET, PUT, DELETE"


def test_responses_have_content_length(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    auth = {"Authorization": f"Bearer {WRITE}"}
    for method, path, body in (("GET", "/healthz", None), ("GET", "/", None), ("GET", "/nope", None),
                               ("POST", "/api/records", b"{}"), ("GET", "/api/records", None)):
        conn.request(method, path, body=body, headers=auth)
        resp = conn.getresponse()
        data = resp.read()
        assert int(resp.getheader("Content-Length")) == len(data)
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("PUT", "/api/records/f-running-ok--run--plan-f-running-ok", headers=auth)  # no Content-Length at all
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 400
    conn.close()


def test_oversized_body_is_413(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.putrequest("PUT", "/api/records/f-running-ok--run--plan-f-running-ok")
    conn.putheader("Authorization", f"Bearer {WRITE}")
    conn.putheader("Content-Length", str(1048576 + 1))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413 and json.loads(resp.read()) == {"error": "payload_too_large"}
    assert resp.getheader("Connection") == "close"
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.putrequest("POST", "/login")
    conn.putheader("Origin", base(server))
    conn.putheader("Content-Length", "5000")
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()


# ---- main ----------------------------------------------------------------------------------------

def run_main(env_extra, *args, tmp_path=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD")}
    env.update(env_extra)
    extra = ["--db", str(tmp_path / "b.sqlite3")] if tmp_path else []
    return subprocess.run([*SCRIPT_CMD, "--port", "0", *extra, *args], env=env, capture_output=True,
                          text=True, timeout=5 if tmp_path else 30)


def test_main_refuses_a_missing_or_short_token():
    result = run_main({})
    assert result.returncode == 2
    assert result.stderr.startswith("board_server: TLD_BOARD_TOKEN")
    result = run_main({"TLD_BOARD_TOKEN": "short"})
    assert result.returncode == 2 and "at least 24" in result.stderr


def test_main_refuses_a_short_passphrase_or_one_equal_to_the_token():
    short = run_main({"TLD_BOARD_TOKEN": WRITE, "TLD_BOARD_OWNER_PASSPHRASE": "fifteen-chars!!"})
    assert short.returncode == 2 and "at least 16" in short.stderr
    same = run_main({"TLD_BOARD_TOKEN": WRITE, "TLD_BOARD_OWNER_PASSPHRASE": WRITE})
    assert same.returncode == 2 and "must differ" in same.stderr


def test_main_refuses_a_short_secret_and_a_bad_session_url():
    env = {"TLD_BOARD_TOKEN": WRITE, "TLD_BOARD_OWNER_PASSPHRASE": PASSPHRASE}
    assert "TLD_BOARD_SECRET" in run_main({**env, "TLD_BOARD_SECRET": "short"}).stderr
    bad = run_main({**env, "TLD_BOARD_SESSION_URL": "http://x.example.org/"})
    assert bad.returncode == 2 and "TLD_BOARD_SESSION_URL" in bad.stderr


def test_secret_file_is_generated_once_with_mode_0600(tmp_path):
    db = str(tmp_path / "b.sqlite3")
    first = board_server.load_secret(db, {})
    path = tmp_path / "b.sqlite3.secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and len(first) == 64
    assert board_server.load_secret(db, {}) == first
    assert board_server.load_secret(db, {"TLD_BOARD_SECRET": "e" * 32}) == b"e" * 32
    path.write_text("tiny")
    with pytest.raises(ValueError):
        board_server.load_secret(db, {})



# ---- dismiss and restore ----------------------------------------------------------------------------

def _put(server, doc_id, data, if_version=None):
    body = {"data": data} if if_version is None else {"data": data, "if_version": if_version}
    return call(server, "PUT", f"/api/records/{doc_id}", token=WRITE, body=body)


def _owner_post(server, owner, path, body=None, **kwargs):
    cookie, csrf = owner
    return call(server, "POST", path, body=body, cookie=cookie, csrf=csrf, origin=True, **kwargs)


def _listed(server, doc_id):
    records = call(server, "GET", "/api/records", token=WRITE)[2]["records"]
    return next(r for r in records if r["id"] == doc_id)


def test_dismiss_shows_dismissed_at_and_a_session_write_clears_it(server, owner):
    assert _put(server, "dis-one--run--x", _matrix_record("dis-one"))[0] == 200
    status, _, body = _owner_post(server, owner, "/api/records/dis-one--run--x/dismiss", {"version": 1})
    assert status == 200 and body["id"] == "dis-one--run--x" and body["version"] == 1 and body["dismissed_at"]
    assert _listed(server, "dis-one--run--x")["dismissed_at"] == body["dismissed_at"]
    assert call(server, "GET", "/api/records/dis-one--run--x", token=WRITE)[2]["dismissed_at"] == body["dismissed_at"]
    assert _put(server, "dis-one--run--x", _matrix_record("dis-one"), 1)[0] == 200
    assert _listed(server, "dis-one--run--x")["dismissed_at"] is None


def test_dismiss_with_a_wrong_version_is_409_version_conflict(server, owner):
    _put(server, "dis-two--run--x", _matrix_record("dis-two"))
    status, _, body = _owner_post(server, owner, "/api/records/dis-two--run--x/dismiss", {"version": 5})
    assert status == 409 and body["error"] == "version_conflict" and body["current"]["version"] == 1


def test_dismiss_of_a_pr_open_record_is_200(server, owner):
    quiet = record()
    quiet.update(project="dis-three", repo="example-org/dis-three", plan_slug="x", status="pr_open",
                 finished_at=quiet["updated_at"], next_check_at=None)
    assert _put(server, "dis-three--run--x", quiet)[0] == 200
    status, _, body = _owner_post(server, owner, "/api/records/dis-three--run--x/dismiss", {"version": 1})
    assert status == 200 and body["dismissed_at"]
    assert _listed(server, "dis-three--run--x")["dismissed_at"] == body["dismissed_at"]


def test_dismiss_with_an_extra_key_is_400(server, owner):
    _put(server, "dis-four--run--x", _matrix_record("dis-four"))
    status, _, body = _owner_post(server, owner, "/api/records/dis-four--run--x/dismiss", {"version": 1, "x": 1})
    assert (status, body) == (400, {"error": "bad_request"})


def test_dismiss_body_must_be_exactly_a_positive_int_version(server, owner):
    _put(server, "dis-five--run--x", _matrix_record("dis-five"))
    path = "/api/records/dis-five--run--x/dismiss"
    for body in ({"version": True}, {"version": 0}, {"version": "1"}, {"version": 1.0}, [], {}):
        status, _, payload = _owner_post(server, owner, path, body)
        assert (status, payload) == (400, {"error": "bad_request"}), body
    status, _, payload = _owner_post(server, owner, path, raw=b"{")
    assert (status, payload) == (400, {"error": "bad_request"})
    for action in ("dismiss", "restore"):
        status, _, payload = _owner_post(server, owner, f"/api/records/no-such/{action}",
                                         {"version": 1} if action == "dismiss" else None)
        assert (status, payload) == (404, {"error": "not_found"})


def test_restore_clears_the_dismissal(server, owner):
    _put(server, "dis-six--run--x", _matrix_record("dis-six"))
    _owner_post(server, owner, "/api/records/dis-six--run--x/dismiss", {"version": 1})
    status, _, body = _owner_post(server, owner, "/api/records/dis-six--run--x/restore")
    assert (status, body) == (200, {"id": "dis-six--run--x", "dismissed_at": None})
    assert _listed(server, "dis-six--run--x")["dismissed_at"] is None


def test_the_owner_still_cannot_write_a_record(server, owner):
    cookie, csrf = owner
    status, _, _ = call(server, "PUT", "/api/records/dis-seven--run--x", cookie=cookie, csrf=csrf, origin=True,
                        body={"data": _matrix_record("dis-seven")})
    assert status == 403


def test_a_session_cannot_dismiss_through_put(server):
    data = _matrix_record("dis-eight")
    data["dismissed_at"] = "2026-11-09T12:00:00Z"
    assert _put(server, "dis-eight--run--x", data)[0] in (200, 400, 422)
    _put(server, "dis-eight--run--x", _matrix_record("dis-eight"))
    entry = call(server, "GET", "/api/records/dis-eight--run--x", token=WRITE)[2]
    assert entry["dismissed_at"] is None


def test_the_matrix_covers_every_policy_entry():
    covered = set()
    for method, path, _, _ in MATRIX:
        url = path.format(rec="x", ask="a-0000000000000000")
        for pattern, name, methods in board_server.ROUTES:
            if pattern.match(url) and method in methods:
                covered.add((name, method))
                break
    # login is the one route outside the matrix: it has no principal, and its own tests cover it.
    assert covered == set(board_server.POLICY) - {("login", "POST")}
