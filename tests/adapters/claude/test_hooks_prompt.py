"""The Claude adapter's UserPromptSubmit support: command detection, the prompt Action, the prompt result."""
import json

from hooks_helpers import claude_adapter as ca, event

from tld.guard.action import Decision


def test_known_commands_lists_commands_and_skills():
    names = ca.known_commands()
    assert {"make-plan", "git-ops", "runtime"} <= names


def test_invoked_command_reads_the_typed_line():
    assert ca.invoked_command("/tld:make-plan x") == "make-plan"
    assert ca.invoked_command("/make-plan") == "make-plan"
    assert ca.invoked_command("  /tld:git-ops hi") == "git-ops"
    assert ca.invoked_command("please /tld:make-plan") is None
    assert ca.invoked_command("/tld:nope") is None
    assert ca.invoked_command("make-plan") is None


def test_prompt_event_becomes_a_prompt_action(tmp_path):
    payload = {"session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit",
               "prompt": "/tld:make-plan x"}
    action = ca.to_action(payload, str(tmp_path))
    assert (action.kind, action.prompt, action.invoked, action.session_id) == ("prompt", "/tld:make-plan x", "make-plan", "s1")
    assert ca.to_action({**payload, "prompt": 5}, str(tmp_path)) is None
    assert ca.to_action({k: v for k, v in payload.items() if k != "session_id"}, str(tmp_path)).session_id is None


def test_tool_events_carry_the_session_id(tmp_path):
    for tool, args in (("Bash", {"command": "ls"}), ("Write", {"file_path": "a", "content": "x"}),
                       ("mcp__github__push_files", {})):
        assert ca.to_action(event(tool, tmp_path, **args), str(tmp_path)).session_id == "s1"


def test_prompt_result_never_exits_nonzero():
    for decision in (Decision("deny", "no"), Decision("error", "broken")):
        r = ca.to_result(decision, prompt=True)
        assert r.code == 0 and r.stderr == ""
        assert json.loads(r.stdout) == {"systemMessage": decision.reason}


def test_prompt_result_renders_additional_context():
    r = ca.to_result(Decision("allow", "", "heads up", "CTX"), prompt=True)
    assert r.code == 0
    assert json.loads(r.stdout) == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "CTX"},
                                    "systemMessage": "heads up"}
    only_ctx = json.loads(ca.to_result(Decision("allow", "", None, "CTX"), prompt=True).stdout)
    assert "systemMessage" not in only_ctx
    only_notice = json.loads(ca.to_result(Decision("allow", "", "n"), prompt=True).stdout)
    assert only_notice == {"systemMessage": "n"}
    assert ca.to_result(Decision("allow"), prompt=True) == ca.Result(0)


def test_non_prompt_to_result_is_unchanged():
    assert ca.to_result(Decision("deny", "no")) == ca.Result(2, "no")
    assert ca.to_result(Decision("error", "bad")) == ca.Result(1, "bad")
    assert ca.to_result(Decision("allow", "", "n", "CTX")) == ca.Result(0, "", json.dumps({"systemMessage": "n"}))
    assert ca.to_result(Decision("allow")) == ca.Result(0, "", "")
