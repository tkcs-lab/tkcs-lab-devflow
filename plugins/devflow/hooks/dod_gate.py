#!/usr/bin/env python3
"""Stop hook `dod-gate`: block stopping until the profile's definition-of-done commands pass.

Opt-in (`hooks.dod_gate.enabled: true`). Which sessions it applies to is documented in docs/hooks.md:
every session in a checkout, except one that marked itself exempt with `dod_gate.py --exempt` (the
/implement orchestrator, which legitimately stops at human gates). It never loops: it honours
`stop_hook_active`, counts failed attempts, and lets the session stop after `max_attempts` of them,
saying why.

    dod_gate.py            # hook mode: Stop event JSON on stdin
    dod_gate.py --exempt   # mark this checkout's session exempt (run by the commands, not by hand)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import _common
from _common import DEFAULT_MAX_ATTEMPTS, Ctx, ProfileError

NAME = "dod-gate"
MARKER_TTL_SECONDS = 24 * 3600   # an exemption lapses a day after the exempt session last stopped
TOTAL_BUDGET_SECONDS = 1700      # hooks.json allows 1800
TAIL_LINES = 25


# --------------------------------------------------------------------------- state files

def _git(project: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", project, *args], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def state_dir(project: str) -> Path:
    git_dir = _git(project, "rev-parse", "--absolute-git-dir")
    if git_dir and git_dir.strip():
        d = Path(git_dir.strip()) / "devflow"
    else:
        d = Path(tempfile.gettempdir()) / ("devflow-hooks-" + hashlib.sha1(project.encode()).hexdigest()[:12])
    return d


def marker_path(project: str) -> Path:
    return state_dir(project) / "dod-gate-exempt.json"


def mark_exempt(project: str) -> Path:
    path = marker_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "exempt", "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    return path


def exempt(project: str) -> bool:
    """True while an exempt marker is younger than the TTL; every look refreshes it, so an orchestrator
    that keeps stopping (check-ins, human gates) stays exempt."""
    path = marker_path(project)
    try:
        if time.time() - path.stat().st_mtime > MARKER_TTL_SECONDS:
            return False
        os.utime(path)
    except OSError:
        return False
    return True


def _state_file(project: str, session_id: object) -> Path:
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(session_id or "nosession"))[:80]
    return state_dir(project) / f"dod-gate-{sid}.json"


def load_state(project: str, session_id: object) -> dict:
    try:
        data = json.loads(_state_file(project, session_id).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(project: str, session_id: object, state: dict) -> bool:
    path = _state_file(project, session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- the tree

def has_changes(project: str, main: str) -> bool:
    """False only when the tree is clean and HEAD has no commit that origin/<main> lacks."""
    if (_git(project, "status", "--porcelain") or "").strip():
        return True
    for ref in (f"origin/{main}", main):
        ahead = _git(project, "rev-list", "--count", f"{ref}..HEAD")
        if ahead is not None:
            return ahead.strip() != "0"
    return True  # cannot tell: treat as changed


def fingerprint(project: str) -> str:
    h = hashlib.sha256()
    for args in (("rev-parse", "HEAD"), ("status", "--porcelain"), ("diff", "HEAD")):
        h.update((_git(project, *args) or "").encode())
    for rel in (_git(project, "ls-files", "-o", "--exclude-standard") or "").splitlines():
        try:
            st = os.stat(os.path.join(project, rel))
            h.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            pass
    return h.hexdigest()


# --------------------------------------------------------------------------- running the gate

def dod_commands(ctx: Ctx) -> list[tuple[str, str | None]]:
    verify = (ctx.profile or {}).get("verify")
    entries = verify.get("dod") if isinstance(verify, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ProfileError("toolkit.yaml: missing required key 'verify.dod' (the dod-gate runs it)")
    out: list[tuple[str, str | None]] = []
    for entry in entries:
        if isinstance(entry, str) and entry:
            out.append((entry, None))
        elif isinstance(entry, dict) and isinstance(entry.get("run"), str) and entry["run"]:
            cwd = entry.get("cwd")
            out.append((entry["run"], cwd if isinstance(cwd, str) else None))
        else:
            raise ProfileError("toolkit.yaml: every entry of 'verify.dod' must be a string or a mapping with 'run'")
    return out


def tail(text: str) -> str:
    lines = text.strip().splitlines()[-TAIL_LINES:]
    return "\n".join("      " + line[:300] for line in lines)


def run_gate(project: str, commands: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    """Run every command (the report is complete even after a failure); returns (command, why) failures."""
    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    failures: list[tuple[str, str]] = []
    for run, cwd in commands:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failures.append((run, "not run: the gate's time budget was used up"))
            continue
        try:
            r = subprocess.run(run, shell=True, cwd=os.path.join(project, cwd) if cwd else project,
                               capture_output=True, text=True, timeout=remaining, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            failures.append((run, "timed out"))
            continue
        except OSError as exc:
            failures.append((run, f"could not start: {exc}"))
            continue
        if r.returncode != 0:
            failures.append((run, f"exit {r.returncode}\n{tail(r.stdout + chr(10) + r.stderr)}"))
    return failures


MAX_ATTEMPTS_LIMIT = 10


def _limit_for_errors(ctx: Ctx) -> int:
    """The attempt limit to use when the profile itself is broken: the configured one if it is valid, else the default."""
    try:
        gate = ctx.hooks_section().get("dod_gate")
    except ProfileError:
        return DEFAULT_MAX_ATTEMPTS
    value = gate.get("max_attempts") if isinstance(gate, dict) else None
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_ATTEMPTS_LIMIT:
        return value
    return DEFAULT_MAX_ATTEMPTS


def evaluate(ctx: Ctx) -> str | None:
    """A profile error counts as a failed attempt like any other failure, so it cannot block the session forever."""
    try:
        return _evaluate(ctx)
    except ProfileError as exc:
        project = ctx.project_dir
        sid = ctx.payload.get("session_id")
        state = load_state(project, sid)
        now = fingerprint(project)
        if now == state.get("gave_up"):
            return None
        attempts = int(state.get("profile_attempts", 0)) + 1
        limit = _limit_for_errors(ctx)
        saved = save_state(project, sid, {"profile_attempts": attempts})
        if attempts >= limit or (ctx.payload.get("stop_hook_active") and not saved):
            save_state(project, sid, {"gave_up": now, "profile_attempts": 0})
            ctx.notice = (f"letting the session stop although the profile is still broken ({exc}): "
                          f"{attempts} failed attempt(s) reached the limit of {limit}"
                          + ("" if saved else ", and the attempt counter could not be saved") + ". Fix the profile.")
            return None
        return f"{exc} (attempt {attempts} of {limit})"


def _evaluate(ctx: Ctx) -> str | None:
    gate = ctx.hooks_section().get("dod_gate")
    if gate is None:
        return None
    if not isinstance(gate, dict):
        raise ProfileError("toolkit.yaml: 'hooks.dod_gate' must be a mapping")
    if gate.get("enabled") is not True:
        return None
    max_attempts = gate.get("max_attempts", DEFAULT_MAX_ATTEMPTS)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ProfileError("toolkit.yaml: 'hooks.dod_gate.max_attempts' must be a positive integer")
    if max_attempts > MAX_ATTEMPTS_LIMIT:
        raise ProfileError("toolkit.yaml: 'hooks.dod_gate.max_attempts' must be between 1 and 10")
    main = ctx.require_main_branch()
    commands = dod_commands(ctx)
    project = ctx.project_dir
    if exempt(project) or not has_changes(project, main):
        return None
    sid = ctx.payload.get("session_id")
    state = load_state(project, sid)
    if fingerprint(project) in (state.get("passed"), state.get("gave_up")):
        return None  # nothing changed since the gate last passed, or since it gave up
    failures = run_gate(project, commands)
    now = fingerprint(project)  # after the run: the commands may have written files
    if not failures:
        save_state(project, sid, {"passed": now, "attempts": 0})
        return None
    attempts = int(state.get("attempts", 0)) + 1
    names = ", ".join(f"`{run}`" for run, _ in failures)
    saved = save_state(project, sid, {"attempts": attempts})
    if attempts >= max_attempts or (ctx.payload.get("stop_hook_active") and not saved):
        save_state(project, sid, {"gave_up": now, "attempts": 0})
        ctx.notice = (f"letting the session stop although the definition of done is still red ({names}): "
                      f"{attempts} failed attempt(s) reached the limit of {max_attempts}"
                      + ("" if saved else ", and the attempt counter could not be saved")
                      + ". Fix it before opening or updating a pull request.")
        return None
    detail = "\n".join(f"  - `{run}`: {why}" for run, why in failures)
    return (f"you cannot stop yet: the definition of done is red (attempt {attempts} of {max_attempts}).\n"
            f"{detail}\nFix the cause (never skip, loosen or delete a test), run /dod, and stop again. After "
            f"{max_attempts} failed attempts the gate lets the session stop and tells the user why.")


def cli(argv: list[str]) -> int:
    if argv[:1] == ["--exempt"]:
        project = _common.find_project(os.getcwd())[0]
        print(f"dod-gate: this session is exempt ({mark_exempt(project)})")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    _common.main(NAME, evaluate, fail_closed=False)
