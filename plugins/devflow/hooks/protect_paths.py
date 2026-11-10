#!/usr/bin/env python3
"""PreToolUse hook `protect-paths`: deny edits to the paths the profile lists.

Covers Write / Edit / MultiEdit / NotebookEdit, and the file writes a Bash command visibly makes:
redirections, tee, sed -i, perl -i, cp, mv, install, ln, rm, unlink, truncate, touch, dd of=, git rm,
git mv. A program that writes a file on its own (a package manager updating its lockfile, a Python
one-liner) is not seen; that is why lockfiles are protected from hand edits, not from tools.
"""
from __future__ import annotations

import glob as globmod
import os
import re

import _common
from _common import BUILTIN_PROTECT_ALLOW, DEFAULT_PROTECT_PATHS, Ctx
from _gitgh import Item, iter_items
from _shell import ParseError, base, is_dynamic

NAME = "protect-paths"
WRITE_OPS = {">", ">>", ">|", "&>", "&>>", ">&", "<>"}


# --------------------------------------------------------------------------- patterns

def _regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(pattern: str, rel: str) -> bool:
    """A pattern without a slash matches the file name at any depth; one with a slash is anchored at
    the repository root. `**` crosses directories, `*` and `?` do not. A trailing slash means the directory."""
    pattern = pattern[2:] if pattern.startswith("./") else pattern.lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    if "/" not in pattern:
        return bool(_regex(pattern).match(os.path.basename(rel)))
    return bool(_regex(pattern).match(rel))


def relative(ctx: Ctx, path: str, here: str) -> list[str]:
    """Repo-relative spellings of `path` (as written, and with symlinks resolved); [] when outside."""
    path = os.path.expanduser(path)
    absolute = os.path.normpath(path if os.path.isabs(path) else os.path.join(here, path))
    roots = {os.path.normpath(ctx.project_dir), os.path.realpath(ctx.project_dir)}
    found: list[str] = []
    for candidate in dict.fromkeys([absolute, os.path.realpath(absolute)]):
        for root in roots:
            rel = os.path.relpath(candidate, root)
            if rel != ".." and not rel.startswith("../") and rel != ".":
                found.append(rel)
    return list(dict.fromkeys(found))


def violation(ctx: Ctx, path: str, here: str) -> str | None:
    protect = ctx.list_key("protect_paths", DEFAULT_PROTECT_PATHS)
    allow = BUILTIN_PROTECT_ALLOW + ctx.list_key("protect_paths_allow", [])
    for rel in relative(ctx, path, here):
        if any(matches(a, rel) for a in allow):
            continue
        for pat in protect:
            if matches(pat, rel):
                return message(rel, pat)
    return None


def message(rel: str, pattern: str) -> str:
    name = os.path.basename(rel)
    if rel == ".claude/toolkit.yaml":
        hint = "The project profile is changed by people, not by a session; tell the user what should change."
    elif name.startswith(".env"):
        hint = "Environment files hold secrets and are never edited by a session; document a variable in .env.example instead."
    elif name.endswith(".lock") or name in ("package-lock.json", "go.sum"):
        hint = "Regenerate lockfiles with the project's own lock command (see deps.lock_freshness), never by hand."
    elif rel.startswith(".github/workflows/"):
        hint = "Workflow changes are made by the owner; describe the change you need in your report or the pull request."
    else:
        hint = "Describe the change you need in your report instead."
    return (f"blocked: `{rel}` is a protected path (it matches `{pattern}` in hooks.protect_paths). {hint} "
            "If the task really requires it, ask the user to make the change or to list the path under "
            "hooks.protect_paths_allow in .claude/toolkit.yaml.")


# --------------------------------------------------------------------------- Bash writes

VALUE_OPTS = {
    "touch": {"-d", "-t", "-r", "--date", "--reference"},
    "truncate": {"-s", "-r", "--size", "--reference"},
    "install": {"-m", "-o", "-g", "-S", "-t", "--mode", "--owner", "--group", "--suffix", "--target-directory"},
    "cp": {"-S", "-t", "--suffix", "--target-directory"},
    "mv": {"-S", "-t", "--suffix", "--target-directory"},
    "ln": {"-S", "-t", "--suffix", "--target-directory"},
    "sed": {"-e", "-f", "--expression", "--file", "-l", "--line-length"},
    "perl": {"-e", "-E", "-I", "-M", "-m"},
}
SCRIPT_OPTS = {"-e", "-E", "-f", "--expression", "--file"}
TARGET_DIR_OPTS = {"-t", "--target-directory"}


def parse_args(args: list[str], value_opts: set[str]) -> tuple[list[str], list[tuple[str, str | None]]]:
    """Positionals and (option, value) pairs of a simple command line."""
    positional: list[str] = []
    opts: list[tuple[str, str | None]] = []
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            positional += args[i:]
            break
        if a.startswith("-") and a != "-":
            name, eq, val = a.partition("=")
            if name in value_opts and not eq and i < len(args):
                val, i = args[i], i + 1
            opts.append((name, val if (eq or name in value_opts) else None))
        else:
            positional.append(a)
    return positional, opts


def _in_place(name: str, opts: list[tuple[str, str | None]]) -> bool:
    for opt, _ in opts:
        if opt == "--in-place":
            return True
        if opt.startswith("-") and not opt.startswith("--") and "i" in opt[1:] and (
                name == "perl" or name == "sed"):
            return True
    return False


def written_paths(it: Item) -> list[str]:
    paths = [t for op, t in it.redirects if op in WRITE_OPS and t and not re.fullmatch(r"\d+|-", t)]
    if not it.words:
        return paths
    name, args = base(it.words[0]), it.words[1:]
    if name == "git":
        if it.git and it.git.sub in ("rm", "mv"):
            paths += parse_args(it.git.args, set())[0]
    elif name == "tee":
        paths += parse_args(args, set())[0]
    elif name == "dd":
        paths += [a[3:] for a in args if a.startswith("of=")]
    elif name in ("sed", "perl"):
        positional, opts = parse_args(args, VALUE_OPTS[name])
        if _in_place(name, opts):  # the script is the first positional unless -e / -f gave it
            paths += positional if any(o in SCRIPT_OPTS for o, _ in opts) else positional[1:]
    elif name in ("rm", "unlink", "shred", "truncate", "touch"):
        paths += parse_args(args, VALUE_OPTS.get(name, set()))[0]
    elif name in ("cp", "install", "ln", "mv"):
        positional, opts = parse_args(args, VALUE_OPTS[name])
        target = next((v for o, v in opts if o in TARGET_DIR_OPTS), None)
        dest, sources = (target, positional) if target else (positional[-1], positional[:-1]) if positional else (None, [])
        if dest:
            paths.append(dest)
            if target or dest.endswith("/") or os.path.isdir(os.path.join(it.dir, os.path.expanduser(dest))):
                paths += [os.path.join(dest, os.path.basename(src.rstrip("/"))) for src in sources]
        if name == "mv":
            paths += sources
    return paths


def check_bash(ctx: Ctx, command: str) -> str | None:
    try:
        items = list(iter_items(ctx.cwd, command))
    except ParseError:
        return None  # the destructive hooks refuse unparseable commands; this one only guards paths
    for it in items:
        for path in written_paths(it):
            if is_dynamic(path):
                continue
            expanded = globmod.glob(os.path.join(it.dir, os.path.expanduser(path))) if any(
                ch in path for ch in "*?[") else []
            for candidate in [path, *expanded]:
                msg = violation(ctx, candidate, it.dir)
                if msg:
                    return msg
    return None


def evaluate(ctx: Ctx) -> str | None:
    if ctx.tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = ctx.tool_input.get("file_path") or ctx.tool_input.get("notebook_path")
        return violation(ctx, path, ctx.cwd) if isinstance(path, str) and path else None
    if ctx.tool == "Bash" and isinstance(ctx.tool_input.get("command"), str):
        return check_bash(ctx, ctx.tool_input["command"])
    return None


if __name__ == "__main__":
    _common.main(NAME, evaluate, fail_closed=False)
