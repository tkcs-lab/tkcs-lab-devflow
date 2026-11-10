#!/usr/bin/env python3
"""PreToolUse hook `no-git-tag`: no creating, moving, deleting or pushing tags.

Reading stays allowed (`git tag -l`, `git describe`, `git fetch --tags`, `git ls-remote --tags`).
The release workflow runs in CI and is not affected.
"""
from __future__ import annotations

import re

import _common
from _common import Ctx
from _gitgh import Item, gh_path, iter_items, parse_gh_api, parse_push, parse_refspecs, ref_exists, short_ref
from _shell import ParseError, is_dynamic

NAME = "no-git-tag"
INSTEAD = ("Tags are cut by the release workflow in CI, on the maintainer's decision. Do not create, move, "
           "delete or push a tag from a session; say in your report that a release is due instead. Reading "
           "is fine: `git tag -l`, `git describe`, `git fetch --tags`, `git ls-remote --tags`.")
TAG_REF = re.compile(r"^repos/[^/]+/[^/]+/git/refs/tags(/.*)?$")

LIST_LONG = ("list", "verify", "contains", "no-contains", "points-at", "merged", "no-merged")
LIST_LONG_VALUE = ("contains", "no-contains", "points-at", "merged", "no-merged")
CREATE_LONG = ("annotate", "sign", "force", "delete", "edit", "local-user", "message", "file")
CREATE_LONG_VALUE = ("local-user", "message", "file")
OTHER_LONG_VALUE = ("sort", "format", "cleanup")


def deny(what: str) -> str:
    return f"blocked: {what}. {INSTEAD}"


def _resolve(name: str, *tables: tuple[str, ...]) -> str | None:
    names = [n for t in tables for n in t]
    if name in names:
        return name
    hits = [n for n in names if len(name) >= 2 and n.startswith(name)]
    return hits[0] if len(hits) == 1 else None


def check_tag(args: list[str]) -> str | None:
    list_mode = create = delete = False
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--":
            positional += args[i:]
            break
        if a.startswith("--"):
            name, eq, _ = a[2:].partition("=")
            full = _resolve(name, LIST_LONG, CREATE_LONG, OTHER_LONG_VALUE)
            if full in LIST_LONG:
                list_mode = True
            elif full in CREATE_LONG:
                create = True
                delete = delete or full == "delete"
            if not eq and full in LIST_LONG_VALUE + CREATE_LONG_VALUE + OTHER_LONG_VALUE:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if ch in "lv":
                    list_mode = True
                elif ch == "n":
                    list_mode = True
                    break
                elif ch in "asfde":
                    create = True
                    delete = delete or ch == "d"
                elif ch in "mFu":
                    create = True
                    if k == len(a) - 1:
                        i += 1
                    break
        else:
            positional.append(a)
    if delete:
        return deny("`git tag -d` deletes a tag")
    if list_mode:
        return None
    if create or positional:
        return deny("`git tag` would create or move a tag")
    return None


def check_push(it: Item) -> str | None:
    push = parse_push(it.git.args)
    if push.tags:
        return deny("`git push --tags` / `--follow-tags` pushes tags")
    specs = parse_refspecs(push.refspecs)
    for k, spec in enumerate(specs):
        if spec.raw == "tag" and k + 1 < len(specs):
            return deny(f"`git push {push.repo} tag {specs[k + 1].raw}` pushes a tag")
        if "refs/tags/" in spec.src or "refs/tags/" in spec.dst:
            return deny(f"refspec `{spec.raw}` names a tag")
        if is_dynamic(spec.src) or not spec.src:
            continue
        name = short_ref(spec.src)
        if ref_exists(it.dir, f"refs/tags/{name}", it.git.repo_opts):
            return deny(f"`{spec.src}` is the name of a tag in this repository, so pushing it pushes the tag")
    return None


def check_gh(it: Item) -> str | None:
    path = gh_path(it.words)
    if path[:2] in (["release", "create"], ["release", "delete"]):
        return deny(f"`gh {path[0]} {path[1]}` creates or deletes a tag")
    if path[:1] == ["api"]:
        api = parse_gh_api(it.words)
        if api.method != "GET":
            ep = api.endpoint
            if TAG_REF.match(ep) or re.match(r"^repos/[^/]+/[^/]+/git/tags$", ep) or \
                    re.match(r"^repos/[^/]+/[^/]+/releases$", ep) or \
                    (re.match(r"^repos/[^/]+/[^/]+/git/refs$", ep) and api.fields.get("ref", "").startswith("refs/tags/")):
                return deny("this `gh api` call creates, moves or deletes a tag")
    return None


def evaluate(ctx: Ctx) -> str | None:
    if ctx.tool != "Bash" or not isinstance(ctx.tool_input.get("command"), str):
        return None
    try:
        items = list(iter_items(ctx.cwd, ctx.tool_input["command"]))
    except ParseError as exc:
        return (f"blocked: cannot parse this command ({exc}), so it cannot be checked for tag changes. "
                "Rewrite it as plain, separate commands.")
    for it in items:
        msg = None
        if it.kind == "git":
            sub = it.git.sub
            if sub == "tag":
                msg = check_tag(it.git.args)
            elif sub == "push":
                msg = check_push(it)
            elif sub == "update-ref" and any("refs/tags/" in a for a in it.git.args):
                msg = deny("`git update-ref` on refs/tags/ changes a tag")
        elif it.kind == "gh":
            msg = check_gh(it)
        if msg:
            return msg
    return None


if __name__ == "__main__":
    _common.main(NAME, evaluate, fail_closed=True)
