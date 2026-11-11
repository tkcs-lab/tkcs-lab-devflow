"""The trusted copy of the profile: `.tld/toolkit.yaml` as it is on the remote main branch.

`hooks.disable` and the protect lists are read from this copy, never from the working tree or from a
local branch, so a session cannot switch a guardrail off by rewriting its own files or refs:

    git fetch --no-tags origin +refs/heads/<main>:refs/tld/trusted

The fetch is cached for TTL_SECONDS with a stamp in `<git dir>/tld/trusted.json`; a failed fetch is retried
after FAIL_TTL_SECONDS. The guards deny shell commands that write `refs/tld/*` or point `origin` elsewhere
(see integrity.py), which keeps the ref what the fetch made it. With no trusted copy (no remote, no network,
no commit yet) nothing is disabled and the protect lists are the defaults plus the working tree's.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

TRUSTED_REF = "refs/tld/trusted"
TTL_SECONDS = 600
FAIL_TTL_SECONDS = 60
FETCH_TIMEOUT = 8
PROFILE_PATH = ".tld/toolkit.yaml"


def _git(project: str, *args: str, timeout: float = 5) -> subprocess.CompletedProcess | None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def _git_dir(project: str) -> Path | None:
    r = _git(project, "rev-parse", "--absolute-git-dir")
    return Path(r.stdout.strip()) if r and r.returncode == 0 and r.stdout.strip() else None


def _stamp(git_dir: Path) -> dict:
    try:
        data = json.loads((git_dir / "tld" / "trusted.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_stamp(git_dir: Path, data: dict) -> None:
    try:
        (git_dir / "tld").mkdir(parents=True, exist_ok=True)
        tmp = git_dir / "tld" / f"trusted.json.{os.getpid()}"
        tmp.write_text(json.dumps(data))
        os.replace(tmp, git_dir / "tld" / "trusted.json")
    except OSError:
        pass


def refresh(project: str, main: str, now: float | None = None) -> bool:
    """Fetch the remote main branch into TRUSTED_REF unless the stamp is fresh. True when the ref holds it."""
    git_dir = _git_dir(project)
    if git_dir is None or not main:
        return False
    now = time.time() if now is None else now
    stamp = _stamp(git_dir)
    fresh = stamp.get("branch") == main and 0 <= now - float(stamp.get("at", 0) or 0) < (
        TTL_SECONDS if stamp.get("ok") else FAIL_TTL_SECONDS)
    if not fresh:
        r = _git(project, "fetch", "--no-tags", "--quiet", "--no-write-fetch-head", "origin",
                 f"+refs/heads/{main}:{TRUSTED_REF}", timeout=FETCH_TIMEOUT)
        ok = bool(r and r.returncode == 0)
        # another guard of the same call may hold the ref lock; its fetch fills the same ref
        _write_stamp(git_dir, {"branch": main, "at": now, "ok": ok})
        if not ok and stamp.get("branch") != main:
            return False
    r = _git(project, "rev-parse", "--verify", "-q", f"{TRUSTED_REF}^{{commit}}")
    return bool(r and r.returncode == 0)


def trusted_profile(project: str, main: str | None) -> tuple[dict | None, bool]:
    """(profile on the remote main branch, available). Available with None means the branch has no profile."""
    if not isinstance(main, str) or not main or not refresh(project, main):
        return None, False
    r = _git(project, "show", f"{TRUSTED_REF}:{PROFILE_PATH}")
    if r is None:
        return None, False
    if r.returncode != 0:
        return None, True
    try:
        import yaml
        data = yaml.safe_load(r.stdout)
    except Exception:  # noqa: BLE001 - an unreadable trusted copy is treated as missing
        return None, False
    return (data if isinstance(data, dict) else None), True
