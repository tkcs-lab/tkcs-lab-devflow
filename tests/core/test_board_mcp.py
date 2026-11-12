import copy
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from board_helpers import ask_doc
from conftest import TLD, FIXTURES, tld_cmd

from tld.board import mcp as board_mcp  # noqa: E402
from tld.board import server as board_server  # noqa: E402
from tld.board.store import Store  # noqa: E402

WRITE = "w" * 24
SCRIPT = TLD / "board" / "server.py"
SCRIPT_CMD = tld_cmd("board", "server")


def record(doc_id="f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if d["id"] == doc_id))


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "m.sqlite3"))


@pytest.fixture
def server(tmp_path):
    srv = board_server.make_server(Store(str(tmp_path / "b.sqlite3")), board_server.Tokens(WRITE),
                                   "T", "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def rpc(method, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def tool(store, name, arguments=None):
    reply = board_mcp.handle(store, rpc("tools/call", {"name": name, "arguments": arguments or {}}))
    result = reply["result"]
    return json.loads(result["content"][0]["text"]), result["isError"]


def post(server, body, token=WRITE, headers=None, raw=None, method="POST"):
    url = f"http://127.0.0.1:{server.server_address[1]}/mcp"
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


def test_initialize_echoes_a_supported_protocol(store):
    reply = board_mcp.handle(store, rpc("initialize", {"protocolVersion": "2024-11-05"}))
    result = reply["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": "tld-board", "version": "1"}
    assert "board_set" in result["instructions"]


def test_initialize_falls_back_to_the_newest(store):
    reply = board_mcp.handle(store, rpc("initialize", {"protocolVersion": "1999-01-01"}))
    assert reply["result"]["protocolVersion"] == board_mcp.PROTOCOLS[0]


def test_tools_list_has_the_record_and_ask_tools_and_no_delete(store):
    tools = board_mcp.handle(store, rpc("tools/list"))["result"]["tools"]
    assert sorted(t["name"] for t in tools) == ["board_answers", "board_ask", "board_cancel", "board_get",
                                                "board_list", "board_set"]
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["inputSchema"]["additionalProperties"] is False
        assert t["description"]


def test_board_set_then_get_then_list(store):
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok", "data": record()})
    assert (payload, is_error) == ({"id": "f-running-ok", "version": 1}, False)
    got, is_error = tool(store, "board_get", {"id": "f-running-ok"})
    assert not is_error and got["version"] == 1 and got["data"] == record()
    listed, is_error = tool(store, "board_list")
    assert not is_error and [r["id"] for r in listed["records"]] == ["f-running-ok"]
    assert listed["records"][0]["dismissed_at"] is None and got["dismissed_at"] is None
    missing, is_error = tool(store, "board_get", {"id": "nope"})
    assert (missing, is_error) == ({"error": "not_found"}, True)


def test_board_set_conflict_is_an_error_result(store):
    tool(store, "board_set", {"id": "f-running-ok", "data": record()})
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok", "data": record(), "if_version": 5})
    assert is_error and payload["error"] == "version_conflict"
    assert payload["current"]["version"] == 1
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok", "data": record(), "if_version": 1})
    assert not is_error and payload["version"] == 2


def test_board_set_invalid_is_an_error_result(store):
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok", "data": {"project": "x"}})
    assert is_error and payload["error"] == "invalid" and payload["errors"]
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok", "data": record(), "if_version": 0})
    assert is_error and payload["error"] == "bad_arguments"
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok"})
    assert is_error and payload["error"] == "bad_arguments" and payload["detail"]


def test_board_set_first_write_conflicts_when_the_record_exists(store):
    tool(store, "board_set", {"id": "f-running-ok", "data": record()})
    payload, is_error = tool(store, "board_set", {"id": "f-running-ok", "data": record()})
    assert is_error and payload["error"] == "version_conflict" and payload["current"]["version"] == 1


def test_board_delete_is_not_a_tool(store):
    """S19: deleting records is the board playbook's CLI step after the owner confirms, never an MCP tool."""
    tool(store, "board_set", {"id": "f-running-ok", "data": record()})
    reply = board_mcp.handle(store, rpc("tools/call", {"name": "board_delete", "arguments": {"ids": ["f-running-ok"]}}))
    assert reply["error"]["code"] == -32602
    assert store.get("f-running-ok") is not None


def test_board_ask_answers_cancel(store):
    ask, is_error = tool(store, "board_ask", {"ask": ask_doc()})
    assert not is_error and ask["state"] == "open" and ask["id"].startswith("a-")
    payload, is_error = tool(store, "board_answers", {"id": ask["id"]})
    assert (payload["state"], payload["answers"], is_error) == ("open", {}, False)
    store.answer_ask(ask["id"], {"SEC-1": "drop", "go": True})
    payload, _ = tool(store, "board_answers", {"id": ask["id"]})
    assert payload["state"] == "answered" and payload["answers"] == {"SEC-1": "drop", "go": True}
    payload, is_error = tool(store, "board_cancel", {"id": ask["id"]})
    assert is_error and payload["error"] == "not_open"
    other, _ = tool(store, "board_ask", {"ask": ask_doc()})
    payload, is_error = tool(store, "board_cancel", {"id": other["id"]})
    assert (payload, is_error) == ({"id": other["id"], "state": "cancelled"}, False)


def test_board_ask_tools_reject_bad_arguments(store):
    payload, is_error = tool(store, "board_ask", {"ask": ask_doc(questions=[])})
    assert is_error and payload["error"] == "invalid"
    payload, is_error = tool(store, "board_ask", {"ask": ask_doc(), "extra": 1})
    assert is_error and payload["error"] == "bad_arguments"
    payload, is_error = tool(store, "board_answers", {"id": "a-ffffffffffffffff"})
    assert (payload, is_error) == ({"error": "not_found"}, True)
    payload, is_error = tool(store, "board_cancel", {"id": 5})
    assert is_error and payload["error"] == "bad_arguments"


def test_no_mcp_tool_answers_an_ask(store):
    names = {t["name"] for t in board_mcp.TOOLS}
    assert not any("answer" in n and n != "board_answers" for n in names)
    for t in board_mcp.TOOLS:
        assert "answers" not in t["inputSchema"]["properties"]


def test_unknown_tool_is_32602(store):
    reply = board_mcp.handle(store, rpc("tools/call", {"name": "nope", "arguments": {}}))
    assert reply["error"]["code"] == -32602
    reply = board_mcp.handle(store, rpc("tools/call", {"name": "board_list", "arguments": [1]}))
    assert reply["error"]["code"] == -32602


def test_unknown_method_is_32601(store):
    reply = board_mcp.handle(store, rpc("resources/list"))
    assert reply["error"]["code"] == -32601 and reply["id"] == 1
    assert board_mcp.handle(store, rpc("ping"))["result"] == {}


def test_notification_gets_202_and_no_body(server):
    status, headers, body = post(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert status == 202 and body == b"" and headers["Content-Length"] == "0"
    status, _, body = post(server, rpc("ping"))
    assert status == 200 and json.loads(body)["result"] == {}
    assert "Mcp-Session-Id" not in post(server, rpc("ping"))[1]


def test_batch_is_rejected_with_400(server):
    status, _, body = post(server, [rpc("ping")])
    assert status == 400 and json.loads(body)["error"]["code"] == -32600


def test_non_json_is_32700(server):
    status, _, body = post(server, None, raw=b"not json")
    assert status == 400 and json.loads(body)["error"]["code"] == -32700


def test_mcp_requires_the_write_token(server):
    assert post(server, rpc("ping"), token=None)[0] == 401
    cookie, csrf = login_cookie(server)
    status, _, _ = post(server, rpc("ping"), token=None, headers={"Cookie": cookie, "X-CSRF-Token": csrf})
    assert status in (401, 403)
    assert post(server, rpc("ping"), token="x" * 24)[0] == 401


def test_mcp_get_is_405(server):
    for method in ("GET", "DELETE", "PUT"):
        status, headers, _ = post(server, None, method=method)
        assert status == 405 and headers["Allow"] == "POST"


def test_origin_header_is_refused_unless_allowed(server):
    status, _, body = post(server, rpc("ping"), headers={"Origin": "https://evil.example"})
    assert status == 403 and json.loads(body) == {"error": "origin_not_allowed"}
    server.allow_origins = ("https://board.example",)
    assert post(server, rpc("ping"), headers={"Origin": "https://board.example"})[0] == 200


def test_script_run_reports_a_conflict(tmp_path):
    env = {**os.environ, "TLD_BOARD_TOKEN": WRITE}
    proc = subprocess.Popen(
        [*SCRIPT_CMD, "--port", "0", "--db", str(tmp_path / "s.sqlite3")],
        env=env, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stderr.readline().strip()
        prefix = "board_server: listening on http://127.0.0.1:"
        assert line.startswith(prefix), line
        port = int(line[len(prefix):])
        replies = []
        for n in (1, 2):
            msg = rpc("tools/call", {"name": "board_set",
                                     "arguments": {"id": "f-running-ok", "data": record()}}, msg_id=n)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=json.dumps(msg).encode(),
                                         method="POST", headers={"Authorization": f"Bearer {WRITE}",
                                                                 "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                replies.append(json.loads(resp.read())["result"])
        assert replies[0]["isError"] is False
        assert replies[1]["isError"] is True
        assert "version_conflict" in replies[1]["content"][0]["text"]
    finally:
        proc.terminate()
        proc.wait(10)
        proc.stderr.close()


def login_cookie(server):
    """No owner UI on this server: any cookie is ignored, so the cookie alone is unauthenticated."""
    return "tld_owner=1.2.3", "x"
