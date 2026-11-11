#!/usr/bin/env python3
"""Sync a patch-carrying fork to the newest upstream release tag (without committing).

  plan    --upstream-url URL --version-file F --pattern RE
          prints {"current": ..., "latest": ..., "up_to_date": bool}
  prepare --upstream-url URL --version-file F --tag T --branch B --base REF
          creates branch B from REF, three-way merges upstream's old commit (base), the fork
          (HEAD) and tag T, rewrites the version file; prints `clean` (exit 0) or the conflicted
          paths (exit 2, markers left in the working tree). Never commits, never pushes.

The version file has exactly three lines: `tag: <tag>`, `commit: <40-hex sha>`, `synced_at: <YYYY-MM-DD>`.
Exit 1 and `upstream_sync: <message>` on any error; 3 when no release is eligible.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from tld.ops import pick_release


class SyncError(Exception):
    pass


def git(*args, cwd=None, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    env["PATH"] = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip() \
        + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(["git", "-c", "credential.helper=", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SyncError(f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def parse_version_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SyncError(f"cannot read version file {path} ({exc.strerror or exc})")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) != 3:
        raise SyncError(f"version file {path} must have exactly three lines (tag, commit, synced_at)")
    values = {}
    for line, key in zip(lines, ("tag", "commit", "synced_at")):
        prefix = f"{key}: "
        if not line.startswith(prefix) or not line[len(prefix):].strip():
            raise SyncError(f"version file {path}: expected line '{key}: <value>', got '{line}'")
        values[key] = line[len(prefix):].strip()
    if not re.fullmatch(r"[0-9a-f]{40}", values["commit"]):
        raise SyncError(f"version file {path}: 'commit' must be a 40-character lowercase hex sha")
    try:
        datetime.date.fromisoformat(values["synced_at"])
    except ValueError:
        raise SyncError(f"version file {path}: 'synced_at' must be a date YYYY-MM-DD")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["synced_at"]):
        raise SyncError(f"version file {path}: 'synced_at' must be a date YYYY-MM-DD")
    return values


def cmd_plan(args):
    current = parse_version_file(args.version_file)["tag"]
    out = git("ls-remote", "--tags", args.upstream_url).stdout
    try:
        latest = pick_release.choose(pick_release.parse_lines(out), args.pattern)
    except pick_release.PickError as exc:
        raise SyncError(str(exc))
    print(json.dumps({"current": current, "latest": latest, "up_to_date": latest == current}))
    return 0


def cmd_prepare(args):
    root = git("rev-parse", "--show-toplevel").stdout.strip()
    vfile = Path(args.version_file)
    if not vfile.is_absolute():
        vfile = Path(root) / vfile
    old = parse_version_file(vfile)
    if git("status", "--porcelain", "--untracked-files=no", cwd=root).stdout.strip():
        raise SyncError("the working tree has uncommitted changes")
    if git("rev-parse", "--verify", "-q", f"refs/heads/{args.branch}", cwd=root, check=False).returncode == 0:
        raise SyncError(f"branch {args.branch} already exists")
    git("checkout", "-b", args.branch, args.base, cwd=root)

    new_ref, old_ref = "refs/tld/new", "refs/tld/old"
    git("fetch", "--no-tags", args.upstream_url, f"+refs/tags/{args.tag}:{new_ref}", cwd=root)
    new_commit = git("rev-parse", f"{new_ref}^{{commit}}", cwd=root).stdout.strip()
    old_commit = old["commit"]
    if git("cat-file", "-e", f"{old_commit}^{{commit}}", cwd=root, check=False).returncode != 0:
        fetched = git("fetch", "--no-tags", args.upstream_url, f"+{old_commit}:{old_ref}", cwd=root, check=False)
        if fetched.returncode != 0:
            git("fetch", "--no-tags", args.upstream_url, f"+refs/tags/{old['tag']}:{old_ref}", cwd=root)
        if git("cat-file", "-e", f"{old_commit}^{{commit}}", cwd=root, check=False).returncode != 0:
            raise SyncError(f"recorded upstream commit {old_commit} is not in the upstream")

    git("read-tree", "-m", "-u", old_commit, "HEAD", new_commit, cwd=root)
    git("merge-index", "-o", "git-merge-one-file", "-a", cwd=root, check=False)
    unmerged = sorted({line.split("\t", 1)[1] for line in git("ls-files", "-u", cwd=root).stdout.splitlines()})

    vfile.write_text(f"tag: {args.tag}\ncommit: {new_commit}\n"
                     f"synced_at: {datetime.datetime.now(datetime.timezone.utc).date().isoformat()}\n",
                     encoding="utf-8")
    rel = os.path.relpath(vfile, root)
    if rel not in unmerged:
        git("add", "--", rel, cwd=root)
    if unmerged:
        print("\n".join(unmerged))
        return 2
    print("clean")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="upstream_sync.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="report the current and the newest release tag")
    p.add_argument("--upstream-url", required=True)
    p.add_argument("--version-file", required=True)
    p.add_argument("--pattern", required=True)
    p.set_defaults(func=cmd_plan)
    q = sub.add_parser("prepare", help="merge the new release into a new branch, without committing")
    q.add_argument("--upstream-url", required=True)
    q.add_argument("--version-file", required=True)
    q.add_argument("--tag", required=True)
    q.add_argument("--branch", required=True)
    q.add_argument("--base", required=True)
    q.set_defaults(func=cmd_prepare)
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except SyncError as exc:
        print(f"upstream_sync: {exc}", file=sys.stderr)
        return 1
    except pick_release.NoRelease:
        print("upstream_sync: no eligible release", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
