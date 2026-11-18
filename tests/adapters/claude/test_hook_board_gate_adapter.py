"""board-gate through the Claude adapter: PostToolUse payloads become tool_result actions, the script blocks once."""
import json

import pytest

from hooks_helpers import PROFILE, claude_adapter, make_repo_with_origin, run_script
from tld.guard import board_gate

ON = PROFILE + "hooks:\n  board_gate:\n    enabled: true\n"
MCP_SET = "mcp__plugin_tld_tld-board__board_set"


def post(tool, cwd, response=None, **tool_input):
    payload = {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "PostToolUse", "tool_name": tool,
               "tool_input": tool_input}
    if response is not None:
        payload["tool_response"] = response
    return payload


def prompt(cwd, text):
    return {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "UserPromptSubmit", "prompt": text}


def stop(cwd, active=False):
    return {"session_id": "s1", "cwd": str(cwd), "hook_event_name": "Stop", "stop_hook_active": active}


def test_bash_result_becomes_a_tool_result_action(tmp_path):
    a = claude_adapter.to_action(post("Bash", tmp_path, "done\n", command="ls"), str(tmp_path))
    assert (a.kind, a.command, a.output, a.session_id) == ("tool_result", "ls", "done\n", "s1")


def test_board_set_result_becomes_a_tool_result_action(tmp_path):
    response = {"content": [{"type": "text", "text": '{"id":"x","version":2}'}]}
    a = claude_adapter.to_action(post(MCP_SET, tmp_path, response, id="x"), str(tmp_path))
    assert (a.kind, a.op, a.command, a.args, a.output) == ("tool_result", "board_set", None, {"id": "x"},
                                                           '{"id":"x","version":2}')


def test_missing_tool_response_gives_empty_output(tmp_path):
    assert claude_adapter.to_action(post("Bash", tmp_path, command="ls"), str(tmp_path)).output == ""


def test_other_tools_give_no_action(tmp_path):
    for tool in ("Read", "mcp__github__push_files", "mcp__plugin_tld_tld-board__board_get"):
        assert claude_adapter.to_action(post(tool, tmp_path, "x", file_path="f"), str(tmp_path)) is None


@pytest.mark.parametrize("response, text", [
    ("plain", "plain"), ({"stdout": "o\n", "stderr": "e"}, "o\n"), ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "a\nb"),
    ({"content": [{"type": "image"}, {"type": "text", "text": "t"}]}, "t"), (None, ""), (3, ""), ({"stdout": 1}, ""),
])
def test_result_text(response, text):
    assert claude_adapter._result_text(response) == text


def test_record_commands_are_known_commands():
    assert set(board_gate.RECORD_COMMANDS) <= claude_adapter.known_commands()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    return make_repo_with_origin(tmp_path / "repo", "feature/demo", ON)


def test_prompt_then_board_set_then_stop_allows(repo):
    assert run_script("board-gate", prompt(repo, "/tld:docs init x")).returncode == 0
    r = run_script("board-gate", post(MCP_SET, repo, {"content": [{"type": "text", "text": '{"id":"p--docs","version":1}'}]}))
    assert r.returncode == 0
    r = run_script("board-gate", stop(repo))
    assert (r.returncode, r.stderr) == (0, "")


def test_prompt_then_client_set_then_stop_allows(repo):
    run_script("board-gate", prompt(repo, "/tld:docs init x"))
    response = {"stdout": '{"id":"p--docs","version":2}\n', "stderr": "", "interrupted": False}
    run_script("board-gate", post("Bash", repo, response, command="tld board client set p--docs - --if-version 1"))
    r = run_script("board-gate", stop(repo))
    assert (r.returncode, r.stderr) == (0, "")


def test_prompt_then_failed_board_set_then_stop_blocks(repo):
    run_script("board-gate", prompt(repo, "/tld:docs init x"))
    run_script("board-gate", post(MCP_SET, repo, {"content": [{"type": "text", "text": '{"error":"version_conflict"}'}]}))
    r = run_script("board-gate", stop(repo))
    assert r.returncode == 2 and r.stderr.startswith("tld board-gate:"), r
    assert run_script("board-gate", stop(repo)).returncode == 0


def test_unknown_payload_exits_0_silently(repo):
    r = run_script("board-gate", {"session_id": "s1", "cwd": str(repo), "hook_event_name": "Notification"})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    r = run_script("board-gate", {}, project=repo, stdin=json.dumps({"cwd": str(repo)}))
    assert r.returncode == 0 and r.stderr == ""


def test_a_malformed_hooks_disable_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("TLD_BOARD_URL", "https://board.example")
    monkeypatch.setenv("TLD_BOARD_TOKEN", "t")
    repo = make_repo_with_origin(tmp_path / "repo", "feature/demo", ON + "  disable: board-gate\n")
    run_script("board-gate", prompt(repo, "/tld:docs init x"))
    assert run_script("board-gate", stop(repo)).returncode == 0


def mcp(text):
    return {"content": [{"type": "text", "text": text}]}


ASK = "mcp__plugin_tld_tld-board__board_ask"
NEW_TOOLS = [
    (ASK, "board_ask", {"file": "f.json"}, '{"id":"a-1f","state":"open"}'),
    ("ScheduleWakeup", "timer", {"delaySeconds": 600}, "scheduled"),
    ("CronCreate", "timer", {"cron": "* * * * *"}, "created"),
    ("mcp__claude-code-remote__send_later", "timer", {"message": "m", "delay_minutes": 10}, "ok"),
    ("mcp__claude-code-remote__create_trigger", "timer", {"name": "n"}, "ok"),
    ("mcp__github__add_issue_comment", "ask_comment", {"body": "<!-- tld-ask -->\nq"}, '{"id":1}'),
    ("mcp__github__issue_write", "ask_comment", {"body": "<!-- tld-ask -->\nq"}, '{"id":2}'),
    ("mcp__claude-code-remote__create_session", "worker_start", {"prompt": "p"}, '{"id":"session_1"}'),
    ("mcp__claude-code-remote__archive_session", "worker_stop", {"session_id": "session_1"}, "archived"),
    ("mcp__github__create_pull_request", "pr_create", {"title": "t"}, '{"number":3}'),
]


@pytest.mark.parametrize("tool, op, tool_input, text", NEW_TOOLS)
def test_new_tools_become_tool_result_actions(tmp_path, tool, op, tool_input, text):
    a = claude_adapter.to_action(post(tool, tmp_path, mcp(text), **tool_input), str(tmp_path))
    assert (a.kind, a.op, a.command, a.args, a.output, a.session_id) == ("tool_result", op, None, tool_input, text, "s1")


@pytest.mark.parametrize("flag", ["isError", "is_error"])
@pytest.mark.parametrize("tool", [MCP_SET] + [t[0] for t in NEW_TOOLS])
def test_a_failed_tool_response_gives_no_action(tmp_path, tool, flag):
    response = {"content": [{"type": "text", "text": "boom"}], flag: True}
    assert claude_adapter.to_action(post(tool, tmp_path, response, x="y"), str(tmp_path)) is None


@pytest.mark.parametrize("tool", ["CronDelete", "mcp__plugin_tld_tld-board__board_get"])
def test_near_miss_tools_give_no_action(tmp_path, tool):
    assert claude_adapter.to_action(post(tool, tmp_path, mcp("x"), id="x"), str(tmp_path)) is None


def blocked(repo, reason):
    r = run_script("board-gate", stop(repo))
    assert r.returncode == 2 and reason in r.stderr, r
    return r


def not_blocked(repo):
    r = run_script("board-gate", stop(repo))
    assert (r.returncode, r.stderr) == (0, ""), r


def test_ask_without_timer_blocks_until_a_timer_is_armed(repo):
    run_script("board-gate", prompt(repo, "/tld:make-plan x"))
    run_script("board-gate", post(ASK, repo, mcp('{"id":"a-1f"}'), file="f.json"))
    blocked(repo, "armed no timer")
    run_script("board-gate", post(ASK, repo, mcp('{"id":"a-2f"}'), file="g.json"))
    run_script("board-gate", post("mcp__claude-code-remote__send_later", repo, mcp("ok"), message="m"))
    r = run_script("board-gate", stop(repo))
    assert "armed no timer" not in r.stderr


def test_push_then_stop_blocks_until_a_board_set(repo):
    run_script("board-gate", prompt(repo, "/tld:make-plan x"))
    run_script("board-gate", post(MCP_SET, repo, mcp('{"id":"p","version":1}'), id="p"))
    not_blocked(repo)
    run_script("board-gate", post("Bash", repo, {"stdout": "pushed\n"}, command="git push origin x"))
    blocked(repo, "changed things")
    run_script("board-gate", post("Bash", repo, {"stdout": "pushed\n"}, command="git push origin x"))
    run_script("board-gate", post(MCP_SET, repo, mcp('{"id":"p","version":2}'), id="p"))
    not_blocked(repo)


def test_failed_board_set_changes_neither_rule(repo):
    run_script("board-gate", prompt(repo, "/tld:make-plan x"))
    run_script("board-gate", post(MCP_SET, repo, {**mcp("boom"), "isError": True}, id="p"))
    blocked(repo, "tld board-gate:")  # the first-record rule: nothing was written
    run_script("board-gate", post(MCP_SET, repo, mcp('{"id":"p","version":1}'), id="p"))
    run_script("board-gate", post("Bash", repo, {"stdout": "p\n"}, command="git push origin x"))
    run_script("board-gate", post(MCP_SET, repo, {**mcp("boom"), "is_error": True}, id="p"))
    blocked(repo, "changed things")  # the failed write did not clear the dirty rule


def test_failed_ask_is_not_counted_and_failed_timer_does_not_arm(repo):
    run_script("board-gate", prompt(repo, "/tld:make-plan x"))
    run_script("board-gate", post(ASK, repo, {**mcp('{"id":"a-1f"}'), "isError": True}, file="f.json"))
    run_script("board-gate", post(MCP_SET, repo, mcp('{"id":"p","version":1}'), id="p"))
    not_blocked(repo)
    run_script("board-gate", post(ASK, repo, mcp('{"id":"a-2f"}'), file="g.json"))
    run_script("board-gate", post("ScheduleWakeup", repo, {**mcp("no"), "isError": True}, delaySeconds=600))
    blocked(repo, "armed no timer")


@pytest.mark.parametrize("value", ["false", "no", 1, "true"])
@pytest.mark.parametrize("tool", [MCP_SET] + [t[0] for t in NEW_TOOLS])
def test_only_a_boolean_true_marks_a_response_failed(tmp_path, tool, value):
    response = {"content": [{"type": "text", "text": "x"}], "isError": value}
    assert claude_adapter.to_action(post(tool, tmp_path, response, x="y"), str(tmp_path)) is not None


def test_a_deeply_nested_event_is_a_hook_problem_not_a_crash():
    r = claude_adapter.execute("board-gate", "[" * 200000)
    assert r.code in (0, 1)
