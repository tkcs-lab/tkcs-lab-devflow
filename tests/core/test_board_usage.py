"""Usage readings: the settings, the validation, the window view, the store and the endpoint."""
import json
import sqlite3

import pytest

from board_helpers import WRITE, call, login, running
from conftest import FIXTURES

from tld.board import server as board_server
from tld.board import usage
from tld.board.store import Store

NOW = 1794570000
EVENT = json.loads((FIXTURES / "usage-event.json").read_text())["unifiedWindows"]


def body(**changes):
    doc = {"five_hour": {"utilization": 0.3, "resets_at": NOW + 3600}, "source": "final"}
    doc.update(changes)
    return doc


def row(kind="five_hour", resets_at=NOW + 3600, observed_at=NOW, utilization=0.26, plan="max", factor=5.0,
        source="final"):
    return (kind, resets_at, observed_at, utilization, plan, factor, source)


# ---- parse_plan ---------------------------------------------------------------------------------

def test_parse_plan_unset_is_off_with_factor_5():
    assert usage.parse_plan({}) == (None, 5.0)


@pytest.mark.parametrize("plan", ["standard", "max"])
def test_parse_plan_accepts_standard_and_max(plan):
    assert usage.parse_plan({"TLD_BOARD_PLAN": plan, "TLD_BOARD_MAX_FACTOR": "4.5"}) == (plan, 4.5)


def test_parse_plan_rejects_another_plan():
    with pytest.raises(ValueError, match="^TLD_BOARD_PLAN must be standard or max$"):
        usage.parse_plan({"TLD_BOARD_PLAN": "gold"})


@pytest.mark.parametrize("factor", ["1", "21", "x", "0", "nan", "inf", "-5"])
def test_parse_plan_rejects_a_bad_factor(factor):
    with pytest.raises(ValueError, match="^TLD_BOARD_MAX_FACTOR must be a number above 1 and at most 20$"):
        usage.parse_plan({"TLD_BOARD_MAX_FACTOR": factor})


def test_parse_plan_factor_bounds_are_above_1_and_at_most_20():
    assert usage.parse_plan({"TLD_BOARD_MAX_FACTOR": "20"})[1] == 20.0
    assert usage.parse_plan({"TLD_BOARD_MAX_FACTOR": "1.01"})[1] == 1.01


def test_main_with_an_unknown_plan_exits_2_and_prints_the_message(monkeypatch, capsys):
    monkeypatch.setenv("TLD_BOARD_TOKEN", WRITE)
    monkeypatch.setenv("TLD_BOARD_PLAN", "gold")
    assert board_server.main(["--port", "0"]) == 2
    assert capsys.readouterr().err.strip() == "board_server: TLD_BOARD_PLAN must be standard or max"


# ---- validate -----------------------------------------------------------------------------------

def test_validate_accepts_the_windows_of_the_fixture():
    doc = {kind: {"utilization": w["utilization"], "resets_at": w["resetsAt"]} for kind, w in EVENT.items()}
    doc["source"] = "scheduled"
    samples, source, errors = usage.validate(doc, EVENT["five_hour"]["resetsAt"] - 3600)
    assert errors == [] and source == "scheduled"
    assert samples == [{"kind": "five_hour", "resets_at": 1794572400, "utilization": 0.26},
                       {"kind": "seven_day", "resets_at": 1794978000, "utilization": 0.46}]


def test_validate_floors_resets_at_to_the_minute():
    samples, _, errors = usage.validate(body(five_hour={"utilization": 0, "resets_at": NOW + 3659}), NOW)
    assert errors == [] and samples[0]["resets_at"] % 60 == 0 and samples[0]["resets_at"] == (NOW + 3659) // 60 * 60


@pytest.mark.parametrize("value", [-0.1, 1.6, True, "0.2", None, float("nan")])
def test_validate_rejects_a_bad_utilization(value):
    _, _, errors = usage.validate(body(five_hour={"utilization": value, "resets_at": NOW + 60}), NOW)
    assert errors == ["five_hour.utilization must be a number from 0 to 1.5"]


@pytest.mark.parametrize("value", [0, 1.5, 1])
def test_validate_accepts_the_utilization_bounds(value):
    assert usage.validate(body(five_hour={"utilization": value, "resets_at": NOW + 60}), NOW)[2] == []


@pytest.mark.parametrize("value", [NOW - 10, NOW, NOW + 18601, NOW + 60.0, True, "x", None])
def test_validate_rejects_a_bad_resets_at(value):
    _, _, errors = usage.validate(body(five_hour={"utilization": 0.1, "resets_at": value}), NOW)
    assert len(errors) == 1 and errors[0].startswith("five_hour.resets_at must be an integer")


def test_validate_resets_at_bounds():
    def check(kind, resets_at):
        return usage.validate({kind: {"utilization": 0.1, "resets_at": resets_at}, "source": "final"}, NOW)[2]

    assert check("five_hour", NOW) != [] and check("five_hour", NOW + 1) == []
    assert check("five_hour", NOW + 18600) == [] and check("five_hour", NOW + 18601) != []
    assert check("seven_day", NOW + 604800 + 600) == [] and check("seven_day", NOW + 604800 + 601) != []


@pytest.mark.parametrize("doc,fragment", [
    (body(extra=1), "extra is not allowed"),
    (body(observed_at=5), "observed_at is not allowed"),
    ({"source": "final"}, "at least one of"),
    ({}, "source must be one of final, scheduled"),
    (body(source="other"), "source must be one of final, scheduled"),
    (body(five_hour=[]), "five_hour must be an object"),
    (body(five_hour={"utilization": 0.1, "resets_at": NOW + 60, "x": 1}), "five_hour.x is not allowed"),
    (body(five_hour={"utilization": 0.1}), "five_hour.resets_at must be an integer"),
    ([], "must be a JSON object"),
])
def test_validate_rejects_a_bad_shape(doc, fragment):
    samples, _, errors = usage.validate(doc, NOW)
    assert samples == [] and any(fragment in e for e in errors), errors


# ---- windows ------------------------------------------------------------------------------------

def one(rows, factor=5.0, now=NOW):
    return usage.windows(rows, factor, now)["five_hour"][0]


def test_windows_build_the_documented_fields():
    end = NOW + 3600
    win = one([row(observed_at=NOW - 600, utilization=0.1), row(observed_at=NOW - 300, utilization=0.3),
               row(observed_at=NOW, utilization=0.26)])
    assert win == {"resets_at": end, "start": end - 18000, "samples": 3, "first_seen": NOW - 600,
                   "last_seen": NOW, "plan": "max", "peak_standard": 150.0, "last_standard": 130.0,
                   "peak_max": 30.0, "over": True, "blocked_hours": round((end - (NOW - 300)) / 3600, 1),
                   "idle": False, "complete": False, "sources": ["final"]}


def test_windows_over_and_blocked_hours():
    below = one([row(utilization=0.2)])
    assert below["peak_standard"] == 100.0 and below["over"] is False and below["blocked_hours"] is None
    crossing = one([row(observed_at=NOW - 7200, utilization=0.1), row(observed_at=NOW - 3600, utilization=0.3)])
    assert crossing["over"] and crossing["blocked_hours"] == round((NOW + 3600 - (NOW - 3600)) / 3600, 1) == 2.0


def test_windows_idle_at_4_9_and_not_at_5_0():
    standard = {"plan": "standard"}
    assert one([row(utilization=0.049, **standard)])["idle"] is True
    assert one([row(utilization=0.05, **standard)])["idle"] is False
    assert one([row(utilization=0.0, **standard)])["idle"] is True


def test_windows_complete_when_the_window_has_ended():
    assert one([row(resets_at=NOW)])["complete"] is True
    assert one([row(resets_at=NOW + 60)])["complete"] is False


def test_windows_convert_a_standard_row_and_a_max_row_differently():
    assert one([row(plan="standard", factor=5.0, utilization=0.26)])["peak_standard"] == 26.0
    assert one([row(plan="max", factor=5.0, utilization=0.26)])["peak_standard"] == 130.0
    assert one([row(plan="max", factor=3.0, utilization=0.26)])["peak_standard"] == 78.0  # the stored factor


def test_a_factor_change_moves_only_peak_max():
    stored = [row(plan="max", factor=5.0, utilization=0.26)]
    five, four = one(stored, 5.0), one(stored, 4.0)
    assert (five["peak_standard"], five["peak_max"]) == (130.0, 26.0)
    assert (four["peak_standard"], four["peak_max"]) == (130.0, 32.5)


def test_two_samples_30_seconds_apart_merge_into_one_window():
    samples, _, _ = usage.validate(body(five_hour={"utilization": 0.1, "resets_at": NOW + 3601}), NOW)
    later, _, _ = usage.validate(body(five_hour={"utilization": 0.2, "resets_at": NOW + 3631}), NOW)
    rows = [row(resets_at=samples[0]["resets_at"], observed_at=NOW),
            row(resets_at=later[0]["resets_at"], observed_at=NOW + 30)]
    assert samples[0]["resets_at"] == later[0]["resets_at"]
    assert len(usage.windows(rows, 5.0, NOW)["five_hour"]) == 1 and one(rows)["samples"] == 2


def test_the_plan_of_a_window_follows_its_newest_sample():
    win = one([row(observed_at=NOW - 60, plan="standard", utilization=0.9), row(observed_at=NOW, plan="max")])
    assert win["plan"] == "max"
    win = one([row(observed_at=NOW - 60, plan="max"), row(observed_at=NOW, plan="standard", utilization=0.1)])
    assert win["plan"] == "standard" and win["last_standard"] == 10.0 and win["peak_standard"] == 130.0


def test_windows_keep_the_last_60_per_kind_oldest_first():
    rows = [row(resets_at=NOW + 60 * i) for i in range(1, 71)]
    rows.append(row(kind="seven_day", resets_at=NOW + 60))
    out = usage.windows(rows, 5.0, NOW)
    ends = [w["resets_at"] for w in out["five_hour"]]
    assert len(ends) == 60 and ends == sorted(ends) and ends[0] == NOW + 60 * 11 and ends[-1] == NOW + 60 * 70
    assert len(out["seven_day"]) == 1 and out["seven_day"][0]["start"] == NOW + 60 - 604800


def test_windows_of_no_rows_are_empty_lists():
    assert usage.windows([], 5.0, NOW) == {"five_hour": [], "seven_day": []}


def test_windows_list_the_sources_of_a_window():
    win = one([row(observed_at=NOW - 60, source="scheduled"), row(observed_at=NOW, source="final")])
    assert win["sources"] == ["final", "scheduled"]


# ---- the store ----------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "b.sqlite3"))


def sample(kind="five_hour", resets_at=NOW + 3600, utilization=0.3):
    return {"kind": kind, "resets_at": resets_at, "utilization": utilization}


def test_the_51st_sample_of_a_window_deletes_the_oldest(store):
    for i in range(51):
        store.add_usage([sample(utilization=i / 100)], "final", "max", 5.0, NOW + i)
    rows = store.list_usage()
    assert len(rows) == 50 and rows[0][2] == NOW + 1 and rows[-1][2] == NOW + 50


def test_add_usage_stores_the_settings_and_orders_the_rows(store):
    store.add_usage([sample("seven_day", NOW + 7200), sample("five_hour", NOW + 3600)], "scheduled", "max", 4.0, NOW)
    assert store.list_usage() == [("five_hour", NOW + 3600, NOW, 0.3, "max", 4.0, "scheduled"),
                                  ("seven_day", NOW + 7200, NOW, 0.3, "max", 4.0, "scheduled")]


def test_the_same_second_replaces_the_sample(store):
    store.add_usage([sample(utilization=0.1)], "final", "max", 5.0, NOW)
    store.add_usage([sample(utilization=0.2)], "final", "max", 5.0, NOW)
    assert [r[3] for r in store.list_usage()] == [0.2]


def test_a_window_older_than_120_days_is_removed(store):
    old = NOW - 120 * 86400 - 1
    store.add_usage([sample(resets_at=old)], "final", "max", 5.0, old - 100)
    store.add_usage([sample(resets_at=NOW - 120 * 86400)], "final", "max", 5.0, NOW - 120 * 86400 - 100)
    assert len(store.list_usage()) == 2  # trimmed relative to each insert's own time
    store.add_usage([sample()], "final", "max", 5.0, NOW)
    assert [r[1] for r in store.list_usage()] == [NOW - 120 * 86400, NOW + 3600]  # exactly 120 days stays
    store.add_usage([sample(resets_at=NOW + 7200)], "final", "max", 5.0, NOW + 1)
    assert all(r[1] >= NOW + 1 - 120 * 86400 for r in store.list_usage()) and len(store.list_usage()) == 2


def test_the_20001st_row_removes_the_oldest(store, monkeypatch):
    monkeypatch.setattr(usage, "MAX_ROWS", 20)
    for i in range(21):
        store.add_usage([sample(resets_at=NOW + 3600 + 60 * i)], "final", "max", 5.0, NOW)
    rows = store.list_usage()
    assert len(rows) == 20 and rows[0][1] == NOW + 3600 + 60


def test_the_row_limit_constant_is_20000():
    assert (usage.MAX_ROWS, usage.MAX_PER_WINDOW, usage.RETENTION_DAYS, usage.MAX_BODY, usage.SLACK) == \
        (20000, 50, 120, 4096, 600)


def make_schema_4(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE records(id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL)")
    db.execute("CREATE TABLE asks(id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, "
               "data TEXT NOT NULL)")
    db.execute("CREATE TABLE revoked_sessions(nonce TEXT PRIMARY KEY, expires INTEGER NOT NULL)")
    db.execute("CREATE TABLE dismissals(doc_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
               "dismissed_at TEXT NOT NULL)")
    db.execute("INSERT INTO revoked_sessions VALUES (?, ?)", ("a" * 32, 99999999999))
    db.execute("PRAGMA user_version = 4")
    db.commit()
    db.close()


def test_a_schema_4_database_migrates_to_5_and_keeps_its_rows(tmp_path):
    path = tmp_path / "v4.sqlite3"
    make_schema_4(path)
    store = Store(str(path))
    assert store.schema_version() == 5 and store.session_revoked("a" * 32)
    assert store.list_usage() == []
    store.add_usage([sample()], "final", "max", 5.0, NOW)
    again = Store(str(path))  # a second open changes nothing
    assert again.schema_version() == 5 and again.session_revoked("a" * 32)
    assert len(again.list_usage()) == 1
    db = sqlite3.connect(path)
    assert db.execute("SELECT name FROM sqlite_master WHERE name = 'usage_samples'").fetchone() is not None
    db.close()


# ---- the endpoint -------------------------------------------------------------------------------

@pytest.fixture
def board(tmp_path):
    with running(tmp_path, usage_plan=("max", 5.0), clock=lambda: NOW) as srv:
        yield srv


def post(srv, payload=None, raw=None):
    return call(srv, "POST", "/api/usage", token=WRITE, body=payload, raw=raw)


def get_usage(srv):
    cookie, csrf = login(srv)
    return call(srv, "GET", "/api/usage", cookie=cookie, csrf=csrf)


def test_post_then_get_shows_the_window(board):
    status, _, answer = post(board, body())
    assert (status, answer) == (200, {"stored": 1})
    status, _, answer = get_usage(board)
    assert status == 200 and answer["now"] == NOW and answer["plan"] == "max" and answer["factor"] == 5.0
    assert answer["windows"]["seven_day"] == []
    (win,) = answer["windows"]["five_hour"]
    assert win["resets_at"] == (NOW + 3600) // 60 * 60 and win["peak_standard"] == 150.0 and win["peak_max"] == 30.0
    assert win["over"] is True and win["sources"] == ["final"] and win["samples"] == 1


def test_get_with_the_session_token_is_403(board):
    assert call(board, "GET", "/api/usage", token=WRITE)[0] == 403
    assert call(board, "GET", "/api/usage")[0] == 401


def test_post_without_a_plan_is_409_usage_off(tmp_path):
    with running(tmp_path, clock=lambda: NOW) as srv:
        assert post(srv, body())[0:3:2] == (409, {"error": "usage_off"})
        assert post(srv, {"nonsense": True})[0:3:2] == (409, {"error": "usage_off"})  # checked first
        status, _, answer = get_usage(srv)
        assert status == 200 and answer["plan"] is None and answer["windows"] == {"five_hour": [], "seven_day": []}


def test_an_invalid_body_is_422_with_its_errors(board):
    status, _, answer = post(board, body(five_hour={"utilization": 2, "resets_at": NOW + 60}))
    assert status == 422 and answer["error"] == "invalid"
    assert answer["errors"] == ["five_hour.utilization must be a number from 0 to 1.5"]
    assert board.store.list_usage() == []


def test_not_json_is_400(board):
    assert post(board, raw=b"{nope")[0] == 400


def test_a_body_above_4096_bytes_is_413(board):
    status, _, answer = post(board, raw=b" " * 4097)
    assert (status, answer) == (413, {"error": "payload_too_large"})


def test_a_body_of_4096_bytes_is_read(board):
    doc = json.dumps(body()).encode()
    status, _, _ = post(board, raw=doc + b" " * (4096 - len(doc)))
    assert status == 200
    status, _, _ = post(board, raw=b'{"source": "final", "x": "' + b"a" * (4096 - 28) + b'"}')
    assert status == 422


def test_the_stored_sample_uses_the_server_clock_and_settings(tmp_path):
    with running(tmp_path, usage_plan=("standard", 4.0), clock=lambda: NOW) as srv:
        assert post(srv, body(source="scheduled"))[0] == 200
        assert srv.store.list_usage() == [("five_hour", (NOW + 3600) // 60 * 60, NOW, 0.3, "standard", 4.0,
                                           "scheduled")]
