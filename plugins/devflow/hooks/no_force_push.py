#!/usr/bin/env python3
"""PreToolUse hook `no-force-push`: no force push and no branch deletion by push."""
from __future__ import annotations

import re

import _common
from _common import Ctx
from _gitgh import Item, gh_path, iter_items, parse_gh_api, parse_push, parse_refspecs
from _shell import ParseError

NAME = "no-force-push"
INSTEAD = ("Push normally (`git push -u origin <branch>`). If the push is rejected because the remote branch "
           "moved, `git fetch`, merge `origin/<branch>` into yours (a merge commit, never a rebase) and push "
           "again. Branches are deleted by the owner, not by a session.")
REF_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/git/refs/heads/.+$")


def deny(what: str) -> str:
    return f"blocked: {what}. {INSTEAD}"


def check_push(it: Item) -> str | None:
    push = parse_push(it.git.args)
    if push.dynamic_option:
        return deny("an argument that is only known at run time sits where a push option could be, so it cannot "
                    "be checked for --force")
    if push.force:
        return deny("a force push rewrites remote history (--force, -f, --force-with-lease, --force-if-includes)")
    if push.delete:
        return deny("--delete, -d, --prune and --mirror delete remote branches")
    for spec in parse_refspecs(push.refspecs):
        if spec.plus:
            return deny(f"refspec `{spec.raw}` starts with `+`, which forces the update")
        if spec.delete:
            return deny(f"refspec `{spec.raw}` deletes the remote ref")
    return None


def check_gh(it: Item) -> str | None:
    path = gh_path(it.words)
    if path[:2] == ["pr", "close"] and any(
            w in ("-d", "--delete-branch") or (w.startswith("--del") and "--delete-branch".startswith(w))
            for w in it.words[1:]):
        return deny("`gh pr close --delete-branch` deletes the pull request branch")
    if path[:1] == ["api"]:
        api = parse_gh_api(it.words)
        if api.method == "DELETE" and REF_ENDPOINT.match(api.endpoint):
            return deny("this `gh api` call deletes a branch")
    return None


def evaluate(ctx: Ctx) -> str | None:
    if ctx.tool != "Bash" or not isinstance(ctx.tool_input.get("command"), str):
        return None
    try:
        items = list(iter_items(ctx.cwd, ctx.tool_input["command"]))
    except ParseError as exc:
        return (f"blocked: cannot parse this command ({exc}), so it cannot be checked for force pushes. "
                "Rewrite it as plain, separate commands.")
    for it in items:
        msg = check_push(it) if it.kind == "git" and it.git.sub == "push" else \
            check_gh(it) if it.kind == "gh" else None
        if msg:
            return msg
    return None


if __name__ == "__main__":
    _common.main(NAME, evaluate, fail_closed=True)
