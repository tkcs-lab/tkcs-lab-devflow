"""The pure checks of `tld ops deps-prepare` (no git calls): what counts as a lockfile, what is protected,
whether a commit's identity is the dependency bot's, and whether a workflow diff only moves action refs.

Everything here is a function of its arguments, so the tests can reach every branch without a repository.
"""
from __future__ import annotations

import re
import unicodedata

from tld.guard._common import BUILTIN_PROTECT_ALLOW, GUARDED_WORKFLOWS
from tld.guard.protect_paths import ALWAYS_PROTECTED, matches

BUILTIN_LOCKFILES = ("*.lock", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "go.sum")
BOT_AUTHOR = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
# GitHub's web-flow committer signs API commits; matched by e-mail or by the name `GitHub`.
BOT_COMMITTER = BOT_AUTHOR + ("noreply@github.com",)
WORK_PREFIX = "refs/heads/tld-deps/"  # local work branches: the only refs exempt from the bot check
WORKFLOW_DIR = ".github/workflows/"
USES_LINE = re.compile(r"^(\s*(?:-\s+)?uses:\s*)([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
                       r"@([A-Za-z0-9][A-Za-z0-9_.-]*)(\s+#.*)?\s*$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")

# Why a group is left out (the reasons `deps-prepare` itself emits) and the four that name a file.
PREPARE_REASONS = ("does-not-apply", "no-change", "lock-uncovered", "lockfile-only", "not-bot-authored",
                   "protected-path", "unexpected-change", "workflow-not-a-bump")
FILE_REASONS = ("lock-uncovered", "protected-path", "unexpected-change", "workflow-not-a-bump")

_FIXED_PROTECTED = (".tld/toolkit.yaml", ".mcp.json", ".claude/settings*.json", ".claude/hooks/**", ".git/**")
_ENV_PATTERNS = (".env", ".env.*")


def entry_globs(entries: list[dict]) -> list[str]:
    return [g for e in entries for g in e.get("lockfiles", [])]


def is_covered(path: str, lock_globs: list[str]) -> bool:
    """A `lockfiles` glob of some lock entry matches the path."""
    return any(matches(g, path) for g in lock_globs)


def is_lockfile(path: str, lock_globs: list[str]) -> bool:
    return is_covered(path, lock_globs) or any(matches(p, path) for p in BUILTIN_LOCKFILES)


def fold(text: str) -> str:
    """NFC and case-folded: a case-insensitive file system maps `.CLAUDE/x` onto `.claude/x`."""
    return unicodedata.normalize("NFC", text).casefold()


def is_workflow(path: str) -> bool:
    return fold(path).startswith(WORKFLOW_DIR)


def is_protected(path: str, resolved: dict) -> bool:
    """A path a dependency group may not change (the protected list of the profile and the fixed paths). Paths and
    patterns are compared case-folded."""
    path = fold(path)
    fixed = [fold(p) for p in _FIXED_PROTECTED + tuple(ALWAYS_PROTECTED) + tuple(GUARDED_WORKFLOWS)]
    if any(matches(p, path) for p in fixed):
        return True
    if any(matches(fold(a), path) for a in BUILTIN_PROTECT_ALLOW):
        return False  # templates of environment files, as for the guard
    if any(matches(p, path) for p in _ENV_PATTERNS):
        return True
    entries = (resolved.get("deps") or {}).get("lock_freshness") or []
    exempt = set(BUILTIN_LOCKFILES) | set(entry_globs(entries)) | {".github/workflows/**"}
    extra = (resolved.get("hooks") or {}).get("protect_paths") or []
    return any(p not in exempt and matches(fold(p), path) for p in extra)


def identity_ok(author_name: str, author_email: str, committer_name: str, committer_email: str) -> bool:
    """The commit's identity says it is the dependency bot's (it cannot prove it)."""
    if author_name != BOT_AUTHOR[0] or author_email not in BOT_AUTHOR:
        return False
    return committer_email in BOT_COMMITTER or committer_name == "GitHub"


def workflow_moves(diff_text: str) -> list[dict] | None:
    """The `(action, from, to)` moves of a `git diff -U0` of one workflow file, or None when it is anything else
    than a move of action refs: every hunk has as many removed as added lines, each pair is a `uses:` line with the
    same prefix and the same action and a different ref, and a pinned SHA is replaced by a SHA."""
    moves: list[dict] = []
    removed: list[str] = []
    added: list[str] = []
    in_hunk = False

    def flush() -> bool:
        if len(removed) != len(added):
            return False
        for old_line, new_line in zip(removed, added):
            old, new = USES_LINE.match(old_line), USES_LINE.match(new_line)
            if not old or not new or old.group(1) != new.group(1) or old.group(2) != new.group(2):
                return False
            action, old_ref, new_ref = old.group(2), old.group(3), new.group(3)
            if ".." in action.split("/") or old_ref == new_ref:
                return False
            if SHA40.match(old_ref) and not SHA40.match(new_ref):
                return False
            moves.append({"action": action, "from": old_ref, "to": new_ref})
        removed.clear()
        added.clear()
        return True

    for line in diff_text.split("\n"):
        if line.startswith("@@"):
            if in_hunk and not flush():
                return None
            in_hunk = True
        elif not in_hunk or line.startswith("\\"):
            continue  # the file header before the first hunk, or "\ No newline at end of file"
        elif line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
        elif line:
            return None
    if in_hunk and not flush():
        return None
    return moves or None
