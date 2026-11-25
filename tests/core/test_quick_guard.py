"""The guards a quick session meets: plan-gate opens for it, protect-paths keeps its protected paths."""
import pytest

import hooks_helpers as hh
from hooks_helpers import bash, event, make_repo, make_repo_with_origin, run
from tld.guard import _common, markers, plan_gate
from tld.guard.action import Action

ON = hh.PROFILE + "hooks:\n  plan_gate:\n    enabled: true\n"
PROTECTED = [".env", ".env.local", "uv.lock", "package-lock.json", "go.sum", "Cargo.lock",
             ".github/workflows/tld-land.yml", ".github/workflows/tld-release.yml", ".git/config"]


def decide(action):
    return _common.run_guard("plan-gate", plan_gate.evaluate, False, action)


def write(repo, path, sid="s1"):
    return decide(Action("write", str(repo), str(repo), path=str(repo / path), session_id=sid))


def prompt(repo, text, invoked=None, sid="s1"):
    return decide(Action("prompt", str(repo), str(repo), prompt=text, invoked=invoked, session_id=sid))


def test_a_quick_prompt_opens_only_its_own_session(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    assert write(repo, "src/a.py", "s1").verdict == "deny"
    assert prompt(repo, "/tld:quick x", "quick", "s1").context is None
    assert write(repo, "src/a.py", "s1").verdict == "allow"
    assert write(repo, "src/a.py", "s2").verdict == "deny"


def test_a_quick_worker_is_allowed(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    assert prompt(repo, "tld-worker: quick #1\nfix it", None, "w1").context is None
    assert write(repo, "src/a.py", "w1").verdict == "allow"


@pytest.fixture()
def open_repo(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", "feature/demo", ON)
    prompt(repo, "/tld:quick x", "quick", "s1")
    markers.write(str(repo), "plan-open")
    return repo


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_paths_stay_denied_in_a_quick_session(open_repo, path):
    assert run("protect-paths", event("Write", open_repo, file_path=path, content="x")).code == 2
    assert run("protect-paths", bash("echo x > " + path, open_repo)).code == 2


def test_an_ordinary_path_is_allowed(open_repo):
    assert run("protect-paths", event("Write", open_repo, file_path="src/app.py", content="x")).code == 0
    assert run("protect-paths", bash("echo x > src/app.py", open_repo)).code == 0


def test_the_profile_decides_not_the_session(tmp_path):
    repo = make_repo_with_origin(tmp_path / "r", "feature/demo", ON)
    paths = (".tld/toolkit.yaml", ".github/workflows/ci.yml")
    before = [run("protect-paths", event("Write", repo, file_path=p, content="x")).code for p in paths]
    prompt(repo, "/tld:quick x", "quick", "s1")
    markers.write(str(repo), "plan-open")
    after = [run("protect-paths", event("Write", repo, file_path=p, content="x")).code for p in paths]
    assert before == after
