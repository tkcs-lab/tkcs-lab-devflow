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
import sys

from tld.guard import _common, markers
from tld.guard._common import BUILTIN_PROTECT_ALLOW, DEFAULT_PROTECT_PATHS, GUARDED_WORKFLOWS, Ctx
from tld.guard._gitgh import Item, iter_items
from tld.guard._shell import ParseError, base, is_dynamic

NAME = "protect-paths"
# Guardrail files: protected whatever the profile says (hooks.protect_paths and protect_paths_allow never remove them).
# Neutral ones only; the Claude adapter passes its own (`~/.claude/**`, `.mcp.json`) as settings.extra_protected.
ALWAYS_PROTECTED = [".git/config", ".git/hooks/**", ".git/tld/**"]  # .git/tld: the guards' own markers
# Protected on their absolute/home path, wherever the write is (S8): git's own configuration.
ALWAYS_PROTECTED_ABS = ["~/.gitconfig", "~/.config/git/**"]
CONFIG_PREFIXES = ("alias.", "remote.", "push.", "branch.", "include.", "includeif.", "url.")
CONFIG_EXACT = ("core.hookspath",)  # sets the hooks directory; can run arbitrary code on the next git command
CONFIG_WRITE_OPTS = {"--add", "--replace-all", "--unset", "--unset-all", "--rename-section", "--remove-section",
                     "-e", "--edit"}
CONFIG_VALUE_OPTS = {"-f", "--file", "--blob", "-t", "--type", "--default", "--comment"}
BRACE_CAP = 64
WRITE_OPS = {">", ">>", ">|", "&>", "&>>", ">&", "<>"}
PROFILE = ".tld/toolkit.yaml"
PROFILE_MARKER = markers.KINDS["profile"][0]
PROFILE_TTL_SECONDS = markers.KINDS["profile"][1]   # /setup may edit the profile for two hours after --allow-profile


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


def _abspath(path: str, here: str) -> str:
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(here, path))


def abs_match(pattern: str, path_abs: str) -> bool:
    """Match an absolute or `~`-rooted pattern against an absolute path, with the same `**`/`*` rules."""
    pat = os.path.expanduser(pattern)
    if pat.endswith("/"):
        pat += "**"
    for cand in dict.fromkeys([path_abs, os.path.realpath(path_abs)]):
        if _regex(pat).match(cand):
            return True
    return False


def outside_protected(ctx: Ctx, path: str, here: str) -> str | None:
    """S8: files outside the project that a session must not edit, matched on their absolute path
    (git's own config, and whatever the adapter lists, e.g. `~/.claude/**`)."""
    path_abs = _abspath(path, here)
    patterns = list(ALWAYS_PROTECTED_ABS) + [p for p in ctx.settings.extra_protected if p.startswith(("~", "/"))]
    for pat in patterns:
        if abs_match(pat, path_abs):
            return (f"blocked: `{path}` is a protected file ({pat}); a session does not edit it. "
                    "Describe the change you need in your report instead.")
    return None


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


def profile_allowed(project: str) -> bool:
    """True while the /setup marker of this checkout is younger than the TTL."""
    return markers.read(project, "profile") is not None


def workflow_install_allowed(project: str, rel: str) -> bool:
    """True while the install marker of this checkout names this workflow file and is younger than its TTL."""
    data = markers.read(project, "workflow-install") or {}
    files = data.get("files")
    return isinstance(files, list) and rel in files


def workflow_message(rel: str) -> str:
    return (f"blocked: `{rel}` is a tld workflow file; it is written only by the step that installs it (`/land`, "
            "`repo-admin`), after `tld guard allow-workflow-install " + os.path.basename(rel) + "` and until "
            "`tld guard end-allow`. Describe the change you need in your report instead.")


def plugin_root_hit(path: str, here: str) -> str | None:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return None
    path = os.path.expanduser(path)
    absolute = os.path.normpath(path if os.path.isabs(path) else os.path.join(here, path))
    for cand in dict.fromkeys([absolute, os.path.realpath(absolute)]):
        for r in dict.fromkeys([os.path.normpath(root), os.path.realpath(root)]):
            if cand == r or cand.startswith(r.rstrip("/") + "/"):
                return (f"blocked: `{cand}` is a protected path (it is under $CLAUDE_PLUGIN_ROOT, the installed "
                        "plugin). Describe the change you need in your report instead.")
    return None


def violation(ctx: Ctx, path: str, here: str) -> str | None:
    protect = ctx.list_key("protect_paths", DEFAULT_PROTECT_PATHS)
    allow = BUILTIN_PROTECT_ALLOW + ctx.list_key("protect_paths_allow", [])
    hit = plugin_root_hit(path, here) or outside_protected(ctx, path, here)
    if hit:
        return hit
    always = ALWAYS_PROTECTED + [p for p in ctx.settings.extra_protected if not p.startswith(("~", "/"))]
    for rel in relative(ctx, path, here):
        for pat in always:
            if matches(pat, rel):
                return message(rel, pat)
        if rel in GUARDED_WORKFLOWS:
            if workflow_install_allowed(ctx.project_dir, rel):
                continue
            return workflow_message(rel)
        if any(matches(a, rel) for a in allow):
            continue
        if rel == PROFILE and profile_allowed(ctx.project_dir):
            continue
        for pat in protect:
            if matches(pat, rel):
                return message(rel, pat)
    return None


def hard_link_hit(ctx: Ctx, path: str, here: str) -> str | None:
    """The write target is another name (hard link) for an existing protected file: same (device, inode)."""
    target = os.path.normpath(os.path.expanduser(path) if os.path.isabs(os.path.expanduser(path))
                              else os.path.join(here, os.path.expanduser(path)))
    try:
        st = os.stat(target)
    except OSError:
        return None
    if st.st_nlink < 2 or not os.path.isfile(target):
        return None
    protect = ctx.list_key("protect_paths", DEFAULT_PROTECT_PATHS) + ALWAYS_PROTECTED + GUARDED_WORKFLOWS
    root = os.path.realpath(ctx.project_dir)
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".venv", "__pycache__")]
        for fn in filenames:
            seen += 1
            if seen > 50000:
                return None
            full = os.path.join(dirpath, fn)
            try:
                other = os.stat(full)
            except OSError:
                continue
            if (other.st_dev, other.st_ino) != (st.st_dev, st.st_ino) or os.path.realpath(full) == os.path.realpath(target):
                continue
            rel = os.path.relpath(full, root)
            if any(matches(p, rel) for p in protect):
                return (f"blocked: `{path}` is a hard link to the protected path `{rel}`. "
                        "Describe the change you need in your report instead.")
    return None


def expand_braces(word: str) -> list[str] | None:
    """Bash brace expansion of `{a,b}` groups (nested allowed); None when the result exceeds BRACE_CAP."""
    start = word.find("{")
    while start != -1:
        depth, commas, i = 0, [], start
        while i < len(word):
            c = word[i]
            depth += c == "{"
            depth -= c == "}"
            if c == "," and depth == 1:
                commas.append(i)
            if depth == 0:
                break
            i += 1
        if depth == 0 and commas:
            bounds = [start, *commas, i]
            out: list[str] = []
            for a, b in zip(bounds, bounds[1:]):
                sub = expand_braces(word[:start] + word[a + 1:b] + word[i + 1:])
                if sub is None:
                    return None
                out += sub
                if len(out) > BRACE_CAP:
                    return None
            return out
        start = word.find("{", start + 1)
    return [word]


def message(rel: str, pattern: str) -> str:
    name = os.path.basename(rel)
    if rel == ".tld/toolkit.yaml":
        hint = "The project profile is changed by people or by /setup, not by a session; tell the user what should change."
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
            "hooks.protect_paths_allow in .tld/toolkit.yaml.")


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
        elif it.git and it.git.sub == "checkout":
            gargs = it.git.args
            if "--" in gargs:
                paths += gargs[gargs.index("--") + 1:]
            else:  # S17: `git checkout <ref> <path>` with no `--`: treat every positional as a candidate path
                positional = parse_args(gargs, {"-b", "-B", "--orphan", "--conflict", "--pathspec-from-file"})[0]
                paths += [p for p in positional if p not in ("-b", "-B")]
        elif it.git and it.git.sub == "restore":
            paths += parse_args(it.git.args, {"--source", "-s", "--pathspec-from-file"})[0]
        elif it.git and it.git.sub == "apply":  # S17: applies a patch; the files it writes are named inside it
            for pf in parse_args(it.git.args, {"--exclude", "--include", "--directory", "-p",
                                               "--build-fake-ancestor", "--whitespace"})[0]:
                paths += patch_targets(os.path.join(it.dir, os.path.expanduser(pf)))
    elif name == "patch":  # S17: `patch target < diff`, or `patch -i diff target`
        positional, _ = parse_args(args, {"-i", "--input", "-o", "--output", "-p", "--strip", "-d", "--directory",
                                          "-B", "-r", "-D", "-F", "-g", "-z", "-V"})
        paths += positional
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


def patch_targets(path: str) -> list[str]:
    """Repo-relative files a unified diff writes: the `+++ b/<path>` lines (and `diff --git`)."""
    out: list[str] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(1_000_000)
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith("+++ ") and line[4:].strip() not in ("/dev/null", ""):
            target = line[4:].strip().split("\t")[0]
            out.append(target[2:] if target[:2] in ("a/", "b/") else target)
        elif line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                b = parts[3]
                out.append(b[2:] if b[:2] in ("a/", "b/") else b)
    return list(dict.fromkeys(out))


def config_violation(it: Item) -> str | None:
    """`git config` writes of keys that can redirect pushes or run commands (alias, remote, push, branch, include)."""
    if not it.git or it.git.sub != "config":
        return None
    positional, opts = parse_args(it.git.args, CONFIG_VALUE_OPTS)
    names = {o for o, _ in opts}
    write = bool(names & CONFIG_WRITE_OPTS) or len(positional) >= 2
    keys = [k.lower() for k in positional[:2 if "--rename-section" in names else 1]]
    if write and (not keys or any(k.startswith(CONFIG_PREFIXES) or k in CONFIG_EXACT for k in keys)):
        return ("blocked: `git config` write to " + (f"`{positional[0]}`" if positional else "the git configuration")
                + " would change a protected path (git's configuration can redirect pushes or run commands). "
                "Ask the user to make this change.")
    return None


def link_sources(it: Item) -> list[str]:
    if not it.words or base(it.words[0]) != "ln":
        return []
    positional, opts = parse_args(it.words[1:], VALUE_OPTS["ln"])
    if any(o in TARGET_DIR_OPTS for o, _ in opts) or len(positional) == 1:
        return positional
    return positional[:-1]


def _resolve_env(path: str, env: dict[str, str]) -> str:
    """Substitute `$NAME` / `${NAME}` by a literal value the same command set in front of it."""
    if "$" not in path or not env:
        return path
    for name, value in env.items():
        if value and not is_dynamic(value):
            path = path.replace("${" + name + "}", value).replace("$" + name, value)
    return path


def check_bash(ctx: Ctx, command: str) -> str | None:
    try:
        items = list(iter_items(ctx.cwd, command))
    except ParseError:
        return None  # the destructive hooks refuse unparseable commands; this one only guards paths
    seen_env: dict[str, str] = {}  # NAME=value assignments from earlier simple commands (`F=.env; echo x > $F`)
    for it in items:
        for name, value in it.env.items():
            if value and not is_dynamic(value):
                seen_env[name] = value
        msg = config_violation(it)
        if msg:
            return msg
        for src in link_sources(it):
            if is_dynamic(src):
                continue
            for cand in expand_braces(src) or [src]:
                msg = violation(ctx, cand, it.dir) or violation(ctx, os.path.join(cand, "x"), it.dir)
                if msg:
                    return msg
        for path in written_paths(it):
            path = _resolve_env(path, {**seen_env, **it.env})  # S17: `F=.env; echo x > $F`
            if is_dynamic(path):
                continue
            words = expand_braces(path)
            if words is None:
                return (f"blocked: `{path}` expands to more than {BRACE_CAP} paths, so it cannot be checked "
                        "against the protected paths.")
            for word in words:
                expanded = globmod.glob(os.path.join(it.dir, os.path.expanduser(word))) if any(
                    ch in word for ch in "*?[") else []
                for candidate in [word, *expanded]:
                    msg = violation(ctx, candidate, it.dir) or hard_link_hit(ctx, candidate, it.dir)
                    if msg:
                        return msg
    return None


def evaluate(ctx: Ctx) -> str | None:
    if ctx.action.kind == "write":
        path = ctx.action.path
        return violation(ctx, path, ctx.cwd) if isinstance(path, str) and path else None
    if ctx.action.kind == "shell" and isinstance(ctx.action.command, str):
        return check_bash(ctx, ctx.action.command)
    return None


def main(argv: list[str] | None = None) -> int:
    """The `tld guard allow-*` / `end-allow` command line (the hook path goes through the adapter)."""
    return markers.cli(list(sys.argv[1:] if argv is None else argv))


cli = markers.cli  # the adapter hands the old flag forms (`protect_paths.py --allow-profile`) to `cli`


if __name__ == "__main__":
    sys.exit(main())
