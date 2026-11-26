"""repo-admin checks for the org base profile: does each repository extend the base, is the pin current,
which guarded keys does it override, and do the repository's merge settings allow its merge style.

Registered as the one entry `profile` in repo_admin.CHECKS. It runs only when the policy has a `profile`
section (`base`, `pin`, `guarded_overrides`). Everything is read through the policy's API client: each
repository's `.tld/toolkit.yaml` at its default branch, and the base file at the commit the repository pins.
Nothing is fetched with git and no cache is written: the profile is resolved offline (no fetch, no
trusted copy).

The module takes the repo_admin names it needs lazily (`_ra()`), because repo_admin imports this module.
"""
from __future__ import annotations

import re
import urllib.parse

import yaml

from tld.profile import base as base_mod
from tld.profile import merge as merge_mod
from tld.profile import resolve as resolve_mod
from tld.profile.defaults import Env

PROFILE_PATH = ".tld/toolkit.yaml"
EXTENDS_LINE = re.compile(r"^(?P<lead>[ \t]+extends:[ \t]*)(?P<value>[^\s#]+)(?P<rest>[ \t]*(?:#.*)?)$")
QUOTED = re.compile(r"'([^']+)'")
STYLE_SETTING = {"merge-commit": "allow_merge_commit", "squash": "allow_squash_merge"}
MAX_SHOWN = 3


def _ra():
    from tld.ops import repo_admin
    return repo_admin


def _quote(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


# ---------------------------------------------------------------------------------------- the pin

def want_pin(ctx) -> tuple[str, str | None]:
    """(commit, tag) the policy wants every repository to pin: the `pin` commit, or the newest version tag of the
    base repository (else its default branch head, tag None)."""
    cfg = ctx.p["profile"]
    owner, repo, _path = base_mod.parse_source(cfg["base"])
    pin = cfg.get("pin", "latest-tag")
    tags = ctx.memo(("base-tags", owner, repo), lambda: ctx.c.paginate(f"/repos/{owner}/{repo}/tags") or [])
    versions = {t["name"]: t["commit"]["sha"].lower() for t in tags
                if isinstance(t, dict) and base_mod.TAG_RE.match(str(t.get("name", ""))) and (t.get("commit") or {}).get("sha")}
    if pin != "latest-tag":
        return pin, next((n for n in sorted(versions, key=base_mod._tag_key, reverse=True) if versions[n] == pin), None)
    if versions:
        newest = max(versions, key=base_mod._tag_key)
        return versions[newest], newest
    default = ctx.c.get(f"/repos/{owner}/{repo}")["default_branch"]
    head = ctx.c.get(f"/repos/{owner}/{repo}/branches/{urllib.parse.quote(default, safe='/')}")
    return head["commit"]["sha"].lower(), None


def bump_extends(text: str, source: str, sha: str, tag: str | None) -> str | None:
    """`text` with only its `extends:` line (under `tld:`) rewritten to `<source>@<sha>  # <tag>`; None when the
    text has no single such line to rewrite."""
    lines = text.split("\n")
    inside, hits = False, []
    for i, line in enumerate(lines):
        if re.match(r"^\S", line) and not line.startswith("#"):
            inside = line.startswith("tld:")
        elif inside and EXTENDS_LINE.match(line.rstrip("\r")):
            hits.append(i)
    if len(hits) != 1:
        return None
    line = lines[hits[0]]
    cr = "\r" if line.endswith("\r") else ""
    m = EXTENDS_LINE.match(line.rstrip("\r"))
    lines[hits[0]] = f"{m.group('lead')}{source}@{sha}" + (f"  # {tag}" if tag else "") + cr
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------- reading

def _profile_text(ctx, repo: dict, snap) -> str | None:
    fn = repo["full_name"]
    if not any(e.get("type") == "blob" and e["path"] == PROFILE_PATH for e in snap.entries):
        return None
    return ctx.c.get_text(f"/repos/{fn}/contents/{_quote(PROFILE_PATH)}", {"ref": snap.commit})


def _base_text(ctx, ref) -> str:
    return ctx.memo(("base-text", ref.source, ref.sha), lambda: ctx.c.get_text(
        f"/repos/{ref.owner}/{ref.repo}/contents/{_quote(ref.path)}", {"ref": ref.sha}))


def _env(ctx, repo: dict, snap) -> Env:
    """What the defaults may look at: the files of the default branch, read through the API (never git)."""
    fn = repo["full_name"]
    present = {e["path"] for e in snap.entries}

    def read(path: str) -> str | None:
        if path not in present:
            return None
        try:
            return ctx.c.get_text(f"/repos/{fn}/contents/{_quote(path)}", {"ref": snap.commit})
        except _ra().ApiError:
            return None

    owner = base_mod.OWNER_RE.match(ctx.org) and ctx.org or None
    return Env(exists=lambda p: p.rstrip("/") in present, read=read, origin_owner=owner, main_branch=snap.branch)


def repo_profile(ctx, repo: dict) -> dict | None:
    """A repository's resolved profile at its default branch (the steps `check_profile` runs, offline), or None when
    it has none, cannot be read, names a base that is refused, or does not resolve. Memoised per repository."""
    return _load(ctx, repo)[0]


def profile_unresolved(ctx, repo: dict) -> bool:
    """True when the repository has a profile file that cannot be read, is refused or does not resolve."""
    profile, exists = _load(ctx, repo)
    return exists and profile is None


def _load(ctx, repo: dict) -> tuple[dict | None, bool]:
    return ctx.memo(("profile", repo["full_name"]), lambda: _read_profile(ctx, repo))


def _read_profile(ctx, repo: dict) -> tuple[dict | None, bool]:
    """(the resolved profile or None, whether a profile file is listed in the default branch)."""
    exists = False
    try:
        snap = ctx.snapshot(repo)
        if snap.empty:
            return None, False
        exists = any(e.get("type") == "blob" and e["path"] == PROFILE_PATH for e in snap.entries)
        text = _profile_text(ctx, repo, snap)
        if text is None:
            return None, exists
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            return None, exists
        tld = raw.get("tld")
        extends = tld.get("extends") if isinstance(tld, dict) else None
        data = ref = None
        if extends is not None:
            ref = resolve_mod.parse_pin(extends)
            data, errors = base_mod.check_base_text(_base_text(ctx, ref), ref.label)
            if errors:
                return None, exists
        res = resolve_mod.resolve(raw, base=data, base_ref=ref, trusted=None, env=_env(ctx, repo, snap))
    except (base_mod.BaseError, _ra().ApiError, yaml.YAMLError):
        return None, exists
    return (res.profile if not res.errors else None), exists


# ---------------------------------------------------------------------------------------- the check

def _plain(message: str) -> str:
    return message[len(resolve_mod.PREFIX):] if message.startswith(resolve_mod.PREFIX) else message


def check_profile(ctx) -> list:
    ra = _ra()
    cfg = ctx.p.get("profile")
    if not cfg:
        return []
    Finding, Action = ra.Finding, ra.Action
    try:
        want_sha, want_tag = want_pin(ctx)
    except ra.ApiError as exc:
        return [ra.failure("profile", ctx.org, exc)]
    owner, repo_name, path = base_mod.parse_source(cfg["base"])
    source = f"{owner}/{repo_name}/{path}"
    base_repo = f"{owner}/{repo_name}"
    report = cfg.get("guarded_overrides", "report") == "report"

    def one(repo):
        fn, out = repo["full_name"], []
        snap = ctx.snapshot(repo)
        if snap.empty:
            return out
        text = _profile_text(ctx, repo, snap)
        if text is None:
            return out  # not a tld repository: nothing to say about its profile
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError:
            raw = None
        if not isinstance(raw, dict):
            return [Finding("profile-invalid-extends", fn, "unreadable", f"{PROFILE_PATH} is not a YAML mapping", "warn",
                            manual=f"fix {PROFILE_PATH}, then run /setup in update mode")]
        tld = raw.get("tld")
        extends = tld.get("extends") if isinstance(tld, dict) else None
        if extends is None:
            if fn.lower() != base_repo.lower():
                out.append(Finding("profile-no-extends", fn, "extends", f"{PROFILE_PATH} does not extend the base {source}",
                                   "warn", manual=f"run /setup in update mode: it writes `tld.extends: {source}@{want_sha}`"
                                   + (f"  # {want_tag}`" if want_tag else "`")))
            return out
        try:
            ref = resolve_mod.parse_pin(extends)
        except base_mod.BaseError as exc:
            return [Finding("profile-invalid-extends", fn, "extends", _plain(str(exc)), "warn",
                            manual=f"run /setup in update mode: it writes `tld.extends: {source}@{want_sha}`")]
        if ref.source.lower() != source.lower():
            return [Finding("profile-invalid-extends", fn, "extends",
                            f"tld.extends names {ref.source}, the policy's base is {source}", "warn",
                            manual="run /setup in update mode, or change `profile.base` in the policy")]
        if ref.sha != want_sha:
            new = bump_extends(text, source, want_sha, want_tag)
            shown = want_tag or want_sha[:7]
            message = f"the base pin {ref.sha[:7]} is not {shown} ({want_sha[:7]})"
            if new is None:
                out.append(Finding("profile-pin-old", fn, "pin", message, "warn",
                                   manual=f"change the `extends:` line of {PROFILE_PATH} to `{source}@{want_sha}`"))
            else:
                change = {"op": "put", "path": PROFILE_PATH, "content": new,
                          "mode": next((e.get("mode", "100644") for e in snap.entries if e["path"] == PROFILE_PATH), "100644")}
                out.append(Finding("profile-pin-old", fn, "pin", f"{message}; bump it with a pull request titled "
                                   f"'chore: bump the tld base to {shown}'", "fix", Action("files", repo=fn, changes=[change])))
        try:
            data, errors = base_mod.check_base_text(_base_text(ctx, ref), ref.label)
        except ra.ApiError as exc:
            out.append(Finding("profile-invalid-extends", fn, "base", f"the base {ref.label} could not be read: "
                               f"HTTP {exc.status}: {exc.message}", "warn"))
            return out
        if errors:
            out.append(Finding("profile-invalid-extends", fn, "base", _plain(errors[0])[:300], "warn"))
            return out
        res = resolve_mod.resolve(raw, base=data, base_ref=ref, trusted=None, env=_env(ctx, repo, snap))
        if res.errors:
            shown = "; ".join(_plain(e) for e in res.errors[:MAX_SHOWN]) + (" ..." if len(res.errors) > MAX_SHOWN else "")
            out.append(Finding("profile-invalid-extends", fn, "resolve", f"the profile does not resolve against the base "
                               f"{ref.label}: {shown}", "warn", manual="fix the profile, or run /setup in update mode"))
            return out
        if report:
            for n, error in enumerate(merge_mod.guarded_errors(data, res.profile, [], ref.label)):
                key = (QUOTED.search(error) or [None, "?"])[1]
                what = _plain(error).split(";")[0].split(": ", 1)[-1]
                out.append(Finding("profile-guarded-override", fn, f"{key}:{n}", f"overrides a guarded key the base "
                                   f"allows: {key}: {what}", "info"))
        style = (res.profile.get("git") or {}).get("merge_style", "merge-commit")
        setting = STYLE_SETTING.get(style)
        if setting and ctx.repo(repo).get(setting) is False:
            out.append(Finding("profile-merge-style", fn, setting, f"the profile's merge style is {style}, but the "
                               f"repository has {setting} off", "warn", manual=f"turn {setting} on at https://github.com/{fn}/settings"))
        return out

    return ra.per_repo(ctx, "profile", one)
