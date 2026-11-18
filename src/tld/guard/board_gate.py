"""board-gate (UserPromptSubmit, PostToolUse, Stop): a session that a record-writing tld command started cannot end
its turn before it has written its status record to the board once.

Opt-in (`hooks.board_gate.enabled: true`) and only when a board is configured. The gate covers the commands that always
write a record; `docs` counts only in its `init` and `tidy` modes (`check` writes none). A prompt that starts such a
command opens a per-session state file; a successful record write (the `board_set` tool or `tld board client set`)
marks it written; the first Stop without a write is blocked once. It is a nudge, not a control, and it never makes a
network call. See docs/architecture/hooks.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from tld.board import client
from tld.board.inbox import MARKER as ASK_MARKER
from tld.dod.gate import state_dir
from tld.guard._common import Ctx, ProfileError
from tld.guard.action import Action

NAME = "board-gate"
RECORD_COMMANDS = ("make-plan", "implement", "review", "setup", "migrate", "land", "deps", "upstream", "docs", "ci", "questions")
RECORD_MODES = {"docs": ("init", "tidy")}  # commands that write a record only in some modes
SESSION_TTL_SECONDS = 24 * 3600
CLIENT_SET = re.compile(r"\bboard\s+client\s+set\b")
ASK_COMMAND = re.compile(r"\bboard\s+ask(?![-\w])")
ASK_ID_LINE = re.compile(r"^a-[0-9a-f]+$")
GIT_PUSH = re.compile(r"\bgit\s+push\b|\bgh\s+pr\s+create\b")
DIRTY_OPS = ("worker_start", "worker_stop", "pr_create")
COUNTERS = ("write_seq", "dirty_seq", "dirty_blocked_seq", "ask_seq", "timer_seq", "timer_blocked_seq")
_REMINDER = re.compile(r"\A\s*<system-reminder>.*?</system-reminder>\s*", re.S)
_ARG_TYPED = re.compile(r"\A\s*/(?:tld:)?[a-z][a-z-]*(?:\s+(\S+))?")
_ARG_EXPANDED = re.compile(r"\A\s*(?:<command-message>[^<]*</command-message>\s*)?<command-name>/[^<]*</command-name>"
                           r"(?:\s*<command-args>\s*([^\s<]+))?")

MESSAGE = ('this session was started by /tld:{command} and has not written its status record to the board. '
           'Write it now: use the board_set tool, or when that tool is missing or fails run "tld board client set '
           '<id> - " with the record on stdin (the id comes from "tld board record-id"). If the board cannot be '
           'reached, say so in your final reply and stop. '
           'If the playbook says to write no record yet, say so and stop. This check blocks only once.')

DIRTY_MESSAGE = ('this session was started by /tld:{command} and has changed things since its last status record: it asked a '
                 'question, started or stopped a worker, opened a pull request or pushed. Write the record now: use the '
                 'board_set tool, or when that tool is missing or fails run "tld board client set <id> - " with the record '
                 'on stdin. Set updated_at, the state of every item that changed, and every extra item (a fix, a revision, '
                 'a second review) that started. If the board cannot be reached, say so in your final reply and stop. '
                 'If the playbook says to write no record yet, say so and stop. This check blocks only once per change.')
TIMER_MESSAGE = ('this session posted an ask and armed no timer after it. Arm it now with schedule_wakeup (60 minutes when '
                 'the answer watch runs, else 10 minutes), write its time into last_event as "timer <ISO time>" and write '
                 'the record, unless the playbook says to write no record yet. If this run is unattended (no person started '
                 'it), a timer is not needed: say so and stop. This check blocks only once per ask.')


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
    loaded = {"command": command, "opened_at": opened, "written": data.get("written") is True,
              "blocked": data.get("blocked") is True}
    for key in COUNTERS:
        value = data.get(key)
        loaded[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    return loaded


def _save(path: Path, state: dict) -> None:
    """Write the state atomically and refresh `opened_at`, so the TTL counts from the last activity."""
    state["opened_at"] = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, path)


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


def is_ask_post(action: Action) -> bool:
    """An ask that was posted: the `board_ask` tool answered an id, `tld board ask` printed one, or an issue comment
    or body starts with the ask marker. Never raises."""
    if action.kind != "tool_result":
        return False
    try:
        output = action.output if isinstance(action.output, str) else ""
        if action.op == "board_ask":
            obj = json.loads(output)
            return isinstance(obj, dict) and isinstance(obj.get("id"), str) and obj["id"].startswith("a-")
        if action.op == "ask_comment":
            body = (action.args or {}).get("body")
            return isinstance(body, str) and body.startswith(ASK_MARKER)
        if action.command and ASK_COMMAND.search(action.command):
            lines = [line.strip() for line in output.splitlines()]
            return any(ASK_ID_LINE.match(line) or line.startswith(ASK_MARKER) for line in lines)
    except Exception:  # noqa: BLE001 - detection never raises
        return False
    return False


def is_timer(action: Action) -> bool:
    return action.kind == "tool_result" and action.op == "timer"


def is_change(action: Action) -> bool:
    """Any other change of the run: a worker started or stopped, a pull request opened, a push."""
    if action.kind != "tool_result":
        return False
    return action.op in DIRTY_OPS or bool(action.command and GIT_PUSH.search(action.command))


def _first_argument(prompt: str | None) -> str | None:
    """The first word after the command name in a typed (`/tld:docs init x`) or expanded prompt, or None."""
    text = prompt or ""
    while (r := _REMINDER.match(text)):
        text = text[r.end():]
    m = _ARG_TYPED.match(text) or _ARG_EXPANDED.match(text)
    return m.group(1) if m else None


def writes_record(command: str | None, prompt: str | None) -> bool:
    """Whether a prompt of this command writes a status record."""
    if command not in RECORD_COMMANDS:
        return False
    modes = RECORD_MODES.get(command)
    return modes is None or _first_argument(prompt) in modes


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
        if writes_record(a.invoked, a.prompt):
            state = _load(path)
            if state is None or state["command"] != a.invoked:
                _save(path, {"command": a.invoked, "opened_at": time.time(), "written": False, "blocked": False,
                             **dict.fromkeys(COUNTERS, 0)})
        return None
    if a.kind == "tool_result":
        state = _load(path)
        if state is None:
            return None
        changed = False
        if is_record_write(a):
            state["written"] = True
            state["write_seq"] = state["dirty_seq"]
            changed = True
        if is_ask_post(a):
            state["ask_seq"] += 1
            state["dirty_seq"] += 1
            changed = True
        if is_timer(a):
            state["timer_seq"] = state["ask_seq"]
            changed = True
        if is_change(a):
            state["dirty_seq"] += 1
            changed = True
        if changed:
            _save(path, state)
        return None
    if a.kind != "stop":
        return None
    if ctx.disabled(NAME):
        return None
    state = _load(path)
    if state is None:
        return None
    if state["ask_seq"] > state["timer_seq"] and state["timer_blocked_seq"] < state["ask_seq"]:
        state["timer_blocked_seq"] = state["ask_seq"]
        _save(path, state)
        return TIMER_MESSAGE
    try:
        config = client.load_config()
    except client.ConfigError:
        return None
    if config is None:
        return None
    if not state["written"] and not state["blocked"]:
        state["blocked"] = True
        _save(path, state)
        return MESSAGE.format(command=state["command"])
    if state["written"] and state["dirty_seq"] > state["write_seq"] and state["dirty_blocked_seq"] < state["dirty_seq"]:
        state["dirty_blocked_seq"] = state["dirty_seq"]
        _save(path, state)
        return DIRTY_MESSAGE.format(command=state["command"])
    return None
