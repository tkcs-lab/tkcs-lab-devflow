import pytest

from tld.guard import _common
from tld.guard.action import Action, Decision, allow


def test_prompt_is_an_action_kind(tmp_path):
    assert Action("prompt", str(tmp_path), str(tmp_path)).kind == "prompt"
    with pytest.raises(ValueError):
        Action("nonsense", str(tmp_path), str(tmp_path))


def test_prompt_action_carries_text_and_invoked(tmp_path):
    a = Action("prompt", str(tmp_path), str(tmp_path), session_id="s1", prompt="/tld:ask hi", invoked="ask")
    assert (a.prompt, a.invoked, a.session_id) == ("/tld:ask hi", "ask", "s1")
    assert Action("shell", str(tmp_path), str(tmp_path)).prompt is None


def test_decision_context_defaults_to_none():
    assert Decision("allow").context is None
    assert allow().context is None


def test_allow_carries_context():
    d = allow("n", "c")
    assert (d.verdict, d.notice, d.context) == ("allow", "n", "c")


def test_run_guard_copies_ctx_context_into_the_decision(tmp_path):
    def evaluate(ctx):
        ctx.context = "hello"
        return None

    d = _common.run_guard("x", evaluate, False, Action("prompt", str(tmp_path), str(tmp_path), prompt="hi"))
    assert d.verdict == "allow"
    assert d.context == "hello"


def test_run_guard_deny_has_no_context(tmp_path):
    def evaluate(ctx):
        ctx.context = "hello"
        return "no"

    d = _common.run_guard("x", evaluate, False, Action("prompt", str(tmp_path), str(tmp_path), prompt="hi"))
    assert d.verdict == "deny"
    assert d.context is None
