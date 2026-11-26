"""protect-paths: the profile is editable only while the /setup marker of this checkout is fresh (D10)."""
import json
import subprocess
import sys
import time

import pytest

from hooks_helpers import HOOKS, PROFILE as BASE_PROFILE, bash, event, make_repo, run, run_script

HOOK = "protect-paths"
PROFILE = ".tld/toolkit.yaml"
# The profile is no longer on the default protect list: a repository that adds it back (here with the workflows) is the
# case the /setup marker still serves.
LISTED = BASE_PROFILE + "hooks:\n  protect_paths: ['.tld/toolkit.yaml', '.env', '*.lock', '.github/workflows/**']\n"


@pytest.fixture()
def fresh_repo(tmp_path):
    return make_repo(tmp_path / "repo", "feature/demo", LISTED)


def test_the_profile_and_ordinary_workflows_are_allowed_by_default(tmp_path):
    repo = make_repo(tmp_path / "plain", "feature/demo")
    assert write(repo, PROFILE) == 0 and write(repo, ".github/workflows/ci.yml") == 0
STILL_DENIED = [".env", "uv.lock", ".github/workflows/ci.yml"]


def cli(repo, flag):
    return subprocess.run([sys.executable, str(HOOKS / "protect_paths.py"), flag], cwd=repo, capture_output=True,
                          text=True, timeout=60)


def write(repo, path):
    return run(HOOK, event("Write", repo, file_path=path, content="x")).code


def marker(repo):
    return next((repo / ".git" / "tld").glob("protect-paths-profile.json"))


def test_denied_without_a_marker(fresh_repo):
    assert write(fresh_repo, PROFILE) == 2


def test_allow_profile_lets_only_the_profile_through(fresh_repo):
    r = cli(fresh_repo, "--allow-profile")
    assert r.returncode == 0
    assert r.stdout.startswith("protect-paths: .tld/toolkit.yaml may be edited for the next 2 hours (")
    assert write(fresh_repo, PROFILE) == 0
    assert write(fresh_repo, str(fresh_repo / PROFILE)) == 0
    for path in STILL_DENIED:
        assert write(fresh_repo, path) == 2, path
    assert write(fresh_repo, "sub/.tld/toolkit.yaml") == 0  # was never protected


def test_expired_marker_denies_again(fresh_repo):
    cli(fresh_repo, "--allow-profile")
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 3600))
    marker(fresh_repo).write_text(json.dumps({"written_at": old}))
    assert write(fresh_repo, PROFILE) == 2


def test_garbage_marker_denies(fresh_repo):
    cli(fresh_repo, "--allow-profile")
    marker(fresh_repo).write_text("not json")
    assert write(fresh_repo, PROFILE) == 2


def test_end_allow_denies_again(fresh_repo):
    cli(fresh_repo, "--allow-profile")
    r = cli(fresh_repo, "--end-allow")
    assert r.returncode == 0 and r.stdout.strip() == ("protect-paths: .tld/toolkit.yaml is protected again; workflow installs, "
                                                      "real git-ops runs and real release runs are off")
    assert write(fresh_repo, PROFILE) == 2
    assert cli(fresh_repo, "--end-allow").returncode == 0  # idempotent


def test_bash_follows_the_same_rule(fresh_repo):
    command = f"sed -i 's/main/trunk/' {PROFILE}"
    assert run(HOOK, bash(command, fresh_repo)).code == 2
    cli(fresh_repo, "--allow-profile")
    assert run(HOOK, bash(command, fresh_repo)).code == 0
    assert run(HOOK, bash("sed -i 's/a/b/' .env", fresh_repo)).code == 2


def test_script_contract_with_the_marker(fresh_repo):
    cli(fresh_repo, "--allow-profile")
    payload = event("Write", fresh_repo, file_path=PROFILE, content="x")
    assert run_script(HOOK, payload).returncode == 0


def test_a_marker_in_one_repository_does_not_allow_another(tmp_path):
    a, b = make_repo(tmp_path / "a", "feature/x", LISTED), make_repo(tmp_path / "b", "feature/x", LISTED)
    cli(a, "--allow-profile")
    assert write(a, PROFILE) == 0
    assert write(b, PROFILE) == 2
