#!/usr/bin/env python3
"""Combine dependency update groups onto one local branch, lockfiles left for the lock commands.

  tld ops deps-prepare --base REF --branch NAME --group REF [--group REF ...] [--bot-ref REF ...]

Each --group is a Dependabot branch (or a local `tld-deps/*` work branch built from one). The groups are applied
in the order given on top of --base, which must be the remote default branch: every change except the lockfiles
(the lockfiles of a group are put back to their merge-base blobs before the merge, so main's own lockfile changes
never conflict with them). A group that cannot be applied safely is left out with a reason. --bot-ref names the
Dependabot branches a work branch was built from: a work branch may only change a workflow file the way one of them
does. Creates branch NAME and checks it out; nothing is pushed and no hook, lock command or group ref is run or moved.
Prints JSON: the groups with their state, the bot refs and the lock commands to run. Exit 0 a branch was made,
3 no group applied (no branch), 1 `deps: <message>` an error (no branch), 2 a usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from tld.guard.protect_paths import matches
from tld.guard.trust import _env, trusted
from tld.ops import deps_checks as chk
from tld.profile.validate import validate

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]*$")
ZERO = "0" * 40
IDENT = {"GIT_AUTHOR_NAME": "tld", "GIT_AUTHOR_EMAIL": "tld@localhost",
         "GIT_COMMITTER_NAME": "tld", "GIT_COMMITTER_EMAIL": "tld@localhost"}


class DepsError(Exception):
    pass


def git(*args, cwd=None, env_extra=None, check=True, timeout=None):
    """One git call: no hooks, no `ext::` transport, no replace objects, the environment of the guards."""
    env = _env()
    env.update(env_extra or {})
    try:
        proc = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never",
                               "-c", "commit.gpgsign=false", *args],
                              cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DepsError(f"git {args[0]} could not run ({exc})")
    if check and proc.returncode != 0:
        raise DepsError(f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def plain_name(value: str) -> bool:
    return bool(NAME_RE.match(value)) and not any(bad in value for bad in ("..", "//", "@{")) \
        and not value.endswith(("/", ".", ".lock"))


def resolve(profile: dict) -> dict:
    errors, _, resolved = validate(profile, None)
    if errors:
        raise DepsError(f"the trusted profile is invalid: {errors[0]}")
    return resolved


def lock_entries(profile: dict, resolved: dict | None = None) -> list[dict]:
    """The `deps.lock_freshness` entries of the resolved profile (defaults and written values alike)."""
    if resolved is None:
        resolved = resolve(profile)
    return list((resolved.get("deps") or {}).get("lock_freshness") or [])


def commit_sha(root: str, ref: str) -> str | None:
    p = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=root, check=False)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def ls_remote_heads(root: str, pattern: str) -> dict[str, str]:
    try:
        p = git("ls-remote", "--heads", "origin", pattern, cwd=root, timeout=60)
    except DepsError:
        raise DepsError("cannot reach origin")
    out = {}
    for line in p.stdout.splitlines():
        sha, _, name = line.partition("\t")
        out[name.strip()] = sha.strip()
    return out


def choose_base(root: str, base: str, t) -> str:
    """The commit the combined branch starts from: the trusted default branch's, or the one origin reports now."""
    sha = commit_sha(root, base)
    if sha == t.sha:
        return sha
    head = f"refs/heads/{t.branch}"
    if sha and t.branch and ls_remote_heads(root, head).get(head) == sha:
        blob_new = git("rev-parse", "--verify", "--quiet", f"{sha}:.tld/toolkit.yaml", cwd=root, check=False)
        blob_old = git("rev-parse", "--verify", "--quiet", f"{t.sha}:.tld/toolkit.yaml", cwd=root, check=False)
        if blob_new.returncode == 0 and blob_new.stdout.strip() == blob_old.stdout.strip():
            return sha
        raise DepsError("the profile changed on the default branch since the trusted copy was read; run again")
    raise DepsError(f"--base {base} is not the remote default branch ({str(t.sha)[:12]})")


def raw_changes(root: str, mb: str, sha: str) -> list[tuple[str, str, str, str]]:
    """(old mode, new mode, status, path) of every change from mb to sha, sorted by path."""
    out = git("diff", "--raw", "--no-renames", "--no-ext-diff", "-z", mb, sha, cwd=root).stdout
    tokens = out.split("\0")
    changes = []
    i = 0
    while i + 1 < len(tokens) and tokens[i].startswith(":"):
        meta = tokens[i][1:].split()
        changes.append((meta[0], meta[1], meta[4][0], tokens[i + 1]))
        i += 2
    return sorted(changes, key=lambda c: c[3])


def identity_of_commits(root: str, mb: str, sha: str) -> bool:
    out = git("log", "--format=%an%x00%ae%x00%cn%x00%ce", f"{mb}..{sha}", cwd=root).stdout
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) != 4 or not chk.identity_ok(*parts):
            return False
    return True


def check_bot_refs(root: str, base_sha: str, bot_refs: list[str]) -> tuple[list[dict], list[str]]:
    """(the report of each --bot-ref, the tips of the good ones)."""
    report, tips = [], []
    for ref in bot_refs:
        sha = commit_sha(root, ref)
        mb = git("merge-base", base_sha, sha, cwd=root, check=False).stdout.strip() if sha else ""
        ok = bool(mb) and identity_of_commits(root, mb, sha)
        report.append({"ref": ref, "state": "ok" if ok else "not-bot-authored"})
        if ok:
            tips.append(sha)
    return report, tips


def classify(root, ref, sha, mb, resolved, entries, bot_tips):
    """(reason, file, moves, files, lockfiles) for one group; reason None when it may be applied."""
    globs = chk.entry_globs(entries)
    changes = raw_changes(root, mb, sha)
    files = [c[3] for c in changes]
    lockfiles = [f for f in files if chk.is_lockfile(f, globs)]
    changed = [f for f in files if f not in lockfiles]
    full = git("rev-parse", "--symbolic-full-name", ref, cwd=root, check=False).stdout.strip() or ref
    work = full.startswith(chk.WORK_PREFIX)

    def out(reason, file=None, moves=()):
        return reason, file, list(moves), files, lockfiles

    if not work and not identity_of_commits(root, mb, sha):
        return out("not-bot-authored")
    for old_mode, new_mode, status, path in changes:
        if new_mode in ("120000", "160000") or status == "T" or (status == "M" and old_mode != new_mode):
            return out("unexpected-change", path)
    for path in files:
        if chk.is_protected(path, resolved):
            return out("protected-path", path)
    moves: list[dict] = []
    for old_mode, new_mode, status, path in changes:
        if not chk.is_workflow(path):
            continue
        if status != "M":
            return out("workflow-not-a-bump", path)
        diff = git("diff", "-U0", "--no-ext-diff", "--no-textconv", mb, sha, "--", path, cwd=root).stdout
        found = chk.workflow_moves(diff)
        if found is None:
            return out("workflow-not-a-bump", path)
        if work:
            blob = git("rev-parse", "--verify", "--quiet", f"{sha}:{path}", cwd=root, check=False).stdout.strip()
            if not blob or not any(
                    git("rev-parse", "--verify", "--quiet", f"{tip}:{path}", cwd=root, check=False).stdout.strip()
                    == blob for tip in bot_tips):
                return out("workflow-not-a-bump", path)
        moves += found
    for path in lockfiles:
        if not chk.is_covered(path, globs):
            return out("lock-uncovered", path)
    if not changed:
        return out("lockfile-only")
    return out(None, None, moves)


def neutral_commit(root, sha, mb, lockfiles) -> str:
    """A commit of `sha`'s tree with the lockfiles put back to `mb`'s blobs, child of `mb`."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("read-tree", sha, cwd=root, env_extra=env)
        for path in lockfiles:
            listed = git("ls-tree", "-z", mb, "--", path, cwd=root).stdout
            if listed:
                meta, _, _name = listed.rstrip("\0").partition("\t")
                mode, _, blob = meta.split()
                git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", cwd=root, env_extra=env)
            else:
                git("update-index", "--force-remove", "--", path, cwd=root, env_extra=env)
        tree = git("write-tree", cwd=root, env_extra=env).stdout.strip()
    return git("commit-tree", tree, "-p", mb, "-m", "neutral", cwd=root, env_extra=IDENT).stdout.strip()


def raw_paths(root, a, b) -> list[str]:
    out = git("diff", "--raw", "--no-renames", "--no-ext-diff", "-z", a, b, cwd=root).stdout.split("\0")
    return [out[i + 1] for i in range(0, len(out) - 1, 2) if out[i].startswith(":")]


def apply_group(root, head, mb, sha, changed, lockfiles, ref):
    """(new head or None, reason or None): merge `sha` without its lockfiles into `head`."""
    neutral = neutral_commit(root, sha, mb, lockfiles)
    merged = git("merge-tree", "--write-tree", "--merge-base", mb, head, neutral, cwd=root, check=False)
    if merged.returncode == 1:
        return None, "does-not-apply"
    if merged.returncode != 0:
        raise DepsError(f"git merge-tree failed: {(merged.stderr or merged.stdout).strip()}")
    tree = merged.stdout.splitlines()[0].strip()
    if tree == git("rev-parse", f"{head}^{{tree}}", cwd=root).stdout.strip():
        return None, "no-change"
    # merge-tree follows renames between mb and head, which the group's own diff did not: the merge may then change
    # another path than the group does. Only the group's own non-lockfile paths may differ from head.
    if set(raw_paths(root, head, tree)) != set(changed):
        return None, "does-not-apply"
    new = git("commit-tree", tree, "-p", head, "-m", f"chore(deps): apply {ref}", cwd=root, env_extra=IDENT)
    return new.stdout.strip(), None


def prepare(args) -> tuple[dict, int]:
    root = git("rev-parse", "--show-toplevel").stdout.strip()
    for value in [args.base, args.branch, *args.group, *args.bot_ref]:
        if not plain_name(value):
            raise DepsError(f"not a plain ref name: {value}")
    if git("status", "--porcelain", "--untracked-files=no", cwd=root).stdout.strip():
        raise DepsError("the working tree has uncommitted changes")
    head_ref = f"refs/heads/{args.branch}"
    if git("rev-parse", "--verify", "--quiet", head_ref, cwd=root, check=False).returncode == 0 \
            or head_ref in ls_remote_heads(root, head_ref):
        raise DepsError(f"branch {args.branch} already exists")
    for ref in [*args.group, *args.bot_ref]:
        if commit_sha(root, ref) is None:
            raise DepsError(f"unknown ref: {ref}")
    t = trusted(root)
    if not t.available:
        raise DepsError(f"no trusted copy of the profile ({t.problem})")
    if t.profile is None:
        raise DepsError("the remote default branch has no .tld/toolkit.yaml")
    base_sha = choose_base(root, args.base, t)
    resolved = resolve(t.profile)
    entries = lock_entries(t.profile, resolved)

    bot_report, bot_tips = check_bot_refs(root, base_sha, args.bot_ref)
    head = base_sha
    groups, applied = [], []
    for ref in args.group:
        sha = commit_sha(root, ref)
        entry = {"ref": ref, "sha": None, "state": "left_out", "reason": None, "file": None,
                 "files": [], "lockfiles": [], "workflow_moves": []}
        groups.append(entry)
        mb = git("merge-base", base_sha, sha, cwd=root, check=False).stdout.strip()
        if not mb:
            entry["reason"] = "does-not-apply"
            continue
        reason, file, moves, files, lockfiles = classify(root, ref, sha, mb, resolved, entries, bot_tips)
        entry.update(files=files, lockfiles=lockfiles, file=file if reason in chk.FILE_REASONS else None)
        if reason:
            entry["reason"] = reason
            continue
        new, reason = apply_group(root, head, mb, sha, [f for f in files if f not in lockfiles], lockfiles, ref)
        if reason:
            entry["reason"] = reason
            continue
        head = new
        entry.update(sha=new, state="applied", workflow_moves=moves)
        applied.append(entry)

    selected = []
    for i, e in enumerate(entries):
        when, locks = e.get("when", []), e.get("lockfiles", [])
        hit = any(matches(g, f) for a in applied for f in a["files"] if f not in a["lockfiles"] for g in when) \
            or any(matches(g, f) for a in applied for f in a["lockfiles"] for g in locks)
        if hit:
            selected.append({"index": i, "run": e.get("run"), "when": when, "lockfiles": locks})
    result = {"branch": args.branch, "base": args.base, "base_sha": base_sha, "groups": groups,
              "bot_refs": bot_report, "lock_commands": selected}
    if not applied:
        return result, 3
    git("update-ref", head_ref, head, ZERO, cwd=root)
    checkout = git("checkout", "-q", args.branch, "--", cwd=root, check=False)
    if checkout.returncode != 0:
        git("update-ref", "-d", head_ref, cwd=root, check=False)
        raise DepsError(f"cannot check out {args.branch}: {(checkout.stderr or checkout.stdout).strip()}")
    return result, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tld ops deps-prepare", description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="the remote default branch (a ref)")
    ap.add_argument("--branch", required=True, help="the combined branch to create")
    ap.add_argument("--group", action="append", required=True, default=[], help="a group's branch; repeatable")
    ap.add_argument("--bot-ref", action="append", default=[], help="a Dependabot branch a work branch was built from")
    args = ap.parse_args(argv)
    try:
        result, code = prepare(args)
    except DepsError as exc:
        print(f"deps: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
