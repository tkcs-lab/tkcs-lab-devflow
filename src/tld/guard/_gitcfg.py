"""Local `git` lookups shared by the guardrail hooks (stdlib only): run git, current branch, ref exists."""
from __future__ import annotations

import os
import subprocess

from tld.guard._shell import ParseError


class GitLookupError(ParseError):
    """A git lookup the hook needs could not be answered (timeout, cannot run, unexpected status)."""


def _run_git(ctx_dir: str, repo_opts: list[str], *args: str, strict: bool = False) -> str | None:
    """Stdout of `git`, or None. Status 1 is "no such value" and gives None. Any other failure gives None
    too, unless `strict`: then a timeout, a launch error or another status raises GitLookupError."""
    cmd = ["git", *repo_opts, *args]
    try:
        r = subprocess.run(cmd, cwd=ctx_dir if os.path.isdir(ctx_dir) else None, capture_output=True,
                           text=True, timeout=5, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        if strict:
            raise GitLookupError(f"`git {args[0]}` timed out") from None
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        if strict:
            raise GitLookupError(f"`git {args[0]}` could not run ({type(exc).__name__})") from None
        return None
    if r.returncode == 0:
        return r.stdout.strip()
    if strict and r.returncode != 1:
        raise GitLookupError(f"`git {args[0]}` exited with status {r.returncode}")
    return None


def current_branch(ctx_dir: str, repo_opts: list[str] | None = None) -> str | None:
    """The short branch name; None for a detached HEAD. Raises GitLookupError when git cannot answer."""
    return _run_git(ctx_dir, repo_opts or [], "symbolic-ref", "--short", "-q", "HEAD", strict=True)


def ref_exists(ctx_dir: str, full_ref: str, repo_opts: list[str] | None = None) -> bool:
    """True when the local repository has `full_ref` (for example refs/tags/v1). Raises GitLookupError."""
    return _run_git(ctx_dir, repo_opts or [], "show-ref", "--verify", "-q", full_ref, strict=True) is not None


def git_config_values(ctx_dir: str, repo_opts: list[str], overrides: list[str], key: str) -> list[str]:
    """Every effective value of `key`: the `-c` / environment `overrides` (key=value; key compared
    case-insensitively) replace the file values when present, else `git config --get-all`."""
    want = key.lower()
    mine = [o.partition("=")[2] for o in overrides if o.partition("=")[0].lower() == want]
    if mine:
        return mine
    out = _run_git(ctx_dir, repo_opts, "config", "--no-includes", "--get-all", key)
    return out.splitlines() if out else []


def git_config_value(ctx_dir: str, repo_opts: list[str], overrides: list[str], key: str) -> str | None:
    values = git_config_values(ctx_dir, repo_opts, overrides, key)
    return values[-1] if values else None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "yes", "on", "1")


def bare_push_destinations(it, push, main: str) -> list[str] | None:  # noqa: ARG001
    """Short branch names a push without an explicit refspec would update, or None when that cannot be
    resolved (mirror, a glob, matching, a detached HEAD, a missing upstream)."""
    from tld.guard._gitgh import has_glob, parse_refspecs, short_ref  # circular at import time
    d, opts, ov = it.dir, it.git.repo_opts, it.git.config
    cur = current_branch(d, opts)
    if cur is None:
        return None
    remote = (push.repo or git_config_value(d, opts, ov, f"branch.{cur}.pushRemote")
              or git_config_value(d, opts, ov, "remote.pushDefault")
              or git_config_value(d, opts, ov, f"branch.{cur}.remote") or "origin")
    if _truthy(git_config_value(d, opts, ov, f"remote.{remote}.mirror")):
        return None
    pushes = git_config_values(d, opts, ov, f"remote.{remote}.push")
    if pushes:
        out = []
        for spec in parse_refspecs(pushes):
            dst = short_ref(spec.dst)
            if spec.dynamic or has_glob(dst) or not dst:
                return None
            out.append(cur if dst in ("HEAD", "@") else dst)
        return out
    mode = (git_config_value(d, opts, ov, "push.default") or "simple").lower()
    if mode in ("simple", "current"):
        return [cur]
    if mode in ("upstream", "tracking"):
        merge = git_config_value(d, opts, ov, f"branch.{cur}.merge")
        return [short_ref(merge)] if merge else None
    if mode == "nothing":
        return []
    return None
