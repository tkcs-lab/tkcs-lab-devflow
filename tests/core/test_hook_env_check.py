"""env-check (session_start, prompt): a warning when a cloud session runs in an environment the profile does not list."""
import pytest
import yaml

import hooks_helpers as hh
from hooks_helpers import make_repo, make_repo_with_origin
from tld.guard import _common, env_check
from tld.guard.action import Action

PROFILE = hh.PROFILE + "runtime:\n  environments: [TLD, TLD Swift]\n"
PREFIX = "tld env-check: this cloud session does not say"


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path / "repo", "feature/demo", profile=PROFILE)


def decide(action):
    return _common.run_guard("env-check", env_check.evaluate, False, action)


def prompt(repo, name=None, invoked="make-plan", remote=True):
    return decide(Action("prompt", str(repo), str(repo), prompt="/tld:x", invoked=invoked, session_id="s1",
                         remote=remote, runtime_environment=name))


def start(repo, name=None, remote=True):
    return decide(Action("session_start", str(repo), str(repo), session_id="s1", remote=remote,
                         runtime_environment=name))


def silent(d):
    assert d.verdict == "allow" and d.notice is None and d.context is None


def test_env_check_silent_when_not_remote(repo):
    silent(prompt(repo, "Default", remote=False))
    silent(start(repo, None, remote=False))


def test_env_check_silent_without_the_profile_key(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    silent(prompt(repo, "Default"))
    silent(start(repo, None))


@pytest.mark.parametrize("name", ["TLD", "  tld  ", "TLD SWIFT"])
def test_env_check_silent_when_the_name_is_listed(repo, name):
    silent(prompt(repo, name))
    silent(start(repo, name))


@pytest.mark.parametrize("make", [prompt, start])
def test_env_check_warns_when_the_name_is_unset(repo, make):
    d = make(repo, None)
    assert d.verdict == "allow" and d.context is None
    assert d.notice.startswith(PREFIX) and '"TLD" or "TLD Swift"' in d.notice


def test_env_check_warns_when_the_name_is_another(repo):
    d = prompt(repo, "Default")
    assert d.verdict == "allow" and d.context is None
    assert d.notice.startswith("tld env-check: ") and 'runs in the environment "Default"' in d.notice


def test_env_check_a_prompt_without_invoked_is_silent_but_the_start_warns(repo):
    silent(prompt(repo, "Default", invoked=None))
    assert start(repo, "Default").notice


def test_env_check_other_action_kinds_are_silent(repo):
    silent(decide(Action("shell", str(repo), str(repo), command="ls", remote=True, runtime_environment="Default")))
    silent(decide(Action("stop", str(repo), str(repo), session_id="s1", remote=True, runtime_environment="Default")))


def test_env_check_names_from_the_variable_are_cleaned_and_cut(repo):
    d = prompt(repo, "A\x1b[31mB\x9b‮" + "x" * 200)
    for bad in ("\x1b", "\x9b", "‮"):
        assert bad not in d.notice
    quoted = d.notice.split('environment "', 1)[1].split('", and', 1)[0]
    assert quoted.startswith("A[31mB") and len(quoted) == 100


def test_env_check_names_from_the_profile_are_cleaned_and_cut(tmp_path):
    text = hh.PROFILE + yaml.safe_dump({"runtime": {"environments": ["T\x1bLD" + "y" * 150]}})
    repo = make_repo(tmp_path / "r", "feature/demo", profile=text)
    d = prompt(repo, "Default")
    assert "\x1b" not in d.notice
    quoted = d.notice.split("profile expects \"", 1)[1].split('". If', 1)[0]
    assert quoted.startswith("TLD") and len(quoted) <= 100


@pytest.mark.parametrize("runtime", ["runtime: TLD\n", "runtime:\n  environments: TLD\n", "runtime:\n  environments: []\n",
                                     "runtime:\n  environments: [3]\n", "runtime:\n  environments: [\"  \"]\n"])
def test_env_check_malformed_shapes_are_silent(tmp_path, runtime):
    repo = make_repo(tmp_path / "r", "feature/demo", profile=hh.PROFILE + runtime)
    silent(prompt(repo, "Default"))
    silent(start(repo, None))


def test_env_check_disable_switches_it_off(tmp_path):
    both = PROFILE + "hooks:\n  disable: [env-check]\n"
    off = make_repo_with_origin(tmp_path / "off", committed=both, working=both)
    silent(prompt(off, "Default"))
    on = make_repo_with_origin(tmp_path / "on", committed=PROFILE, working=PROFILE)
    assert prompt(on, "Default").notice


def test_env_check_a_malformed_disable_list_never_denies(tmp_path):
    text = PROFILE + "hooks:\n  disable: env-check\n"
    repo = make_repo_with_origin(tmp_path / "r", committed=text, working=text)
    assert prompt(repo, "Default").verdict != "deny"


def test_env_check_the_disable_lookup_runs_only_when_it_would_warn(repo, monkeypatch):
    calls = []

    def disabled(self, name):
        calls.append(name)
        return False

    monkeypatch.setattr(_common.Ctx, "disabled", disabled)
    silent(prompt(repo, "TLD"))
    assert calls == []
    assert prompt(repo, "Default").notice
    assert calls == ["env-check"]


def test_env_check_a_missing_profile_is_silent(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", profile=None)
    silent(prompt(repo, "Default"))
