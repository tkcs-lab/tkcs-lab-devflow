import copy
import json
import os
import subprocess
import urllib.request

from board_helpers import WRITE, base, running
from conftest import FIXTURES, tld_cmd

from tld.board import record as board_record
from tld.board.resolve import resolve

NOW = "2026-11-12T10:00:00Z"
RESOLVE = tld_cmd("board", "resolve")
STALE = tld_cmd("board", "stale")


def fixture_record(doc_id):
    docs = json.loads((FIXTURES / "board-records.json").read_text())
    return copy.deepcopy(next(d["data"] for d in docs if doc_id in (d["id"], d["data"]["project"])))


def waiting():
    rec = fixture_record("f-waiting")
    rec["status"] = "running"
    rec["next_check_at"] = "2026-11-09T09:10:00Z"
    return rec


def run(rec, *extra, now=NOW, reason="PRs merged"):
    args = [*RESOLVE, "-", "--now", now, "--reason", reason, *extra]
    return subprocess.run(args, input=json.dumps(rec), capture_output=True, text=True, timeout=30)


def test_resolve_clears_a_needs_you_record():
    rec = waiting()
    assert board_record.validate(rec, "f-waiting") == []
    before = copy.deepcopy(rec)
    res = run(rec)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert board_record.validate(out, "f-waiting") == []
    assert out["needs_you"] is False and out["status"] == "done"
    assert out["finished_at"] == NOW and out["updated_at"] == NOW
    assert out["next_check_at"] is None and out["needs_you_reason"] == "" and out["needs_you_since"] is None
    assert out["last_event"] == "PRs merged"
    assert rec == before


def test_resolve_clears_a_prompt_run_record():
    rec = json.loads((FIXTURES / "status-records" / "good-run-prompt.json").read_text())
    out = resolve(rec, "2026-11-09T12:00:00Z", "merged")
    assert out["status"] == "done" and out["plan_url"] is None
    assert out["phases"] == [] and out["needs_you"] is False


def test_resolve_accepts_an_entry_with_or_without_dismissed_at():
    for extra in ({}, {"dismissed_at": None}, {"dismissed_at": "2026-11-09T11:00:00Z"}):
        res = run({"id": "f-waiting", "version": 1, **extra, "data": waiting()})
        assert res.returncode == 0, res.stderr
        assert json.loads(res.stdout)["status"] == "done"


def test_resolve_refuses_a_record_that_does_not_need_you():
    rec = waiting()
    rec["needs_you"] = False
    rec["needs_you_reason"] = ""
    rec["needs_you_since"] = None
    res = run(rec)
    assert res.returncode == 1 and res.stdout == ""
    assert res.stderr.startswith("board_resolve: ")


def test_resolve_refuses_an_empty_and_a_long_reason():
    assert run(waiting(), reason="").returncode == 1
    assert run(waiting(), reason="x" * 201).returncode == 1
    res = run(waiting(), reason="x" * 200)
    assert res.returncode == 0, res.stderr


def test_resolve_reads_a_file(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(waiting()))
    res = subprocess.run([*RESOLVE, str(path), "--now", NOW, "--reason", "ok"], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_resolve_clears_a_command_record():
    rec = fixture_record("f-maint-deps--deps")
    res = run(rec)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["status"] == "done" and out["finished_at"] == NOW
    assert board_record.validate(out, "f-maint-deps--deps") == []


def test_resolve_refuses_an_output_that_does_not_validate():
    rec = waiting()
    rec["surprise"] = 1
    res = run(rec)
    assert res.returncode == 1
    assert res.stderr.startswith("board_resolve: ")


def test_prune_clears_a_record_through_client_get_resolve_and_set(tmp_path):
    with running(tmp_path) as srv:
        doc_id = "f-waiting"
        rec = waiting()
        for key in ("updated_at", "needs_you_since", "next_check_at"):
            rec[key] = "2026-11-12T09:00:00Z"
        srv.store.set(doc_id, rec, None)
        srv.store.dismiss(doc_id, 1)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TLD_BOARD_")}
        env.update(TLD_BOARD_URL=base(srv), TLD_BOARD_TOKEN=WRITE)
        client = tld_cmd("board", "client")
        got = subprocess.run([*client, "get", doc_id], env=env, capture_output=True, text=True, timeout=30)
        assert got.returncode == 0, got.stderr
        res = subprocess.run([*RESOLVE, "-", "--now", NOW, "--reason", "PRs merged"], input=got.stdout,
                             capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, res.stderr
        put = subprocess.run([*client, "set", doc_id, "-", "--if-version", "1"], input=res.stdout, env=env,
                             capture_output=True, text=True, timeout=30)
        assert put.returncode == 0, put.stderr
        with urllib.request.urlopen(urllib.request.Request(
                f"{base(srv)}/api/records/{doc_id}", headers={"Authorization": f"Bearer {WRITE}"})) as resp:
            entry = json.load(resp)
        assert entry["version"] == 2 and entry["dismissed_at"] is None
        assert entry["data"]["needs_you"] is False and entry["data"]["status"] == "done"


def stale_ids(entries):
    res = subprocess.run([*STALE, "-", "--now", "2026-11-09T12:00:00Z"], input=json.dumps(entries),
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return res.stdout.split()


def test_stale_prints_every_dismissed_record():
    entry = {"id": "f-waiting", "version": 1, "data": fixture_record("f-waiting")}
    assert stale_ids([entry]) == []
    assert stale_ids([{**entry, "dismissed_at": None}]) == []
    assert stale_ids([{**entry, "dismissed_at": "2026-11-09T11:00:00Z"}]) == ["f-waiting"]
    quiet = {"id": "f-running-ok", "version": 1, "data": fixture_record("f-running-ok")}
    assert stale_ids([quiet]) == []
    assert stale_ids([{**quiet, "dismissed_at": None}]) == []
    assert stale_ids([{**quiet, "dismissed_at": "2026-11-09T11:00:00Z"}]) == ["f-running-ok"]


def test_stale_matches_the_links_fixture():
    fixture = json.loads((FIXTURES / "board-links.json").read_text())
    res = subprocess.run([*STALE, "-", "--now", fixture["now"]], input=json.dumps(fixture["entries"]),
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert sorted(res.stdout.split()) == sorted(fixture["expected_stale"])
