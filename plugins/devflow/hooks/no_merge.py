#!/usr/bin/env python3
"""PreToolUse hook `no-merge`: no pull request merge, no approval, no push to the main branch.

Matches Bash and the GitHub MCP tools that merge, approve or write to a branch. Local `git merge`
is deliberately allowed (/implement merges phase branches and origin/<main> into the feature
branch, /land merges on its own chore/land-* branch).
"""
from __future__ import annotations

import re

import _common
from _common import Ctx
from _gitcfg import bare_push_destinations
from _gitgh import (Item, current_branch, gh_path, has_glob, iter_items, parse_gh_api, parse_push,
                    parse_refspecs, read_input_text, short_ref)
from _shell import ParseError, is_dynamic

NAME = "no-merge"
HUMAN = "Open a pull request from your feature branch and stop; a human reviews and merges it."

MERGE_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/pulls/\d+/merge$")
REVIEW_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/pulls/\d+/reviews(/\d+/events)?$")
MERGES_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/merges$")
REF_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/git/refs/heads/(.+)$")
MERGE_UPSTREAM = re.compile(r"^repos/[^/]+/[^/]+/merge-upstream$")
RENAME_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/branches/(.+)/rename$")
CONTENTS_ENDPOINT = re.compile(r"^repos/[^/]+/[^/]+/contents/.+$")
GRAPHQL_MERGE = re.compile(r"\b(mergePullRequest|enablePullRequestAutoMerge|mergeBranch|updateRef)\b")
GRAPHQL_REVIEW = re.compile(r"\b(addPullRequestReview|submitPullRequestReview)\b")
CURL_MERGE = re.compile(r"/pulls/\d+/merge\b")
MCP_ALWAYS = {"merge_pull_request": "merges a pull request", "enable_pr_auto_merge": "enables auto-merge"}
MCP_BRANCH_WRITES = {"push_files", "create_or_update_file", "delete_file"}


def deny(what: str) -> str:
    return f"blocked: {what}. {HUMAN}"


def check_push(ctx: Ctx, it: Item) -> str | None:
    push = parse_push(it.git.args)
    main = ctx.require_main_branch()
    if push.all_refs:
        return deny(f"`git push` with --all, --branches or --mirror would update `{main}`")
    for item in it.git.config:
        key = item.partition("=")[0]
        if key.lower().startswith(("remote.", "push.", "branch.")):
            return deny(f"`-c {key}` changes where `git push` writes")
    specs = parse_refspecs(push.refspecs)
    if not specs:
        if push.tags:
            return None  # tags only; the no-git-tag hook owns those
        dests = bare_push_destinations(it, push, main)
        if dests is None:
            return deny("the destination of this `git push` cannot be determined from your git configuration")
        if main in dests:
            return deny(f"`git push` would update `{main}` (the current branch or its configured destination)")
        return None
    for spec in specs:
        if spec.dynamic:
            continue
        dst = short_ref(spec.dst)
        if has_glob(dst):
            return deny(f"refspec `{spec.raw}` is a pattern that can match `{main}`")
        if spec.src in ("HEAD", "@") and spec.src == spec.dst:
            dst = current_branch(it.dir, it.git.repo_opts) or ""
        if dst == main:
            return deny(f"`git push {spec.raw}` would update `{main}`")
    return None


def check_gh(ctx: Ctx, it: Item) -> str | None:
    path = gh_path(it.words)
    if path[:2] == ["pr", "merge"]:
        return deny("`gh pr merge` merges (or arms auto-merge on) a pull request")
    if path[:2] == ["pr", "review"]:
        for w in it.words[1:]:
            if w == "--approve" or (w.startswith("--ap") and "--approve".startswith(w)):
                return deny("`gh pr review --approve` approves a pull request")
            if w.startswith("-") and not w.startswith("--") and "a" in w[1:]:
                return deny("`gh pr review -a` approves a pull request")
        return None
    if path[:2] in (["alias", "set"], ["alias", "import"]):
        return deny("a `gh` alias could hide a merge or an approval")
    if path[:1] == ["api"]:
        return check_gh_api(ctx, it)
    if path[:2] == ["repo", "sync"]:
        main = ctx.require_main_branch()
        w = it.words
        for i, a in enumerate(w):
            val = w[i + 1] if i + 1 < len(w) else ""
            if a == "--force":
                return deny("`gh repo sync --force` overwrites the destination branch")
            if (a in ("--branch", "-b") and short_ref(val) == main) or (
                    a.startswith("--branch=") and short_ref(a.partition("=")[2]) == main):
                return deny(f"`gh repo sync` updates `{main}`")
    return None


def check_gh_api(ctx: Ctx, it: Item) -> str | None:
    api = parse_gh_api(it.words)
    ep, method = api.endpoint, api.method
    if ep == "graphql":
        text = "\n".join(api.texts)
        if api.input_file:
            body = read_input_text(api, it.dir)
            if body is None:
                return deny("`gh api graphql --input` reads a query this hook cannot inspect (a file that is "
                            "missing or stdin); pass the query with -f query=...")
            text += "\n" + body
        for name in api.field_files:
            body = read_input_text(api, it.dir, name)
            if body is None:
                return deny("`gh api graphql -F query=@file` reads a query this hook cannot inspect (a file that "
                            "is missing or stdin); pass the query with -f query=...")
            text += "\n" + body
        m = GRAPHQL_MERGE.search(text)
        if m:
            return deny(f"the GraphQL mutation `{m.group(1)}` merges or moves a branch")
        if GRAPHQL_REVIEW.search(text) and re.search(r"\bAPPROVE\b", text):
            return deny("this GraphQL call approves a pull request")
        return None
    if method == "GET":
        return None
    if MERGE_ENDPOINT.match(ep):
        return deny("this `gh api` call is the pull request merge endpoint")
    if REVIEW_ENDPOINT.match(ep) and (api.fields.get("event", "").upper() == "APPROVE" or "APPROVE" in (
            read_input_text(api, it.dir) or "")):
        return deny("this `gh api` call approves a pull request")
    if MERGE_UPSTREAM.match(ep) and method == "POST":
        main = ctx.require_main_branch()
        if short_ref(api.fields.get("branch", main)) == main:
            return deny(f"this `gh api` call fast-forwards or merges upstream into `{main}`")
    m = RENAME_ENDPOINT.match(ep)
    if m and m.group(1) == ctx.require_main_branch():
        return deny("this `gh api` call renames the main branch")
    if MERGES_ENDPOINT.match(ep):
        main = ctx.require_main_branch()
        if api.fields.get("base") in (main, None):
            return deny(f"this `gh api` call merges a branch into `{main}`")
    m = REF_ENDPOINT.match(ep)
    if m:
        main = ctx.require_main_branch()
        if m.group(1) == main:
            return deny(f"this `gh api` call changes the ref of `{main}`")
    if CONTENTS_ENDPOINT.match(ep) and method in ("PUT", "DELETE", "POST"):
        main = ctx.require_main_branch()
        if api.fields.get("branch", main) == main:
            return deny(f"this `gh api` call commits to `{main}` (no `branch` field means the default branch)")
    return None


def check_bash(ctx: Ctx, command: str) -> str | None:
    try:
        items = list(iter_items(ctx.cwd, command))
    except ParseError as exc:
        return (f"blocked: cannot parse this command ({exc}), so it cannot be checked for merges or pushes to "
                "the main branch. Rewrite it as plain, separate commands.")
    for it in items:
        if it.kind == "git" and it.git.sub == "push":
            msg = check_push(ctx, it)
        elif it.kind == "gh":
            msg = check_gh(ctx, it)
        elif it.words and it.words[0].rsplit("/", 1)[-1] in ("curl", "wget", "http", "https", "xh"):
            msg = deny("this request calls the pull request merge endpoint") if any(
                CURL_MERGE.search(w) for w in it.words[1:] if not is_dynamic(w)) else None
        else:
            msg = None
        if msg:
            return msg
    return None


def check_mcp(ctx: Ctx) -> str | None:
    name = ctx.tool.rsplit("__", 1)[-1]
    args = ctx.tool_input
    if name in MCP_ALWAYS:
        return deny(f"`{name}` {MCP_ALWAYS[name]}")
    if name == "pull_request_review_write" and str(args.get("event", "")).upper() == "APPROVE":
        return deny("this review approves a pull request")
    if name in MCP_BRANCH_WRITES:
        main = ctx.require_main_branch()
        branch = args.get("branch")
        if not branch or (isinstance(branch, str) and short_ref(branch) == main):
            return deny(f"`{name}` writes to `{branch or main}` (no `branch` means the default branch)")
    return None


def evaluate(ctx: Ctx) -> str | None:
    if ctx.tool == "Bash":
        command = ctx.tool_input.get("command")
        return check_bash(ctx, command) if isinstance(command, str) else None
    if ctx.tool.startswith("mcp__"):
        return check_mcp(ctx)
    return None


if __name__ == "__main__":
    _common.main(NAME, evaluate, fail_closed=True)
