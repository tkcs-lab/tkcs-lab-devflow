"""The trusted copy of the profile: `.tld/toolkit.yaml` as it is on the remote's default branch.

`hooks.disable` and the protect lists are read from this copy, never from the working tree or from a
local branch, so a session cannot switch a guardrail off by rewriting its own files or refs. Which branch is
trusted is not taken from the working tree either (a branch could name itself): it is the default branch the
remote reports.

    git ls-remote --symref <origin url> HEAD          -> the default branch and its commit
    git fetch --no-tags <origin url> +refs/heads/<default>:refs/tld/trusted   (only when the commit is missing)

The result is cached for TTL_SECONDS in `<git dir>/tld/trusted.json` (a failure is retried after FAIL_TTL_SECONDS):
the origin URL, the default branch and the commit SHA. The profile is read from that SHA, and the ref must still
point at it. The origin URL recorded at the first lookup is kept: when origin's (insteadOf-resolved) URL differs
from it later, the trusted copy counts as unavailable. Every git call here runs without replace objects, hooks or
the `ext::` transport. With no trusted copy (no remote, no network, no commit yet, a moved URL or ref) nothing
is disabled and the protect lists are the defaults plus the working tree's.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

TRUSTED_REF = "refs/tld/trusted"
TTL_SECONDS = 600
FAIL_TTL_SECONDS = 60
LS_REMOTE_TIMEOUT = 5
FETCH_TIMEOUT = 7
PROFILE_PATH = ".tld/toolkit.yaml"
FALLBACK_MAINS = ("main", "master")  # also protected while the remote's default branch is unknown
# The hook's own git calls must not be steered by the session's environment or by objects it planted.
# (The runtime's own git configuration in the environment, such as a proxy's url rewrites, is kept: a command the
# session runs cannot change the environment the hook process inherits.)
STRIP_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
             "GIT_INDEX_FILE", "GIT_NAMESPACE", "GIT_REPLACE_REF_BASE", "GIT_GRAFT_FILE")
SAFE_OPTS = ("-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never", "-c", "core.fsmonitor=false")
SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


@dataclass
class Trusted:
    profile: dict | None = None   # the profile on the default branch (None: the branch has none, or unavailable)
    available: bool = False       # a trusted copy could be read
    branch: str | None = None     # the remote's default branch, when known (even if the copy is unavailable)
    sha: str | None = None        # the commit the profile is read from
    origin: bool = True           # an origin remote is configured
    problem: str | None = None    # why it is unavailable, for the notice


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    return env


def _git(project: str, *args: str, timeout: float = 5) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *SAFE_OPTS, "-C", project, *args], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL, env=_env())
    except (OSError, subprocess.SubprocessError):
        return None


def _out(r: subprocess.CompletedProcess | None) -> str | None:
    return r.stdout.strip() if r is not None and r.returncode == 0 and r.stdout.strip() else None


def _git_dir(project: str) -> Path | None:
    out = _out(_git(project, "rev-parse", "--absolute-git-dir"))
    return Path(out) if out else None


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


def origin_url(project: str) -> str | None:
    """origin's fetch URL as git would use it (insteadOf applied); None without an origin."""
    return _out(_git(project, "ls-remote", "--get-url", "origin")) if _out(
        _git(project, "config", "--no-includes", "--get", "remote.origin.url")) else None


def remote_default(project: str, url: str) -> tuple[str, str] | None:
    """(default branch, commit SHA) the remote at `url` advertises for HEAD, or None."""
    out = _out(_git(project, "ls-remote", "--symref", url, "HEAD", timeout=LS_REMOTE_TIMEOUT))
    if not out:
        return None
    branch = sha = None
    for line in out.splitlines():
        left, _, name = line.partition("\t")
        if name.strip() != "HEAD":
            continue
        if left.startswith("ref: refs/heads/"):
            branch = left[len("ref: refs/heads/"):].strip()
        elif SHA_RE.match(left.strip()):
            sha = left.strip()
    return (branch, sha) if branch and sha else None


def origin_head(project: str) -> str | None:
    """The branch the local `refs/remotes/origin/HEAD` names (set by clone or `remote set-head`), or None. Only ever
    used to protect one more name, never to choose the trusted copy."""
    out = _out(_git(project, "symbolic-ref", "-q", "refs/remotes/origin/HEAD"))
    return out[len("refs/remotes/origin/"):] if out and out.startswith("refs/remotes/origin/") else None


def _ref_sha(project: str) -> str | None:
    return _out(_git(project, "rev-parse", "--verify", "-q", f"{TRUSTED_REF}^{{commit}}"))


def _has_commit(project: str, sha: str) -> bool:
    r = _git(project, "cat-file", "-e", f"{sha}^{{commit}}")
    return bool(r and r.returncode == 0)


def _lookup(project: str, url: str) -> dict | None:
    """Ask the remote for its default branch, make sure the commit is here and point TRUSTED_REF at it."""
    found = remote_default(project, url)
    if found is None:
        return None
    branch, sha = found
    if not _has_commit(project, sha):
        _git(project, "fetch", "--no-tags", "--quiet", "--no-write-fetch-head", url,
             f"+refs/heads/{branch}:{TRUSTED_REF}", timeout=FETCH_TIMEOUT)
        fetched = _ref_sha(project)
        if fetched and fetched != sha and not _has_commit(project, sha):
            sha = fetched  # the branch moved between the two calls; the fetch is the newer answer
        if not _has_commit(project, sha):
            return None
    if _ref_sha(project) != sha:
        _git(project, "update-ref", TRUSTED_REF, sha)  # another guard of the same call may hold the lock
    return {"branch": branch, "sha": sha} if _ref_sha(project) == sha else None


def state(project: str, now: float | None = None) -> Trusted:
    """The trusted copy's branch and SHA, refreshed from the remote when the stamp is stale."""
    git_dir = _git_dir(project)
    if git_dir is None:
        return Trusted(problem="not a git repository", origin=False)
    url = origin_url(project)
    if not url:
        return Trusted(problem="no origin remote", origin=False)
    now = time.time() if now is None else now
    stamp = _stamp(git_dir)
    recorded = stamp.get("url") if isinstance(stamp.get("url"), str) else None
    if recorded and recorded != url:
        return Trusted(branch=stamp.get("branch") if isinstance(stamp.get("branch"), str) else None,
                       problem=f"origin now points to another URL than the one recorded at the first lookup "
                               f"({recorded})")
    age = now - float(stamp.get("at", 0) or 0) if isinstance(stamp.get("at"), (int, float)) else -1
    fresh = 0 <= age < (TTL_SECONDS if stamp.get("ok") else FAIL_TTL_SECONDS)
    if not fresh:
        found = _lookup(project, url)
        latest = _stamp(git_dir)  # a parallel guard may have finished meanwhile; never overwrite its success
        if found:
            stamp = {"url": recorded or url, "at": now, "ok": True, **found}
            _write_stamp(git_dir, stamp)
        elif latest.get("ok") and latest.get("url") == (recorded or url) and latest.get("at") != stamp.get("at"):
            stamp = latest
        else:
            stamp = {**{k: stamp[k] for k in ("branch", "sha") if k in stamp}, "url": recorded or url, "at": now,
                     "ok": False}
            _write_stamp(git_dir, stamp)
    branch = stamp.get("branch") if isinstance(stamp.get("branch"), str) and stamp.get("branch") else None
    sha = stamp.get("sha") if isinstance(stamp.get("sha"), str) and SHA_RE.match(stamp.get("sha")) else None
    if not sha:
        return Trusted(branch=branch, problem="the remote's default branch could not be read")
    if _ref_sha(project) != sha:
        return Trusted(branch=branch, problem=f"{TRUSTED_REF} no longer points at the commit the remote reported")
    return Trusted(available=True, branch=branch, sha=sha)


def trusted(project: str, now: float | None = None) -> Trusted:
    """The profile on the remote default branch. `available` with `profile` None: the branch has no profile."""
    st = state(project, now)
    if not st.available:
        return st
    r = _git(project, "show", f"{st.sha}:{PROFILE_PATH}")
    if r is None:
        return Trusted(branch=st.branch, problem="git could not run")
    if r.returncode != 0:
        return Trusted(available=True, branch=st.branch, sha=st.sha)
    try:
        import yaml
        data = yaml.safe_load(r.stdout)
    except Exception:  # noqa: BLE001 - an unreadable trusted copy is treated as missing
        return Trusted(branch=st.branch, problem="the profile on the default branch is not valid YAML")
    return Trusted(data if isinstance(data, dict) else None, True, st.branch, st.sha)


def trusted_profile(project: str, main: str | None = None) -> tuple[dict | None, bool]:  # noqa: ARG001
    """(profile on the remote default branch, available). `main` is ignored: the branch comes from the remote."""
    t = trusted(project)
    return t.profile, t.available
