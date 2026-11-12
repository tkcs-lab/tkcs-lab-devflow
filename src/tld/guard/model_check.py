"""model-check (session_start and prompt): warns once when a tld command starts in a session at the strong level.

Never denies. It sets a notice for the user only; levels are `strong`, `standard` and `fast`, never model names.
See docs/architecture/hooks.md.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tld.dod.gate import state_dir
from tld.guard._common import Ctx

NAME = "model-check"
NOTICE = ("this session runs at the strong level, the most expensive. /tld:{cmd} is meant for the {level} level, "
          "and its later turns (check-ins, wakes) run on the session's model. Switch the session's model before it "
          "continues (the level may come from your previous turn, for example a /tld:make-plan run).")


def session_file(project: str, sid: object) -> Path:
    return state_dir(project) / "model-check" / (hashlib.sha256(str(sid).encode()).hexdigest()[:16] + ".json")


def _store(project: str, sid: object, level: str) -> None:
    path = session_file(project, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"level": level}))


def _stored(project: str, sid: object) -> str | None:
    try:
        level = json.loads(session_file(project, sid).read_text()).get("level")
    except (OSError, ValueError, AttributeError):
        return None
    return level if isinstance(level, str) else None


def evaluate(ctx: Ctx) -> None:
    ctx.notice = None
    a = ctx.action
    if a.kind == "session_start":
        if a.session_level and a.session_id:
            try:
                _store(ctx.project_dir, a.session_id, a.session_level)
            except OSError:
                pass
        return None
    if a.kind != "prompt" or not a.invoked:
        return None
    level = a.session_level
    if level is None and a.session_id:
        level = _stored(ctx.project_dir, a.session_id)
    if level == "strong" and a.command_level != "strong" and not ctx.disabled(NAME):
        ctx.notice = NOTICE.format(cmd=a.invoked, level=a.command_level or "standard")
    return None
