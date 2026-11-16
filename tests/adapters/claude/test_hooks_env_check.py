"""The Claude adapter of env-check: the events, CLAUDE_CODE_REMOTE and TLD_ENVIRONMENT."""
import json

import pytest

import hooks_helpers as hh
from hooks_helpers import claude_adapter as ca, make_repo

PROFILE = hh.PROFILE + "runtime:\n  environments: [TLD]\n"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.delenv("TLD_ENVIRONMENT", raising=False)


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path / "r", "feature/x", profile=PROFILE)


def _start(repo):
    return {"session_id": "s1", "cwd": str(repo), "hook_event_name": "SessionStart"}


def _prompt(repo, text="/tld:board"):
    return {"session_id": "s1", "cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": text}


def test_env_check_session_start_warns_with_a_system_message_only(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    r = hh.run("env-check", _start(repo), project=repo)
    out = json.loads(r.stdout)
    assert r.code == 0 and out["systemMessage"].startswith("tld env-check: ") and "hookSpecificOutput" not in out


def test_env_check_prompt_warns_and_names_the_environment(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setenv("TLD_ENVIRONMENT", "Default")
    r = hh.run("env-check", _prompt(repo), project=repo)
    out = json.loads(r.stdout)
    assert r.code == 0 and "Default" in out["systemMessage"] and "hookSpecificOutput" not in out


def test_env_check_a_prompt_that_starts_no_command_is_silent(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    r = hh.run("env-check", _prompt(repo, "hello"), project=repo)
    assert r.code == 0 and r.stdout == ""


@pytest.mark.parametrize("value", [None, "1", "false"])
def test_env_check_only_the_word_true_means_remote(repo, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("CLAUDE_CODE_REMOTE", value)
    assert ca.to_action(_start(repo), str(repo)).remote is False
    r = hh.run("env-check", _prompt(repo), project=repo)
    assert r.code == 0 and r.stdout == ""


def test_env_check_a_listed_name_is_silent(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setenv("TLD_ENVIRONMENT", "TLD")
    r = hh.run("env-check", _prompt(repo), project=repo)
    assert r.code == 0 and r.stdout == ""


def test_env_check_an_empty_variable_is_no_name(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setenv("TLD_ENVIRONMENT", "")
    assert ca.to_action(_start(repo), str(repo)).runtime_environment is None


def test_env_check_the_real_script_warns(repo):
    r = hh.run_script("env-check", _prompt(repo), project=repo,
                      extra_env={"CLAUDE_CODE_REMOTE": "true", "TLD_ENVIRONMENT": "Default"})
    assert r.returncode == 0 and "systemMessage" in json.loads(r.stdout)
