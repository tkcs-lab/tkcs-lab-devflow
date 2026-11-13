"""tld board usage: the shapes of the reading, the exit codes and what the board stores."""
import io
import json

import pytest

from board_helpers import running
from conftest import FIXTURES

from tld.board import usage_client

NOW = 1794570000
FIXTURE = FIXTURES / "usage-event.json"
EVENT = json.loads(FIXTURE.read_text())
WINDOWS = EVENT["unifiedWindows"]


@pytest.fixture
def board(tmp_path, monkeypatch):
    with running(tmp_path, usage_plan=("max", 5.0), clock=lambda: NOW) as srv:
        monkeypatch.setenv("TLD_BOARD_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        monkeypatch.setenv("TLD_BOARD_TOKEN", "w" * 24)
        yield srv


def send(args, clock=lambda: NOW):
    return usage_client.main(args, clock=clock)


def write(tmp_path, doc, name="r.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return str(path)


def stored(srv):
    return [(r[0], r[1], r[3], r[6]) for r in srv.store.list_usage()]


EXPECTED = [("five_hour", 1794572400, 0.26, "final"), ("seven_day", 1794978000, 0.46, "final")]


def test_fixture_stores_both_windows(board, capsys):
    assert send([str(FIXTURE)]) == 0
    assert capsys.readouterr().out.strip() == '{"stored":2}'
    assert stored(board) == EXPECTED


def test_three_shapes_give_the_same_body():
    bodies = [usage_client.build_body(doc, "final", NOW)
              for doc in (EVENT, {"rate_limit_info": EVENT}, WINDOWS)]
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["source"] == "final" and set(bodies[0]) == {"five_hour", "seven_day", "source"}


def test_shapes_are_stored(board, tmp_path):
    assert send([write(tmp_path, {"rate_limit_info": EVENT})]) == 0
    assert stored(board) == EXPECTED


def test_resets_at_spelling(board, tmp_path):
    doc = {k: {"utilization": v["utilization"], "resets_at": v["resetsAt"]} for k, v in WINDOWS.items()}
    assert send([write(tmp_path, doc)]) == 0
    assert stored(board) == EXPECTED


def test_expired_window_is_dropped(board, tmp_path, capsys):
    doc = {"five_hour": {"utilization": 0.3, "resetsAt": NOW - 1}}
    assert send([write(tmp_path, doc)]) == 0
    assert "usage: no current window in the reading" in capsys.readouterr().err
    assert stored(board) == []


def test_one_expired_one_current(board, tmp_path):
    doc = {"five_hour": {"utilization": 0.3, "resetsAt": NOW}, "seven_day": WINDOWS["seven_day"]}
    assert send([write(tmp_path, doc)]) == 0
    assert stored(board) == [EXPECTED[1]]


def test_usage_off_exits_1(tmp_path, monkeypatch, capsys):
    with running(tmp_path, clock=lambda: NOW) as srv:
        monkeypatch.setenv("TLD_BOARD_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        monkeypatch.setenv("TLD_BOARD_TOKEN", "w" * 24)
        assert send([str(FIXTURE)]) == 1
    assert "usage: the board has usage off: set TLD_BOARD_PLAN on the board host" in capsys.readouterr().err


def test_no_board_exits_3(monkeypatch, capsys):
    monkeypatch.delenv("TLD_BOARD_URL", raising=False)
    monkeypatch.delenv("TLD_BOARD_TOKEN", raising=False)
    assert send([str(FIXTURE)]) == 3
    assert "no board configured" in capsys.readouterr().err


def test_invalid_json_exits_1(board, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{nope")
    assert send([str(path)]) == 1
    assert send([str(tmp_path / "missing.json")]) == 1


def test_not_understood_exits_1(board, tmp_path):
    assert send([write(tmp_path, [1, 2])]) == 1
    assert send([write(tmp_path, {"status": "allowed"})]) == 1
    assert send([write(tmp_path, {"five_hour": {"utilization": 0.1}})]) == 1


def test_stdin(board, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(FIXTURE.read_text()))
    assert send(["-"]) == 0
    assert stored(board) == EXPECTED


def test_source_scheduled(board):
    assert send([str(FIXTURE), "--source", "scheduled"]) == 0
    assert {r[6] for r in board.store.list_usage()} == {"scheduled"}


def test_refused_value_exits_1(board, tmp_path, capsys):
    doc = {"five_hour": {"utilization": 2, "resetsAt": 1794572400}}
    assert send([write(tmp_path, doc)]) == 1
    assert "HTTP 422" in capsys.readouterr().err
    assert stored(board) == []


def test_bad_source_exits_2():
    with pytest.raises(SystemExit) as exc:
        send([str(FIXTURE), "--source", "other"])
    assert exc.value.code == 2
