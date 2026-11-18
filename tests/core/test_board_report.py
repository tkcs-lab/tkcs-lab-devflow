"""The board keeps, checks and serves one report page per record (plan 72, section 3.9)."""
import copy
import hashlib
import http.client
import json
import sqlite3
import threading
import time

import pytest

from board_helpers import WRITE, call, login, running, running_pair
from conftest import FIXTURES

from tld.board import report_check
from tld.board import server as board_server
from tld.board import store as board_store
from tld.board.store import ReportError, Store

REC = "report-one--run--plan-report-one"

A = "<!doctype html><head>"
B = "</head><body>"
C = '<script>x</script></body><script id="d" type="application/json">'
D = "</script>"


def _sha(text):
    return hashlib.sha256(text.encode("utf8")).hexdigest()


@pytest.fixture(autouse=True)
def fake_viewer(monkeypatch):
    monkeypatch.setattr(report_check, "VIEWER_PARTS", tuple((len(p), _sha(p)) for p in (A, B, C, D)))


def fake_page(payload='{"repo":{"web":null},"n":1}', title="t"):
    return A + report_check.CSP_META + B + f"<title>{title}</title>" + C + payload + D


def record(slug="report-one"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    data = copy.deepcopy(next(d["data"] for d in docs if d["data"]["project"] == "f-running-ok"))
    data.update(project=slug, repo=f"example-org/{slug}", plan_slug=f"plan-{slug}", needs_you=False,
                next_check_at=None)
    return data


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "b.sqlite3"))
    s.set(REC, record(), None)
    return s


@pytest.fixture
def server(tmp_path):
    with running(tmp_path) as srv:
        srv.store.set(REC, record(), None)
        yield srv


def put(srv, rec=REC, body=None, token=WRITE):
    data = (fake_page() if body is None else body)
    data = data.encode() if isinstance(data, str) else data
    return call(srv, "PUT", f"/api/records/{rec}/report", token=token, raw=data)


# ---- the store ------------------------------------------------------------------------------------

def test_put_get_replace_and_meta(store):
    got = store.put_report(REC, b"<p>one</p>")
    assert got == {"id": REC, "size": 10, "sha256": hashlib.sha256(b"<p>one</p>").hexdigest()}
    body, meta = store.get_report(REC)
    assert body == b"<p>one</p>" and meta["size"] == 10 and meta["sha256"] == got["sha256"]
    assert meta["created_at"].endswith("Z") and len(meta["created_at"]) == 20
    store.put_report(REC, b"<p>two!</p>")
    assert store.get_report(REC)[0] == b"<p>two!</p>"
    assert store._db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
    assert store.delete_report(REC) is True and store.get_report(REC) is None
    assert store.delete_report(REC) is False


@pytest.mark.parametrize("doc_id,body,code", [
    ("missing--run--x", b"x", "no_record"),
    ("Bad/../x", b"x", "invalid_id"),
    ("", b"x", "invalid_id"),
    (REC, b"", "bad_body"),
    (REC, b"a\0b", "bad_body"),
    (REC, b"\xff\xfe", "bad_body"),
])
def test_put_report_refuses(store, doc_id, body, code):
    with pytest.raises(ReportError) as err:
        store.put_report(doc_id, body)
    assert err.value.code == code
    assert store._db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_a_report_over_the_limit_is_too_large(store, monkeypatch):
    monkeypatch.setattr(board_store, "MAX_REPORT", 10)
    store.put_report(REC, b"x" * 10)
    with pytest.raises(ReportError) as err:
        store.put_report(REC, b"x" * 11)
    assert err.value.code == "too_large"
    assert store.get_report(REC)[0] == b"x" * 10


def test_the_total_limit_counts_other_records_and_allows_a_replacement(store, monkeypatch):
    other = "report-two--run--plan-report-two"
    store.set(other, record("report-two"), None)
    monkeypatch.setattr(board_store, "MAX_REPORTS_TOTAL", 20)
    store.put_report(REC, b"x" * 12)
    with pytest.raises(ReportError) as err:
        store.put_report(other, b"y" * 9)
    assert err.value.code == "store_full"
    store.put_report(other, b"y" * 8)
    store.put_report(REC, b"z" * 12)  # replacing keeps the total within the limit
    with pytest.raises(ReportError) as err:
        store.put_report(REC, b"z" * 13)
    assert err.value.code == "store_full"


def test_deleting_the_record_removes_its_report(store):
    store.put_report(REC, b"<p>r</p>")
    assert store.delete(REC) is True
    assert store.get_report(REC) is None
    assert store._db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_report_meta_is_one_query_and_never_reads_a_body(store):
    other = "report-two--run--plan-report-two"
    store.set(other, record("report-two"), None)
    store.put_report(REC, b"<p>r</p>")
    statements = []
    store._db.set_trace_callback(statements.append)
    meta = store.report_meta([REC, other, "nobody"])
    store._db.set_trace_callback(None)
    assert set(meta) == {REC} and set(meta[REC]) == {"size", "sha256", "created_at"}
    selects = [s for s in statements if s.startswith("SELECT")]
    assert len(selects) == 1 and "body" not in selects[0].split("FROM")[0]
    assert store.report_meta([]) == {}


def test_a_delete_racing_the_write_leaves_no_orphan(store, monkeypatch):
    seen = {}
    real = Store._reports_total

    def total(conn, doc_id):
        thread = threading.Thread(target=store.delete, args=(REC,))
        thread.start()
        thread.join(0.2)
        seen["alive"] = thread.is_alive()  # the lock is held, so the delete waits
        seen["thread"] = thread
        return real(conn, doc_id)

    monkeypatch.setattr(Store, "_reports_total", staticmethod(total))
    store.put_report(REC, b"<p>r</p>")
    seen["thread"].join(5)
    assert seen["alive"] is True
    assert store.get_report(REC) is None
    assert store._db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_an_older_database_upgrades_to_the_report_schema(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    s = Store(path)
    s.set(REC, record(), None)
    s._db.execute("DROP TABLE reports")
    s._db.execute("PRAGMA user_version = 5")
    s._db.commit()
    s._db.close()
    again = Store(path)
    assert again.schema_version() == board_store.SCHEMA_VERSION == 6
    assert again.get(REC) is not None
    again.put_report(REC, b"<p>r</p>")
    assert again.get_report(REC)[0] == b"<p>r</p>"
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 6


# ---- the server -----------------------------------------------------------------------------------

EXPECTED_HEADERS = {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Disposition": 'inline; filename="change-report.html"',
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval'; "
        "style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; form-action 'none'; "
        "base-uri 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def test_a_valid_page_is_stored_and_served_to_the_owner_with_exact_headers(server):
    page = fake_page()
    status, _, body = put(server, body=page)
    assert status == 200
    assert body == {"id": REC, "size": len(page.encode()), "sha256": _sha(page)}
    cookie, _ = login(server)
    status, headers, got = call(server, "GET", f"/api/records/{REC}/report", cookie=cookie)
    assert status == 200 and got == page.encode()
    for key, value in EXPECTED_HEADERS.items():
        assert headers[key] == value, key
    assert headers["Content-Length"] == str(len(page.encode()))


def test_the_session_token_cannot_read_the_report_and_the_owner_cannot_write_it(server):
    put(server)
    assert call(server, "GET", f"/api/records/{REC}/report", token=WRITE)[0] == 403
    assert call(server, "GET", f"/api/records/{REC}/report")[0] == 401
    cookie, csrf = login(server)
    assert call(server, "PUT", f"/api/records/{REC}/report", cookie=cookie, csrf=csrf, origin=True,
                raw=fake_page().encode())[0] == 403
    assert put(server, token="x" * 24)[0] == 401


def test_report_boundary(server, monkeypatch):
    monkeypatch.setattr(board_store, "MAX_REPORT", 10)
    monkeypatch.setattr(report_check, "check", lambda text: [])
    status, _, body = call(server, "PUT", f"/api/records/{REC}/report", token=WRITE, raw=b"x" * 10)
    assert status == 200 and body["size"] == 10
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("PUT", f"/api/records/{REC}/report", body=b"x" * 11,
                 headers={"Authorization": f"Bearer {WRITE}", "Content-Length": "11"})
    resp = conn.getresponse()
    assert resp.status == 413 and resp.getheader("Connection") == "close"
    assert json.loads(resp.read()) == {"error": "payload_too_large"}
    conn.close()
    assert server.store.get_report(REC)[0] == b"x" * 10


@pytest.mark.parametrize("make", [
    lambda: fake_page().replace("<body>", "<body >", 1),
    lambda: fake_page(payload='{"a":"<script>"}'),
    lambda: fake_page(payload='{"repo":{"web":null},"ownerUrl":"https://evil.example/?x=1"}'),
    lambda: "<p>x</p>",
    lambda: fake_page(title="a<b"),
])
def test_report_page_rule_is_422(server, make):
    status, _, body = put(server, body=make())
    assert status == 422 and body["error"] == "invalid_report" and body["reasons"]
    assert server.store.get_report(REC) is None


def test_report_upload_trickle_is_408(server, monkeypatch):
    import socket
    monkeypatch.setattr(board_server, "REPORT_DEADLINE", 0.6)
    monkeypatch.setattr(board_server.Handler, "timeout", 0.5)
    sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=5)
    sock.sendall(f"PUT /api/records/{REC}/report HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {WRITE}\r\n"
                 f"Content-Length: 50\r\n\r\n".encode())
    reply = b""
    for _ in range(8):
        try:
            sock.sendall(b"<")
        except OSError:
            break
        time.sleep(0.2)
        sock.settimeout(0.01)
        try:
            reply += sock.recv(4096)
        except (TimeoutError, BlockingIOError, socket.timeout):
            pass
        if b"408" in reply:
            break
    sock.settimeout(2)
    try:
        reply += sock.recv(4096)
    except (TimeoutError, OSError):
        pass
    sock.close()
    assert b" 408 " in reply.split(b"\r\n", 1)[0] + b" "
    assert server.store.get_report(REC) is None


def test_report_bad_bodies_are_400(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    for data in (b"", b"a\0b", b"\xff"):
        conn.request("PUT", f"/api/records/{REC}/report", body=data,
                     headers={"Authorization": f"Bearer {WRITE}", "Content-Length": str(len(data))})
        resp = conn.getresponse()
        assert resp.status == 400 and json.loads(resp.read()) == {"error": "bad_request"}, data
    conn.close()
    assert server.store.get_report(REC) is None


def test_report_without_content_length_is_400(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.putrequest("PUT", f"/api/records/{REC}/report")
    conn.putheader("Authorization", f"Bearer {WRITE}")
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 400 and json.loads(resp.read()) == {"error": "bad_request"}
    conn.close()


def test_report_store_full_is_507(server, monkeypatch):
    monkeypatch.setattr(board_store, "MAX_REPORTS_TOTAL", 10)
    status, _, body = put(server)
    assert status == 507 and body == {"error": "store_full"}
    assert server.store.get_report(REC) is None


def test_a_record_rewrite_keeps_the_report(server):
    page = fake_page()
    assert put(server, body=page)[0] == 200
    version = call(server, "GET", f"/api/records/{REC}", token=WRITE)[2]["version"]
    status, _, _ = call(server, "PUT", f"/api/records/{REC}", token=WRITE,
                        body={"data": record(), "if_version": version})
    assert status == 200
    cookie, _ = login(server)
    status, _, got = call(server, "GET", f"/api/records/{REC}/report", cookie=cookie)
    assert status == 200 and got == page.encode()


def test_deleting_the_record_over_http_removes_the_report(server):
    assert put(server)[0] == 200
    assert call(server, "DELETE", f"/api/records/{REC}", token=WRITE)[0] == 200
    assert server.store.get_report(REC) is None
    assert server.store._db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


def test_the_report_can_be_deleted_by_itself(server):
    assert call(server, "DELETE", f"/api/records/{REC}/report", token=WRITE)[0] == 404
    put(server)
    assert call(server, "DELETE", f"/api/records/{REC}/report", token=WRITE)[0] == 200
    assert server.store.get(REC) is not None
    assert server.store.get_report(REC) is None


def test_report_slots(server, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(board_server, "REPORT_SLOTS", slots)
    assert slots.acquire(blocking=False)
    try:
        status, headers, body = put(server)
        assert status == 503 and body == {"error": "busy"} and headers["Connection"] == "close"
        assert not slots.acquire(blocking=False)  # the failed upload did not take or release the slot
    finally:
        slots.release()
    monkeypatch.setattr(board_store, "MAX_REPORT", 5)
    assert put(server)[0] == 413
    assert put(server, rec="nobody--run--x")[0] == 404
    assert slots.acquire(blocking=False)
    slots.release()


def test_report_unknown_record_is_404_before_the_body_is_read(server, monkeypatch):
    def fail(*a, **k):
        raise AssertionError("the body was read")

    monkeypatch.setattr(board_server.Handler, "_read_body", fail)
    status, headers, body = put(server, rec="nobody--run--x")
    assert status == 404 and body == {"error": "not_found"} and headers["Connection"] == "close"
    assert put(server, rec="Bad..id")[0] == 404


def test_report_get_is_404_on_the_api_listener_and_put_is_404_on_the_page_listener(tmp_path):
    with running_pair(tmp_path) as (page, api):
        page.store.set(REC, record(), None)
        cookie, csrf = login(page)
        assert call(api, "GET", f"/api/records/{REC}/report", token=WRITE)[0] == 404
        assert call(page, "PUT", f"/api/records/{REC}/report", cookie=cookie, csrf=csrf, origin=True,
                    raw=fake_page().encode())[0] == 404
        assert call(page, "DELETE", f"/api/records/{REC}/report", cookie=cookie, csrf=csrf, origin=True)[0] == 404
        assert call(api, "PUT", f"/api/records/{REC}/report", token=WRITE, raw=fake_page().encode())[0] == 200
        assert call(page, "GET", f"/api/records/{REC}/report", cookie=cookie)[0] == 200
        assert call(page, "GET", f"/api/records/{REC}/report", token=WRITE)[0] == 403


def test_records_list_and_get_carry_report_meta_and_the_409_does_not(server):
    other = "report-two--run--plan-report-two"
    server.store.set(other, record("report-two"), None)
    page = fake_page()
    put(server, body=page)
    cookie, _ = login(server)
    for kwargs in ({"token": WRITE}, {"cookie": cookie}):
        _, _, listing = call(server, "GET", "/api/records", **kwargs)
        by_id = {r["id"]: r for r in listing["records"]}
        meta = by_id[REC]["report"]
        assert set(meta) == {"size", "sha256", "created_at"} and meta["sha256"] == _sha(page)
        assert by_id[other]["report"] is None
        _, _, one = call(server, "GET", f"/api/records/{REC}", **kwargs)
        assert one["report"] == meta
        _, _, none = call(server, "GET", f"/api/records/{other}", **kwargs)
        assert none["report"] is None
    status, _, conflict = call(server, "PUT", f"/api/records/{REC}", token=WRITE,
                               body={"data": record(), "if_version": None})
    assert status == 409 and "report" not in conflict["current"]
