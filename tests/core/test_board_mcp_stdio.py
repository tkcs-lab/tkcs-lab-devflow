import io
import json
import os
import subprocess
import sys
import threading

import pytest

from conftest import ROOT, TLD, tld_cmd

from tld.board import client as board_client  # noqa: E402
from tld.board import mcp_stdio as board_mcp_stdio  # noqa: E402
from tld.board import server as board_server  # noqa: E402
from tld.board.store import Store  # noqa: E402

WRITE = "w" * 24
SCRIPT = TLD / "board" / "mcp_stdio.py"
SCRIPT_CMD = tld_cmd("board", "mcp-stdio")
CONFIG = board_client.Config("http://127.0.0.1:1", WRITE)


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


def run(lines, config, call=None):
    out = io.StringIO()
    stdin = io.StringIO("".join(line + "\n" for line in lines))
    if call is None:
        board_mcp_stdio.serve(stdin, out, config)
    else:
        board_mcp_stdio.serve(stdin, out, config, call=call)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def req(msg_id, method, params=None):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def test_forwards_a_request_and_writes_the_reply():
    seen = []

    def fake(config, method, path, body=None, **kw):
        seen.append((config, method, path, body))
        return 200, {"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}}

    replies = run([req(7, "ping")], CONFIG, fake)
    assert replies == [{"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}]
    assert seen == [(CONFIG, "POST", "/mcp", {"jsonrpc": "2.0", "id": 7, "method": "ping"})]


def test_notification_writes_nothing():
    note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert run([note], CONFIG, lambda *a, **k: (202, None)) == []


def test_http_error_becomes_a_jsonrpc_error():
    replies = run([req(3, "tools/list")], CONFIG, lambda *a, **k: (401, {"error": "unauthorized"}))
    assert replies == [{"jsonrpc": "2.0", "id": 3, "error": {"code": -32000, "message": "board server: HTTP 401"}}]


def test_oserror_becomes_a_jsonrpc_error():
    def boom(*a, **k):
        raise ConnectionRefusedError("no")

    replies = run([req("a", "tools/list")], CONFIG, boom)
    assert replies == [{"jsonrpc": "2.0", "id": "a",
                        "error": {"code": -32000, "message": "board server: ConnectionRefusedError"}}]
    # a notification that fails gets no reply
    note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert run([note], CONFIG, boom) == []


def test_without_config_initialize_and_empty_tool_list():
    replies = run([req(1, "initialize", {"protocolVersion": "2025-03-26"}), req(2, "tools/list"), req(3, "ping")], None)
    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert "No tld board is configured" in replies[0]["result"]["instructions"]
    assert replies[1] == {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}
    assert replies[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}
    other = run([req(4, "initialize", {"protocolVersion": "1999-01-01"})], None)
    assert other[0]["result"]["protocolVersion"] == "2025-06-18"


def test_without_config_other_methods_are_32601():
    replies = run([req(5, "tools/call", {"name": "board_list"}), json.dumps({"jsonrpc": "2.0", "method": "x"})], None)
    assert len(replies) == 1 and replies[0]["id"] == 5 and replies[0]["error"]["code"] == -32601


def test_unparsable_line_is_dropped(capsys):
    replies = run(["not json", "[1, 2]", req(1, "ping")], None)
    assert replies == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    assert "board_mcp_stdio:" in capsys.readouterr().err


def test_stdout_has_only_json_lines(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD_")}
    proc = subprocess.run([*SCRIPT_CMD], env=env, capture_output=True, text=True, timeout=30,
                          input="garbage\n" + req(1, "initialize") + "\n" + req(2, "ping") + "\n")
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_end_to_end_with_the_real_server(server):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD_")}
    env["TLD_BOARD_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
    env["TLD_BOARD_TOKEN"] = WRITE
    docs = json.loads((ROOT / "tests" / "fixtures" / "board-records.json").read_text())
    rec = next(d["data"] for d in docs if d["data"]["project"] == "f-running-ok")
    lines = [
        req(1, "initialize", {"protocolVersion": "2025-06-18"}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        req(2, "tools/list"),
        req(3, "tools/call", {"name": "board_set", "arguments": {"id": "f-running-ok--run--plan-f-running-ok", "data": rec}}),
    ]
    proc = subprocess.run([*SCRIPT_CMD], env=env, capture_output=True, text=True, timeout=30,
                          input="\n".join(lines) + "\n")
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["serverInfo"]["name"] == "tld-board"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {"board_get", "board_list", "board_set", "board_ask", "board_answers", "board_cancel"}
    assert replies[2]["result"]["isError"] is False
    assert json.loads(replies[2]["result"]["content"][0]["text"]) == {"id": "f-running-ok--run--plan-f-running-ok", "version": 1}
    assert server.store.get("f-running-ok--run--plan-f-running-ok")["version"] == 1


def test_config_error_is_treated_as_no_config():
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD_")}
    env["TLD_BOARD_URL"] = "http://board.example.org"
    env["TLD_BOARD_TOKEN"] = WRITE
    proc = subprocess.run([*SCRIPT_CMD], env=env, capture_output=True, text=True, timeout=30,
                          input=req(1, "tools/list") + "\n")
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    assert "board_mcp_stdio:" in proc.stderr and "must be https" in proc.stderr
