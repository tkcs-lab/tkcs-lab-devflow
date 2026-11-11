"""The Claude Code adapter of the eval harness: the headless command, its environment, the stream-json parser and
its mapping onto the neutral action log. No model call: the agent refuses to run under pytest."""
import json
import os

import pytest
from evals_support import bash

from evals.adapters import claude as claude_adapter
from evals.adapters.claude.runner import ClaudeCodeAgent, build_command, clean_env
from evals.adapters.claude.stream import parse_stream, to_actions, tool_calls
from evals.harness.actions import KINDS
from evals.harness.agents import AgentError, adapter
from evals.harness.model import AgentRequest


def stream_bash(cmd, is_error=False, call_id="t1"):
    """A Bash tool call and its result, as stream-json events."""
    evs = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": cmd}}]}}]
    if is_error is not None:
        evs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "is_error": is_error, "content": "x"}]}})
    return evs


def tool_use(name, inp, call_id, is_error=True, content="denied"):
    return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": inp}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "is_error": is_error,
                                                      "content": [{"type": "text", "text": content}]}]}}]


def test_the_core_finds_the_adapter_by_name():
    assert adapter("claude") is claude_adapter and claude_adapter.Agent is ClaudeCodeAgent
    with pytest.raises(KeyError):
        adapter("nope")


def test_real_agent_refuses_under_pytest():
    assert os.environ.get("PYTEST_CURRENT_TEST")
    with pytest.raises(AgentError, match="never run under pytest"):
        ClaudeCodeAgent().run(AgentRequest(workdir=os.getcwd(), prompt="x", plugin_dirs=[], model=None, timeout_s=10, max_budget_usd=1))


def test_build_command_flags(tmp_path):
    cmd = build_command(AgentRequest(tmp_path, "/tld:dod", [tmp_path / "p"], "haiku", 60, 0.5))
    assert cmd[:3] == ["claude", "-p", "/tld:dod"]
    for flag in ("--output-format", "stream-json", "--verbose", "--plugin-dir", "--max-budget-usd", "--strict-mcp-config",
                 "--no-session-persistence", "--permission-mode", "dontAsk", "--setting-sources"):
        assert flag in cmd
    assert cmd[cmd.index("--max-budget-usd") + 1] == "0.5000" and cmd[cmd.index("--model") + 1] == "haiku"
    assert "--bare" not in cmd  # --bare skips plugin hooks


def test_clean_env_drops_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep")
    monkeypatch.setenv("NPM_TOKEN", "x")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep")
    env = clean_env()
    assert "GITHUB_TOKEN" not in env and "AWS_SECRET_ACCESS_KEY" not in env and env["ANTHROPIC_API_KEY"] == "keep"
    assert "NPM_TOKEN" not in env and "GH_ENTERPRISE_TOKEN" not in env and env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep"


def test_clean_env_isolates_home_and_network(monkeypatch, tmp_path):
    for k in ("HTTPS_PROXY", "https_proxy", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_EMAIL", "SSL_CERT_FILE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    env = clean_env()
    assert env["HOME"] != os.environ["HOME"]
    for k in ("HTTPS_PROXY", "https_proxy", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_EMAIL", "SSL_CERT_FILE"):
        assert k not in env
    assert env["ANTHROPIC_API_KEY"] == "keep" and env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep"
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["GIT_AUTHOR_NAME"] and env["GIT_COMMITTER_EMAIL"]
    home = tmp_path / "h"
    assert clean_env(home=home)["HOME"] == str(home)
    kept = clean_env(keep_proxy=True)
    assert kept["HTTPS_PROXY"] == "x" and kept["SSL_CERT_FILE"] == "x"


def test_parse_stream_extracts_metrics():
    lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "m1", "plugins": [{"name": "tld"}]}),
        json.dumps({"type": "stream_event", "event": {}}),
        "not json",
        json.dumps({"type": "result", "subtype": "success", "result": "hi", "num_turns": 4, "total_cost_usd": 0.12,
                    "duration_ms": 2500, "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
                                                   "cache_creation_input_tokens": 4}}),
    ]
    res = parse_stream(lines)
    assert (res.model, res.turns, res.cost_usd, res.duration_s, res.result_text) == ("m1", 4, 0.12, 2.5, "hi")
    assert res.tokens == {"input": 1, "output": 2, "cache_read": 3, "cache_creation": 4} and res.error is None
    assert len(res.transcript) == 2


def test_parse_stream_flags_budget_stop_and_missing_plugin():
    res = parse_stream([json.dumps({"type": "system", "subtype": "init", "plugins": [], "plugin_errors": [{"message": "x"}]}),
                        json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True})])
    assert res.aborted == "cost_ceiling" and "plugin did not load" in res.error


def test_missing_plugin_is_an_error():
    res = parse_stream([json.dumps({"type": "system", "subtype": "init", "plugins": [{"name": "other"}]})])
    assert "plugin did not load" in res.error


def test_run_requires_a_credential(monkeypatch, capsys):
    from evals.harness import cli
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(claude_adapter.Agent, "run", lambda *a, **k: pytest.fail("model called"))
    assert cli.main(["run", "--task", "make-plan-large"]) == 2
    assert "set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN" in capsys.readouterr().err
    assert cli.main(["run", "--task", "make-plan-large", "--dry-run"]) == 0


def test_tool_calls_pairs_results():
    calls = tool_calls(stream_bash("git status", is_error=True) + stream_bash("ls", is_error=None, call_id="t2"))
    assert [(c["name"], c["is_error"]) for c in calls] == [("Bash", True), ("Bash", None)]


def test_to_actions_maps_every_tool_kind():
    events = (tool_use("Bash", {"command": "git push origin main"}, "a")
              + tool_use("Write", {"file_path": ".env", "content": "X=1"}, "b", is_error=False, content="ok")
              + tool_use("MultiEdit", {"file_path": "a.py", "edits": [{"new_string": "p"}, {"new_string": "q"}]}, "c")
              + tool_use("Read", {"file_path": "README.md"}, "d", is_error=False)
              + tool_use("mcp__github__merge_pull_request", {"pullNumber": 3}, "e")
              + tool_use("TodoWrite", {"todos": []}, "f", is_error=False)
              + [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "g", "name": "Bash", "input": {"command": "ls"}}]}}])
    acts = to_actions(events)
    assert [a["kind"] for a in acts] == ["shell", "write", "write", "read", "github_op", "other", "shell"]
    assert {a["kind"] for a in acts} <= set(KINDS)
    assert acts[0]["command"] == "git push origin main" and acts[0]["error"] is True and acts[0]["output"] == "denied"
    assert acts[1]["path"] == ".env" and acts[1]["content"] == "X=1" and acts[1]["error"] is False
    assert acts[2]["content"] == "p\nq"
    assert acts[4]["op"] == "merge_pull_request" and acts[4]["args"] == {"pullNumber": 3}
    assert acts[6]["error"] is None


def test_parse_stream_fills_the_action_log():
    res = parse_stream([json.dumps(ev) for ev in stream_bash("git tag v1", is_error=True)])
    assert res.actions == to_actions(res.transcript) and res.actions[0]["kind"] == "shell"


def test_graders_see_the_same_thing_from_a_transcript_and_from_canned_actions():
    from evals.harness.graders import forbidden_calls
    from_stream = to_actions(stream_bash("git push --force origin main", is_error=True))
    canned = bash("git push --force origin main", is_error=True)
    assert [o for _, o in forbidden_calls(from_stream)] == [o for _, o in forbidden_calls(canned)] == [{"force-push", "merge"}]


def test_command_model_reads_the_front_matter():
    assert claude_adapter.command_model("/tld:review") == "opus"
    assert claude_adapter.command_model("/tld:dod") is None and claude_adapter.command_model(None) is None
    assert set(claude_adapter.command_files()) >= {"dod", "implement", "land", "deps", "upstream", "docs", "board"}
