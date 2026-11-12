"""The Claude adapter's UserPromptSubmit support: command detection, the prompt Action, the prompt result."""
import json
import subprocess
import sys

import hooks_helpers as hh
from hooks_helpers import HOOKS, claude_adapter as ca, event, make_repo

from tld.guard.action import Decision

# The shape in which a client delivered /tld:make-plan to the hook: reminders, then the expanded command.
EXPANDED_PROMPT = ("<system-reminder>\nx\n</system-reminder>\n<system-reminder>\ny\n</system-reminder>\n"
                   "<command-message>tld:make-plan</command-message>\n<command-name>/tld:make-plan</command-name>\n"
                   "<command-args>a\nb</command-args>")


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


def test_expanded_command_with_reminders_is_invoked():
    assert ca.invoked_command(EXPANDED_PROMPT) == "make-plan"


def test_expanded_command_without_message_is_invoked():
    assert ca.invoked_command("<command-name>/tld:make-plan</command-name>") == "make-plan"
    assert ca.invoked_command("<command-name>/make-plan</command-name>") == "make-plan"


def test_reminder_then_typed_slash_command_is_invoked():
    assert ca.invoked_command("<system-reminder>x</system-reminder>/tld:make-plan a") == "make-plan"


def test_command_name_later_in_the_text_is_not_invoked():
    assert ca.invoked_command("hello <command-name>/tld:make-plan</command-name>") is None


def test_unknown_expanded_command_is_none():
    assert ca.invoked_command("<command-name>/tld:nope</command-name>") is None


def test_command_name_inside_a_reminder_is_not_invoked():
    assert ca.invoked_command("<system-reminder>x <command-name>/tld:make-plan</command-name></system-reminder>hello") is None
    assert ca.invoked_command("<system-reminder>x<command-name>/tld:make-plan</command-name>") is None


def test_reminder_then_prose_is_not_invoked():
    assert ca.invoked_command("<system-reminder>x</system-reminder>please /tld:make-plan") is None


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


# ---- end to end through execute("plan-gate", ...) ------------------------------------------------
ON = hh.PROFILE + "hooks:\n  plan_gate:\n    enabled: true\n"


def prompt_event(cwd, text, sid="s1"):
    return {"session_id": sid, "cwd": str(cwd), "hook_event_name": "UserPromptSubmit", "prompt": text}


def gate(repo, payload):
    return hh.run("plan-gate", payload, project=repo)


def test_plain_prompt_returns_context_json(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    r = gate(repo, prompt_event(repo, "add a comment to README.md"))
    assert r.code == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit" and "/tld:make-plan" in out["additionalContext"]


def test_opening_prompt_opens_then_write_is_allowed(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    write = event("Write", repo, file_path=str(repo / "a.txt"), content="x")
    assert gate(repo, write).code == 2
    assert gate(repo, prompt_event(repo, "/tld:make-plan add a thing")) == ca.Result(0)
    assert gate(repo, write).code == 0


def test_expanded_prompt_opens_then_write_is_allowed(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    write = event("Write", repo, file_path=str(repo / "a.txt"), content="x")
    assert gate(repo, write).code == 2
    assert gate(repo, prompt_event(repo, EXPANDED_PROMPT)) == ca.Result(0)
    assert gate(repo, write).code == 0


def test_write_in_a_closed_session_exits_2_with_the_deny_text(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    r = gate(repo, event("Write", repo, file_path=str(repo / "a.txt"), content="x"))
    assert r.code == 2 and "blocked:" in r.stderr + r.stdout and "/tld:make-plan" in r.stderr + r.stdout


def test_script_runs_as_a_subprocess(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo", ON)
    import os
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    r = subprocess.run([sys.executable, str(HOOKS / "plan_gate.py")], input=json.dumps(prompt_event(repo, "hello")),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "additionalContext" in r.stdout


def test_gate_off_prints_nothing(tmp_path):
    repo = make_repo(tmp_path / "r", "feature/demo")
    assert gate(repo, prompt_event(repo, "hello")) == ca.Result(0)
    assert gate(repo, event("Write", repo, file_path=str(repo / "a.txt"), content="x")) == ca.Result(0)
