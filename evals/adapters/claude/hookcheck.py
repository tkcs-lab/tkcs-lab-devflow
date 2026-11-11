"""Feed PreToolUse hook scripts directly (no model call): a free, deterministic layer under the guardrail tasks.

Protocol (https://code.claude.com/docs/en/hooks, checked 2.1.322): JSON on stdin with tool_name and tool_input;
exit 2 blocks (stderr is the reason); exit 0 may print {"hookSpecificOutput": {"permissionDecision": "deny"|...}}.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

from evals.harness.common import EVALS, ROOT

CLAUDE = ROOT / "adapters" / "claude"

HOOKS_JSON = CLAUDE / "hooks" / "hooks.json"
CASES = EVALS / "adapters" / "claude" / "hook_cases.yaml"


def load_cases(path: Path = CASES) -> list[dict]:
    return yaml.safe_load(path.read_text())["cases"]


def matcher_matches(matcher: str | None, tool: str) -> bool:
    """Claude Code's matcher rule (2.1.322): a plain `A|B` list of names compares each name for equality;
    anything else is an unanchored regex search; an empty matcher or `*` matches every tool."""
    if not matcher or matcher == "*":
        return True
    if re.fullmatch(r"[a-zA-Z0-9_|]+", matcher):
        return tool in matcher.split("|")
    return re.search(matcher, tool) is not None


def pretooluse_hooks(hooks_json: Path, tool_name: str) -> list[dict]:
    data = json.loads(hooks_json.read_text())
    out = []
    for group in data.get("hooks", {}).get("PreToolUse", []):
        if matcher_matches(group.get("matcher", ""), tool_name):
            out += [h for h in group.get("hooks", []) if h.get("type", "command") == "command"]
    return out


def decide(hooks_json: Path, tool_name: str, tool_input: dict, cwd: Path, timeout_s: int = 30) -> tuple[str, str]:
    """('deny' | 'allow', reason): deny when any matching hook blocks (exit 2 or a deny decision)."""
    root = hooks_json.parents[3]  # <plugin root>/adapters/claude/hooks/hooks.json
    payload = json.dumps({"session_id": "eval", "cwd": str(cwd), "hook_event_name": "PreToolUse",
                          "tool_name": tool_name, "tool_input": tool_input, "tool_use_id": "toolu_eval"})
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PROJECT_DIR": str(cwd)}
    for hook in pretooluse_hooks(hooks_json, tool_name):
        cmd = [hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(root))] if not hook.get("args") else \
            [hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(root)),
             *[a.replace("${CLAUDE_PLUGIN_ROOT}", str(root)) for a in hook["args"]]]
        p = subprocess.run(cmd if hook.get("args") else cmd[0], shell=not hook.get("args"), input=payload, cwd=cwd,
                           env=env, capture_output=True, text=True, timeout=hook.get("timeout", timeout_s))
        if p.returncode == 2:
            return "deny", p.stderr.strip()
        if p.returncode == 0 and p.stdout.strip().startswith("{"):
            try:
                spec = json.loads(p.stdout).get("hookSpecificOutput", {})
            except json.JSONDecodeError:
                continue
            if spec.get("permissionDecision") == "deny":
                return "deny", spec.get("permissionDecisionReason", "")
    return "allow", ""
