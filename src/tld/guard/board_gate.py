"""board-gate (UserPromptSubmit, PostToolUse, Stop): a session that a record-writing tld command started cannot end
its turn before it has written its status record to the board once.

Opt-in (`hooks.board_gate.enabled: true`) and only when a board is configured. A prompt that starts a record-writing
command opens a per-session state file; a successful record write (the `board_set` tool or `tld board client set`)
marks it written; the first Stop without a write is blocked once. It is a nudge, not a control, and it never makes a
network call. See docs/architecture/hooks.md.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from tld.board import client
from tld.dod.gate import state_dir
from tld.guard._common import Ctx, ProfileError
from tld.guard.action import Action

NAME = "board-gate"
RECORD_COMMANDS = ("make-plan", "implement", "review", "setup", "migrate", "land", "deps", "upstream", "docs", "ci")
SESSION_TTL_SECONDS = 24 * 3600
CLIENT_SET = re.compile(r"\bboard\s+client\s+set\b")

MESSAGE = ('this session was started by /tld:{command} and has not written its status record to the board. '
           'Write it now: use the board_set tool, or when that tool is missing or fails run "tld board client set '
           '<id> - " with the record on stdin (the id comes from "tld board record-id"). If the board cannot be '
           'reached, say so in your final reply and stop. This check blocks only once.')


def enabled(ctx: Ctx) -> bool:
    gate = ctx.hooks_section().get("board_gate")
    if gate is None:
        return False
    if not isinstance(gate, dict):
        raise ProfileError("toolkit.yaml: 'hooks.board_gate' must be a mapping")
    value = gate.get("enabled", False)
    if not isinstance(value, bool):
        raise ProfileError("toolkit.yaml: 'hooks.board_gate.enabled' must be true or false")
    return value


def state_file(project: str, sid: object) -> Path:
    return state_dir(project) / "board-gate" / (hashlib.sha256(str(sid).encode()).hexdigest()[:16] + ".json")


def _load(path: Path) -> dict | None:
    """The state, or None when there is none, it is unreadable, malformed or older than the TTL."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    opened, command = data.get("opened_at"), data.get("command")
    if isinstance(opened, bool) or not isinstance(opened, (int, float)) or not isinstance(command, str):
        return None
    if time.time() - opened > SESSION_TTL_SECONDS:
        return None
    return {"command": command, "opened_at": opened, "written": data.get("written") is True,
            "blocked": data.get("blocked") is True}


def _save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def _is_record(text: str) -> bool:
    try:
        obj = json.loads(text)
    except ValueError:
        return False
    return (isinstance(obj, dict) and isinstance(obj.get("id"), str)
            and isinstance(obj.get("version"), int) and not isinstance(obj.get("version"), bool))


def is_record_write(action: Action) -> bool:
    """A record write that succeeded: the `board_set` tool, or `tld board client set`, answered `{"id", "version"}`."""
    if action.kind != "tool_result":
        return False
    output = action.output or ""
    if action.op == "board_set":
        return _is_record(output.strip())
    if action.command and CLIENT_SET.search(action.command):
        lines = [line.strip() for line in output.splitlines() if line.strip().startswith("{")]
        return bool(lines) and _is_record(lines[-1])
    return False


def evaluate(ctx: Ctx) -> str | None:
    try:
        return _evaluate(ctx)
    except ProfileError as exc:
        ctx.notice = str(exc)
        return None
    except Exception:  # noqa: BLE001 - a nudge fails open
        return None


def _evaluate(ctx: Ctx) -> str | None:
    if not enabled(ctx):
        return None
    a = ctx.action
    if not a.session_id:
        return None
    path = state_file(ctx.project_dir, a.session_id)
    if a.kind == "prompt":
        if a.invoked in RECORD_COMMANDS:
            state = _load(path)
            if state is None or state["command"] != a.invoked:
                _save(path, {"command": a.invoked, "opened_at": time.time(), "written": False, "blocked": False})
        return None
    if a.kind == "tool_result":
        state = _load(path)
        if state is not None and not state["written"] and is_record_write(a):
            state["written"] = True
            _save(path, state)
        return None
    if a.kind != "stop":
        return None
    if ctx.disabled(NAME) or a.continuing:
        return None
    try:
        config = client.load_config()
    except client.ConfigError:
        return None
    if config is None:
        return None
    state = _load(path)
    if state is None or state["written"] or state["blocked"]:
        return None
    state["blocked"] = True
    _save(path, state)
    return MESSAGE.format(command=state["command"])
