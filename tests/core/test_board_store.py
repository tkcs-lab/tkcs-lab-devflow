import copy
import json
import sys
import threading

import pytest

from board_helpers import ask_doc
from conftest import FIXTURES

from tld.board.store import MAX_RECORD, Conflict, Invalid, NotFound, Store


def record(doc_id="f-running-ok"):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if d["id"] == doc_id))


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "b.sqlite3"))


def test_store_set_creates_version_1(store):
    assert store.set("f-running-ok", record(), None) == {"id": "f-running-ok", "version": 1}
    got = store.get("f-running-ok")
    assert got["version"] == 1 and got["data"] == record()
    assert store.count() == 1
    assert [r["id"] for r in store.list()] == ["f-running-ok"]
    assert store.get("missing") is None


def test_store_set_needs_matching_if_version(store):
    store.set("f-running-ok", record(), None)
    assert store.set("f-running-ok", record(), 1)["version"] == 2
    with pytest.raises(Conflict) as exc:
        store.set("f-running-ok", record(), 1)
    assert exc.value.current["version"] == 2
    with pytest.raises(Conflict) as exc:
        store.set("f-starting", record("f-starting"), 3)
    assert exc.value.current is None


def test_store_set_without_if_version_conflicts_when_the_record_exists(store):
    store.set("f-running-ok", record(), None)
    with pytest.raises(Conflict) as exc:
        store.set("f-running-ok", record(), None)
    assert exc.value.current["id"] == "f-running-ok"


def test_store_rejects_an_invalid_record(store):
    bad = record()
    bad["unknown"] = 1
    with pytest.raises(Invalid) as exc:
        store.set("f-running-ok", bad, None)
    assert exc.value.errors
    with pytest.raises(Invalid):
        store.set("other-id", record(), None)  # doc id must equal the project
    assert store.count() == 0


def test_store_rejects_a_bad_id(store):
    for bad in ("", "UPPER", "-lead", "a/b", "x" * 101):
        with pytest.raises(Invalid) as exc:
            store.set(bad, record(), None)
        assert exc.value.errors == [f"document id '{bad}' is not valid"]


def test_store_rejects_an_oversized_record(store):
    big = record()
    big["phases"][0]["title"] = "x" * (MAX_RECORD + 1)
    with pytest.raises(Invalid) as exc:
        store.set("f-running-ok", big, None)
    assert exc.value.errors == ["the record is larger than 262144 bytes"]


def test_store_delete(store):
    store.set("f-running-ok", record(), None)
    assert store.delete("f-running-ok") is True
    assert store.delete("f-running-ok") is False
    assert store.count() == 0


def test_store_persists_across_reopen(tmp_path):
    path = str(tmp_path / "b.sqlite3")
    Store(path).set("f-running-ok", record(), None)
    again = Store(path)
    assert again.get("f-running-ok")["version"] == 1


def test_store_two_threads_cannot_both_create(store):
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        try:
            store.set("f-running-ok", record(), None)
            results.append("ok")
        except Conflict:
            results.append("conflict")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1 and results.count("conflict") == 7


# ---- schema migration and asks ---------------------------------------------------------------------

def test_an_old_database_is_migrated_and_keeps_its_records(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)  # the first board: one table, user_version 0
    db.execute("CREATE TABLE records(id TEXT PRIMARY KEY, version INTEGER NOT NULL, data TEXT NOT NULL)")
    db.execute("INSERT INTO records VALUES (?, ?, ?)", ("f-running-ok", 7, json.dumps(record())))
    db.commit()
    db.close()
    store = Store(str(path))
    assert store.schema_version() == 2
    assert store.get("f-running-ok") == {"id": "f-running-ok", "version": 7, "data": record()}
    ask = store.create_ask(ask_doc())
    reopened = Store(str(path))  # idempotent on a migrated database
    assert reopened.get_ask(ask["id"]) == ask and reopened.count() == 1


def test_a_newer_database_is_refused(tmp_path):
    import sqlite3
    path = tmp_path / "new.sqlite3"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.commit()
    db.close()
    with pytest.raises(RuntimeError, match="schema 99"):
        Store(str(path))


def test_asks_are_listed_open_first(tmp_path):
    times = iter(f"2026-11-09T12:00:0{n}Z" for n in range(10))
    store = Store(str(tmp_path / "a.sqlite3"), clock=lambda: next(times))
    a = store.create_ask(ask_doc())
    b = store.create_ask(ask_doc())
    c = store.create_ask(ask_doc())
    store.answer_ask(a["id"], {"SEC-1": "plan", "go": True})
    assert [x["id"] for x in store.list_asks()] == [b["id"], c["id"], a["id"]]
    assert [x["id"] for x in store.list_asks("answered")] == [a["id"]]
    assert store.get_ask(a["id"])["answered_at"] == "2026-11-09T12:00:03Z"


def test_answers_are_validated_and_normalised(tmp_path):
    store = Store(str(tmp_path / "a.sqlite3"))
    ask = store.create_ask(ask_doc())
    for bad in ({"go": True}, {"SEC-1": "PLAN!", "go": True}, {"SEC-1": "plan", "go": "yes"},
                {"SEC-1": "plan", "go": True, "ghost": 1}, {"SEC-1": "plan", "go": True, "notes": 5}, []):
        with pytest.raises(Invalid):
            store.answer_ask(ask["id"], bad)
    done = store.answer_ask(ask["id"], {"SEC-1": "Plan", "go": False, "notes": "  "})
    assert done["answers"] == {"SEC-1": "plan", "go": False}  # option case normalised, empty text dropped
    with pytest.raises(Conflict):
        store.answer_ask(ask["id"], {"SEC-1": "plan", "go": True})
    with pytest.raises(NotFound):
        store.answer_ask("a-ffffffffffffffff", {})


def test_open_asks_are_capped(tmp_path, monkeypatch):
    from tld.board import store as store_mod
    monkeypatch.setattr(store_mod, "MAX_OPEN_ASKS", 2)
    store = Store(str(tmp_path / "a.sqlite3"))
    first = store.create_ask(ask_doc())
    store.create_ask(ask_doc())
    with pytest.raises(Invalid, match="open asks"):
        store.create_ask(ask_doc())
    store.cancel_ask(first["id"])
    store.create_ask(ask_doc())
