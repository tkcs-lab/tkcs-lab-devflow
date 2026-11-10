"""dod-gate (Stop): block stopping until verify.dod passes. Opt-in, loop-free, orchestrator-exempt."""
import json
import os
import subprocess
import sys
import time

import pytest

import hooks_helpers as hh
from hooks_helpers import HOOKS, git, make_repo, run

HOOK = "dod-gate"


def profile(dod, enabled=True, extra=""):
    gate = f"  dod_gate:\n    enabled: {str(enabled).lower()}\n{extra}" if enabled is not None else ""
    return ("git:\n  main_branch: main\nverify:\n  dod:\n" + "".join(f"    - {json.dumps(c)}\n" for c in dod)
            + ("hooks:\n" + gate if gate else ""))


def stop(repo, active=False, session="s1"):
    return {"session_id": session, "cwd": str(repo), "hook_event_name": "Stop", "stop_hook_active": active}


@pytest.fixture()
def counter(tmp_path):
    path = tmp_path / "count.txt"

    def count():
        return len(path.read_text()) if path.exists() else 0
    count.cmd = f"printf x >> {path}"
    return count


def repo_with(tmp_path, dod, enabled=True, extra="", change=True):
    repo = make_repo(tmp_path / "repo", "feature/demo", profile(dod, enabled, extra))
    if change:
        (repo / "work.txt").write_text("new work\n")
    return repo


def test_off_by_default(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"], enabled=None)
    assert run(HOOK, stop(repo)).code == 0
    repo = repo_with(tmp_path / "b", ["exit 1"], enabled=False)
    assert run(HOOK, stop(repo)).code == 0


def test_nothing_to_check_when_nothing_changed(tmp_path, counter):
    repo = repo_with(tmp_path, [counter.cmd], change=False)
    git(repo, "checkout", "-q", "main")
    assert run(HOOK, stop(repo)).code == 0 and counter() == 0, "clean tree on main: the gate does not run"


def test_committed_work_ahead_of_main_is_checked(tmp_path, counter):
    repo = repo_with(tmp_path, [counter.cmd + "; exit 1"], change=False)
    (repo / "a.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "work")
    assert run(HOOK, stop(repo)).code == 2 and counter() == 1


def test_green_gate_lets_the_session_stop_and_is_not_rerun_on_the_same_tree(tmp_path, counter):
    repo = repo_with(tmp_path, [counter.cmd])
    assert run(HOOK, stop(repo)).code == 0 and counter() == 1
    assert run(HOOK, stop(repo)).code == 0 and counter() == 1, "same tree, same session: cached"
    (repo / "work.txt").write_text("changed\n")
    assert run(HOOK, stop(repo)).code == 0 and counter() == 2, "the tree changed: run again"


def test_red_gate_blocks_with_the_failure_and_what_to_do(tmp_path):
    repo = repo_with(tmp_path, ["echo ok-step", "echo 'AssertionError: 1 != 2' >&2; echo more; exit 3"])
    r = run(HOOK, stop(repo))
    assert r.code == 2
    assert "attempt 1 of 3" in r.stderr and "exit 3" in r.stderr and "AssertionError: 1 != 2" in r.stderr
    assert "ok-step" not in r.stderr, "only failing commands are reported"
    assert "never skip, loosen or delete a test" in r.stderr and "/dod" in r.stderr


def test_every_failing_command_is_reported(tmp_path):
    repo = repo_with(tmp_path, ["exit 1", "exit 2", "true"])
    err = run(HOOK, stop(repo)).stderr
    assert "`exit 1`" in err and "`exit 2`" in err and "`true`" not in err


def test_loop_limit_then_stop_is_allowed_with_the_reason(tmp_path, counter):
    repo = repo_with(tmp_path, [counter.cmd + "; exit 1"])
    assert "attempt 1 of 3" in run(HOOK, stop(repo)).stderr
    assert "attempt 2 of 3" in run(HOOK, stop(repo, active=True)).stderr
    last = run(HOOK, stop(repo, active=True))
    assert last.code == 0 and last.stderr == ""
    notice = json.loads(last.stdout)["systemMessage"]
    assert "still red" in notice and "limit of 3" in notice and "3 failed attempt" in notice
    assert counter() == 3
    again = run(HOOK, stop(repo))
    assert again.code == 0 and counter() == 3, "after giving up on a tree the gate does not run it again"
    (repo / "work.txt").write_text("more edits\n")
    back = run(HOOK, stop(repo))
    assert back.code == 2 and "attempt 1 of 3" in back.stderr, "new edits: the gate is back, counting from the start"


def test_max_attempts_is_configurable(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"], extra="    max_attempts: 1\n")
    r = run(HOOK, stop(repo))
    assert r.code == 0 and "limit of 1" in json.loads(r.stdout)["systemMessage"]


def test_sessions_are_counted_separately(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    assert "attempt 1 of 3" in run(HOOK, stop(repo, session="a")).stderr
    assert "attempt 2 of 3" in run(HOOK, stop(repo, session="a")).stderr
    assert "attempt 1 of 3" in run(HOOK, stop(repo, session="b")).stderr


def test_stop_hook_active_without_a_writable_counter_stops_instead_of_looping(tmp_path, monkeypatch):
    repo = repo_with(tmp_path, ["exit 1"])
    dg = hh.module(HOOK)
    monkeypatch.setattr(dg, "save_state", lambda *a, **k: False)
    first = run(HOOK, stop(repo, active=False))
    assert first.code == 2, "the first block is fine, the next stop carries stop_hook_active"
    second = run(HOOK, stop(repo, active=True))
    assert second.code == 0 and "could not be saved" in json.loads(second.stdout)["systemMessage"]


def test_commands_run_in_their_cwd_and_a_timeout_is_a_failure(tmp_path, monkeypatch):
    repo = repo_with(tmp_path, [])
    (repo / "sub").mkdir()
    (repo / ".claude" / "toolkit.yaml").write_text(
        "git:\n  main_branch: main\nverify:\n  dod:\n    - run: test -d ../sub && exit 1\n      cwd: sub\n"
        "hooks:\n  dod_gate:\n    enabled: true\n")
    assert "test -d ../sub" in run(HOOK, stop(repo)).stderr
    dg = hh.module(HOOK)
    monkeypatch.setattr(dg, "TOTAL_BUDGET_SECONDS", 0.5)
    (repo / ".claude" / "toolkit.yaml").write_text(profile(["sleep 5"]))
    (repo / "work.txt").write_text("t\n")
    assert "timed out" in run(HOOK, stop(repo)).stderr


# ---- how a session is recognised -------------------------------------------------------------
def mark(repo):
    return subprocess.run([sys.executable, str(HOOKS / "dod_gate.py"), "--exempt"], cwd=repo, capture_output=True,
                          text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})


def test_exempt_session_is_never_blocked(tmp_path, counter):
    repo = repo_with(tmp_path, [counter.cmd + "; exit 1"])
    r = mark(repo)
    assert r.returncode == 0 and "this session is exempt" in r.stdout
    assert (repo / ".git" / "devflow" / "dod-gate-exempt.json").is_file(), "the marker lives in the git dir"
    assert run(HOOK, stop(repo)).code == 0 and counter() == 0
    git(repo, "status", "--porcelain")  # the marker is not part of the working tree
    assert "devflow" not in git(repo, "status", "--porcelain")


def test_unmarked_checkout_is_a_phase_or_single_session(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    assert run(HOOK, stop(repo)).code == 2


def test_the_marker_lapses_after_a_day_and_is_refreshed_by_every_stop(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    mark(repo)
    marker = repo / ".git" / "devflow" / "dod-gate-exempt.json"
    old = time.time() - 23 * 3600
    os.utime(marker, (old, old))
    assert run(HOOK, stop(repo)).code == 0
    assert time.time() - marker.stat().st_mtime < 60, "a stop of the exempt session refreshes the marker"
    old = time.time() - 25 * 3600
    os.utime(marker, (old, old))
    assert run(HOOK, stop(repo)).code == 2


def test_a_fresh_checkout_has_no_marker(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    mark(repo)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
    git(clone, "checkout", "-q", "-b", "feature/x")
    (clone / "new.txt").write_text("x")
    assert run(HOOK, stop(clone)).code == 2, "a child session starts from a fresh clone: not exempt"


# ---- profile problems -------------------------------------------------------------------------
def test_missing_dod_key_fails_loudly(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", "git:\n  main_branch: main\nhooks:\n  dod_gate:\n    enabled: true\n")
    (repo / "w.txt").write_text("x")
    r = run(HOOK, stop(repo))
    assert r.code == 2 and "toolkit.yaml: missing required key 'verify.dod'" in r.stderr


def test_missing_main_branch_fails_loudly(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo",
                     "verify:\n  dod: ['true']\nhooks:\n  dod_gate:\n    enabled: true\n")
    assert "missing required key 'git.main_branch'" in run(HOOK, stop(repo)).stderr


@pytest.mark.parametrize("bad", ["    max_attempts: 0\n", "    max_attempts: lots\n"])
def test_bad_max_attempts_is_reported(tmp_path, bad):
    repo = repo_with(tmp_path, ["true"], extra=bad)
    assert "'hooks.dod_gate.max_attempts' must be a positive integer" in run(HOOK, stop(repo)).stderr


def test_disable_flag(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    (repo / ".claude" / "toolkit.yaml").write_text(profile(["exit 1"]) + "  disable: [dod-gate]\n")
    assert run(HOOK, stop(repo)).code == 0


def test_script_contract(tmp_path):
    repo = repo_with(tmp_path, ["echo broken tests; exit 1"])
    r = subprocess.run([sys.executable, str(HOOKS / "dod_gate.py")], input=json.dumps(stop(repo)), capture_output=True,
                       text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    assert r.returncode == 2 and "broken tests" in r.stderr and r.stdout == ""
    assert subprocess.run([sys.executable, str(HOOKS / "dod_gate.py"), "--bogus"], capture_output=True).returncode == 2
