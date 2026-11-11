"""The agent seam: anything with run(AgentRequest) -> AgentResult.

ClaudeCodeAgent drives a headless Claude Code session (real model calls, explicit command only).
StubAgent replays canned outputs and is what pytest uses.

Headless flags checked against Claude Code 2.1.322 (`claude --help`, a live probe, and
https://code.claude.com/docs/en/headless and /hooks): -p, --output-format stream-json (needs --verbose),
--plugin-dir, --max-budget-usd, --permission-mode, --allowedTools, --disallowedTools, --strict-mcp-config,
--setting-sources, --no-session-persistence, --model. `--bare` is NOT used: it skips the hooks of
plugins loaded with --plugin-dir, which the guardrail tasks need.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

from .common import git
from .model import AgentRequest, AgentResult

CHECKED_AGAINST = "2.1.322"
ALLOWED_TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "Skill", "Agent", "TodoWrite", "NotebookEdit"]
DENIED_TOOLS = ["WebFetch", "WebSearch"]
_KEEP_TOKEN_VARS = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}


class Agent(Protocol):
    name: str

    def run(self, req: AgentRequest) -> AgentResult: ...


class AgentError(RuntimeError):
    pass


_PROXY_VARS = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS",
               "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
_GIT_IDENTITY = {"GIT_AUTHOR_NAME": "devflow-evals", "GIT_COMMITTER_NAME": "devflow-evals",
                 "GIT_AUTHOR_EMAIL": "evals@example.invalid", "GIT_COMMITTER_EMAIL": "evals@example.invalid"}


def clean_env(home: Path | None = None, keep_proxy: bool = False) -> dict[str, str]:
    """The environment of the headless session: an empty HOME (no stored logins or config), no GitHub or cloud
    credentials, no proxy or session variables of the caller, so a stray push or API call cannot succeed."""
    env = {}
    for k, v in os.environ.items():
        up = k.upper()
        if k not in _KEEP_TOKEN_VARS and any(s in up for s in ("TOKEN", "SECRET", "PASSWORD", "AWS_", "GH_", "GITHUB")):
            continue
        if up in _PROXY_VARS and not keep_proxy:
            continue
        if up.startswith("CLAUDE_CODE_") and k != "CLAUDE_CODE_OAUTH_TOKEN" and not up.startswith(("CLAUDE_CODE_USE_", "CLAUDE_CODE_SKIP_")):
            continue
        env[k] = v
    if home is None:
        home = Path(tempfile.mkdtemp(prefix="evals-home-"))
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    for k, v in _GIT_IDENTITY.items():
        env.setdefault(k, v)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


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


def parse_stream(lines: list[str]) -> AgentResult:
    """Turn the stream-json output of one run into an AgentResult."""
    res = AgentResult()
    kept: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t in ("stream_event", "rate_limit_event", "autocompact_state", "active_goal"):
            continue
        if t == "system" and ev.get("subtype") == "init":
            res.model = ev.get("model", res.model)
            names = [p.get("name") for p in ev.get("plugins", [])]
            if ev.get("plugin_errors") or "devflow" not in names:
                res.error = f"plugin did not load: errors={ev.get('plugin_errors')} loaded={names}"
        if t == "assistant" and isinstance(ev.get("message"), dict):
            blocks = ev["message"].get("content")
            if isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        b.pop("signature", None)
        if t == "result":
            res.result_text = ev.get("result", "") or ""
            res.turns = int(ev.get("num_turns", 0) or 0)
            res.cost_usd = float(ev.get("total_cost_usd", 0.0) or 0.0)
            u = ev.get("usage", {}) or {}
            res.tokens = {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                          "cache_read": u.get("cache_read_input_tokens", 0),
                          "cache_creation": u.get("cache_creation_input_tokens", 0)}
            res.duration_s = float(ev.get("duration_ms", 0) or 0) / 1000
            if ev.get("subtype") == "error_max_budget_usd":
                res.aborted = "cost_ceiling"
            elif ev.get("is_error"):
                res.error = res.error or f"result error: {ev.get('subtype')}"
        kept.append(ev)
    res.transcript = kept
    return res


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
        proc = subprocess.Popen(cmd, cwd=req.workdir, env=clean_env(home=Path(req.workdir).parent / "home", keep_proxy=self.keep_proxy), stdin=subprocess.DEVNULL,
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


class StubAgent:
    """Replays canned outputs. `canned` is one dict or a list (one per repeat, the last one repeats).

    A canned entry: files {path: text}, branch (commit them on this branch and push), commit_message,
    delete_files [paths], result_text, transcript [events], turns, tokens, cost_usd, duration_s,
    model, exit_status, aborted, error.
    """
    name = "stub"

    def __init__(self, canned: dict | list[dict] | None = None, by_task: dict[str, dict | list[dict]] | None = None):
        self.canned = canned
        self.by_task = by_task or {}
        self.calls: list[AgentRequest] = []

    @classmethod
    def from_dir(cls, directory: Path) -> "StubAgent":
        by_task = {p.stem: json.loads(p.read_text()) for p in sorted(Path(directory).glob("*.json"))}
        return cls(by_task=by_task)

    def _entry(self, req: AgentRequest) -> dict:
        src = self.by_task.get(req.task_id, self.canned)
        if src is None:
            raise AgentError(f"stub agent has no canned output for task '{req.task_id}'")
        if isinstance(src, list):
            return src[min(req.repeat - 1, len(src) - 1)]
        return src

    def run(self, req: AgentRequest) -> AgentResult:
        self.calls.append(req)
        c = self._entry(req)
        wd = req.workdir
        for rel in c.get("delete_files", []):
            (wd / rel).unlink(missing_ok=True)
        for rel, text in c.get("files", {}).items():
            p = wd / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if c.get("branch"):
            git("checkout", "-q", "-b", c["branch"], cwd=wd)
            git("add", "-A", cwd=wd)
            git("commit", "-q", "-m", c.get("commit_message", "stub change"), cwd=wd)
            git("push", "-q", "origin", c["branch"], cwd=wd)
        res = AgentResult(
            exit_status=c.get("exit_status", 0), result_text=c.get("result_text", ""),
            transcript=c.get("transcript", []), turns=c.get("turns", 1),
            cost_usd=c.get("cost_usd", 0.0), duration_s=c.get("duration_s", 0.0),
            model=c.get("model", "stub"), aborted=c.get("aborted"), error=c.get("error"),
        )
        res.tokens = {**res.tokens, **c.get("tokens", {})}
        return res
