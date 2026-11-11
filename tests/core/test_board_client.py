import copy
import json
import os
import subprocess
import sys
import threading

import pytest

from conftest import TLD, FIXTURES, tld_cmd

from tld.board import client as board_client  # noqa: E402
from tld.board import server as board_server  # noqa: E402
from tld.board.store import Store  # noqa: E402

WRITE = "w" * 24
SCRIPT = TLD / "board" / "client.py"
SCRIPT_CMD = tld_cmd("board", "client")


def record(doc_id="f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if d["id"] == doc_id))


@pytest.fixture
def server(tmp_path):
    srv = board_server.make_server(Store(str(tmp_path / "b.sqlite3")), board_server.Tokens(WRITE, "r" * 24),
                                   "T", "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def env_for(server, token=WRITE):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD_")}
    env["TLD_BOARD_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
    if token is not None:
        env["TLD_BOARD_TOKEN"] = token
    return env


def cli(*args, env=None, stdin=None):
    return subprocess.run([*SCRIPT_CMD, *args], env=env, input=stdin,
                          capture_output=True, text=True, timeout=30)


def test_load_config_none_when_unset():
    assert board_client.load_config({}) is None
    assert board_client.load_config({"TLD_BOARD_URL": "https://b.example.org"}) is None
    assert board_client.load_config({"TLD_BOARD_TOKEN": WRITE}) is None
    assert board_client.load_config({"TLD_BOARD_URL": "", "TLD_BOARD_TOKEN": ""}) is None


def test_load_config_strips_trailing_slash():
    cfg = board_client.load_config({"TLD_BOARD_URL": "https://b.example.org/", "TLD_BOARD_TOKEN": WRITE})
    assert cfg == board_client.Config("https://b.example.org", WRITE)


def test_load_config_refuses_plain_http_for_a_remote_host():
    with pytest.raises(board_client.ConfigError, match="must be https"):
        board_client.load_config({"TLD_BOARD_URL": "http://b.example.org", "TLD_BOARD_TOKEN": WRITE})


def test_load_config_allows_loopback_http():
    for host in ("localhost", "127.0.0.1", "[::1]"):
        cfg = board_client.load_config({"TLD_BOARD_URL": f"http://{host}:8787", "TLD_BOARD_TOKEN": WRITE})
        assert cfg is not None and cfg.url == f"http://{host}:8787"


def test_load_config_allows_http_with_the_override():
    cfg = board_client.load_config({"TLD_BOARD_URL": "http://b.example.org", "TLD_BOARD_TOKEN": WRITE,
                                    "TLD_BOARD_ALLOW_HTTP": "1"})
    assert cfg is not None


def test_load_config_refuses_userinfo():
    for url in ("https://u:p@b.example.org", "https://u@b.example.org", "https://b.example.org?x=1",
                "https://b.example.org#frag"):
        with pytest.raises(board_client.ConfigError):
            board_client.load_config({"TLD_BOARD_URL": url, "TLD_BOARD_TOKEN": WRITE})


def test_cli_exit_3_without_configuration():
    env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD_")}
    for args in (("list",), ("get", "x"), ("health",)):
        res = cli(*args, env=env)
        assert res.returncode == 3 and res.stdout == ""
        assert res.stderr.strip() == "board_client: no board configured"


def test_cli_health(server):
    res = cli("health", env=env_for(server))
    assert (res.returncode, res.stdout) == (0, "ok\n")


def test_cli_health_sends_no_token(server):
    res = cli("health", env=env_for(server, token=None))
    assert (res.returncode, res.stdout) == (0, "ok\n")
    res = cli("list", env=env_for(server, token=None))
    assert res.returncode == 3


def test_cli_set_get_list_delete(server, tmp_path):
    env = env_for(server)
    doc = tmp_path / "r.json"
    doc.write_text(json.dumps(record()))
    res = cli("set", "f-running-ok", str(doc), env=env)
    assert (res.returncode, json.loads(res.stdout)) == (0, {"id": "f-running-ok", "version": 1})
    res = cli("set", "f-running-ok", "-", "--if-version", "1", env=env, stdin=json.dumps(record()))
    assert json.loads(res.stdout) == {"id": "f-running-ok", "version": 2}
    res = cli("get", "f-running-ok", env=env)
    got = json.loads(res.stdout)
    assert res.returncode == 0 and got["version"] == 2 and got["data"] == record()
    assert res.stdout.count("\n") == 1
    res = cli("list", env=env)
    assert [r["id"] for r in json.loads(res.stdout)["records"]] == ["f-running-ok"]
    res = cli("delete", "f-running-ok", env=env)
    assert (res.returncode, json.loads(res.stdout)) == (0, {"deleted": ["f-running-ok"], "missing": []})


def test_cli_set_conflict_exits_1_and_prints_the_body(server):
    env = env_for(server)
    assert cli("set", "f-running-ok", "-", env=env, stdin=json.dumps(record())).returncode == 0
    res = cli("set", "f-running-ok", "-", env=env, stdin=json.dumps(record()))
    body = json.loads(res.stdout)
    assert res.returncode == 1 and body["error"] == "version_conflict" and body["current"]["version"] == 1
    assert "409" in res.stderr


def test_cli_set_invalid_exits_1(server):
    bad = record()
    bad["surprise"] = 1
    res = cli("set", "f-running-ok", "-", env=env_for(server), stdin=json.dumps(bad))
    assert res.returncode == 1 and json.loads(res.stdout)["error"] == "invalid"
    res = cli("set", "f-running-ok", "-", env=env_for(server), stdin="not json")
    assert res.returncode == 1 and res.stdout == ""


def test_cli_wrong_token_exits_1(server):
    res = cli("list", env=env_for(server, token="x" * 24))
    assert res.returncode == 1 and json.loads(res.stdout) == {"error": "unauthorized"}


def test_cli_delete_reports_missing(server):
    env = env_for(server)
    cli("set", "f-running-ok", "-", env=env, stdin=json.dumps(record()))
    res = cli("delete", "f-running-ok", "nope", env=env)
    assert res.returncode == 0
    assert json.loads(res.stdout) == {"deleted": ["f-running-ok"], "missing": ["nope"]}
