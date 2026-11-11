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
    (repo / ".tld" / "toolkit.yaml").write_text(
        "git:\n  main_branch: main\nverify:\n  dod:\n    - run: test -d ../sub && exit 1\n      cwd: sub\n"
        "hooks:\n  dod_gate:\n    enabled: true\n")
    assert "test -d ../sub" in run(HOOK, stop(repo)).stderr
    dg = hh.module(HOOK)
    monkeypatch.setattr(dg, "TOTAL_BUDGET_SECONDS", 0.5)
    (repo / ".tld" / "toolkit.yaml").write_text(profile(["sleep 5"]))
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
    assert (repo / ".git" / "tld" / "dod-gate-exempt.json").is_file(), "the marker lives in the git dir"
    assert run(HOOK, stop(repo)).code == 0 and counter() == 0
    git(repo, "status", "--porcelain")  # the marker is not part of the working tree
    assert "tld" not in git(repo, "status", "--porcelain")


def test_unmarked_checkout_is_a_phase_or_single_session(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    assert run(HOOK, stop(repo)).code == 2


def test_the_marker_lapses_after_a_day_and_is_refreshed_by_every_stop(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    mark(repo)
    marker = repo / ".git" / "tld" / "dod-gate-exempt.json"
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
def three_stops(repo):
    return [run(HOOK, stop(repo, active=True)) for _ in range(3)]


def test_missing_dod_key_fails_loudly_then_gives_up(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", "git:\n  main_branch: main\nhooks:\n  dod_gate:\n    enabled: true\n")
    (repo / "w.txt").write_text("x")
    first, second, third = three_stops(repo)
    assert first.code == 2 and "toolkit.yaml: missing required key 'verify.dod'" in first.stderr
    assert second.code == 2
    assert third.code == 0 and "missing required key 'verify.dod'" in json.loads(third.stdout)["systemMessage"]


def test_missing_main_branch_fails_loudly_then_gives_up(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo",
                     "verify:\n  dod: ['true']\nhooks:\n  dod_gate:\n    enabled: true\n")
    first, second, third = three_stops(repo)
    assert first.code == 2 and "missing required key 'git.main_branch'" in first.stderr
    assert second.code == 2
    assert third.code == 0 and "missing required key 'git.main_branch'" in json.loads(third.stdout)["systemMessage"]


def test_max_attempts_above_10_is_rejected(tmp_path):
    repo = repo_with(tmp_path, ["true"], extra="    max_attempts: 50\n")
    r = run(HOOK, stop(repo))
    assert r.code == 2 and "hooks.dod_gate.max_attempts" in r.stderr and "between 1 and 10" in r.stderr


# ---- how the tree is compared with main ------------------------------------------------------
def test_origin_main_is_compared_even_when_local_main_was_fast_forwarded(tmp_path):
    src = make_repo(tmp_path / "src", "main", profile(["exit 1"]))
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(tmp_path / "origin.git")], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(clone)], check=True)
    git(clone, "checkout", "-q", "-b", "feature/x")
    (clone / "a.txt").write_text("x")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "work")
    git(clone, "branch", "-f", "main", "HEAD")
    assert run(HOOK, stop(clone)).code == 2, "origin/main..HEAD is not empty, although main..HEAD is"


def test_cannot_tell_when_neither_main_nor_origin_main_exists(tmp_path):
    repo = tmp_path / "orphan"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "other")
    (repo / ".tld").mkdir()
    (repo / ".tld" / "toolkit.yaml").write_text(profile(["false"]))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    assert run(HOOK, stop(repo)).code == 2, "cannot tell what is new: treated as changed"


def test_budget_used_up_marks_the_remaining_commands_not_run(tmp_path, monkeypatch):
    repo = repo_with(tmp_path, ["sleep 1", "true"])
    monkeypatch.setattr(hh.module(HOOK), "TOTAL_BUDGET_SECONDS", 0.5)
    r = run(HOOK, stop(repo))
    assert r.code == 2
    assert "`sleep 1`: timed out" in r.stderr
    assert "`true`: not run: the gate's time budget was used up" in r.stderr


@pytest.mark.parametrize("bad", ["    max_attempts: 0\n", "    max_attempts: lots\n"])
def test_bad_max_attempts_is_reported(tmp_path, bad):
    repo = repo_with(tmp_path, ["true"], extra=bad)
    assert "'hooks.dod_gate.max_attempts' must be a positive integer" in run(HOOK, stop(repo)).stderr


def test_disable_flag(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"], change=False)
    (repo / ".tld" / "toolkit.yaml").write_text(profile(["exit 1"]) + "  disable: [dod-gate]\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "disable on main")
    git(repo, "branch", "-f", "main", "HEAD")  # the disable is committed on main
    (repo / "work.txt").write_text("new work\n")
    assert run(HOOK, stop(repo)).code == 0


def test_malformed_disable_does_not_loop_dod_gate(tmp_path):
    repo = repo_with(tmp_path, ["exit 1"])
    cfg = profile(["exit 1"]) + "  disable: dod-gate\n"
    (repo / ".tld" / "toolkit.yaml").write_text(cfg)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "bad disable")
    git(repo, "branch", "-f", "main", "HEAD")
    (repo / "work.txt").write_text("more work\n")
    codes = [run(HOOK, stop(repo, active=True)).code for _ in range(3)]
    assert codes == [2, 2, 0], codes  # three profile-error attempts, then it lets go


def test_script_contract(tmp_path):
    repo = repo_with(tmp_path, ["echo broken tests; exit 1"])
    r = subprocess.run([sys.executable, str(HOOKS / "dod_gate.py")], input=json.dumps(stop(repo)), capture_output=True,
                       text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    assert r.returncode == 2 and "broken tests" in r.stderr and r.stdout == ""
    assert subprocess.run([sys.executable, str(HOOKS / "dod_gate.py"), "--bogus"], capture_output=True).returncode == 2
