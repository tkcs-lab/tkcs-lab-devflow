"""The changelog guard of `protect-paths`, driven by `docs.changelog` of the profile.

The release workflow takes the version from the `## [X.Y.Z]` heading of the changelog, so that heading is the human
gate of a release. A session may add lines under the unreleased section freely. A new version heading (policy
`unreleased`), or any edit at all (policy `release-only`), is allowed only when the change is a changelog change
and nothing else: a separate commit or pull request, apart from the code and the version bump.
"""
from __future__ import annotations

import os
import re

from tld.guard import trust

VERSION_HEADING = re.compile(r"^#{1,4}[ \t]*\[?v?\d+\.\d+[^\n]*$", re.M)


def conf(ctx) -> dict | None:
    """`docs.changelog` of the trusted profile, else of the working tree (a branch can only add protection here)."""
    trusted, available = ctx.trusted()
    for prof in ((trusted,) if available else ()) + (ctx.profile,):
        docs = prof.get("docs") if isinstance(prof, dict) else None
        cl = docs.get("changelog") if isinstance(docs, dict) else None
        if isinstance(cl, dict) and isinstance(cl.get("file"), str) and cl["file"]:
            return cl
    return None


def _hit(ctx, rels: list[str]) -> dict | None:
    cl = conf(ctx)
    return cl if cl and os.path.normpath(cl["file"]) in rels else None


def changelog_only(ctx, file: str) -> bool:
    """True when the branch (commits since the main branch, plus the working tree) changes only the changelog file."""
    changed: set[str] = set()
    status = trust._git(ctx.project_dir, "status", "--porcelain", "-z", "--untracked-files=all")
    if status is None or status.returncode != 0:
        return False
    for entry in status.stdout.split("\0"):
        if entry:
            changed.add(entry[3:])
    base_ok = False
    for name in ctx.main_branches():
        diff = trust._git(ctx.project_dir, "diff", "--name-only", "-z", f"origin/{name}...HEAD")
        if diff is not None and diff.returncode == 0:
            changed |= {p for p in diff.stdout.split("\0") if p}
            base_ok = True
            break
    return base_ok and changed <= {os.path.normpath(file)}


def violation(ctx, path: str, here: str, rels: list[str]) -> str | None:
    """`docs.changelog.policy: release-only`: the changelog is written when a release is cut."""
    cl = _hit(ctx, rels)
    if cl and cl.get("policy") == "release-only" and not changelog_only(ctx, cl["file"]):
        return (f"blocked: `{cl['file']}` is edited at release only (docs.changelog.policy: release-only), in a change "
                "that touches nothing else. Leave it out of this change and put the user-visible note in the pull "
                "request description, or make the changelog edit a separate pull request.")
    return None


def content_violation(ctx, content, rels: list[str], path: str, here: str) -> str | None:
    """Default policy: lines under `docs.changelog.section` are free; a new version heading needs a changelog-only change.
    Only headings the file does not already have count, so rewriting a file with its old releases is fine."""
    cl = _hit(ctx, rels)
    if not cl or cl.get("policy") == "release-only":
        return None
    try:
        with open(os.path.normpath(os.path.join(here, os.path.expanduser(path))), encoding="utf-8", errors="replace") as fh:
            existing = set(VERSION_HEADING.findall(fh.read()))
    except OSError:
        existing = set()
    for where, text in content:
        new = [h for h in VERSION_HEADING.findall(text) if h not in existing]
        if new and not changelog_only(ctx, cl["file"]):
            section = cl.get("section") or "the unreleased section"
            return (f"blocked: {where} for `{cl['file']}` opens a version heading ({new[0].strip()!r}) in a change that "
                    f"also touches other files. The version heading is the release gate: make it a separate pull request "
                    f"that changes only the changelog. Add the line under `{section}` instead.")
    return None
