"""ClaudeCodeAgent drives a headless Claude Code session (real model calls, an explicit command only).

Headless flags checked against Claude Code 2.1.322 (`claude --help`, a live probe, and
https://code.claude.com/docs/en/headless and /hooks): -p, --output-format stream-json (needs --verbose),
--plugin-dir, --max-budget-usd, --permission-mode, --allowedTools, --disallowedTools, --strict-mcp-config,
--setting-sources, --no-session-persistence, --model. `--bare` is NOT used: it skips the hooks of
plugins loaded with --plugin-dir, which the guardrail tasks need.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from evals.harness.agents import AgentError
from evals.harness.common import clean_env as _clean_env
from evals.harness.model import AgentRequest, AgentResult

from .stream import parse_stream

CHECKED_AGAINST = "2.1.322"
ALLOWED_TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill", "Agent", "TodoWrite", "NotebookEdit"]
DENIED_TOOLS = ["WebFetch", "WebSearch"]
_KEEP_TOKEN_VARS = frozenset({"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"})


def _session_var(key: str) -> bool:
    """The caller's own Claude Code session variables (not the provider switches CLAUDE_CODE_USE_*/SKIP_*)."""
    up = key.upper()
    return up.startswith("CLAUDE_CODE_") and not up.startswith(("CLAUDE_CODE_USE_", "CLAUDE_CODE_SKIP_"))


def clean_env(home: Path | None = None, keep_proxy: bool = False) -> dict[str, str]:
    """The environment of the headless session: the core's clean environment, the model credential kept, and
    none of the caller's Claude Code session variables."""
    return _clean_env(home, keep_proxy, keep=_KEEP_TOKEN_VARS, drop=_session_var)


def build_command(req: AgentRequest) -> list[str]:
    cmd = ["claude", "-p", req.prompt, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "dontAsk", "--allowedTools", *ALLOWED_TOOLS,
           "--disallowedTools", *DENIED_TOOLS,
           "--strict-mcp-config", "--setting-sources", "project,local", "--no-session-persistence",
           "--max-budget-usd", f"{req.max_budget_usd:.4f}"]
    for d in req.plugin_dirs:
        cmd += ["--plugin-dir", str(d)]
    if req.model:
        cmd += ["--model", req.model]
    return cmd


class ClaudeCodeAgent:
    name = "claude"

    def __init__(self, claude_bin: str = "claude", keep_proxy: bool = False):
        self.claude_bin = claude_bin
        self.keep_proxy = keep_proxy

    def run(self, req: AgentRequest) -> AgentResult:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            raise AgentError("ClaudeCodeAgent must never run under pytest: real model runs are an explicit command")
        cmd = build_command(req)
        cmd[0] = self.claude_bin
        start = time.monotonic()
        env = clean_env(home=Path(req.workdir).parent / "home", keep_proxy=self.keep_proxy)
        proc = subprocess.Popen(cmd, cwd=req.workdir, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=req.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
        res = parse_stream((out or "").splitlines())
        res.exit_status = proc.returncode
        wall = time.monotonic() - start
        res.duration_s = res.duration_s or wall
        if timed_out:
            res.aborted = "timeout"
        elif proc.returncode != 0 and not res.error and not res.aborted:
            res.error = f"claude exited {proc.returncode}: {(err or '').strip()[:300]}"
        return res
