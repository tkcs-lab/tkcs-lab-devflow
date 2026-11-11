import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import DEVFLOW, ROOT

SYNC = DEVFLOW / "scripts" / "upstream_sync.py"
COMMAND = DEVFLOW / "commands" / "upstream.md"
SEMVER = r"^v[0-9]+\.[0-9]+\.[0-9]+$"
# Built at import time, before conftest's session fixture runs, so it isolates git config itself.
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout.strip()


def sync(cwd, *args):
    return subprocess.run([sys.executable, str(SYNC), *args], cwd=cwd, env=ENV, capture_output=True, text=True)


def write(repo, name, text):
    (repo / name).write_text(text)
    git(repo, "add", name)


@pytest.fixture
def world(tmp_path):
    up = tmp_path / "upstream"
    up.mkdir()
    git(up, "init", "-q", "-b", "main")
    write(up, "app.txt", "".join(f"line {i}\n" for i in range(1, 11)))
    write(up, "other.txt", "one\n")
    git(up, "commit", "-q", "-m", "v1.0.0")
    git(up, "tag", "v1.0.0")
    old_sha = git(up, "rev-parse", "HEAD")
    write(up, "other.txt", "one\ntwo\n")
    git(up, "commit", "-q", "-m", "v1.1.0")
    git(up, "tag", "-a", "-m", "release", "v1.1.0")
    write(up, "new.txt", "new\n")
    git(up, "commit", "-q", "-m", "rc")
    git(up, "tag", "v1.2.0-rc1")
    write(up, "other.txt", "one\ntwo\nthree\n")
    git(up, "commit", "-q", "-m", "v1.2.0")
    git(up, "tag", "v1.2.0")

    fork = tmp_path / "fork"
    fork.mkdir()
    git(fork, "init", "-q", "-b", "main")
    git(up, "archive", "--format=tar", "-o", str(tmp_path / "v1.tar"), "v1.0.0")
    subprocess.run(["tar", "-xf", str(tmp_path / "v1.tar"), "-C", fork], check=True)
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "base")
    text = (fork / "app.txt").read_text().replace("line 3\n", "line 3 patched\n")
    write(fork, "app.txt", text)
    git(fork, "commit", "-q", "-m", "patch")
    write(fork, "UPSTREAM_VERSION", f"tag: v1.0.0\ncommit: {old_sha}\nsynced_at: 2026-01-01\n")
    git(fork, "commit", "-q", "-m", "version file")
    return up, fork


def prepare(fork, up, tag="v1.2.0"):
    return sync(fork, "prepare", "--upstream-url", str(up), "--version-file", "UPSTREAM_VERSION",
                "--tag", tag, "--branch", "chore/upstream-x", "--base", "main")


def test_plan_reports_latest_without_rc(world):
    up, fork = world
    r = sync(fork, "plan", "--upstream-url", str(up), "--version-file", "UPSTREAM_VERSION", "--pattern", SEMVER)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"current": "v1.0.0", "latest": "v1.2.0", "up_to_date": False}


def test_plan_up_to_date(world):
    up, fork = world
    (fork / "UPSTREAM_VERSION").write_text(f"tag: v1.2.0\ncommit: {git(up, 'rev-parse', 'v1.2.0')}\nsynced_at: 2026-01-01\n")
    r = sync(fork, "plan", "--upstream-url", str(up), "--version-file", "UPSTREAM_VERSION", "--pattern", SEMVER)
    assert json.loads(r.stdout)["up_to_date"] is True


def test_plan_no_eligible_release_exit_3(world):
    up, fork = world
    r = sync(fork, "plan", "--upstream-url", str(up), "--version-file", "UPSTREAM_VERSION", "--pattern", "^nomatch$")
    assert r.returncode == 3


def test_clean_prepare_leaves_uncommitted_merge(world):
    up, fork = world
    log = git(fork, "log", "--format=%H")
    r = prepare(fork, up)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "clean"
    assert git(fork, "log", "--format=%H") == log
    assert git(fork, "branch", "--show-current") == "chore/upstream-x"
    assert (fork / "other.txt").read_text() == "one\ntwo\nthree\n"
    assert "line 3 patched" in (fork / "app.txt").read_text()
    new_sha = git(up, "rev-parse", "v1.2.0^{commit}")
    version = (fork / "UPSTREAM_VERSION").read_text().splitlines()
    assert version[0] == "tag: v1.2.0" and version[1] == f"commit: {new_sha}"
    assert re.fullmatch(r"synced_at: \d{4}-\d{2}-\d{2}", version[2])
    assert git(fork, "status", "--porcelain")


def test_annotated_tag_records_peeled_commit(world):
    up, fork = world
    r = prepare(fork, up, tag="v1.1.0")
    assert r.returncode == 0, r.stderr
    assert f"commit: {git(up, 'rev-parse', 'v1.1.0^{commit}')}" in (fork / "UPSTREAM_VERSION").read_text()


def test_conflicting_prepare_lists_the_path(world):
    up, fork = world
    text = (up / "app.txt").read_text().replace("line 3\n", "line 3 upstream\n")
    write(up, "app.txt", text)
    git(up, "commit", "-q", "-m", "conflict")
    git(up, "tag", "v1.3.0")
    log = git(fork, "log", "--format=%H")
    r = prepare(fork, up, tag="v1.3.0")
    assert r.returncode == 2, r.stderr
    assert r.stdout.split() == ["app.txt"]
    assert "<<<<<<<" in (fork / "app.txt").read_text()
    assert git(fork, "log", "--format=%H") == log


@pytest.mark.parametrize("content", ["", "tag: v1.0.0\n", "tag: v1.0.0\ncommit: abc\nsynced_at: 2026-01-01\n",
                                     "tag: v1.0.0\ncommit: " + "a" * 40 + "\nsynced_at: yesterday\n"])
def test_malformed_version_file_exit_1(world, content):
    up, fork = world
    (fork / "UPSTREAM_VERSION").write_text(content)
    r = sync(fork, "plan", "--upstream-url", str(up), "--version-file", "UPSTREAM_VERSION", "--pattern", SEMVER)
    assert r.returncode == 1
    assert r.stderr.startswith("upstream_sync: ")


def test_missing_version_file_exit_1(world):
    up, fork = world
    (fork / "UPSTREAM_VERSION").unlink()
    r = sync(fork, "plan", "--upstream-url", str(up), "--version-file", "UPSTREAM_VERSION", "--pattern", SEMVER)
    assert r.returncode == 1


def test_tag_route_matches_the_spike():
    spike = (ROOT / "docs" / "architecture" / "maintenance-spike.md").read_text()
    route = re.search(r"^ROUTE f: (.+)$", spike, re.M).group(1).strip()
    assert route in COMMAND.read_text()


def test_command_has_no_forbidden_word():
    forbidden = re.search(r"FORBIDDEN = re.compile\(r\"(.*?)\", re.I\)",
                          (ROOT / "tests" / "test_no_project_words.py").read_text()).group(1)
    assert re.search(forbidden, COMMAND.read_text(), re.I) is None


def test_command_flags_exist_in_help():
    help_texts = {"": subprocess.run([sys.executable, str(SYNC), "--help"], capture_output=True, text=True).stdout}
    for sub in ("plan", "prepare"):
        help_texts[sub] = subprocess.run([sys.executable, str(SYNC), sub, "--help"], capture_output=True, text=True).stdout
    lines = [l for l in COMMAND.read_text().splitlines() if "upstream_sync.py" in l]
    assert lines
    for line in lines:
        words = [w.strip("`.,:;()") for w in line.split("upstream_sync.py", 1)[1].split()]
        sub = next((w for w in words if w in ("plan", "prepare")), None)
        assert sub, f"no subcommand in: {line}"
        for flag in re.findall(r"--[a-z-]+", line.split("upstream_sync.py", 1)[1]):
            assert flag in help_texts[sub], f"{flag} not in 'upstream_sync.py {sub} --help'"
