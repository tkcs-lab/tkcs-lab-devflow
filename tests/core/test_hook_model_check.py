"""model-check (session_start, UserPromptSubmit): one notice when a tld command starts in a strong session."""
import pytest

import hooks_helpers as hh
from hooks_helpers import make_repo, make_repo_with_origin
from tld.guard import _common, model_check
from tld.guard.action import Action

PREFIX = "tld model-check: this session runs at the strong level"


@pytest.fixture()
def repo(tmp_path):
    return make_repo(tmp_path / "repo", "feature/demo")


def decide(action):
    return _common.run_guard("model-check", model_check.evaluate, False, action)


def prompt(repo, invoked="implement", level=None, cmd_level=None, sid="s1"):
    return decide(Action("prompt", str(repo), str(repo), prompt="/tld:" + str(invoked), invoked=invoked,
                         session_id=sid, session_level=level, command_level=cmd_level))


def start(repo, level, sid="s1"):
    return decide(Action("session_start", str(repo), str(repo), session_id=sid, session_level=level))


def test_warns_when_the_session_is_strong_and_the_command_is_not(repo):
    d = prompt(repo, level="strong", cmd_level="standard")
    assert d.verdict == "allow" and d.notice.startswith(PREFIX)
    assert d.notice.count(PREFIX) == 1 and "/tld:implement" in d.notice and "standard level" in d.notice
    assert d.context is None


def test_silent_when_the_command_is_strong(repo):
    assert prompt(repo, level="strong", cmd_level="strong").notice is None


def test_silent_when_the_session_level_is_unknown(repo):
    assert prompt(repo, level=None, cmd_level="fast").notice is None
    assert prompt(repo, level="standard", cmd_level="fast").notice is None


def test_silent_without_an_invoked_command(repo):
    assert prompt(repo, invoked=None, level="strong").notice is None


def test_session_start_stores_the_level_and_a_later_prompt_uses_it(repo):
    d = start(repo, "strong")
    assert d.verdict == "allow" and d.notice is None
    assert prompt(repo, level=None, cmd_level="fast").notice.startswith(PREFIX)
    assert "fast level" in prompt(repo, cmd_level="fast").notice
    assert prompt(repo, cmd_level="fast", sid="other").notice is None


def test_the_prompt_level_wins_over_the_stored_one(repo):
    start(repo, "strong")
    assert prompt(repo, level="standard", cmd_level="fast").notice is None


def test_hooks_disable_switches_it_off(tmp_path):
    text = hh.PROFILE + "hooks:\n  disable: [model-check]\n"
    repo = make_repo_with_origin(tmp_path / "r", committed=text, working=text)
    d = prompt(repo, level="strong", cmd_level="standard")
    assert d.verdict == "allow" and d.notice is None


def test_a_missing_or_corrupt_session_file_is_silent(repo):
    assert prompt(repo, cmd_level="fast").notice is None
    start(repo, "strong")
    model_check.session_file(str(repo), "s1").write_text("{not json")
    assert prompt(repo, cmd_level="fast").notice is None
    model_check.session_file(str(repo), "s1").write_text("[1]")
    assert prompt(repo, cmd_level="fast").notice is None
    assert start(repo, None).notice is None


def test_other_kinds_are_silent(repo):
    d = decide(Action("shell", str(repo), str(repo), command="ls", session_id="s1"))
    assert d.verdict == "allow" and d.notice is None


def test_the_notice_names_no_model():
    import re
    assert not re.search("opus|sonnet|haiku", model_check.NOTICE, re.I)


def test_a_malformed_disable_list_never_denies(tmp_path):
    text = hh.PROFILE + "hooks:\n  disable: model-check\n"
    repo = make_repo_with_origin(tmp_path / "r", committed=text, working=text)
    d = prompt(repo, level="strong", cmd_level="standard")
    assert d.verdict == "allow" and d.notice is None
