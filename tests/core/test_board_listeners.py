"""The board's two listeners (--api-port): the page endpoint, the API endpoint and the process around them."""
import copy
import itertools
import json
import os
import re
import signal
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest

from board_helpers import PASSPHRASE, WRITE, ask_doc, call, login, running, running_pair
from conftest import FIXTURES, tld_cmd

from tld.board import server as board_server
from tld.board.store import Store

SCRIPT_CMD = tld_cmd("board", "server")
LINE = re.compile(r"listening on http://127\.0\.0\.1:(\d+) \((page|api)\)$")
WRONG = {"error": "wrong_endpoint"}
NOT_FOUND = {"error": "not_found"}


def record(doc_id="f-running-ok--run--plan-f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if doc_id in (d["id"], d["data"]["project"])))


def _matrix_record(slug):
    data = record()
    data.update(project=slug, repo=f"example-org/{slug}", plan_slug="x", needs_you=True,
                needs_you_reason="Answer the ask", needs_you_since="2026-11-09T11:00:00Z",
                status="waiting_user", next_check_at=None)
    return data


def _rec_id(slug):
    return f"{slug}--run--x"


USAGE = {"five_hour": {"utilization": 0.3, "resets_at": int(time.time()) + 3600}, "source": "final"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def pair(tmp_path):
    with running_pair(tmp_path, usage_plan=("max", 5.0)) as servers:
        yield servers


def seed(page, slug="seed"):
    rec = _rec_id(slug)
    page.store.set(rec, _matrix_record(slug), None)
    return rec, page.store.create_ask(ask_doc())["id"]


# ---- the page endpoint ----------------------------------------------------------------------------

def test_page_listener_serves_the_owner_routes(pair):
    page, _ = pair
    _, ask = seed(page)
    cookie, csrf = login(page)
    assert call(page, "GET", "/")[0] == 200
    assert call(page, "GET", "/api/records", cookie=cookie)[0] == 200
    status, _, body = call(page, "POST", f"/api/asks/{ask}/answer", cookie=cookie, csrf=csrf, origin=True,
                           body={"answers": {"SEC-1": "plan", "go": True}})
    assert status == 200, body
    assert call(page, "GET", "/api/usage", cookie=cookie)[0] == 200


def test_page_listener_refuses_the_session_token(pair):
    page, _ = pair
    status, _, body = call(page, "GET", "/api/records", token=WRITE)
    assert (status, body) == (403, WRONG)
    assert call(page, "GET", "/api/records")[0] == 401
    status, _, body = call(page, "GET", "/", token=WRITE)
    assert (status, body) == (403, WRONG)
    status, headers, body = call(page, "POST", "/login", token=WRITE, body={"passphrase": PASSPHRASE}, origin=True)
    assert (status, body) == (403, WRONG)
    assert headers.get("Set-Cookie") is None


@pytest.mark.parametrize("method,path,body", [
    ("PUT", "/api/records/x", {"data": {}}), ("DELETE", "/api/records/x", None),
    ("POST", "/api/asks", ask_doc()), ("POST", "/mcp", PING), ("POST", "/api/usage", USAGE),
    ("GET", "/mcp", None),
])
def test_page_listener_does_not_serve_the_session_only_routes(pair, method, path, body):
    page, _ = pair
    cookie, csrf = login(page)
    for kwargs in ({}, {"token": WRITE}, {"cookie": cookie, "csrf": csrf, "origin": True}):
        status, _, payload = call(page, method, path, body=body, **kwargs)
        assert (status, payload) == (404, NOT_FOUND), kwargs


def test_page_listener_answers_405_with_what_it_serves(pair):
    page, _ = pair
    status, headers, _ = call(page, "DELETE", "/api/asks")
    assert status == 405 and headers["Allow"] == "GET"


def test_page_listener_keeps_the_owner_origin_and_csrf_checks(pair):
    page, _ = pair
    _, ask = seed(page)
    cookie, csrf = login(page)
    body = {"answers": {"SEC-1": "plan", "go": True}}
    status, _, payload = call(page, "POST", f"/api/asks/{ask}/answer", cookie=cookie, origin=True, body=body)
    assert (status, payload["error"]) == (403, "csrf")
    status, _, payload = call(page, "POST", f"/api/asks/{ask}/answer", cookie=cookie, csrf=csrf,
                              origin="http://evil.example", body=body)
    assert (status, payload["error"]) == (403, "origin_not_allowed")


# ---- the API endpoint -----------------------------------------------------------------------------

def test_api_listener_serves_the_session_routes(pair):
    _, api = pair
    rec = _rec_id("api-one")
    status, _, body = call(api, "PUT", f"/api/records/{rec}", token=WRITE,
                           body={"data": _matrix_record("api-one"), "if_version": None})
    assert status == 200, body
    assert call(api, "GET", "/api/records", token=WRITE)[0] == 200
    status, _, ask = call(api, "POST", "/api/asks", token=WRITE, body=ask_doc())
    assert status == 201, ask
    assert call(api, "GET", f"/api/asks/{ask['id']}", token=WRITE)[0] == 200
    assert call(api, "POST", f"/api/asks/{ask['id']}/cancel", token=WRITE)[0] == 200
    assert call(api, "POST", "/mcp", token=WRITE, body=PING)[0] == 200
    assert call(api, "POST", "/api/usage", token=WRITE, body=USAGE)[0] == 200


@pytest.mark.parametrize("method,path", [
    ("GET", "/"), ("POST", "/login"), ("POST", "/logout"), ("GET", "/api/session"),
    ("POST", "/api/asks/{ask}/answer"), ("POST", "/api/records/{rec}/dismiss"),
    ("POST", "/api/records/{rec}/restore"), ("GET", "/api/usage"),
])
def test_api_listener_does_not_serve_the_owner_routes(pair, method, path):
    page, api = pair
    rec, ask = seed(page)
    for token in (None, WRITE):
        status, _, body = call(api, method, path.format(rec=rec, ask=ask), token=token, body={})
        assert (status, body) == (404, NOT_FOUND), token


def test_api_listener_ignores_the_owner_cookie(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "page").mkdir()
    with running(tmp_path / "api", role=board_server.API_ROLE) as api, running(tmp_path / "page") as page:
        cookie, csrf = login(page)  # the API server's own OwnerAuth would accept this cookie
        ask = api.store.create_ask(ask_doc())["id"]
        status, headers, _ = call(api, "GET", "/api/records", cookie=cookie)
        assert status == 401 and headers["WWW-Authenticate"]
        status, _, _ = call(api, "POST", f"/api/asks/{ask}/cancel", cookie=cookie, csrf=csrf, origin=True)
        assert status == 401
        status, headers, _ = call(api, "GET", "/api/records", token="x" * 24)
        assert status == 401 and headers["WWW-Authenticate"]
        status, headers, _ = call(api, "GET", "/mcp")
        assert status == 405 and headers["Allow"] == "POST"


# ---- the matrix per listener ----------------------------------------------------------------------
# (method, path template, body, expected status for: no credentials, session token, owner cookie) on one port.
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
_IDS = itertools.count(1)


def _route_name(path):
    for pattern, name, _ in board_server.ROUTES:
        if pattern.match(path):
            return name
    raise AssertionError(path)


def _body(kind, slug):
    return {"record": {"data": _matrix_record(slug), "if_version": 1}, "ask": ask_doc(),
            "dismiss": {"version": 1}, "answers": {"answers": {"SEC-1": "plan", "go": True}},
            "rpc": PING, "usage": USAGE, None: None}[kind]


@pytest.fixture(scope="module")
def matrix_pair(tmp_path_factory):
    with running_pair(tmp_path_factory.mktemp("listeners"), usage_plan=("max", 5.0)) as servers:
        yield servers


@pytest.mark.parametrize("who", ["none", "session", "owner", "both"])
@pytest.mark.parametrize("listener", ["page", "api"])
@pytest.mark.parametrize("method,path,body,expected", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_listener_auth_matrix(matrix_pair, listener, who, method, path, body, expected):
    page, api = matrix_pair
    srv = page if listener == "page" else api
    slug = f"lm-{next(_IDS)}"
    rec, ask = seed(page, slug)
    cookie, csrf = login(page)
    kwargs = {"body": _body(body, slug)}
    if who in ("session", "both"):
        kwargs["token"] = WRITE
    if who in ("owner", "both"):
        # the Origin header is the page's own; a session call to POST /mcp with one is refused by its allowlist
        kwargs.update(cookie=cookie, csrf=csrf, origin=listener == "page")
    status, _, payload = call(srv, method, path.format(rec=rec, ask=ask), **kwargs)
    if path == "/healthz":
        want = 200
    elif not board_server.served_by(listener, _route_name(path.format(rec="r", ask="a")), method):
        want = 404
    elif listener == "page" and who in ("session", "both"):
        want = 403
        assert payload == WRONG
    elif listener == "api":
        want = expected[{"none": 0, "session": 1, "owner": 0, "both": 1}[who]]
    else:
        want = expected[{"none": 0, "owner": 2}[who]]
    assert status == want, payload


def test_listener_matrix_covers_every_policy_entry():
    covered = {(_route_name(p.format(rec="r", ask="a")), m) for m, p, _, _ in MATRIX if p != "/healthz"}
    assert covered == set(board_server.POLICY) - {("login", "POST")}


def test_both_listeners_share_one_store(pair):
    page, api = pair
    rec = _rec_id("shared")
    assert call(api, "PUT", f"/api/records/{rec}", token=WRITE,
                body={"data": _matrix_record("shared"), "if_version": None})[0] == 200
    cookie, csrf = login(page)
    status, _, body = call(page, "GET", f"/api/records/{rec}", cookie=cookie)
    assert status == 200 and body["data"]["project"] == "shared"
    _, _, ask = call(api, "POST", "/api/asks", token=WRITE, body=ask_doc())
    status, _, _ = call(page, "POST", f"/api/asks/{ask['id']}/answer", cookie=cookie, csrf=csrf, origin=True,
                        body={"answers": {"SEC-1": "plan", "go": True}})
    assert status == 200
    _, _, body = call(api, "GET", f"/api/asks/{ask['id']}", token=WRITE)
    assert body["state"] == "answered"


def test_healthz_answers_on_both(pair):
    for srv in pair:
        assert call(srv, "GET", "/healthz") [0] == 200


def test_make_server_rejects_an_unknown_role(tmp_path):
    with pytest.raises(ValueError):
        board_server.make_server(Store(str(tmp_path / "b.sqlite3")), board_server.Tokens(WRITE), "T",
                                 "127.0.0.1", 0, role="both ")


def test_served_by_matches_the_documented_split():
    pairs = {(name, m) for _, name, methods in board_server.ROUTES for m in methods}
    assert pairs <= set(board_server.POLICY)
    assert all(board_server.served_by("both", n, m) for n, m in pairs)
    page = {(n, m) for n, m in pairs if board_server.served_by("page", n, m)}
    api = {(n, m) for n, m in pairs if board_server.served_by("api", n, m)}
    assert page == {("page", "GET"), ("login", "POST"), ("logout", "POST"), ("session", "GET"),
                    ("records", "GET"), ("record", "GET"), ("dismiss", "POST"), ("restore", "POST"),
                    ("asks", "GET"), ("ask", "GET"), ("answer", "POST"), ("cancel", "POST"), ("usage", "GET")}
    assert api == {("records", "GET"), ("record", "GET"), ("record", "PUT"), ("record", "DELETE"),
                   ("asks", "GET"), ("asks", "POST"), ("ask", "GET"), ("cancel", "POST"),
                   ("mcp", "POST"), ("usage", "POST")}


# ---- the process ----------------------------------------------------------------------------------

def _env(extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD")}
    env.update({"TLD_BOARD_TOKEN": WRITE, "TLD_BOARD_OWNER_PASSPHRASE": PASSPHRASE})
    env.update(extra)
    return env


def run_main(env_extra, *args):
    return subprocess.run([*SCRIPT_CMD, "--port", "0", *args], env=_env(env_extra), capture_output=True,
                          text=True, timeout=30)


def start_main(tmp_path, *args, env=None):
    """Start the board; (process, {role: port}) once both listening lines were printed."""
    proc = subprocess.Popen([*SCRIPT_CMD, "--port", "0", *args, "--insecure-cookie", "--db",
                             str(tmp_path / "b.sqlite3")], env=_env(env or {}), stderr=subprocess.PIPE, text=True)
    ports = {}
    try:
        while len(ports) < 2:
            line = proc.stderr.readline()
            assert line, "the board stopped before it listened"
            found = LINE.search(line.strip())
            if found:
                ports[found.group(2)] = int(found.group(1))
    except BaseException:
        proc.kill()
        raise
    return proc, ports


def at(port):
    return SimpleNamespace(server_address=("127.0.0.1", port))


def test_main_serves_two_listeners(tmp_path):
    proc, ports = start_main(tmp_path, "--api-port", "0")
    try:
        assert list(ports) == ["page", "api"]
        page, api = at(ports["page"]), at(ports["api"])
        assert call(page, "GET", "/healthz")[0] == 200 and call(api, "GET", "/healthz")[0] == 200
        assert call(page, "PUT", "/api/records/x", token=WRITE, body={})[0] == 404
        assert call(api, "GET", "/")[0] == 404 and call(api, "GET", "/api/session")[0] == 404
        rec = _rec_id("main-e2e")
        data = _matrix_record("main-e2e")
        assert call(api, "PUT", f"/api/records/{rec}", token=WRITE, body={"data": data, "if_version": None})[0] == 200
        cookie, _ = login(page)
        status, _, body = call(page, "GET", f"/api/records/{rec}", cookie=cookie)
        assert status == 200 and body["data"] == data
    finally:
        proc.kill()
        proc.wait(10)


def test_api_port_from_the_environment(tmp_path):
    proc, ports = start_main(tmp_path, env={"TLD_BOARD_API_PORT": "0"})
    try:
        assert set(ports) == {"page", "api"}
    finally:
        proc.kill()
        proc.wait(10)


def test_main_stops_both_listeners_on_interrupt(tmp_path):
    proc, ports = start_main(tmp_path, "--api-port", "0")
    proc.send_signal(signal.SIGINT)
    assert proc.wait(10) == 0
    for port in ports.values():
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", port), timeout=2)


def test_main_reports_an_api_port_in_use(tmp_path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        result = run_main({}, "--api-port", str(taken.getsockname()[1]), "--db", str(tmp_path / "b.sqlite3"))
    assert result.returncode == 2 and "board_server: " in result.stderr


@pytest.mark.parametrize("args", [["--port", "18787", "--api-port", "18787"], ["--api-port", "70000"],
                                  ["--api-port", "-1"]])
def test_api_port_must_differ_from_port_and_be_in_range(args):
    result = run_main({}, *args)
    assert result.returncode == 2 and "--api-port must be" in result.stderr


def test_api_port_needs_the_owner_passphrase():
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD")}
    env["TLD_BOARD_TOKEN"] = WRITE
    result = subprocess.run([*SCRIPT_CMD, "--port", "0", "--api-port", "0"], env=env, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 2 and "--api-port needs TLD_BOARD_OWNER_PASSPHRASE" in result.stderr
