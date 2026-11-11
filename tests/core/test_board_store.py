import copy
import json
import sys
import threading

import pytest

from conftest import FIXTURES

from tld.board.store import MAX_RECORD, Conflict, Invalid, Store  # noqa: E402


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
