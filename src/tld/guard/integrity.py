"""Cross-cutting checks the three destructive guards all run, before their own question.

They close ways to get a write past a guard without the guard seeing it as a write:

- S3  a command whose name is only known at run time, followed by words that look like a git/gh write.
- S4  git configuration pulled in from a file or the environment (`-c include.*`, `GIT_CONFIG_GLOBAL`,
      `GIT_CONFIG_PARAMETERS`, `GIT_DIR` ...), which can set a push destination or an alias we cannot see.
- S1  writes to the refs the trusted profile is read from: `refs/tld/*`, `refs/replace/*`, `refs/remotes/origin/<main>`,
      `refs/heads/<main>` (update-ref, branch -f, fetch and local-path push refspecs, symbolic-ref, `git replace`),
      shell writes into the git directory's refs, objects, info, hooks, config and tld state, and repointing `origin`
      (`remote set-url` / `add` / `rename` / `remove`, `git config [set] remote.origin.url`, `url.*.insteadOf`,
      `-c remote.origin.url` / `-c url.*`).

Each returns a deny message (without a guard prefix) or None. A guard calls `integrity(ctx, it)` for every
item and `dynamic_command(command)` once; a hit is denied with that guard's own "what to do instead".
"""
from __future__ import annotations

import os

from tld.guard._gitgh import Item, parse_config, parse_push, parse_refspecs, short_ref
from tld.guard._shell import DYN, base, is_dynamic, walk_commands

# Words that make a run-time command name worth denying (a git/gh write of some kind).
WRITE_WORDS = {"push", "merge", "tag", "update-ref", "api", "pr", "release", "workflow", "run", "send-pack",
               "http-push", "fetch", "remote", "config", "symbolic-ref", "branch", "replace"}
# Leading NAME=value assignments that redirect git's configuration.
DANGEROUS_ENV = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_PARAMETERS", "GIT_DIR",
                 "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
CONFIG_INJECT = ("include.", "includeif.")
# Config keys that repoint a remote.
URL_KEYS = ("remote.origin.url", "remote.origin.pushurl")
# Refs a session never writes: the trusted copy and replace objects (which would swap what git reads for a SHA).
GUARD_REF_PREFIXES = ("refs/tld/", "refs/replace/")
# Parts of the git directory a shell command never writes (git maintains them; the guards trust them).
GIT_DIR_PARTS = ("refs", "packed-refs", "objects", "info", "hooks", "config", "tld", "shallow")


PLUGIN_CLI_PATHS = ("${CLAUDE_PLUGIN_ROOT}/cli/tld", "$CLAUDE_PLUGIN_ROOT/cli/tld")


def is_tld_cli(word: str, command: str = "") -> bool:
    """The toolkit's own CLI script, which the commands call: `"${CLAUDE_PLUGIN_ROOT}/cli/tld"` (also written
    `"${CLAUDE_PLUGIN_ROOT}"/cli/tld` or `$CLAUDE_PLUGIN_ROOT/cli/tld`) or a bare `tld`. Not any other `$X/.../tld`,
    and not when the same command line assigns CLAUDE_PLUGIN_ROOT itself."""
    stripped = word.strip("\"'")
    if stripped == "tld":
        return True
    if stripped not in PLUGIN_CLI_PATHS:
        return False
    rest = command.replace("${CLAUDE_PLUGIN_ROOT}", "").replace("$CLAUDE_PLUGIN_ROOT", "")
    return "CLAUDE_PLUGIN_ROOT" not in rest


def dynamic_command(command: str) -> str | None:
    """S3: the command name is a run-time value and the rest looks like a git/gh write."""
    for _, cmd in walk_commands(command):
        words = cmd.words
        if not words or not is_dynamic(words[0]) or is_tld_cli(words[0], command):
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
    if ref.startswith(GUARD_REF_PREFIXES) or ref in ("refs/tld", "refs/replace"):
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
    if sub == "push":
        push = parse_push(args)
        local = _local_repo(push.repo, it.dir)
        for spec in parse_refspecs(push.refspecs):
            dst = spec.dst.strip()
            if dst.startswith(GUARD_REF_PREFIXES + ("refs/remotes/",)) or (local and _hits_protected(dst, mains)):
                return msg.format(ref=dst)
    if sub == "replace":  # only the listing forms (`git replace`, `-l [pattern]`, `--format=`) read
        flags_ok = all(a in ("-l", "--list") or a.startswith("--format") or not a.startswith("-") for a in args)
        has_pattern = any(not a.startswith("-") for a in args)
        listing = flags_ok and (not has_pattern or any(a in ("-l", "--list") for a in args))
        if not listing:
            return msg.format(ref="refs/replace/ (git replace)")
    if sub == "remote":
        msg_remote = _remote_change(args)
        if msg_remote:
            return msg_remote
    for key in _own_config_keys(it):
        if key in URL_KEYS:
            return ("blocked: `-c remote.origin.url=...` (or pushurl) repoints the remote the guardrails trust. "
                    "Run git against the real origin.")
        if _rewrites_urls(key):
            return (f"blocked: `-c {key}=...` rewrites remote URLs, so the command may talk to another remote than "
                    "origin. Run git without it.")
    if sub == "config":
        call = parse_config(args)
        if call.write and (call.sub == "edit" or "-e" in args or "--edit" in args):
            return ("blocked: `git config --edit` can repoint the remote the guardrails trust. Ask the user to make "
                    "this change.")
        for key in call.keys if call.write else []:
            if key in URL_KEYS or _rewrites_urls(key) or (call.section and (key == "remote.origin" or
                                                                            key.startswith("url."))):
                return (f"blocked: `git config` write to `{key}` repoints the remote the guardrails trust (origin's "
                        "URL, or a url.*.insteadOf rewrite). A session does not change where origin points.")
    return None


def _own_config_keys(it: Item) -> list[str]:
    """Config keys the command line itself sets: `-c k=v`, `--config-env k=VAR` and its own GIT_CONFIG_KEY_<n>
    assignments. The session's inherited environment (which may carry the platform's own url rewrites) is not
    something a command can change, so it is not counted."""
    keys, words, i = [], it.words, 1
    while i < len(words) and words[i].startswith("-"):
        name, eq, val = words[i].partition("=")
        if name in ("-c", "--config-env") and not eq:
            val = words[i + 1] if i + 1 < len(words) else ""
            i += 1
        if name in ("-c", "--config-env"):
            keys.append(val.partition("=")[0].lower())
        elif name in ("-C", "--git-dir", "--work-tree", "--namespace") and not eq:
            i += 1
        i += 1
    keys += [v.lower() for k, v in it.env.items() if k.startswith("GIT_CONFIG_KEY_")]
    return keys


def _rewrites_urls(key: str) -> bool:
    return key.startswith("url.") and key.endswith((".insteadof", ".pushinsteadof"))


def _local_repo(repo: str | None, here: str) -> bool:
    """A push destination that is this machine's file system (`.`, a path, file://), not a configured remote."""
    if not repo:
        return False
    if repo == "." or repo.startswith(("/", "./", "../", "~", "file:")):
        return True
    if is_dynamic(repo):
        return True
    return ":" not in repo and "/" in repo and os.path.isdir(os.path.join(here, os.path.expanduser(repo)))


REMOTE_SUBS_ON_ORIGIN = {"set-url": "repoints", "add": "would define", "rename": "renames",
                         "remove": "removes", "rm": "removes"}


def _remote_change(args: list[str]) -> str | None:
    """`git remote set-url|add|rename|remove` that touches origin (either side of a rename)."""
    words = [a for a in args if a not in ("-v", "--verbose")]
    if not words or words[0] not in REMOTE_SUBS_ON_ORIGIN:
        return None
    sub = words[0]
    positional, i = [], 1
    while i < len(words):
        if sub == "add" and words[i] in ("-t", "-m"):  # `-t <branch>` / `-m <master>` take a value
            i += 2
            continue
        if not words[i].startswith("-"):
            positional.append(words[i])
        i += 1
    names = positional[:2] if sub == "rename" else positional[:1]
    if "origin" in names or any(is_dynamic(n) for n in names):
        return (f"blocked: `git remote {sub}` {REMOTE_SUBS_ON_ORIGIN[sub]} origin, the remote the guardrails trust "
                "(they read the profile from its default branch). A session does not change, add, rename or "
                "remove origin.")
    return None


def git_dir_write(ctx, it: Item) -> str | None:
    """A shell write (redirect, cp, mv, tee, ...) into the git directory's refs, objects, info, hooks, config or the
    guards' own state, which would move the trusted ref or plant what git reads."""
    from tld.guard.protect_paths import written_paths  # protect_paths imports nothing from here
    paths = [p for p in written_paths(it) if p and not is_dynamic(p)]
    if not paths:
        return None
    roots = []
    for project in dict.fromkeys([ctx.project_dir, os.path.realpath(ctx.project_dir)]):
        gd = os.path.join(project, ".git")
        if os.path.isdir(gd):
            roots += [os.path.normpath(gd), os.path.realpath(gd)]
    for path in paths:
        full = os.path.normpath(os.path.join(it.dir, os.path.expanduser(path)))
        for cand in dict.fromkeys([full, os.path.realpath(full)]):
            for gd in dict.fromkeys(roots):
                rel = os.path.relpath(cand, gd)
                if rel.split(os.sep)[0] in GIT_DIR_PARTS:
                    return (f"blocked: `{path}` is inside the git directory ({rel}); writing it by hand can move the "
                            "refs or plant the objects the guardrails trust. Let git maintain its own directory.")
    return None


def integrity(ctx, it: Item) -> str | None:
    """Every per-item integrity check. Works even without a main branch in the profile (refs/tld/* still covered)."""
    from tld.guard._common import ProfileError
    try:
        mains = ctx.main_branches()
    except ProfileError:
        mains = []
    return config_injection(it) or trusted_ref_write(it, mains) or git_dir_write(ctx, it)
