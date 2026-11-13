#!/usr/bin/env python3
"""PreToolUse hook `no-git-tag`: no creating, moving, deleting or pushing tags.

Reading stays allowed (`git tag -l`, `git describe`, `git fetch --tags`, `git ls-remote --tags`).
Tags have one route (D13): the release workflow, which the owner approves in GitHub. A session starts it only
through the release skill, after the owner's yes: `dry_run=true`, or `dry_run=false` while the release marker of
`tld guard allow-release <workflow-file>` is set (10 minutes). `skip_checks` and inputs the hook cannot read
(`--json`, a field file, every curl dispatch) are denied even with the marker.
The hook also guards the one other ref-changing workflow, git-ops (it deletes branches): a dispatch with
`dry_run` false needs the confirm marker of `tld guard allow-git-ops` (S12).
"""
from __future__ import annotations

import json
import os
import posixpath
import re

from tld.guard import markers
from tld.guard._common import Ctx
from tld.guard._gitcfg import _truthy, git_config_value, git_config_values
from tld.guard._gitgh import (Item, gh_path, iter_items, parse_gh_api, parse_push, parse_refspecs, read_input_text,
                              ref_exists, short_ref)
from tld.guard._shell import ParseError, is_dynamic
from tld.guard.integrity import dynamic_command, integrity

NAME = "no-git-tag"
INSTEAD = ("Tags are cut only by the release workflow, which the owner approves in GitHub; there is no other "
           "route (git-ops deletes branches only). A session starts that workflow only through the release skill, "
           "after the owner's yes. Do not create, move, delete or push a tag from a session; say in your report "
           "that a release is due instead. Reading is fine: `git tag -l`, `git describe`, `git fetch --tags`, "
           "`git ls-remote --tags`.")
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


RELEASE_WORKFLOW = "tld-release.yml"
REL_EDIT = re.compile(r"^repos/[^/]+/[^/]+/releases/[^/]+$")
DISPATCH = re.compile(r"^repos/[^/]+/[^/]+/actions/workflows/([^/]+)/dispatches$")
PUSH_KEY = re.compile(r"^remote\.[^=]*\.(push|mirror)$", re.I)


RUN_VALUE_OPTS = ("--ref", "-r", "-R", "--repo")
API_VALUE_OPTS = ("-q", "--jq", "-t", "--template", "-H", "--header", "-p", "--preview", "--hostname", "--cache",
                  "-X", "--method", "--input")
UNREADABLE_RELEASE = ("this release dispatch has inputs that cannot be read, so dry_run and skip_checks cannot be "
                      "checked; dispatch with plain -f fields or the MCP inputs")


def _profiles(ctx: Ctx) -> list:
    """The working tree's profile and the trusted copy (both: stricter, never looser)."""
    profiles = [ctx.profile]
    try:
        trusted, available = ctx.trusted()
        if available:
            profiles.append(trusted)
    except Exception:  # noqa: BLE001 - the trusted copy is a bonus here
        pass
    return profiles


def _release_names(ctx: Ctx) -> set[str]:
    """File names (and stems) of the release workflow: `tld-release.yml`, plus `release.workflow` of the working
    tree's profile and of the trusted copy."""
    names = {RELEASE_WORKFLOW}
    for prof in _profiles(ctx):
        section = (prof or {}).get("release")
        value = section.get("workflow") if isinstance(section, dict) else None
        if isinstance(value, str) and value.strip():
            names.add(os.path.basename(value.strip()))
    return names | {re.sub(r"\.ya?ml$", "", n) for n in names}


def is_release_workflow(ctx: Ctx, ident) -> bool:
    return isinstance(ident, str) and os.path.basename(ident.strip()) in _release_names(ctx)


def _is_true(value) -> bool:
    return value is True or value == "true"


def _is_exactly_false(value) -> bool:
    return value is False or value == "false"


def release_real_run(ctx: Ctx, ident, why: str) -> str | None:
    """The deny message for a real release run, or None while the release marker names this workflow."""
    marker = markers.read(ctx.project_dir, "release")
    if marker is not None and isinstance(ident, str):
        want = re.sub(r"\.ya?ml$", "", os.path.basename(ident.strip()))
        have = marker.get("workflow")
        if isinstance(have, str) and re.sub(r"\.ya?ml$", "", os.path.basename(have)) == want:
            return None
    return (f"blocked: {why}. A real release run tags the head of the main branch and publishes a release. Only the "
            "release skill starts one: after the owner's yes it runs 'tld guard allow-release <workflow-file>' (it "
            "lapses after 10 minutes), dispatches, and runs 'tld guard end-allow' afterwards.")


def release_inputs_problem(ctx: Ctx, ident, values: dict[str, list]) -> str | None:
    """Judge a release dispatch whose `dry_run` / `skip_checks` values are known (each key maps to every value
    given): skip_checks true is always denied; a real run needs the marker."""
    if any(not _is_exactly_false(v) for v in values.get("skip_checks", [])):
        return deny("this release dispatch sets skip_checks to something other than false; a session never skips the green-commit check")
    dry = values.get("dry_run", [])
    if not dry or any(not _is_true(v) for v in dry):
        return release_real_run(ctx, ident, "this release dispatch does not set dry_run to true")
    return None


# ---- S12: git-ops runs for real only after the user's yes -----------------------------------------------
GIT_OPS_WORKFLOW = "tld-git-ops.yml"
FALSE_WORDS = ("false", "0", "no", "off")
CURL_DISPATCH = re.compile(r"/repos/[^/\s]+/[^/\s]+/actions/workflows/([^/\s?]+)/dispatches")


def _git_ops_names(ctx: Ctx) -> set[str]:
    """File names (and stems) of the git-ops workflow: the default, plus `git_ops.workflow` of the working tree's
    profile and of the trusted copy (both: stricter, never looser)."""
    names = {GIT_OPS_WORKFLOW}
    profiles = [ctx.profile]
    try:
        trusted, available = ctx.trusted()
        if available:
            profiles.append(trusted)
    except Exception:  # noqa: BLE001 - the trusted copy is a bonus here
        pass
    for prof in profiles:
        value = ((prof or {}).get("git_ops") or {}).get("workflow") if isinstance((prof or {}).get("git_ops"), dict) else None
        if isinstance(value, str) and value:
            names.add(os.path.basename(value))
    return names | {re.sub(r"\.ya?ml$", "", n) for n in names}


def is_git_ops_workflow(ctx: Ctx, ident) -> bool:
    return isinstance(ident, str) and os.path.basename(ident.strip()) in _git_ops_names(ctx)


def _is_false(value) -> bool:
    return value is False or (isinstance(value, str) and value.strip().lower() in FALSE_WORDS)


def git_ops_real_run(ctx: Ctx, why: str) -> str | None:
    """The deny message for a real git-ops run, or None while the confirm marker is set."""
    if markers.read(ctx.project_dir, "git-ops") is not None:
        return None
    return (f"blocked: {why}. A real git-ops run deletes a branch. Dry-run it first, show the user the result, "
            "and only after their yes run `tld guard allow-git-ops` (it lapses after 10 minutes), dispatch again, "
            "and run `tld guard end-allow` afterwards.")


def _workflow_run_fields(words: list[str]) -> tuple[dict[str, str], bool]:
    """(-f/-F key=value fields, inputs unreadable) of `gh workflow run`. `--json` reads the inputs from stdin."""
    fields, unreadable, i = {}, False, 0
    while i < len(words):
        w = words[i]
        i += 1
        name, eq, val = w.partition("=")
        if name in ("-f", "--raw-field", "-F", "--field") or (w[:2] in ("-f", "-F") and len(w) > 2 and not w.startswith("--")):
            if w[:2] in ("-f", "-F") and len(w) > 2 and not w.startswith("--"):
                val = w[2:]
            elif not eq:
                val = words[i] if i < len(words) else ""
                i += 1
            key, _, v = val.partition("=")
            if w.startswith(("-F", "--field")) and v.startswith("@"):
                unreadable = True
            fields[key] = v
        elif name == "--json":
            unreadable = True
    return fields, unreadable


def _release_fields(words: list[str], start: int, skip_opts: tuple[str, ...], keymap: dict[str, str]):
    """(values, unreadable): every -f/-F value whose key is in `keymap` (key -> name, matched case-insensitively).
    An option that takes a value consumes the next word verbatim, even one that looks like a flag."""
    values: dict[str, list] = {"dry_run": [], "skip_checks": []}
    unreadable, i = False, start
    while i < len(words):
        w = words[i]
        i += 1
        name, eq, val = w.partition("=")
        short = w[:2] in ("-f", "-F") and len(w) > 2 and not w.startswith("--")
        if name in ("-f", "--raw-field", "-F", "--field") or short:
            if short:
                val = w[2:].lstrip("=") if w[2:3] == "=" else w[2:]
            elif not eq:
                val, i = (words[i] if i < len(words) else ""), i + 1
            key, _, v = val.partition("=")
            if w.startswith(("-F", "--field")) and v.startswith("@"):
                unreadable = True
            if key.lower() in keymap:
                values[keymap[key.lower()]].append(v)
        elif name == "--json" or name == "--input":
            unreadable = True
            i += 0 if eq or name == "--json" else 1
        elif name in skip_opts and not eq:
            i += 1
        elif w[:2] in skip_opts and not w.startswith("--") and len(w) == 2:
            i += 1
    return values, unreadable


def _release_gh_run(ctx: Ctx, it: Item, ident: str) -> str | None:
    """`gh workflow run <release workflow>`: every -f/-F value of dry_run and skip_checks is read."""
    values, unreadable = _release_fields(it.words, 0, RUN_VALUE_OPTS, {"dry_run": "dry_run", "skip_checks": "skip_checks"})
    return deny(UNREADABLE_RELEASE) if unreadable else release_inputs_problem(ctx, ident, values)


def _release_api(ctx: Ctx, it: Item, api, ident: str) -> str | None:
    """`gh api .../dispatches` of the release workflow: inputs[dry_run] / inputs[skip_checks] fields. A body file is
    never read (it can change between the check and the run)."""
    keymap = {"inputs[dry_run]": "dry_run", "inputs[skip_checks]": "skip_checks"}
    values, unreadable = _release_fields(it.words, 2, API_VALUE_OPTS, keymap)
    if unreadable or api.field_files or api.input_file:
        return deny(UNREADABLE_RELEASE)
    return release_inputs_problem(ctx, ident, values)


def check_git_ops_gh_run(ctx: Ctx, it: Item) -> str | None:
    fields, unreadable = _workflow_run_fields(it.words)
    if unreadable:
        return git_ops_real_run(ctx, "this git-ops dispatch reads its inputs from stdin or a file, so `dry_run` "
                                     "cannot be checked")
    if _is_false(fields.get("dry_run", "true")):
        return git_ops_real_run(ctx, "this git-ops dispatch has `dry_run` false")
    return None


def check_git_ops_api(ctx: Ctx, it: Item, api) -> str | None:
    value = api.fields.get("inputs[dry_run]", "true")
    if api.field_files:
        return git_ops_real_run(ctx, "this git-ops dispatch reads a field from a file, so `dry_run` cannot be checked")
    if api.input_file:
        body = read_input_text(api, it.dir)
        try:
            value = (json.loads(body).get("inputs") or {}).get("dry_run", "true") if body is not None else None
        except (ValueError, AttributeError):
            value = None
        if value is None:
            return git_ops_real_run(ctx, "this git-ops dispatch reads a body that cannot be checked for `dry_run`")
    if _is_false(value):
        return git_ops_real_run(ctx, "this git-ops dispatch has `dry_run` false")
    return None


def check_push_config(it: Item, push) -> str | None:
    d, opts, ov = it.dir, it.git.repo_opts, it.git.config
    for item in ov:
        key = item.partition("=")[0]
        if key.lower() == "push.followtags" and _truthy(item.partition("=")[2]) or PUSH_KEY.match(key):
            return deny(f"the `-c {key}` setting pushes tags")
    if _truthy(git_config_value(d, opts, ov, "push.followTags")):
        return deny("`push.followTags` is true, so this push also pushes tags")
    cur = None
    remote = push.repo
    if not remote:
        from tld.guard._gitcfg import current_branch
        cur = current_branch(d, opts)
        remote = (git_config_value(d, opts, ov, f"branch.{cur}.pushRemote") if cur else None) or \
            git_config_value(d, opts, ov, "remote.pushDefault") or \
            (git_config_value(d, opts, ov, f"branch.{cur}.remote") if cur else None) or "origin"
    if any("refs/tags/" in v for v in git_config_values(d, opts, ov, f"remote.{remote}.push")):
        return deny(f"`remote.{remote}.push` names refs/tags/, so this push pushes tags")
    return None


def check_push(it: Item) -> str | None:
    push = parse_push(it.git.args)
    msg = check_push_config(it, push)
    if msg:
        return msg
    if push.tags:
        return deny("`git push --tags` / `--follow-tags` pushes tags")
    specs = parse_refspecs(push.refspecs)
    for k, spec in enumerate(specs):
        if spec.raw == "tag" and k + 1 < len(specs):
            return deny(f"`git push {push.repo} tag {specs[k + 1].raw}` pushes a tag")
        if "refs/tags/" in spec.src or "refs/tags/" in spec.dst or spec.src.startswith("tags/") \
                or spec.dst.startswith("tags/"):
            return deny(f"refspec `{spec.raw}` names a tag")
        if is_dynamic(spec.src) or not spec.src:
            continue
        name = short_ref(spec.src)
        if ref_exists(it.dir, f"refs/tags/{name}", it.git.repo_opts):
            return deny(f"`{spec.src}` is the name of a tag in this repository, so pushing it pushes the tag")
    return None


def _uncheckable_workflow_id(ident: str) -> bool:
    """A workflow referenced by a numeric id (or any non-file value) cannot be checked against the release one."""
    return not ident.lower().endswith((".yml", ".yaml"))


def check_gh(ctx: Ctx, it: Item) -> str | None:
    path = gh_path(it.words)
    if path[:2] == ["workflow", "run"] and len(path) > 2:
        # the workflow may follow an option whose value ends in .yml: look at every word, release first
        for w in it.words:
            if is_release_workflow(ctx, w):
                return _release_gh_run(ctx, it, w)
        if any(is_git_ops_workflow(ctx, w) for w in it.words):
            return check_git_ops_gh_run(ctx, it)
        if is_release_workflow(ctx, path[2]):
            return _release_gh_run(ctx, it, path[2])
        if is_git_ops_workflow(ctx, path[2]):
            return check_git_ops_gh_run(ctx, it)
        if _uncheckable_workflow_id(path[2]):  # S10: a numeric id could be the release workflow
            return deny("`gh workflow run` with a numeric workflow id cannot be checked against the release "
                        "workflow; dispatch a workflow by its file name")
    if path[:2] == ["release", "edit"] and any(w == "--tag" or w.startswith("--tag=") for w in it.words):
        return deny("`gh release edit --tag` moves a release to another tag")
    if path[:2] in (["release", "create"], ["release", "delete"]):
        return deny(f"`gh {path[0]} {path[1]}` creates or deletes a tag")
    if path[:1] == ["api"]:
        api = parse_gh_api(it.words)
        ep = api.endpoint
        clean = posixpath.normpath(re.sub(r"%([0-9a-fA-F]{2})", lambda h: chr(int(h[1], 16)), re.split(r"[?#]", ep)[0])) if ep else ep
        m = DISPATCH.match(re.sub(r"^api/v3/", "", clean))
        if api.method != "GET" and m and is_release_workflow(ctx, m.group(1)):
            return _release_api(ctx, it, api, m.group(1))
        if api.method != "GET" and m and is_git_ops_workflow(ctx, m.group(1)):
            return check_git_ops_api(ctx, it, api)
        if api.method != "GET" and m and _uncheckable_workflow_id(m.group(1)):  # S10: numeric workflow id
            return deny("this `gh api` dispatch uses a numeric workflow id that cannot be checked against the "
                        "release workflow; dispatch a workflow by its file name")
        if api.method in ("PATCH", "PUT", "DELETE") and REL_EDIT.match(ep):
            return deny("this `gh api` call edits or deletes a release, which moves or removes its tag")
        if api.method != "GET":
            if TAG_REF.match(ep) or re.match(r"^repos/[^/]+/[^/]+/git/tags$", ep) or \
                    re.match(r"^repos/[^/]+/[^/]+/releases$", ep) or \
                    (re.match(r"^repos/[^/]+/[^/]+/git/refs$", ep) and api.fields.get("ref", "").startswith("refs/tags/")):
                return deny("this `gh api` call creates, moves or deletes a tag")
    return None


CURL_TAG_API = re.compile(r"/repos/[^/\s]+/[^/\s]+/(releases(?:/[^/\s?#]+)?|git/tags|git/refs(?:/tags(?:/[^\s?#]*)?)?)"
                          r"/?(?:[?#]|$)")
CURL_DATA = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode", "--json", "-F",
             "--form", "--form-string", "-T", "--upload-file", "--post-data", "--post-file", "--body-data",
             "--body-file"}
HTTP_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def _curl_method_and_data(words: list[str]) -> tuple[str, list[str]]:
    """(HTTP method, data words) of a curl / wget / httpie / xh command line."""
    method, data, i = None, [], 1
    while i < len(words):
        w = words[i]
        i += 1
        name, eq, val = w.partition("=")
        if name in ("-X", "--request", "--method") or (w.startswith("-X") and len(w) > 2):
            if w.startswith("-X") and len(w) > 2:
                val = w[2:]
            elif not eq:
                val, i = (words[i] if i < len(words) else ""), i + 1
            method = val.upper()
        elif name in CURL_DATA:
            if not eq:
                val, i = (words[i] if i < len(words) else ""), i + 1
            data.append(val)
        elif w.upper() in HTTP_METHODS and i == 2:  # httpie / xh: `http POST url`
            method = w.upper()
        elif re.match(r"^[A-Za-z_][\w\[\]]*:?=", w) and not w.startswith("-"):  # httpie / xh body items
            data.append(w)
    return method or ("POST" if data else "GET"), data


def check_curl_tag_api(it: Item) -> str | None:
    """S-curl: a raw API call that creates, edits or deletes a release, a tag object or a tag ref (the same
    endpoints as the `gh api` check)."""
    method, data = _curl_method_and_data(it.words)
    if method in ("GET", "HEAD", "OPTIONS"):
        return None
    for w in it.words[1:]:
        if is_dynamic(w):
            continue
        m = CURL_TAG_API.search(w)
        if not m:
            continue
        what = m.group(1)
        if what == "git/refs" and data and all("refs/tags" not in d and not d.startswith("@") for d in data):
            continue  # a branch ref; no-merge owns those
        if what.startswith("releases/") and method == "POST" and what != "releases/generate-notes":
            continue  # e.g. releases/<id>/assets is an upload, not a tag
        if what == "releases/generate-notes":
            continue
        return deny(f"this request ({method} .../{what}) creates, moves or deletes a tag or a release")
    return None


def check_curl(ctx: Ctx, it: Item) -> str | None:
    """A raw API call to a workflow dispatch: the release one is denied (its body is never read), a git-ops one needs the confirm marker
    (its body is not parsed). A call that creates or edits a release or tag is denied like its `gh api` form."""
    msg = check_curl_tag_api(it)
    if msg:
        return msg
    for w in it.words[1:]:
        m = CURL_DISPATCH.search(w) if not is_dynamic(w) else None
        if not m:
            continue
        if is_release_workflow(ctx, m.group(1)):
            return deny(UNREADABLE_RELEASE)
        if is_git_ops_workflow(ctx, m.group(1)):
            return git_ops_real_run(ctx, "this request dispatches git-ops with a body this hook does not read")
        if _uncheckable_workflow_id(m.group(1)):
            return deny("this request dispatches a workflow by numeric id, which cannot be checked against the "
                        "release workflow")
    return None


def _release_mcp(ctx: Ctx, wid: str, inputs) -> str | None:
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)
        except ValueError:
            return deny(UNREADABLE_RELEASE)
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        return deny(UNREADABLE_RELEASE)
    values: dict[str, list] = {"dry_run": [], "skip_checks": []}
    for k, v in inputs.items():
        if isinstance(k, str) and k.lower() in values:
            values[k.lower()].append("true" if v is True else "false" if v is False else v if isinstance(v, str) else "?")
    return release_inputs_problem(ctx, wid, values)


def check_mcp(ctx: Ctx) -> str | None:
    if (ctx.action.op or "") != "actions_run_trigger":
        return None
    args = ctx.action.args
    method = str(args.get("method", ""))
    if method in ("rerun_workflow_run", "rerun_failed_jobs"):
        return deny("re-running a workflow run may re-run the release workflow; a release is cut by a new, "
                    "approved release run, not by re-running an old one")
    if method != "run_workflow":
        return None
    wid = args.get("workflow_id")
    if isinstance(wid, str) and wid.lower().endswith((".yml", ".yaml")):
        if is_release_workflow(ctx, wid):
            return _release_mcp(ctx, wid, args.get("inputs"))
        if is_git_ops_workflow(ctx, wid):
            inputs = args.get("inputs")
            if isinstance(inputs, str):
                try:
                    inputs = json.loads(inputs)
                except ValueError:
                    return git_ops_real_run(ctx, "this git-ops dispatch has inputs that cannot be read")
            if not isinstance(inputs, dict) and inputs is not None:
                return git_ops_real_run(ctx, "this git-ops dispatch has inputs that cannot be read")
            if _is_false((inputs or {}).get("dry_run", "true")):
                return git_ops_real_run(ctx, "this git-ops dispatch has `dry_run` false")
        return None
    return deny("`run_workflow` with a workflow id (not a file name) cannot be checked, and may be the release "
                "workflow; dispatch by file name")


def evaluate(ctx: Ctx) -> str | None:
    if ctx.action.kind == "github_op":
        return check_mcp(ctx)
    if ctx.action.kind != "shell" or not isinstance(ctx.action.command, str):
        return None
    command = ctx.action.command
    try:
        items = list(iter_items(ctx.cwd, command))
    except ParseError as exc:
        return (f"blocked: cannot parse this command ({exc}), so it cannot be checked for tag changes. "
                "Rewrite it as plain, separate commands.")
    dyn = dynamic_command(command)
    if dyn:
        return dyn
    for it in items:
        msg = integrity(ctx, it)
        if msg:
            return msg
        if it.kind == "git":
            sub = it.git.sub
            if sub == "tag":
                msg = check_tag(it.git.args)
            elif sub == "push":
                msg = check_push(it)
            elif sub == "update-ref" and "--stdin" in it.git.args:
                msg = deny("`git update-ref --stdin` can create tags through input that cannot be read")
            elif sub == "update-ref" and any("refs/tags/" in a for a in it.git.args):
                msg = deny("`git update-ref` on refs/tags/ changes a tag")
        elif it.kind == "gh":
            msg = check_gh(ctx, it)
        elif it.words and it.words[0].rsplit("/", 1)[-1] in ("curl", "wget", "http", "https", "xh"):
            msg = check_curl(ctx, it)
        if msg:
            return msg
    return None

