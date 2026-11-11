"""The board server: records API, asks API, the owner's login and the auth matrix of every endpoint."""
import copy
import http.client
import itertools
import json
import os
import stat
import subprocess

import pytest

from board_helpers import PASSPHRASE, SECRET, WRITE, ask_doc, base, call, login, running
from conftest import FIXTURES, tld_cmd

from tld.board import server as board_server

SCRIPT_CMD = tld_cmd("board", "server")


def record(doc_id="f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if d["id"] == doc_id))


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
    ("POST", "/mcp", "rpc", (401, 200, 403)),
    ("POST", "/logout", None, (401, 403, 200)),
]


def _matrix_record(rec):
    data = record()
    data.update(project=rec, repo=f"example-org/{rec}")
    return data


def _body(kind, server, rec="f-running-ok"):
    return {"record": {"data": _matrix_record(rec), "if_version": 1}, "ask": ask_doc(),
            "answers": {"answers": {"SEC-1": "plan", "go": True}},
            "rpc": {"jsonrpc": "2.0", "id": 1, "method": "ping"}, None: None}[kind]


_MATRIX_IDS = itertools.count(1)


@pytest.fixture(scope="module")
def matrix_server(tmp_path_factory):
    """One server for the whole matrix: each case brings its own record id, ask and owner session, so a case
    that deletes, cancels or logs out changes nothing another case reads."""
    with running(tmp_path_factory.mktemp("matrix")) as srv:
        yield srv


@pytest.mark.parametrize("who", ["none", "session", "owner"])
@pytest.mark.parametrize("method,path,body,expected", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_auth_matrix(matrix_server, who, method, path, body, expected):
    srv = matrix_server
    rec = f"matrix-{next(_MATRIX_IDS)}"
    srv.store.set(rec, _matrix_record(rec), None)
    ask = srv.store.create_ask(ask_doc())
    cookie, csrf = login(srv)
    url = path.format(rec=rec, ask=ask["id"])
    kwargs = {"body": _body(body, srv, rec)}
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


def test_login_limiter_caps_the_lockout_and_the_global_rate():
    clock = [0.0]
    limiter = board_server.LoginLimiter(clock=lambda: clock[0])
    for _ in range(40):
        limiter.failure("a")
    assert limiter.retry_after("a") == board_server.LoginLimiter.MAX_LOCK
    other = board_server.LoginLimiter(clock=lambda: clock[0])
    for n in range(board_server.LoginLimiter.GLOBAL_MAX):
        other.failure(f"ip{n}")  # one failure each: no client is locked
    assert other.retry_after("fresh") > 0  # but everybody waits
    clock[0] += board_server.LoginLimiter.WINDOW + 1
    assert other.retry_after("fresh") == 0


def test_trust_proxy_keys_the_limiter_on_x_forwarded_for(tmp_path):
    limiter = board_server.LoginLimiter()
    with running(tmp_path, limiter=limiter, trust_proxy=True) as srv:
        call(srv, "POST", "/login", body={"passphrase": "w" * 20}, origin=True,
             headers={"X-Forwarded-For": "203.0.113.9, 198.51.100.7"})
    assert set(limiter._fails) == {"198.51.100.7"}


def test_passphrase_compare_is_constant_time_on_digests():
    auth = board_server.OwnerAuth(PASSPHRASE, SECRET)
    assert auth.check(PASSPHRASE) and not auth.check(PASSPHRASE + "x") and not auth.check(None)
    import inspect
    assert "compare_digest" in inspect.getsource(board_server.OwnerAuth.check)


# ---- cookies, CSRF and Origin -----------------------------------------------------------------------

def test_owner_post_needs_the_csrf_token_and_the_origin(server, owner):
    cookie, csrf = owner
    ask = new_ask(server)
    path = f"/api/asks/{ask['id']}/answer"
    body = {"answers": {"SEC-1": "plan", "go": True}}
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
    status, _, body = call(server, "PUT", "/api/records/f-running-ok", token=WRITE, body={"data": record()})
    assert (status, body) == (200, {"id": "f-running-ok", "version": 1})
    _, _, body = call(server, "PUT", "/api/records/f-running-ok", token=WRITE,
                      body={"data": record(), "if_version": 1})
    assert body == {"id": "f-running-ok", "version": 2}
    status, _, body = call(server, "GET", "/api/records/f-running-ok", cookie=cookie)
    assert status == 200 and body["version"] == 2 and body["data"] == record()
    _, _, body = call(server, "GET", "/api/records", cookie=cookie)
    assert [r["id"] for r in body["records"]] == ["f-running-ok"]
    assert call(server, "DELETE", "/api/records/f-running-ok", token=WRITE)[2] == {"deleted": True}
    assert call(server, "DELETE", "/api/records/f-running-ok", token=WRITE)[:3:2] == (404, {"error": "not_found"})


def test_put_conflict_returns_409_with_the_current_record(server):
    call(server, "PUT", "/api/records/f-running-ok", token=WRITE, body={"data": record()})
    status, _, body = call(server, "PUT", "/api/records/f-running-ok", token=WRITE, body={"data": record()})
    assert status == 409 and body["error"] == "version_conflict" and body["current"]["version"] == 1
    status, _, body = call(server, "PUT", "/api/records/f-starting", token=WRITE,
                           body={"data": record("f-starting"), "if_version": 4})
    assert status == 409 and body["current"] is None


def test_put_invalid_returns_422_with_errors(server):
    bad = record()
    bad["surprise"] = 1
    status, _, body = call(server, "PUT", "/api/records/f-running-ok", token=WRITE, body={"data": bad})
    assert status == 422 and body["error"] == "invalid" and body["errors"]
    assert call(server, "PUT", "/api/records/f-running-ok", token=WRITE, raw=b"nope")[0] == 400
    assert call(server, "PUT", "/api/records/f-running-ok", token=WRITE, body=[1])[0] == 400
    assert call(server, "PUT", "/api/records/f-running-ok", token=WRITE, body={"if_version": 1})[0] == 400


def test_if_version_true_is_400(server):
    for bad in (True, "1", 0, 1.5):
        status, _, body = call(server, "PUT", "/api/records/f-running-ok", token=WRITE,
                               body={"data": record(), "if_version": bad})
        assert (status, body) == (400, {"error": "bad_request"})
    assert call(server, "PUT", "/api/records/f-running-ok", token=WRITE,
                body={"data": record(), "if_version": None})[0] == 200


# ---- asks -----------------------------------------------------------------------------------------

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
    status, headers, _ = call(server, "POST", "/api/records/f-running-ok", token=WRITE, body={})
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
    conn.request("PUT", "/api/records/f-running-ok", headers=auth)  # no Content-Length at all
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 400
    conn.close()


def test_oversized_body_is_413(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.putrequest("PUT", "/api/records/f-running-ok")
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
