"""Local `git` lookups shared by the guardrail hooks (stdlib only): run git, current branch, ref exists."""
from __future__ import annotations

import os
import subprocess


def _run_git(ctx_dir: str, repo_opts: list[str], *args: str) -> str | None:
    cmd = ["git", *repo_opts, *args]
    try:
        r = subprocess.run(cmd, cwd=ctx_dir if os.path.isdir(ctx_dir) else None, capture_output=True,
                           text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def current_branch(ctx_dir: str, repo_opts: list[str] | None = None) -> str | None:
    return _run_git(ctx_dir, repo_opts or [], "symbolic-ref", "--short", "-q", "HEAD")


def ref_exists(ctx_dir: str, full_ref: str, repo_opts: list[str] | None = None) -> bool:
    """True when the local repository has `full_ref` (for example refs/tags/v1)."""
    try:
        r = subprocess.run(["git", *(repo_opts or []), "show-ref", "--verify", "-q", full_ref],
                           cwd=ctx_dir if os.path.isdir(ctx_dir) else None, capture_output=True,
                           timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0
