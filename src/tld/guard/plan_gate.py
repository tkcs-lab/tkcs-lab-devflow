"""plan-gate (UserPromptSubmit and PreToolUse): a session that no tld command started cannot write to the repository.

Opt-in (`hooks.plan_gate.enabled: true`). A prompt that starts a tld command opens the session; a plain prompt gets
one sentence of context; a write into the repository is denied while the session is not open. See docs/architecture/hooks.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from tld.dod.gate import state_dir
from tld.guard import _writes, markers, protect_paths
from tld.guard._common import Ctx, ProfileError

NAME = "plan-gate"
OPENING = ("make-plan", "implement", "review", "setup", "migrate", "land", "deps", "upstream", "docs", "repo-admin")
CONTENT_WRITES = ("push_files", "create_or_update_file", "delete_file")   # GitHub MCP tools that write files
SESSION_TTL_SECONDS = 24 * 3600
WORKER_COMMAND = "tld guard allow-" + "plan"   # in an /implement worker brief; split so the deny text path never names it

PROMPT_CONTEXT = ("tld plan-gate: this session has no plan. Answer or research only; do not edit files or run commands "
                  "that write. If the message asks for a change, restate it in one or two sentences and propose "
                  "/tld:make-plan. The tld:ask skill describes how.")
DENY = ("blocked: {what} would change the repository, but this session was not started with a tld command, so there "
        "is no plan. Do not retry and do not look for another way to write. Tell the user what you would change and "
        "suggest /tld:make-plan. The tld:ask skill describes how.")


def enabled(ctx: Ctx) -> bool:
    gate = ctx.hooks_section().get("plan_gate")
    if gate is None:
        return False
    if not isinstance(gate, dict):
        raise ProfileError("toolkit.yaml: 'hooks.plan_gate' must be a mapping")
    value = gate.get("enabled", False)
    if not isinstance(value, bool):
        raise ProfileError("toolkit.yaml: 'hooks.plan_gate.enabled' must be true or false")
    return value


def session_file(project: str, sid: object) -> Path:
    return state_dir(project) / "plan-gate" / (hashlib.sha256(str(sid).encode()).hexdigest()[:16] + ".json")


def open_session(project: str, sid: object) -> None:
    path = session_file(project, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"written_at": time.strftime(markers.STAMP, time.gmtime())}))


def session_open(project: str, sid: object) -> bool:
    """True while the session's file is younger than the TTL; every look refreshes it."""
    path = session_file(project, sid)
    try:
        if time.time() - path.stat().st_mtime > SESSION_TTL_SECONDS:
            return False
        os.utime(path)
    except OSError:
        return False
    return True


def gate_open(ctx: Ctx) -> bool:
    if markers.read(ctx.project_dir, "plan-open") is not None:
        return True
    sid = ctx.action.session_id
    return bool(sid) and session_open(ctx.project_dir, sid)


def evaluate(ctx: Ctx) -> str | None:
    try:
        return _evaluate(ctx)
    except ProfileError as exc:
        ctx.notice = str(exc)
        return None


def _counts(ctx: Ctx, path: str, here: str) -> bool:
    return any(rel != ".git" and not rel.startswith(".git/") for rel in protect_paths.relative(ctx, path, here))


def _target(ctx: Ctx) -> str | None:
    """What the action would write inside the repository ("writing `x`" and so on); None when nothing."""
    a = ctx.action
    if a.kind == "write":
        if a.path and _counts(ctx, a.path, a.cwd):
            return f"writing `{a.path}`"
    elif a.kind == "shell":
        try:
            for path, here in _writes.write_targets(ctx, a.command or ""):
                if _counts(ctx, path, here):
                    return f"a command that writes `{path}`"
        except _writes.TooManyPaths as exc:
            return f"a command that writes `{exc}`"
    elif a.kind == "github_op" and a.op in CONTENT_WRITES:
        return f"the GitHub `{a.op}` call"
    return None


def _evaluate(ctx: Ctx) -> str | None:
    if not enabled(ctx):
        return None
    a = ctx.action
    if a.kind == "prompt":
        if ctx.disabled(NAME):
            return None
        if a.invoked in OPENING and a.session_id:
            open_session(ctx.project_dir, a.session_id)
            return None
        if a.invoked is not None or gate_open(ctx):
            return None
        if WORKER_COMMAND in (a.prompt or ""):
            return None
        ctx.context = PROMPT_CONTEXT
        return None
    what = _target(ctx)
    if what is None:
        return None
    if ctx.disabled(NAME):
        return None
    if not a.session_id and markers.read(ctx.project_dir, "plan-open") is None:
        return None
    if gate_open(ctx):
        return None
    return DENY.format(what=what)
