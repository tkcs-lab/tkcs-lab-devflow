"""Cross-cutting checks the three destructive guards all run, before their own question.

They close ways to get a write past a guard without the guard seeing it as a write:

- S3  a command whose name is only known at run time, followed by words that look like a git/gh write.
- S4  git configuration pulled in from a file or the environment (`-c include.*`, `GIT_CONFIG_GLOBAL`,
      `GIT_CONFIG_PARAMETERS`, `GIT_DIR` ...), which can set a push destination or an alias we cannot see.
- S1  writes to the refs the trusted profile is read from: `refs/tld/*`, `refs/remotes/origin/<main>`,
      `refs/heads/<main>`, and repointing `origin` (`remote set-url`, `remote add` over origin, `-c remote.origin.url`).

Each returns a deny message (without a guard prefix) or None. A guard calls `integrity(ctx, it)` for every
item and `dynamic_command(command)` once; a hit is denied with that guard's own "what to do instead".
"""
from __future__ import annotations

import os

from tld.guard._gitgh import Item, parse_push, parse_refspecs, short_ref
from tld.guard._shell import DYN, base, is_dynamic, walk_commands

# Words that make a run-time command name worth denying (a git/gh write of some kind).
WRITE_WORDS = {"push", "merge", "tag", "update-ref", "api", "pr", "release", "workflow", "run", "send-pack",
               "http-push", "fetch", "remote", "config", "symbolic-ref", "branch"}
# Leading NAME=value assignments that redirect git's configuration.
DANGEROUS_ENV = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_DIR",
                 "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
CONFIG_INJECT = ("include.", "includeif.")
# Config keys that repoint a remote.
URL_KEYS = ("remote.origin.url", "remote.origin.pushurl")


def is_tld_launcher(word: str) -> bool:
    """A `.../bin/tld` or bare `tld` invocation: the commands use it and it must stay allowed."""
    stripped = word.strip("\"'")
    return base(stripped) == "tld" or stripped.endswith("/bin/tld")


def dynamic_command(command: str) -> str | None:
    """S3: the command name is a run-time value and the rest looks like a git/gh write."""
    for _, cmd in walk_commands(command):
        words = cmd.words
        if not words or not is_dynamic(words[0]) or is_tld_launcher(words[0]):
            continue
        rest = {w for w in words[1:] if not is_dynamic(w)}
        hit = rest & WRITE_WORDS
        if hit:
            return (f"blocked: the command name `{words[0]}` is only known at run time and is followed by "
                    f"`{sorted(hit)[0]}`, so it could be a git or gh write that cannot be checked. Write the "
                    "command with its real name (`git ...`, `gh ...`) so the guardrails can read it.")
    return None


def _config_keys(it: Item) -> list[str]:
    return [item.partition("=")[0].lower() for item in (it.git.config if it.git else [])]


def config_injection(it: Item) -> str | None:
    """S4: git configuration taken from a file or the environment that could redirect a push or run a command."""
    if it.kind != "git" or it.git is None:
        return None
    for key in _config_keys(it):
        if key.startswith(CONFIG_INJECT):
            return (f"blocked: `-c {key}` pulls in another git config file, which can set a push destination "
                    "or an alias this guard cannot see. Run git without an include override.")
    for name in DANGEROUS_ENV:
        if name in it.env:
            return (f"blocked: `{name}=...` on a git command redirects git's configuration and can set a push "
                    "destination or alias this guard cannot see. Run git without it.")
    if it.git.repo_opts and any(o.startswith("--git-dir=") for o in it.git.repo_opts) and it.git.sub == "config":
        return None
    return None


def _protected_refs(mains: list[str]) -> set[str]:
    refs = {"refs/tld/trusted", "refs/tld"}
    for m in mains:
        refs |= {f"refs/heads/{m}", f"refs/remotes/origin/{m}", m, f"origin/{m}"}
    return refs


def _hits_protected(ref: str, mains: list[str]) -> bool:
    ref = ref.strip()
    if ref.startswith("refs/tld/") or ref == "refs/tld/trusted":
        return True
    short = short_ref(ref)
    for m in mains:
        if ref in (f"refs/heads/{m}", f"refs/remotes/origin/{m}", f"origin/{m}") or short == m:
            return True
    return False


def trusted_ref_write(it: Item, mains: list[str]) -> str | None:
    """S1: a local write to the refs the trusted profile is read from, or a repointing of `origin`."""
    if it.kind != "git" or it.git is None:
        return None
    sub, args = it.git.sub, it.git.args
    msg = ("blocked: writing `{ref}` would change which profile the guardrails trust (they read "
           "hooks.disable and the protect lists from the remote main branch, fetched to refs/tld/trusted). "
           "A session does not move these refs; branch protection on the remote is the control.")
    if sub == "update-ref":
        if "--stdin" in args:
            return msg.format(ref="a ref through --stdin")
        for a in args:
            if not a.startswith("-") and _hits_protected(a, mains):
                return msg.format(ref=a)
    if sub == "symbolic-ref":
        positional = [a for a in args if not a.startswith("-")]
        if positional and _hits_protected(positional[0], mains):
            return msg.format(ref=positional[0])
    if sub == "branch":
        force = any(a in ("-f", "--force", "-M", "-C") or (a.startswith("-") and not a.startswith("--") and
                    ("f" in a[1:] or "M" in a[1:])) for a in args)
        positional = [a for a in args if not a.startswith("-")]
        if (force or any(a in ("-M", "-C") for a in args)) and positional and _hits_protected(positional[0], mains):
            return msg.format(ref=f"refs/heads/{positional[0]}")
    if sub == "fetch":
        for a in args:
            if ":" in a and not a.startswith("-"):
                dst = a.split(":", 1)[1]
                if _hits_protected(dst, mains):
                    return msg.format(ref=dst)
    if sub == "remote":
        if args[:1] == ["set-url"] and "origin" in args[1:3]:
            return ("blocked: `git remote set-url origin ...` repoints the remote the guardrails trust. "
                    "A session does not change origin's URL.")
        if args[:1] == ["add"] and "origin" in args:
            return ("blocked: `git remote add origin ...` would define the remote the guardrails trust. "
                    "A session does not add or replace origin.")
    for key in _config_keys(it):
        if key in URL_KEYS:
            return ("blocked: `-c remote.origin.url=...` (or pushurl) repoints the remote the guardrails trust. "
                    "Run git against the real origin.")
    if it.git.sub == "config":
        positional = [a for a in args if not a.startswith("-")]
        if positional and positional[0].lower() in URL_KEYS and len(positional) >= 2:
            return ("blocked: `git config remote.origin.url ...` repoints the remote the guardrails trust. "
                    "A session does not change origin's URL.")
    return None


def integrity(ctx, it: Item) -> str | None:
    """Every per-item integrity check. Works even without a main branch in the profile (refs/tld/* still covered)."""
    from tld.guard._common import ProfileError
    try:
        mains = ctx.main_branches()
    except ProfileError:
        mains = []
    return config_injection(it) or trusted_ref_write(it, mains)
