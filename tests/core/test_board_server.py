import base64
import copy
import http.client
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from conftest import TLD, FIXTURES, tld_cmd

from tld.board import server as board_server  # noqa: E402
from tld.board.store import Store  # noqa: E402

WRITE = "w" * 24
READ = "r" * 24
SCRIPT = TLD / "board" / "server.py"
SCRIPT_CMD = tld_cmd("board", "server")


def record(doc_id="f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if d["id"] == doc_id))


@pytest.fixture
def server(tmp_path):
    srv = board_server.make_server(Store(str(tmp_path / "b.sqlite3")), board_server.Tokens(WRITE, READ),
                                   "T", "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def call(server, method, path, token=WRITE, body=None, headers=None, raw=None):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def jcall(*args, **kwargs):
    status, headers, body = call(*args, **kwargs)
    return status, json.loads(body) if body else None


def test_healthz_needs_no_token(server):
    assert jcall(server, "GET", "/healthz", token=None) == (200, {"ok": True})


def test_api_requires_a_token(server):
    status, headers, body = call(server, "GET", "/api/records", token=None)
    assert status == 401
    assert json.loads(body) == {"error": "unauthorized"}
    assert headers["WWW-Authenticate"] == 'Basic realm="tld board", charset="UTF-8"'
    assert call(server, "GET", "/api/records", token="x" * 24)[0] == 401
    assert call(server, "GET", "/", token=None)[0] == 401


def test_bearer_and_basic_both_work(server):
    assert call(server, "GET", "/api/records")[0] == 200
    basic = base64.b64encode(f"anyone:{READ}".encode()).decode()
    assert call(server, "GET", "/api/records", token=None, headers={"Authorization": f"Basic {basic}"})[0] == 200
    bad = base64.b64encode(b"anyone:nope").decode()
    assert call(server, "GET", "/api/records", token=None, headers={"Authorization": f"Basic {bad}"})[0] == 401
    assert call(server, "GET", "/api/records", token=None, headers={"Authorization": "Basic !!!"})[0] == 401


def test_read_token_reads_but_cannot_write(server):
    assert call(server, "GET", "/api/records", token=READ)[0] == 200
    assert call(server, "GET", "/", token=READ)[0] == 200
    status, body = jcall(server, "PUT", "/api/records/f-running-ok", token=READ, body={"data": record()})
    assert (status, body) == (403, {"error": "forbidden"})
    assert jcall(server, "DELETE", "/api/records/f-running-ok", token=READ)[0] == 403


def test_put_get_list_delete_roundtrip(server):
    status, body = jcall(server, "PUT", "/api/records/f-running-ok", body={"data": record()})
    assert (status, body) == (200, {"id": "f-running-ok", "version": 1})
    status, body = jcall(server, "PUT", "/api/records/f-running-ok", body={"data": record(), "if_version": 1})
    assert body == {"id": "f-running-ok", "version": 2}
    status, body = jcall(server, "GET", "/api/records/f-running-ok", token=READ)
    assert status == 200 and body["version"] == 2 and body["data"] == record()
    status, body = jcall(server, "GET", "/api/records", token=READ)
    assert [r["id"] for r in body["records"]] == ["f-running-ok"]
    assert jcall(server, "DELETE", "/api/records/f-running-ok") == (200, {"deleted": True})
    assert jcall(server, "DELETE", "/api/records/f-running-ok") == (404, {"error": "not_found"})
    assert jcall(server, "GET", "/api/records/f-running-ok") == (404, {"error": "not_found"})


def test_put_conflict_returns_409_with_the_current_record(server):
    jcall(server, "PUT", "/api/records/f-running-ok", body={"data": record()})
    status, body = jcall(server, "PUT", "/api/records/f-running-ok", body={"data": record()})
    assert status == 409 and body["error"] == "version_conflict" and body["current"]["version"] == 1
    status, body = jcall(server, "PUT", "/api/records/f-starting",
                         body={"data": record("f-starting"), "if_version": 4})
    assert status == 409 and body["current"] is None


def test_put_invalid_returns_422_with_errors(server):
    bad = record()
    bad["surprise"] = 1
    status, body = jcall(server, "PUT", "/api/records/f-running-ok", body={"data": bad})
    assert status == 422 and body["error"] == "invalid" and body["errors"]
    assert jcall(server, "PUT", "/api/records/f-running-ok", raw=b"nope")[0] == 400
    assert jcall(server, "PUT", "/api/records/f-running-ok", body=[1])[0] == 400
    assert jcall(server, "PUT", "/api/records/f-running-ok", body={"if_version": 1})[0] == 400


def test_page_is_served_with_security_headers(server):
    for path in ("/", "/index.html"):
        status, headers, body = call(server, "GET", path, token=READ)
        assert status == 200
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert b"<title>T</title>" in body
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "connect-src 'self'" in headers["Content-Security-Policy"]
    _, headers, _ = call(server, "GET", "/api/records")
    assert "Content-Security-Policy" not in headers and headers["Cache-Control"] == "no-store"


def test_unknown_route_is_401_without_a_token_and_404_with_one(server):
    assert call(server, "GET", "/nope", token=None)[0] == 401
    assert jcall(server, "GET", "/nope") == (404, {"error": "not_found"})


def test_wrong_method_is_405(server):
    status, headers, body = call(server, "POST", "/api/records", body={})
    assert status == 405 and headers["Allow"] == "GET"
    assert json.loads(body) == {"error": "method_not_allowed"}
    assert call(server, "POST", "/", body={})[0] == 405
    assert call(server, "PUT", "/api/records", body={})[0] == 405
    assert call(server, "DELETE", "/")[0] == 405
    status, headers, _ = call(server, "POST", "/api/records/f-running-ok", body={})
    assert status == 405 and headers["Allow"] == "GET, PUT, DELETE"


def test_if_version_true_is_400(server):
    for bad in (True, "1", 0, 1.5):
        status, body = jcall(server, "PUT", "/api/records/f-running-ok",
                             body={"data": record(), "if_version": bad})
        assert (status, body) == (400, {"error": "bad_request"})
    assert jcall(server, "PUT", "/api/records/f-running-ok",
                 body={"data": record(), "if_version": None})[0] == 200


def test_responses_have_content_length(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    auth = {"Authorization": f"Bearer {WRITE}"}
    # Several requests on one keep-alive connection, including an unread-body 405.
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


def run_main(env_extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD")}
    env.update(env_extra)
    return subprocess.run([*SCRIPT_CMD, "--port", "0"], env=env, capture_output=True,
                          text=True, timeout=30)


def test_main_refuses_a_missing_or_short_token():
    result = run_main({})
    assert result.returncode == 2
    assert result.stderr.startswith("board_server: TLD_BOARD_TOKEN")
    result = run_main({"TLD_BOARD_TOKEN": "short"})
    assert result.returncode == 2 and "at least 24" in result.stderr


def test_main_refuses_a_read_token_equal_to_the_write_token():
    same = run_main({"TLD_BOARD_TOKEN": WRITE, "TLD_BOARD_READ_TOKEN": WRITE})
    assert same.returncode == 2 and "must differ" in same.stderr
    short = run_main({"TLD_BOARD_TOKEN": WRITE, "TLD_BOARD_READ_TOKEN": "tiny"})
    assert short.returncode == 2 and "must differ" in short.stderr
