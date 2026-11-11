"""Claude Code adapter of the tld guards: hook event JSON -> tld.guard Action -> exit code and message.

Contract with Claude Code: the event JSON arrives on stdin; exit 0 allows (stdout may carry a
`systemMessage` shown to the user); exit 2 blocks and the stderr text goes back to the agent; any other
exit code is a non-blocking error that only the user sees. Everything Claude-specific lives here: tool
names, `mcp__` tool ids, CLAUDE_PROJECT_DIR, CLAUDE_PLUGIN_ROOT, stop_hook_active and the .claude/ files.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tld.guard import _common  # noqa: E402
from tld.guard.action import Action, Decision, Settings  # noqa: E402

# hook name -> (core module, fail closed)
GUARDS = {"no-merge": ("tld.guard.no_merge", True), "no-force-push": ("tld.guard.no_force_push", True),
          "no-git-tag": ("tld.guard.no_git_tag", True), "secret-scan": ("tld.guard.secret_scan", False),
          "protect-paths": ("tld.guard.protect_paths", False), "dod-gate": ("tld.dod.gate", False)}
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
# Claude Code's own configuration: a session that edits it could switch the hooks off.
PROTECTED = ("~/.claude/**", ".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/**", ".mcp.json")


class Result(NamedTuple):
    code: int
    stderr: str = ""
    stdout: str = ""


def settings() -> Settings:
    return Settings(extra_protected=PROTECTED, plugin_root=os.environ.get("CLAUDE_PLUGIN_ROOT") or None,
                    project_hint=os.environ.get("CLAUDE_PROJECT_DIR") or None)


def _content(tool: str, ti: dict) -> tuple[tuple[str, str], ...]:
    if tool == "Write":
        pieces = [("the new file content", ti.get("content"))]
    elif tool == "Edit":
        pieces = [("the new text", ti.get("new_string"))]
    elif tool == "MultiEdit":
        edits = ti.get("edits") if isinstance(ti.get("edits"), list) else []
        pieces = [(f"the new text of edit {k}", e.get("new_string")) for k, e in enumerate(edits, 1) if isinstance(e, dict)]
    else:
        pieces = [("the new cell source", ti.get("new_source"))]
    return tuple((w, t) for w, t in pieces if isinstance(t, str) and t)


def to_action(payload: dict, project_dir: str | None = None) -> Action | None:
    """The Action a hook event stands for, or None when the guards have nothing to check."""
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
    project = project_dir or _common.find_project(cwd, os.environ.get("CLAUDE_PROJECT_DIR") or None)[0]
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    tool = str(payload.get("tool_name") or "")
    if payload.get("hook_event_name") == "Stop" or (not tool and "stop_hook_active" in payload):
        sid = payload.get("session_id")
        return Action("stop", project, cwd, session_id=None if sid is None else str(sid),
                      continuing=bool(payload.get("stop_hook_active")))
    if tool == "Bash":
        command = ti.get("command")
        return Action("shell", project, cwd, command=command) if isinstance(command, str) else None
    if tool in WRITE_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path")
        return Action("write", project, cwd, path=path if isinstance(path, str) and path else None,
                      content=_content(tool, ti))
    if tool.startswith("mcp__") and "__" in tool[5:]:
        return Action("github_op", project, cwd, op=tool.rsplit("__", 1)[-1], args=dict(ti))
    return None


def to_result(decision: Decision) -> Result:
    if decision.verdict == "deny":
        return Result(2, decision.reason)
    if decision.verdict == "error":
        return Result(1, decision.reason)
    return Result(0, "", json.dumps({"systemMessage": decision.notice}) if decision.notice else "")


def decide(name: str, payload: dict) -> Decision:
    module, fail_closed = GUARDS[name]
    mod = importlib.import_module(module)
    action = to_action(payload)
    if action is None:
        return Decision("allow")
    return _common.run_guard(name, mod.evaluate, fail_closed, action, settings())


def execute(name: str, stdin_text: str) -> Result:
    fail_closed = GUARDS[name][1]
    try:
        payload = json.loads(stdin_text)
        if not isinstance(payload, dict):
            raise ValueError("the event is not a JSON object")
    except ValueError as exc:
        return to_result(_common.problem(name, fail_closed, f"cannot read the hook event ({exc})."))
    try:
        return to_result(decide(name, payload))
    except Exception as exc:  # noqa: BLE001 - loading the guard failed
        return to_result(_common.problem(name, fail_closed, f"internal error while loading ({type(exc).__name__}: {exc})."))


def main(name: str) -> None:
    if len(sys.argv) > 1:  # the old flag forms (`dod_gate.py --exempt`) still reach the core command line
        module = importlib.import_module(GUARDS[name][0])
        sys.exit(module.cli(sys.argv[1:]) if hasattr(module, "cli") else 2)
    result = execute(name, sys.stdin.read())
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    sys.exit(result.code)
