"""plan-gate (UserPromptSubmit, PreToolUse): a session no tld command started cannot write to the repository."""
import os
import time

import pytest

import hooks_helpers as hh
from hooks_helpers import make_repo, make_repo_with_origin
from tld.guard import _common, markers, plan_gate
from tld.guard.action import Action

ON = hh.PROFILE + "hooks:\n  plan_gate:\n    enabled: true\n"


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path / "repo", "feature/demo", ON)


def decide(action):
    return _common.run_guard("plan-gate", plan_gate.evaluate, False, action)


def write(repo, path, sid="s1"):
    return decide(Action("write", str(repo), str(repo), path=str(path), session_id=sid))


def sh(repo, command, sid="s1"):
    return decide(Action("shell", str(repo), str(repo), command=command, session_id=sid))


def gh(repo, op, sid="s1"):
    return decide(Action("github_op", str(repo), str(repo), op=op, session_id=sid))


def prompt(repo, text, invoked=None, sid="s1"):
    return decide(Action("prompt", str(repo), str(repo), prompt=text, invoked=invoked, session_id=sid))


def test_off_by_default_allows_everything(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    assert write(repo, repo / "a.txt").verdict == "allow"
    assert sh(repo, "echo x > a.txt").verdict == "allow"
    assert prompt(repo, "hello").context is None


def test_closed_session_denies_write_inside_repo(repo):
    d = write(repo, repo / "a.txt")
    assert d.verdict == "deny" and "a.txt" in d.reason


def test_closed_session_allows_write_outside_repo(repo, tmp_path):
    assert write(repo, tmp_path / "sibling.txt").verdict == "allow"


def test_closed_session_allows_git_dir_writes(repo):
    assert write(repo, repo / ".git" / "info" / "x").verdict == "allow"


def test_closed_session_denies_bash_redirect_into_repo(repo):
    assert sh(repo, "echo x > out.txt").verdict == "deny"


def test_git_checkout_of_a_name_is_denied_in_a_closed_session(repo):
    assert sh(repo, "git checkout main").verdict == "deny"


def test_worker_brief_prompt_gets_no_context(repo):
    assert prompt(repo, "Run tld guard allow-plan first, then do the work").context is None


@pytest.mark.parametrize("cmd", ["ls", "git status", "cat README.md", "git log"])
def test_closed_session_allows_read_only_bash(repo, cmd):
    assert sh(repo, cmd).verdict == "allow", cmd


def test_closed_session_denies_github_content_writes(repo):
    for op in ("push_files", "create_or_update_file", "delete_file"):
        assert gh(repo, op).verdict == "deny", op
    assert gh(repo, "create_pull_request").verdict == "allow"


def test_prompt_with_opening_command_opens_the_session(repo):
    assert prompt(repo, "/tld:make-plan x", "make-plan").context is None
    assert write(repo, repo / "a.txt").verdict == "allow"
    assert write(repo, repo / "a.txt", sid="other").verdict == "deny"


def test_prompt_with_questions_opens_the_session(repo):
    assert prompt(repo, "/tld:questions", "questions").context is None
    assert write(repo, repo / "a.txt").verdict == "allow"
    assert write(repo, repo / "a.txt", sid="other").verdict == "deny"


def test_release_prompt_opens_the_session(repo):
    assert prompt(repo, "/tld:release minor", "release").context is None
    assert write(repo, repo / "a.txt").verdict == "allow"
    assert write(repo, repo / "a.txt", sid="other").verdict == "deny"


def test_prompt_with_other_known_command_adds_no_context_and_does_not_open(repo):
    assert prompt(repo, "/tld:dod", "dod").context is None
    assert write(repo, repo / "a.txt").verdict == "deny"


def test_plain_prompt_adds_the_context(repo):
    assert prompt(repo, "implement X").context == plan_gate.PROMPT_CONTEXT


def test_plain_prompt_in_an_open_session_adds_nothing(repo):
    prompt(repo, "/tld:implement x", "implement")
    assert prompt(repo, "go on").context is None


def test_worker_marker_opens_the_gate(repo):
    markers.write(str(repo), "plan-open")
    assert write(repo, repo / "a.txt", sid="anything").verdict == "allow"
    assert write(repo, repo / "a.txt", sid=None).verdict == "allow"


def test_no_session_id_and_no_marker_fails_open(repo):
    assert write(repo, repo / "a.txt", sid=None).verdict == "allow"


def test_session_file_name_is_a_hash(repo):
    prompt(repo, "/tld:make-plan x", "make-plan", sid="secret-session-id")
    f = plan_gate.session_file(str(repo), "secret-session-id")
    assert f.is_file() and f.parent.name == "plan-gate" and f.parent.parent.name == "tld"
    assert f.parent.parent.parent.name == ".git" and "secret-session-id" not in f.name


def test_session_lapses_after_24_hours(repo):
    prompt(repo, "/tld:make-plan x", "make-plan")
    f = plan_gate.session_file(str(repo), "s1")
    old = time.time() - plan_gate.SESSION_TTL_SECONDS - 60
    os.utime(f, (old, old))
    assert write(repo, repo / "a.txt").verdict == "deny"


def test_session_is_refreshed_on_read(repo):
    prompt(repo, "/tld:make-plan x", "make-plan")
    f = plan_gate.session_file(str(repo), "s1")
    old = time.time() - plan_gate.SESSION_TTL_SECONDS + 600
    os.utime(f, (old, old))
    assert write(repo, repo / "a.txt").verdict == "allow"
    assert time.time() - f.stat().st_mtime < 60


def test_malformed_plan_gate_section_allows_with_a_notice(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", hh.PROFILE + "hooks:\n  plan_gate: yes\n")
    d = write(repo, repo / "a.txt")
    assert d.verdict == "allow" and d.notice and "plan_gate" in d.notice


def test_disable_in_the_trusted_profile_switches_it_off(tmp_path):
    text = ON + "  disable: [plan-gate]\n"
    repo = make_repo_with_origin(tmp_path / "r", committed=text, working=text)
    assert write(repo, repo / "a.txt").verdict == "allow"
    assert prompt(repo, "hello").context is None


def test_deny_text_names_make_plan_and_not_the_marker_command(repo):
    reason = write(repo, repo / "a.txt").reason
    assert "/tld:make-plan" in reason and "allow-plan" not in reason
