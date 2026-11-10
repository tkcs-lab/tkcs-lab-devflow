"""Parsing of `git` and `gh` command lines for the devflow guardrail hooks (stdlib only).

The hooks ask questions such as "does this push force?", "which refs does it update?" or "does this
`gh api` call merge?". Nothing here runs a network command; the few `git` lookups (current branch,
does a tag exist, is this word an alias) are local reads.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field

from _shell import DYN, ParseError, base, candidates, is_dynamic, split_commands, walk

# ------------------------------------------------------------------------------------- git

GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env",
                  "--exec-path", "--attr-source"}


@dataclass
class Git:
    sub: str | None
    args: list[str]
    dirs: list[str] = field(default_factory=list)      # every -C value, in order
    config: list[str] = field(default_factory=list)    # every -c value (key=value)
    repo_opts: list[str] = field(default_factory=list)  # --git-dir / --work-tree, as given


def parse_git(words: list[str]) -> Git:
    """words[0] is `git`. Splits global options from the subcommand and its arguments."""
    dirs: list[str] = []
    config: list[str] = []
    repo_opts: list[str] = []
    i = 1
    while i < len(words):
        w = words[i]
        if not w.startswith("-"):
            break
        name, eq, val = w.partition("=")
        if name in GIT_VALUE_OPTS and not eq and name != "--exec-path":
            val = words[i + 1] if i + 1 < len(words) else ""
            i += 1
        if name == "-C":
            dirs.append(val)
        elif name == "-c":
            config.append(val)
        elif name in ("--git-dir", "--work-tree"):
            repo_opts.append(f"{name}={val}")
        i += 1
    sub = words[i] if i < len(words) else None
    return Git(sub, words[i + 1:], dirs, config, repo_opts)


def git_context(cwd: str, git: Git) -> str:
    """The directory `git` effectively runs in: cwd followed by every -C (relative ones chain)."""
    path = cwd
    for d in git.dirs:
        path = d if os.path.isabs(d) else os.path.join(path, d)
    return path


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


def expand_alias(git: Git, ctx_dir: str, known: set[str]) -> list[list[str]] | None:
    """If `git.sub` is a configured alias, the command lines it stands for (one per command), else None."""
    if git.sub is None or git.sub in known:
        return None
    value = None
    for item in git.config:
        if item.startswith(f"alias.{git.sub}="):
            value = item.split("=", 1)[1]
    if value is None:
        value = _run_git(ctx_dir, git.repo_opts, "config", "--get", f"alias.{git.sub}")
    if not value:
        return None
    if value.startswith("!"):
        out: list[list[str]] = []
        for cmd in split_commands(value[1:] + " " + " ".join(shlex.quote(a) for a in git.args)):
            out += [c.words for c in candidates(cmd.words, cmd.redirects)]
        return out
    try:
        words = shlex.split(value)
    except ValueError as exc:
        raise ParseError(f"alias {git.sub}: {exc}") from None
    return [["git", *words, *git.args]]


GIT_KNOWN = {"add", "am", "apply", "bisect", "blame", "branch", "checkout", "cherry-pick", "clean", "clone",
             "commit", "config", "describe", "diff", "fetch", "grep", "init", "log", "ls-files", "ls-remote",
             "ls-tree", "merge", "merge-base", "mv", "pull", "push", "rebase", "reflog", "remote", "reset",
             "restore", "revert", "rev-list", "rev-parse", "rm", "shortlog", "show", "show-ref", "stash",
             "status", "submodule", "switch", "symbolic-ref", "tag", "update-ref", "worktree", "cat-file",
             "for-each-ref", "gc", "help", "version", "bundle", "archive", "notes", "format-patch"}


@dataclass
class Item:
    """One command that may run: kind is 'git', 'gh' or 'other'."""
    kind: str
    words: list[str]
    dir: str                      # directory it runs in (cd and -C applied)
    git: Git | None = None
    redirects: list[tuple[str, str]] = field(default_factory=list)


def iter_items(cwd: str, command: str):
    """Every command `command` may run, aliases expanded. Raises ParseError on unparseable input."""
    for hint, words, redirects in walk(command):
        here = cwd if not hint else hint if os.path.isabs(hint) else os.path.join(cwd, hint)
        yield from _items(words, here, redirects, 0)


def _items(words: list[str], here: str, redirects, depth: int):
    if not words:
        yield Item("other", [], here, None, redirects)
        return
    name = base(words[0])
    if name == "git":
        git = parse_git(words)
        ctx_dir = git_context(here, git)
        aliased = expand_alias(git, ctx_dir, GIT_KNOWN) if depth < 3 else None
        if aliased:
            for aw in aliased:
                yield from _items(aw, ctx_dir, [], depth + 1)
        yield Item("git", words, ctx_dir, git, redirects)
    elif name == "gh":
        yield Item("gh", words, here, None, redirects)
    else:
        yield Item("other", words, here, None, redirects)


# ------------------------------------------------------------------------------------- push

LONG_FORCE = ("force", "force-with-lease", "force-if-includes")
LONG_DELETE = ("delete", "prune", "mirror")
LONG_TAGS = ("tags", "follow-tags")
LONG_ALL = ("all", "branches", "mirror")
PUSH_VALUE_LONG = {"push-option", "repo", "receive-pack", "exec"}  # also accepted with `=`


def _long_is(name: str, targets: tuple[str, ...]) -> bool:
    """git accepts any unambiguous prefix of a long option; treat a prefix of a dangerous one as it."""
    return len(name) >= 2 and any(t.startswith(name) for t in targets)


@dataclass
class Push:
    force: bool = False
    delete: bool = False
    tags: bool = False
    all_refs: bool = False
    repo: str | None = None
    refspecs: list[str] = field(default_factory=list)


def parse_push(args: list[str]) -> Push:
    p = Push()
    positional: list[str] = []
    repo_opt: str | None = None
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            positional += args[i:]
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in PUSH_VALUE_LONG and not eq:
                val = args[i] if i < len(args) else ""
                i += 1
            if name == "repo":
                repo_opt = val
            if _long_is(name, LONG_FORCE):
                p.force = True
            if _long_is(name, LONG_DELETE):
                p.delete = True
            if _long_is(name, LONG_TAGS):
                p.tags = True
            if _long_is(name, LONG_ALL):
                p.all_refs = True
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if ch == "f":
                    p.force = True
                elif ch == "d":
                    p.delete = True
                elif ch == "o":  # -o <option> or -o<option>
                    if k == len(a) - 1:
                        i += 1
                    break
        else:
            positional.append(a)
    if repo_opt is not None:
        p.repo, p.refspecs = repo_opt, positional
    elif positional:
        p.repo, p.refspecs = positional[0], positional[1:]
    return p


@dataclass
class Refspec:
    raw: str
    plus: bool       # leading "+"
    src: str
    dst: str
    delete: bool     # ":dst"
    dynamic: bool    # the destination is only known at run time


def parse_refspecs(specs: list[str]) -> list[Refspec]:
    out: list[Refspec] = []
    for raw in specs:
        spec = raw
        plus = spec.startswith("+")
        if plus:
            spec = spec[1:]
        src, colon, dst = spec.partition(":")
        if not colon:
            dst = src
        elif dst == "":
            dst = src
        out.append(Refspec(raw, plus, src, dst, colon == ":" and src == "" and dst != "", is_dynamic(dst)))
    return out


def short_ref(ref: str) -> str:
    for prefix in ("refs/heads/", "heads/"):
        if ref.startswith(prefix):
            return ref[len(prefix):]
    return ref


def has_glob(s: str) -> bool:
    return any(ch in s for ch in "*?[")


# ------------------------------------------------------------------------------------- gh

GH_VALUE_OPTS = {"-R", "--repo", "--hostname"}
GH_API_VALUE = {"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header", "-q", "--jq",
                "-t", "--template", "--input", "--hostname", "-p", "--preview", "--cache"}


def gh_path(words: list[str]) -> list[str]:
    """`gh` subcommand words with options removed: ['pr', 'merge'], ['api', 'repos/..'] ..."""
    out: list[str] = []
    i = 1
    while i < len(words):
        w = words[i]
        if w.startswith("-"):
            name = w.partition("=")[0]
            if name in GH_VALUE_OPTS and "=" not in w:
                i += 1
        else:
            out.append(w)
        i += 1
    return out


@dataclass
class GhApi:
    endpoint: str = ""
    method: str = "GET"
    fields: dict[str, str] = field(default_factory=dict)
    input_file: str | None = None
    texts: list[str] = field(default_factory=list)  # every field value, for GraphQL scanning


def parse_gh_api(words: list[str]) -> GhApi:
    """words: ['gh', 'api', ...]."""
    api = GhApi()
    explicit: str | None = None
    has_body = False
    positional: list[str] = []
    i = 2
    while i < len(words):
        w = words[i]
        i += 1
        if w.startswith("--"):
            name, eq, val = w.partition("=")
            if name in GH_API_VALUE and not eq:
                val = words[i] if i < len(words) else ""
                i += 1
        elif w.startswith("-") and len(w) > 1:
            name, val = w[:2], w[2:]
            if name in GH_API_VALUE and not val:
                val = words[i] if i < len(words) else ""
                i += 1
        else:
            positional.append(w)
            continue
        if name in ("-X", "--method"):
            explicit = val.upper()
        elif name in ("-f", "--raw-field", "-F", "--field"):
            has_body = True
            key, _, v = val.partition("=")
            api.fields[key] = v
            api.texts.append(v)
        elif name == "--input":
            has_body = True
            api.input_file = val
    if positional:
        api.endpoint = positional[0].split("?")[0].lstrip("/")
        if api.endpoint.startswith(("http://", "https://")):
            api.endpoint = api.endpoint.split("/", 3)[-1]
    api.method = explicit or ("POST" if has_body else "GET")
    return api


def read_input_text(api: GhApi, cwd: str) -> str | None:
    """Contents of `--input <file>` (up to 1 MB) or None when it cannot be read (stdin, missing)."""
    if not api.input_file or api.input_file == "-":
        return None
    path = api.input_file if os.path.isabs(api.input_file) else os.path.join(cwd, api.input_file)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(1_000_000)
    except OSError:
        return None


__all__ = [n for n in dir() if not n.startswith("_")] + ["DYN"]
