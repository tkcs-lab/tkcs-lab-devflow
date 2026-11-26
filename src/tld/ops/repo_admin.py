#!/usr/bin/env python3
"""Audit and update GitHub organisation and repository settings from a policy file.

    repo_admin.py validate-policy POLICY [--kind auto|run|override|base] [--public] [--resolved] [--explain] [--offline]
                                  [--org-policy FILE --repo-name NAME]
    repo_admin.py latest-pin OWNER/REPO/PATH
    repo_admin.py whoami [--org ORG]
    repo_admin.py audit --policy POLICY [--repo NAME]... [--check NAME]... [--format md|json] [--out FILE]
    repo_admin.py apply --policy POLICY [--repo NAME]... [--check NAME]... [--only ID]...
                        [--allow-delete] [--yes]

The policy (schema/admin-policy.schema.json, docs/guides/admin.md) says what the organisation and its
repositories should look like; a section that is absent is not managed. `audit` only reads. `apply`
recomputes the findings and, without --yes, prints the calls it would make and changes nothing.
With --yes it makes them, except the irreversible ones (deleting a label, secret, variable, webhook,
deploy key or branch; revoking a token), which also need --allow-delete. Changes to files in a repository
(removing a config directory, installing or updating a workflow) are never pushed to a branch that
exists: they go into one commit on a new branch and one pull request per repository, which this
script never merges.

The token comes from GH_TOKEN or GITHUB_TOKEN, else from `gh auth token`. Without one the script
reads public data only. It needs an organisation owner for most checks; a check it is not allowed to
run is reported as 'unavailable', never skipped silently. The token is never printed.

Exit codes: 0 ok (audit: nothing out of policy); 1 bad input, a check that failed (audit) or a change
that failed (apply); 3 audit found differences. Python 3.11+, PyYAML.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import typing
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from tld.net import SameHostRedirects, opener as net_opener
from tld.ops import repo_admin_detect, repo_admin_extends, repo_admin_policy, repo_admin_profile
from tld.ops.repo_admin_gitops import check_git_ops
from tld.ops.repo_admin_profile import check_profile

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCHEMA = PLUGIN / "schema" / "admin-policy.schema.json"
TEMPLATES = PLUGIN / "templates"
API = "https://api.github.com"
DOCS_HELP = "see docs/guides/admin.md in the tkcs-lab-devflow repo"

# Built-in workflow templates: policy name -> (file, default parameters).
BUILTIN_TEMPLATES = {
    "release": ("tld-release.yml", {"tag_prefix": "v", "release_environment": "tld-release", "version_style": "semver",
                                    "check_script": "", "create_release": "true"}),
    "land": ("tld-land.yml", {}),
}
KNOWN_DOT_DIRS = (".github", ".claude", ".tld", ".devcontainer", ".vscode", ".husky", ".config", ".changeset", ".githooks")
SEVERITIES = ("fix", "warn", "info", "unavailable", "error")
OVERRIDE_PARAMS = ("tag_prefix", "version_style", "check_script", "create_release")  # what a repository may set
SAFE_PARAM = re.compile(r"^[A-Za-z0-9._/-]*$")
# Parameters of a built-in template that take one of a few values.
TEMPLATE_CHOICES = {"release": {"version_style": ("semver", "pep440"), "create_release": ("true", "false")}}
PLACEHOLDER = re.compile(r"__([A-Z][A-Z0-9_]*)__")


# --------------------------------------------------------------------------- GitHub client


class ApiError(Exception):
    """A GitHub request that did not succeed (status 0: no answer at all)."""

    def __init__(self, status: int, message: str, method: str = "", path: str = ""):
        super().__init__(f"{method} {path}: HTTP {status}: {message}")
        self.status, self.message, self.method, self.path = status, message, method, path


def _message(raw: bytes) -> str:
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])[:300]
    except ValueError:
        pass
    return raw.decode("utf-8", "replace").strip()[:300]


def _next_link(header: str | None) -> str | None:
    for part in (header or "").split(","):
        m = re.match(r'\s*<([^>]+)>;\s*rel="next"', part)
        if m:
            return m.group(1)
    return None


def find_token() -> str | None:
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    if shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


_SameHostRedirects = SameHostRedirects  # the shared handler (tld.net); the name stays for callers
_OPENER = net_opener()


class Client:
    """The few GitHub REST calls the checks need. Tests replace the whole object."""

    def __init__(self, token: str | None = None, base: str = API, urlopen=None, sleep=time.sleep):
        self.token = token
        self.base = base.rstrip("/")
        self._urlopen = urlopen or _OPENER.open
        self._sleep = sleep

    def _wait(self, status: int, headers) -> float | None:
        """Seconds to wait before retrying a rate-limited request, or None when it is not one."""
        if status not in (403, 429):
            return None
        retry = headers.get("Retry-After")
        if retry and retry.isdigit():
            return min(int(retry), 90)
        if headers.get("X-RateLimit-Remaining") == "0" and (headers.get("X-RateLimit-Reset") or "").isdigit():
            wait = int(headers["X-RateLimit-Reset"]) - time.time() + 1
            return wait if 0 < wait <= 90 else None
        return None

    def _request(self, method, path, body=None, params=None, accept="application/vnd.github+json"):
        url = path if path.startswith("http") else self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "tld-repo-admin"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        shown = urllib.parse.urlsplit(url).path
        for attempt in range(3):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with self._urlopen(req, timeout=60) as resp:
                    return resp.status, resp.headers, resp.read()
            except urllib.error.HTTPError as exc:
                wait = self._wait(exc.code, exc.headers)
                if wait is not None and attempt < 2:
                    self._sleep(wait)
                    continue
                raise ApiError(exc.code, _message(exc.read()), method, shown) from None
            except urllib.error.URLError as exc:
                raise ApiError(0, str(exc.reason), method, shown) from None
        raise ApiError(429, "rate limited", method, shown)  # pragma: no cover

    def get(self, path, params=None):
        _, _, raw = self._request("GET", path, params=params)
        return json.loads(raw) if raw else None

    def get_text(self, path, params=None) -> str:
        _, _, raw = self._request("GET", path, params=params, accept="application/vnd.github.raw+json")
        return raw.decode("utf-8", "replace")

    def status(self, path) -> int:
        """Status of a GET that answers 204 or 404 (a feature switch); other failures raise."""
        try:
            return self._request("GET", path)[0]
        except ApiError as exc:
            if exc.status == 404:
                return 404
            raise

    def send(self, method, path, body=None):
        _, _, raw = self._request(method, path, body=body)
        return json.loads(raw) if raw else None

    def paginate(self, path, params=None, key=None, max_pages=200):
        out, url, first = [], path, True
        for _ in range(max_pages):
            _, headers, raw = self._request("GET", url, params={"per_page": 100, **(params or {})} if first else None)
            data = json.loads(raw) if raw else None
            out.extend((data or {}).get(key, []) if key else (data or []))
            url, first = _next_link(headers.get("Link")), False
            if not url:
                break
        return out


# --------------------------------------------------------------------------- findings


@dataclasses.dataclass
class Action:
    """One change the script can make. kind 'api': a single call. kind 'files': file changes in one
    repository, made through a pull request (see apply_files)."""

    kind: str
    method: str = ""
    path: str = ""
    body: dict | None = None
    destructive: bool = False
    repo: str = ""
    changes: list = dataclasses.field(default_factory=list)
    note: str = ""  # kind 'files': a line for the pull request body (a value the script detected, for the owner to confirm)

    def describe(self) -> str:
        if self.kind == "api":
            return f"{self.method} {self.path}" + (f" {json.dumps(self.body, sort_keys=True)}" if self.body else "")
        parts = [f"{c['op']} {c['path']}" for c in self.changes]
        return f"pull request on {self.repo}: " + ", ".join(parts)


@dataclasses.dataclass
class Finding:
    """severity: fix (out of policy, the script can change it), warn (out of policy, a person must),
    info, unavailable (the check could not run), error (it failed unexpectedly)."""

    check: str
    scope: str
    subject: str
    message: str
    severity: str
    action: Action | None = None
    manual: str = ""

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.check}\0{self.scope}\0{self.subject}".encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "check": self.check, "scope": self.scope, "severity": self.severity,
            "message": self.message, "manual": self.manual,
            "action": self.action.describe() if self.action else None,
            "destructive": bool(self.action and self.action.destructive),
        }


def failure(check: str, scope: str, exc: ApiError) -> Finding:
    what = f"{exc.method} {exc.path}"
    if exc.status in (401, 403, 404):
        why = {401: "no valid token", 403: "the token may not do this", 404: "not found, or the token may not see it"}[exc.status]
        return Finding(check, scope, what, f"could not check ({why}): {what} answered {exc.status}: {exc.message}", "unavailable")
    return Finding(check, scope, what, f"{what} failed: HTTP {exc.status}: {exc.message}", "error")


# --------------------------------------------------------------------------- policy


def _load_check():
    from tld.profile import validate as module
    return module.check, module.HELP


def _param_errors(where: str, template, params: dict) -> list[str]:
    """The value rules of a workflow template's parameters; `where` is the path prefix of each message."""
    errors: list[str] = []
    for key, value in params.items():
        if not isinstance(value, str) or not SAFE_PARAM.fullmatch(value):
            errors.append(f"'{where}.{key}': must be a string of letters, digits and . _ / - only")
            continue
        choices = TEMPLATE_CHOICES.get(template, {}).get(key)
        if choices and value not in choices:
            errors.append(f"'{where}.{key}': must be one of {', '.join(choices)}")
        if template == "release" and key == "check_script" and (value.startswith(("/", "-")) or ".." in value):
            errors.append(f"'{where}.check_script': must be a path inside the repository")
    return errors


def _kind_schema(kind: str, inherited: bool) -> dict:
    """The schema for one kind of file: override and base need no `org`; a run policy that does not inherit still
    needs the login of an `agent` and of a `release` section."""
    schema = json.loads(SCHEMA.read_text())
    if kind != "run":
        schema["required"] = []
    elif not inherited:
        schema["properties"]["agent"]["required"] = ["agent_login"]
        schema["properties"]["release"]["required"] = ["reviewer_login"]
    return schema


def validate_policy(policy, base_dir: Path | None = None, kind: str = "run", where: str = "",
                    public: str | None = None, inherited: bool = False) -> list[str]:
    """Return one message per problem; an empty list means the policy is valid.

    `kind` is run (the default, `org` required), override or base (no `org`; the class errors of
    repo_admin_policy.key_errors come first, with `where` as their prefix and `public` naming the repository of a
    public base). `inherited` (or a non-empty `extends`) skips the rule that an `agent` or `release` section needs its login."""
    if kind not in ("run", "override", "base"):
        raise ValueError(f"validate_policy: kind must be run, override or base (got {kind!r})")
    if not isinstance(policy, dict):
        return ["the policy must be a YAML mapping"]
    check, profile_help = _load_check()
    inherits = inherited or bool(policy.get("extends"))
    schema = _kind_schema(kind, inherits)
    errors: list[str] = []
    check(policy, schema, schema, "", errors)
    errors = [e.replace(profile_help, DOCS_HELP) for e in errors]
    if kind != "run":
        errors = repo_admin_policy.key_errors(policy, kind, where or kind, public) + errors
    if errors:
        return errors
    forbid = policy.get("config_dirs", {}).get("forbid", [])
    for pattern in forbid:
        bare = pattern.strip("/")
        if (not bare or bare.startswith("..") or "/../" in f"/{bare}/" or pattern.startswith("/")
                or bare in ("*", "**", ".*", ".", ".git") or bare.startswith(".git/")
                or len(re.sub(r"[*?\[\]]", "", bare)) < 2):
            errors.append(f"'config_dirs.forbid': refusing '{pattern}' (use a path or glob below the repository root with at "
                          "least two literal characters, not the root, '.git' or a bare wildcard; * matches within one path segment)")
    labels = policy.get("labels", {}).get("sync", [])
    seen: dict[str, str] = {}
    for label in labels:
        for name in [label["name"], *label.get("aliases", [])]:
            if name.lower() in seen and seen[name.lower()] != label["name"]:
                errors.append(f"'labels.sync': '{name}' is used by both '{seen[name.lower()]}' and '{label['name']}'")
            seen.setdefault(name.lower(), label["name"])
    for i, wf in enumerate(policy.get("workflows", [])):
        where_wf = f"workflows[{i}]"
        if ("template" in wf) == ("path" in wf):
            errors.append(f"'{where_wf}': give exactly one of 'template' and 'path'")
            continue
        if "path" in wf:
            rel = Path(wf["path"])
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"'{where_wf}.path': must be a path below the policy file's directory (no absolute path, no '..')")
                continue
            if base_dir is not None:
                target = (base_dir / rel).resolve()
                if not target.is_relative_to(base_dir.resolve()):
                    errors.append(f"'{where_wf}.path': '{wf['path']}' leaves the policy file's directory (a symbolic link?)")
                    continue
                if not target.is_file():
                    errors.append(f"'{where_wf}.path': file not found: '{wf['path']}' (relative to the policy file)")
        if kind == "override":
            errors += [f"{where or kind}: '{where_wf}.params.{key}': a repository override may set only {', '.join(OVERRIDE_PARAMS)}"
                       for key in wf.get("params", {}) if key not in OVERRIDE_PARAMS]
        errors += _param_errors(f"{where_wf}.params", wf.get("template"), wf.get("params", {}))
        if "path" in wf and "dest" not in wf and not re.match(r"^[A-Za-z0-9._-]+\.ya?ml$", Path(wf["path"]).name):
            errors.append(f"'{where_wf}.path': the file name must end in .yml or .yaml, or set 'dest'")
    errors += _param_errors("workflow_params.release", "release", policy.get("workflow_params", {}).get("release", {}))
    if kind == "run":
        from tld.ops import repo_admin_extends
        errors += repo_admin_extends.parse_list(policy.get("extends"))[1]
        repos = policy.get("repos", {})
        if "override_path" in repos:
            rel = Path(repos["override_path"])
            if rel.is_absolute() or ".." in rel.parts or repos["override_path"].startswith("/"):
                errors.append("'repos.override_path': must be a path below the repository root (no absolute path, no '..')")
        for glob, keys in repos.get("allow_loosen", {}).items():
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                errors.append(f"'repos.allow_loosen.{glob}': must be a list of guarded keys")
                continue
            errors += [f"'repos.allow_loosen': '{k}' is not a guarded key" for k in keys
                       if k not in repo_admin_policy.GUARDED_KEYS]
    return errors


def load_policy(path: str, client=None) -> dict:
    """Read, validate and (with a non-empty `extends`) resolve the policy file that is run.

    Without `extends` the file is the policy. With it, the pinned files are fetched through `client` (default: the
    token's own) and merged under the file; any error stops the run, nothing is guessed."""
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"repo_admin: no policy at '{p}'")
    try:
        policy = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise SystemExit(f"repo_admin: policy is not valid YAML: {exc}")
    if isinstance(policy, dict) and policy and "org" not in policy:
        raise SystemExit(f"repo_admin: '{p}' is a repository override file (it has no 'org'); "
                         "run the audit with the organisation's policy file")
    errors = validate_policy(policy, p.resolve().parent)
    if errors:
        raise SystemExit("\n".join(f"policy: {e}" for e in errors))
    if policy.get("extends"):
        from tld.ops import repo_admin_extends
        try:
            res = repo_admin_extends.resolve(client if client is not None else _client(), policy)
        except (ApiError, ValueError) as exc:
            raise SystemExit(f"policy: cannot resolve 'extends': {clean(exc)}")
        if res.errors or res.policy is None:
            raise SystemExit("\n".join(f"policy: {clean(e)}" for e in res.errors))
        policy = res.policy
    policy["_dir"] = str(p.resolve().parent)
    return policy


# --------------------------------------------------------------------------- context


@dataclasses.dataclass
class Snapshot:
    branch: str = ""
    commit: str = ""
    tree: str = ""
    entries: list = dataclasses.field(default_factory=list)
    truncated: bool = False
    empty: bool = False


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _when(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


OVERRIDE_PATH = ".tld/admin-policy.yaml"
MAX_MESSAGE = 300


def _restore_guarded(org: dict, eff: dict, allowed: set) -> tuple[dict, list]:
    """Fail closed: a guarded key the organisation sets must keep a value of the expected kind. When the effective value
    is missing or of another type (an override that blanked a section), the organisation's value is put back."""
    out, found = copy.deepcopy(eff), []
    for key in repo_admin_policy.GUARDED_KEYS:
        if key in allowed:
            continue
        org_value, value = repo_admin_policy._get(org, key), repo_admin_policy._get(out, key)
        if org_value is repo_admin_policy._MISSING:
            continue
        if value is not repo_admin_policy._MISSING and _same_kind(key, org_value, value):
            continue
        found.append(repo_admin_policy.Loosening(key, copy.deepcopy(org_value),
                                                 None if value is repo_admin_policy._MISSING else clean(value, 80)))
        repo_admin_policy._set(out, key, copy.deepcopy(org_value))
    return out, found


def _same_kind(key: str, org_value, value) -> bool:
    if key in repo_admin_policy.LIST_KEYS:
        return isinstance(value, list)
    if key in repo_admin_policy.ORDERED:
        return value in repo_admin_policy.ORDERED[key]
    return isinstance(value, bool) if isinstance(org_value, bool) else type(value) is type(org_value)


def _check_logins(org: dict, eff: dict, override: dict) -> tuple[dict, list]:
    """The reviewer may never be the agent (compared without case). An explicit override of a login or of release.*
    away from the organisation's value is reported."""
    out, warns = copy.deepcopy(eff), []
    for section, key in (("agent", "agent_login"), ("release", "reviewer_login")):
        mine = (override.get(section) or {}) if isinstance(override.get(section), dict) else {}
        if key in mine and mine[key] != repo_admin_policy._get(org, f"{section}.{key}"):
            warns.append((f"login:{section}.{key}", f"the override sets {section}.{key} to {clean(mine[key], 80)!r}, "
                                                    "not the organisation's value"))
    release_set = override.get("release")
    if isinstance(release_set, dict):
        for key in release_set:
            if key == "environment" and isinstance(release_set[key], str) and release_set[key].casefold() == AGENT_ENV.casefold():
                continue  # the drop below reports it, under the subject release:environment
            if key != "reviewer_login" and release_set[key] != repo_admin_policy._get(org, f"release.{key}"):
                warns.append((f"release:{clean(key, 40)}", f"the override sets release.{clean(key, 40)} away from the organisation's value"))
    agent, reviewer = repo_admin_policy._get(out, "agent.agent_login"), repo_admin_policy._get(out, "release.reviewer_login")
    if isinstance(agent, str) and isinstance(reviewer, str) and agent.casefold() == reviewer.casefold():
        gone = []
        for dotted in ("agent.agent_login", "release.reviewer_login"):
            value = repo_admin_policy._get(org, dotted)
            section, key = dotted.split(".")
            if value is repo_admin_policy._MISSING:  # nothing to fall back on: the part that needs the login stands down
                out[section].pop(key, None)
                gone.append(dotted)
            else:
                repo_admin_policy._set(out, dotted, copy.deepcopy(value))
        agent, reviewer = repo_admin_policy._get(out, "agent.agent_login"), repo_admin_policy._get(out, "release.reviewer_login")
        still = isinstance(agent, str) and isinstance(reviewer, str) and agent.casefold() == reviewer.casefold()
        if still:  # the organisation's own logins are equal: the agent may not review its own release
            out["release"].pop("reviewer_login", None)
        if still:
            tail = ("the organisation's logins are equal too, so release.reviewer_login is dropped, the release check stands "
                    "down and the agent's role is not checked for this repository")
        elif gone:
            parts = [("agent.agent_login has no organisation value, so it is derived from the repository's profile or the "
                      "agent role check stands down") if d == "agent.agent_login" else
                     "release.reviewer_login has no organisation value, so it is dropped and the release check stands down"
                     for d in gone]
            tail = "; ".join(parts) + " for this repository"
        else:
            tail = "the organisation's logins apply"
        warns.append(("login:same", "the reviewer login equals the agent login; " + tail))
    env = repo_admin_policy._get(out, "release.environment")
    if isinstance(env, str) and env.casefold() == AGENT_ENV.casefold():
        fallback = repo_admin_policy._get(org, "release.environment")
        if isinstance(fallback, str) and fallback.casefold() != AGENT_ENV.casefold():
            out["release"]["environment"] = fallback
        else:
            del out["release"]["environment"]
        warns.append(("release:environment", f"release.environment may not be the agent environment {AGENT_ENV}; "
                                             "the organisation's or the default environment applies"))
    return out, warns


def _usable(doc) -> dict:
    """The part of an override that may be applied: only overridable sections, each a mapping (`workflows` a list of
    mappings that hold only template, params and remove). Whatever the caller validated, a bad shape is dropped."""
    out: dict = {}
    for key, value in (doc if isinstance(doc, dict) else {}).items():
        if key not in repo_admin_policy.OVERRIDABLE:
            continue
        if key == "workflows":
            if isinstance(value, list):
                out[key] = [{k: v for k, v in e.items() if k in ("template", "params", "remove")}
                            for e in value if isinstance(e, dict) and isinstance(e.get("template"), str)
                            and isinstance(e.get("params", {}), dict)]
        elif isinstance(value, dict):
            out[key] = copy.deepcopy(value)
    return out


def effective_policy(org: dict, override_doc, repo_name: str) -> tuple[dict, list, list]:
    """(the effective policy, the loosenings put back, the login warnings) of one repository: the one place where an
    override meets the organisation policy, for the audit and for `validate-policy --org-policy`."""
    doc = _usable(override_doc)
    allowed = repo_admin_policy.allowed_for(org, repo_name)
    eff, loose = repo_admin_policy.clamp_guarded(org, repo_admin_policy.apply_override(org, doc), allowed)
    eff, more = _restore_guarded(org, eff, allowed)
    eff, warns = _check_logins(org, eff, doc)
    return eff, loose + more, warns


SAME_LOGIN = "reviewer equals the agent login"  # the reason derive_logins gives


class Logins(typing.NamedTuple):
    """agent / reviewer: the effective logins (None when missing or refused); reasons: why one is missing; same: both
    were equal, so the reviewer is refused; dropped: the policy merge already dropped the reviewer for that."""
    agent: str | None
    reviewer: str | None
    reasons: list
    same: bool = False
    dropped: bool = False
    agent_derived: bool = False  # taken from the repository's profile (repository-controlled), not from a policy
    reviewer_derived: bool = False


@dataclasses.dataclass
class Override:
    """What a repository's override file holds: `doc` is None when there is none or when it has problems."""
    doc: dict | None
    path: str
    legacy: bool = False
    problems: list = dataclasses.field(default_factory=list)
    notes: list = dataclasses.field(default_factory=list)


class Ctx:
    """The client, the policy and the caches one run shares."""

    def __init__(self, client, policy: dict, only_repos=(), now: dt.datetime | None = None, detect: bool = True):
        self.c, self.p, self.org = client, policy, policy["org"]
        self.detect = detect  # False: the policy check proposes nothing from the repositories (--no-detect)
        self.only = set(only_repos)
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self._cache: dict = {}

    def memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    @property
    def inherited(self) -> bool:
        return bool(self.p.get("_inherited"))

    def override(self, repo: dict) -> Override:
        """The repository's override file (repos.override_path of the run policy) at its default branch, checked as data:
        shape and credentials first, then the class errors of its kind. A whole old policy (it has `org`) is converted."""
        return self.memo(("override", repo["full_name"]), lambda: self._read_override(repo))

    def _read_override(self, repo: dict) -> Override:
        fn = repo["full_name"]
        path = (self.p.get("repos") or {}).get("override_path") or OVERRIDE_PATH
        if not isinstance(path, str):
            path = OVERRIDE_PATH
        where = f"{fn}:{path}"

        def bad(*problems) -> Override:
            return Override(None, path, False, [clean(p, MAX_MESSAGE) for p in problems], [])

        rel = Path(path)
        if rel.is_absolute() or ".." in rel.parts or path.startswith("/"):
            return bad("repos.override_path must be a path below the repository root")
        snap = self.snapshot(repo)
        listed = any(e.get("type") == "blob" and e.get("path") == path for e in snap.entries)
        if snap.empty or not (listed or snap.truncated):
            return Override(None, path)
        try:
            text = self.c.get_text(f"/repos/{fn}/contents/{urllib.parse.quote(path, safe='/')}", {"ref": snap.commit})
        except ApiError as exc:
            if exc.status == 404 and not listed:  # a tree too large to list: the path itself says whether the file exists
                return Override(None, path)
            return bad(f"{path} cannot be read (HTTP {exc.status})" + ("" if listed else "; the file tree is too large to list it"))
        if not isinstance(text, str) or not text.strip():
            return Override(None, path)
        doc, errors = repo_admin_extends.shape_errors(text, f"override {where}")
        if errors or doc is None:
            return bad(*(errors or [f"{path} is not a mapping"]))
        notes: list[str] = []
        legacy = "org" in doc
        if legacy:
            errors = validate_policy(doc, kind="run")
            if errors:
                return bad(*errors)
            run_only = [f"dropped run-only key '{key}'" for key in ("extends", "repos") if key in doc]
            doc, notes = repo_admin_policy.legacy_to_override(doc, self.p)
            notes += run_only
        errors = validate_policy(doc, kind="override", where=where)
        if errors:
            return bad(*errors)
        return Override(doc, path, legacy, [], [clean(n, MAX_MESSAGE) for n in notes])

    def pol(self, repo: dict) -> dict:
        """The effective policy of one repository. Without `extends` it is the policy itself and nothing is read."""
        if not self.inherited:
            return self.p
        return self.memo(("pol", repo["full_name"]), lambda: self._effective(repo))

    def logins(self, repo: dict) -> "Logins":
        """The effective agent and reviewer logins of one repository: the explicit values of its effective policy, else
        the ones derived from its resolved profile (read only when a value is missing)."""
        return self.memo(("logins", repo["full_name"]), lambda: self._logins(repo))

    def _logins(self, repo: dict) -> "Logins":
        pol = self.pol(repo)
        has_agent, has_release = isinstance(pol.get("agent"), dict), isinstance(pol.get("release"), dict)
        agent = (pol.get("agent") or {}).get("agent_login") if has_agent else None
        reviewer = (pol.get("release") or {}).get("reviewer_login") if has_release else None
        agent, reviewer = (v if isinstance(v, str) and v else None for v in (agent, reviewer))
        dropped = any(subject == "login:same" for subject, _ in self.pol_warnings(repo))  # the merge dropped the reviewer
        reasons: list[str] = []
        agent_derived = reviewer_derived = False
        compare = agent  # a release section without an agent section still compares with the profile's git.bot_login
        if (has_agent and agent is None) or (has_release and reviewer is None and not dropped) or (has_release and not has_agent):
            profile = repo_admin_profile.repo_profile(self, repo)
            d_agent, _, reasons = repo_admin_policy.derive_logins(profile)
            reasons = [r for r in reasons if r != SAME_LOGIN]
            # The reviewer candidate must not depend on the profile's own bot_login: only the effective pair is compared.
            git = profile.get("git") if isinstance(profile, dict) else None
            bare = {**profile, "git": {k: v for k, v in git.items() if k != "bot_login"}} if isinstance(git, dict) else profile
            _, d_reviewer, _ = repo_admin_policy.derive_logins(bare)
            if has_agent and agent is None:
                agent, agent_derived = d_agent, d_agent is not None
            if has_release and reviewer is None and not dropped:
                reviewer, reviewer_derived = d_reviewer, d_reviewer is not None
            compare = agent if has_agent else d_agent
        same = False
        org_agent, org_reviewer = (repo_admin_policy._get(self.p, k) for k in ("agent.agent_login", "release.reviewer_login"))
        if (dropped and isinstance(org_agent, str) and isinstance(org_reviewer, str)
                and org_agent.casefold() == org_reviewer.casefold()):
            same = True  # the organisation's own logins are equal: the merge dropped the reviewer, the agent role is not checked
            reasons = reasons + [SAME_LOGIN]
        elif has_release and compare and reviewer and compare.casefold() == reviewer.casefold():
            same, reviewer, reviewer_derived = True, None, False  # fail closed on the effective pair only
            reasons = reasons + [SAME_LOGIN]
        return Logins(agent, reviewer, reasons, same, dropped, agent_derived, reviewer_derived)

    def loosenings(self, repo: dict) -> list:
        """The guarded settings an override of this repository tried to loosen and that were put back."""
        self.pol(repo)
        return self._cache.get(("loose", repo["full_name"]), [])

    def pol_warnings(self, repo: dict) -> list[tuple[str, str]]:
        """(subject, message) of what the merge noticed about the logins of this repository."""
        self.pol(repo)
        return self._cache.get(("warn", repo["full_name"]), [])

    def _effective(self, repo: dict) -> dict:
        fn = repo["full_name"]
        # An override is data an agent can edit: effective_policy applies only what is safe, whatever was validated.
        eff, loose, warns = effective_policy(self.p, self.override(repo).doc, repo["name"])
        self._cache[("loose", fn)] = loose
        self._cache[("warn", fn)] = warns
        return eff

    @property
    def partial(self) -> bool:
        """True when every --repo was given as owner/name: only those repositories are fetched, so the
        organisation-wide 'unused' checks (which need to see every repository) stand down."""
        return bool(self.only) and all("/" in name for name in self.only)

    @property
    def all_repos(self) -> list[dict]:
        if self.partial:
            return self.memo("repos", lambda: [self.c.get(f"/repos/{name}") for name in sorted(self.only)])
        return self.memo("repos", lambda: self.c.paginate(f"/orgs/{self.org}/repos", {"type": "all"}))

    @property
    def org_complete(self) -> bool:
        """True when the repository list holds every repository the organisation has. A token that cannot see
        some repositories under-counts where a secret is used, so nothing of the organisation may be deleted as unused."""

        def build() -> bool:
            try:
                org = self.c.get(f"/orgs/{self.org}")
            except ApiError:
                return False
            counts = [org.get("public_repos"), org.get("total_private_repos")]
            return all(isinstance(n, int) for n in counts) and len(self.all_repos) >= sum(counts)

        return self.memo("complete", build)

    @property
    def scan_repos(self) -> list[dict]:
        """Every live repository: where a secret or variable of the organisation might be used."""
        return [r for r in self.all_repos if not r.get("archived")]

    @property
    def repos(self) -> list[dict]:
        cfg = self.p.get("repos", {})
        out = []
        for r in self.all_repos:
            name = r["name"]
            if cfg.get("skip_archived", True) and r.get("archived"):
                continue
            if cfg.get("skip_forks", True) and r.get("fork"):
                continue
            if not any(fnmatch.fnmatchcase(name, g) for g in cfg.get("include", ["*"])):
                continue
            if any(fnmatch.fnmatchcase(name, g) for g in cfg.get("exclude", [])):
                continue
            if self.only and name not in self.only and r["full_name"] not in self.only:
                continue
            out.append(r)
        return out

    def repo(self, repo: dict) -> dict:
        return self.memo(("repo", repo["full_name"]), lambda: self.c.get(f"/repos/{repo['full_name']}"))

    def snapshot(self, repo: dict) -> Snapshot:
        def build() -> Snapshot:
            fn, branch = repo["full_name"], self.repo(repo)["default_branch"]
            try:
                b = self.c.get(f"/repos/{fn}/branches/{urllib.parse.quote(branch, safe='/')}")
            except ApiError as exc:
                if exc.status == 404:
                    return Snapshot(branch=branch, empty=True)
                raise
            tree_sha = b["commit"]["commit"]["tree"]["sha"]
            tree = self.c.get(f"/repos/{fn}/git/trees/{tree_sha}", {"recursive": "1"})
            return Snapshot(branch, b["commit"]["sha"], tree_sha, tree.get("tree", []), bool(tree.get("truncated")))

        return self.memo(("snap", repo["full_name"]), build)

    def automation_files(self, repo: dict) -> tuple[list[tuple[str, str]], bool]:
        """([(path, text)] of the workflow files and dependabot.yml on the default branch, unreadable). unreadable is
        true when a file could not be read or the tree was too large to list."""

        def build():
            snap = self.snapshot(repo)
            files, unreadable = [], snap.truncated
            for e in snap.entries:
                if e.get("type") != "blob" or not re.match(r"^\.github/(workflows/[^/]+|dependabot)\.ya?ml$", e["path"]):
                    continue
                try:
                    files.append((e["path"], self.c.get_text(
                        f"/repos/{repo['full_name']}/contents/{urllib.parse.quote(e['path'], safe='/')}", {"ref": snap.commit})))
                except ApiError:
                    unreadable = True
            return files, unreadable

        return self.memo(("files", repo["full_name"]), build)

    def usage(self, repo: dict) -> tuple[set, set, bool]:
        """(secret names, variable names, opaque) that a repository's workflows and dependabot.yml
        refer to. opaque is true when the text hides some (secrets: inherit, a computed name, the whole
        context as in toJSON(secrets), or a file that could not be read), so nothing may be called unused.
        Only the default branch is read."""

        def build():
            files, opaque = self.automation_files(repo)
            secrets, variables = set(), set()
            for _, text in files:
                for kind, dotted, quoted in REFERENCE.findall(text):
                    (secrets if kind == "secrets" else variables).add((dotted or quoted).upper())
                if INHERIT.search(text) or COMPUTED.search(text) or WHOLE_CONTEXT.search(text):
                    opaque = True
            return secrets, variables, opaque

        return self.memo(("usage", repo["full_name"]), build)


REFERENCE = re.compile(r"\b(secrets|vars)\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([^'\"]+)['\"]\s*\])")
INHERIT = re.compile(r"^\s*secrets:\s*inherit\b", re.M)
COMPUTED = re.compile(r"\b(?:secrets|vars)\s*\[\s*(?!['\"])")
WHOLE_CONTEXT = re.compile(r"\$\{\{(?:(?!\}\}).)*?\b(?:secrets|vars)\b(?!\s*[.\[])", re.S)  # toJSON(secrets), format('{0}', vars)


def per_repo(ctx: Ctx, check: str, fn) -> list[Finding]:
    out: list[Finding] = []
    for repo in ctx.repos:
        try:
            out += fn(repo)
        except ApiError as exc:
            out.append(failure(check, repo["full_name"], exc))
    return out


def api(method, path, body=None, destructive=False) -> Action:
    return Action("api", method, path, body, destructive)


# --------------------------------------------------------------------------- organisation checks

ORG_READ_ONLY = {"two_factor_requirement_enabled"}


def check_org(ctx: Ctx) -> list[Finding]:
    want = ctx.p.get("org_settings")
    if not want:
        return []
    org = ctx.c.get(f"/orgs/{ctx.org}")
    out = []
    for key, value in want.items():
        if key not in org:
            out.append(Finding("org", ctx.org, key, f"cannot read '{key}' (organisation owner needed)", "unavailable"))
        elif org[key] != value:
            msg = f"{key} is {org[key]!r}, policy wants {value!r}"
            if key in ORG_READ_ONLY:
                out.append(Finding("org", ctx.org, key, msg, "warn",
                                   manual=f"change it at https://github.com/organizations/{ctx.org}/settings/security"))
            else:
                out.append(Finding("org", ctx.org, key, msg, "fix", api("PATCH", f"/orgs/{ctx.org}", {key: value})))
    return out


def check_members(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("members")
    if not cfg:
        return []
    out = []
    people = f"https://github.com/orgs/{ctx.org}/people"
    if cfg.get("require_two_factor"):
        for m in ctx.c.paginate(f"/orgs/{ctx.org}/members", {"filter": "2fa_disabled"}):
            out.append(Finding("members", ctx.org, f"2fa:{m['login']}", f"{m['login']} has two-factor authentication disabled",
                               "warn", manual=f"ask them to enable it, or remove them at {people}"))
    if "max_owners" in cfg:
        owners = [m["login"] for m in ctx.c.paginate(f"/orgs/{ctx.org}/members", {"role": "admin"})]
        if len(owners) > cfg["max_owners"]:
            out.append(Finding("members", ctx.org, "owners", f"{len(owners)} owners ({', '.join(sorted(owners))}), policy allows "
                               f"{cfg['max_owners']}", "warn", manual=f"change roles at {people}"))
    return out


def check_apps(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("apps")
    if cfg is None:
        return []
    allowed = {a.lower() for a in cfg.get("allow", [])}
    base = f"https://github.com/organizations/{ctx.org}/settings/installations"
    out = []
    for inst in ctx.c.paginate(f"/orgs/{ctx.org}/installations", key="installations"):
        slug = inst.get("app_slug", "?")
        where = f"{base}/{inst['id']}"
        if slug.lower() not in allowed:
            out.append(Finding("apps", ctx.org, slug, f"app '{slug}' is installed but not in apps.allow "
                               f"(repositories: {inst.get('repository_selection', '?')})", "warn",
                               manual=f"uninstall it or add it to apps.allow: {where}"))
        elif inst.get("suspended_at"):
            out.append(Finding("apps", ctx.org, f"{slug}:suspended", f"app '{slug}' is suspended", "warn",
                               manual=f"unsuspend or uninstall it: {where}"))
    out.append(Finding("apps", ctx.org, "oauth", "OAuth app authorisations and classic personal access tokens cannot be listed "
                       "through the API", "info",
                       manual=f"review https://github.com/organizations/{ctx.org}/settings/oauth_application_policy and "
                              "https://github.com/settings/tokens by hand"))
    return out


def check_tokens(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("tokens", {}).get("fine_grained")
    if cfg is None:
        return []
    max_days, out = cfg.get("max_unused_days"), []
    for t in ctx.c.paginate(f"/orgs/{ctx.org}/personal-access-tokens"):
        last, granted = _when(t.get("token_last_used_at")), _when(t.get("access_granted_at"))
        why = None
        if t.get("token_expired") and cfg.get("revoke_expired", True):
            why = "expired"
        elif max_days:
            ref = last or granted
            if ref is not None and (ctx.now - ref).days > max_days:
                why = f"{'not used for' if last else 'never used, granted'} {(ctx.now - ref).days} days"
        if why:
            owner = (t.get("owner") or {}).get("login", "?")
            out.append(Finding("tokens", ctx.org, str(t["id"]), f"fine-grained token '{t.get('token_name', '?')}' of {owner}: {why}",
                               "fix", api("POST", f"/orgs/{ctx.org}/personal-access-tokens/{t['id']}", {"action": "revoke"}, True)))
    return out


# --------------------------------------------------------------------------- repository settings


def check_repo(ctx: Ctx) -> list[Finding]:
    if not ctx.p.get("repo_settings") and not ctx.inherited:
        return []

    def one(repo):
        want = ctx.pol(repo).get("repo_settings")
        if not want:
            return []
        full, fn = ctx.repo(repo), repo["full_name"]
        return [Finding("repo", fn, key, f"{key} is {full.get(key)!r}, policy wants {value!r}", "fix",
                        api("PATCH", f"/repos/{fn}", {key: value}))
                for key, value in want.items() if full.get(key) != value]

    return per_repo(ctx, "repo", one)


SCANNING = {"secret_scanning": "secret_scanning", "secret_push_protection": "secret_scanning_push_protection"}


def check_security(ctx: Ctx) -> list[Finding]:
    if not ctx.p.get("security") and not ctx.inherited:
        return []

    def one(repo):
        want = ctx.pol(repo).get("security")
        if not want:
            return []
        fn, out = repo["full_name"], []

        def diff(key, have, value, enable: Action, disable: Action):
            if have != value:
                out.append(Finding("security", fn, key, f"{key} is {'on' if have else 'off'}, policy wants "
                                   f"{'on' if value else 'off'}", "fix", enable if value else disable))

        if "vulnerability_alerts" in want:
            path = f"/repos/{fn}/vulnerability-alerts"
            diff("vulnerability_alerts", ctx.c.status(path) == 204, want["vulnerability_alerts"], api("PUT", path), api("DELETE", path))
        if "automated_security_fixes" in want:
            path = f"/repos/{fn}/automated-security-fixes"
            try:
                have = bool((ctx.c.get(path) or {}).get("enabled"))
            except ApiError as exc:
                if exc.status != 404:
                    raise
                have = False
            diff("automated_security_fixes", have, want["automated_security_fixes"], api("PUT", path), api("DELETE", path))
        if "private_vulnerability_reporting" in want:
            path = f"/repos/{fn}/private-vulnerability-reporting"
            diff("private_vulnerability_reporting", bool((ctx.c.get(path) or {}).get("enabled")),
                 want["private_vulnerability_reporting"], api("PUT", path), api("DELETE", path))
        sa = ctx.repo(repo).get("security_and_analysis")
        for key, api_key in SCANNING.items():
            if key not in want:
                continue
            if sa is None or api_key not in sa:
                out.append(Finding("security", fn, key, f"cannot read {key} (admin access, and GitHub Advanced Security on "
                                   "private repositories, are needed)", "unavailable"))
                continue
            def body(status):
                return {"security_and_analysis": {api_key: {"status": status}}}
            diff(key, sa[api_key].get("status") == "enabled", want[key],
                 api("PATCH", f"/repos/{fn}", body("enabled")), api("PATCH", f"/repos/{fn}", body("disabled")))
        return out

    return per_repo(ctx, "security", one)


def check_actions(ctx: Ctx) -> list[Finding]:
    if not ctx.p.get("actions") and not ctx.inherited:
        return []

    def one(repo):
        want = ctx.pol(repo).get("actions")
        if not want:
            return []
        fn, out = repo["full_name"], []
        if "enabled" in want:
            have = ctx.c.get(f"/repos/{fn}/actions/permissions")["enabled"]
            if have != want["enabled"]:
                out.append(Finding("actions", fn, "enabled", f"Actions enabled is {have}, policy wants {want['enabled']}", "fix",
                                   api("PUT", f"/repos/{fn}/actions/permissions", {"enabled": want["enabled"]})))
        wf_keys = [k for k in ("default_workflow_permissions", "can_approve_pull_request_reviews") if k in want]
        if wf_keys:
            have = ctx.c.get(f"/repos/{fn}/actions/permissions/workflow")
            for k in wf_keys:
                if have.get(k) != want[k]:
                    out.append(Finding("actions", fn, k, f"{k} is {have.get(k)!r}, policy wants {want[k]!r}", "fix",
                                       api("PUT", f"/repos/{fn}/actions/permissions/workflow", {k: want[k]})))
        return out

    return per_repo(ctx, "actions", one)


def protection_body(cfg: dict) -> dict:
    checks = cfg.get("require_status_checks", [])
    return {
        "required_status_checks": {"strict": cfg.get("strict", False), "contexts": checks} if checks else None,
        "enforce_admins": cfg.get("enforce_admins", False),
        "required_pull_request_reviews": ({"required_approving_review_count": cfg.get("approvals", 1)}
                                          if cfg.get("require_pull_request", True) else None),
        "restrictions": None,
        "required_linear_history": cfg.get("linear_history", False),
        "allow_force_pushes": cfg.get("allow_force_pushes", False),
        "allow_deletions": cfg.get("allow_deletions", False),
    }


def check_protection(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("branch_protection")
    if cfg is None:
        return []
    if (ctx.p.get("rulesets") or {}).get("default_branch") is not None and cfg.get("branch", "default") == "default":
        return []  # the ruleset tld-main is the protection of the default branch

    def one(repo):
        fn, snap = repo["full_name"], ctx.snapshot(repo)
        if snap.empty:
            return []
        branch = snap.branch if cfg.get("branch", "default") == "default" else cfg["branch"]
        quoted = urllib.parse.quote(branch, safe="/")
        if branch != snap.branch:
            try:
                ctx.c.get(f"/repos/{fn}/branches/{quoted}")
            except ApiError as exc:
                if exc.status != 404:
                    raise
                return [Finding("protection", fn, branch, f"branch '{branch}' does not exist", "info")]
        try:
            have = ctx.c.get(f"/repos/{fn}/branches/{quoted}/protection")
        except ApiError as exc:
            if exc.status != 404:
                raise
            have = None
        try:
            rules = ctx.c.get(f"/repos/{fn}/rules/branches/{quoted}") or []
        except ApiError as exc:
            if exc.status not in (403, 404):
                raise
            rules = []
        if have is None and not rules:
            return [Finding("protection", fn, branch, f"branch '{branch}' has no protection rule and no ruleset", "fix",
                            api("PUT", f"/repos/{fn}/branches/{quoted}/protection", protection_body(cfg)))]
        out = []
        if have is not None:
            want = protection_body(cfg)
            reviews = (have.get("required_pull_request_reviews") or {}).get("required_approving_review_count", 0)
            want_reviews = (want["required_pull_request_reviews"] or {}).get("required_approving_review_count", 0)
            rsc = have.get("required_status_checks") or {}
            have_checks = set(rsc.get("contexts", [])) | {c.get("context") for c in rsc.get("checks", [])}
            diffs = []
            if reviews < want_reviews:
                diffs.append(f"{reviews} required approvals, policy wants {want_reviews}")
            missing = set((want["required_status_checks"] or {}).get("contexts", [])) - have_checks
            if missing:
                diffs.append(f"required checks lack {', '.join(sorted(missing))}")
            if bool((have.get("enforce_admins") or {}).get("enabled")) != want["enforce_admins"]:
                diffs.append(f"enforce_admins differs from {want['enforce_admins']}")
            if bool((have.get("allow_force_pushes") or {}).get("enabled")) and not want["allow_force_pushes"]:
                diffs.append("force pushes are allowed")
            if bool((have.get("allow_deletions") or {}).get("enabled")) and not want["allow_deletions"]:
                diffs.append("deleting the branch is allowed")
            for d in diffs:
                out.append(Finding("protection", fn, f"{branch}:{d}", f"branch '{branch}': {d}", "warn",
                                   manual=f"change it at https://github.com/{fn}/settings/branches (an existing rule is never replaced)"))
        return out

    return per_repo(ctx, "protection", one)


# --------------------------------------------------------------------------- rulesets and the agent account
#
# The server-side control (docs/guides/admin.md): rulesets on the default branch and on tags, an agent account
# with the write role and no more, and the agent token in an environment only the default branch can use.

MAIN_RULESET, TAG_RULESET = "tld-main", "tld-tags"
ADMIN_ROLE_ID = 5          # the repository role 'admin' as a ruleset bypass actor
AGENT_ENV, AGENT_SECRET = "tld-agent", "TLD_AGENT_TOKEN"
RELEASE_ENV, RELEASE_SECRET = "tld-release", "TLD_RELEASE_TOKEN"
ROLE_ABOVE_WRITE = ("admin", "maintain")
ROLE_BELOW_WRITE = ("triage", "read", "none")


def ruleset_bodies(cfg: dict, live_checks: list | None = None) -> list[dict]:
    """The rulesets the policy asks for, as request bodies of POST/PUT /repos/{owner}/{repo}/rulesets. The status checks
    are `required_status_checks` of the default branch when that key is present (an explicit [] removes the rule);
    when it is absent, `live_checks` (the contexts the live ruleset already requires) are kept."""
    out = []
    main = cfg.get("default_branch")
    if main is not None:
        rules = [{"type": "deletion"}, {"type": "non_fast_forward"},
                 {"type": "pull_request", "parameters": {
                     "required_approving_review_count": 1, "dismiss_stale_reviews_on_push": True,
                     "require_last_push_approval": True, "require_code_owner_review": False,
                     "required_review_thread_resolution": False}}]
        checks = main["required_status_checks"] if "required_status_checks" in main else (live_checks or [])
        if checks:
            rules.append({"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": False,
                "required_status_checks": [c if isinstance(c, dict) else {"context": c} for c in checks]}})
        bypass = ([{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
                  if main.get("admin_bypass") else [])
        out.append({"name": MAIN_RULESET, "target": "branch", "enforcement": "active", "bypass_actors": bypass,
                    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}, "rules": rules})
    if cfg.get("tags"):
        out.append({"name": TAG_RULESET, "target": "tag", "enforcement": "active",
                    # Only the admin role: no workflow's GITHUB_TOKEN can tag. The release workflow tags with
                    # TLD_RELEASE_TOKEN, an owner token kept in the reviewed environment tld-release.
                    "bypass_actors": [{"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
                    "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
                    "rules": [{"type": "creation"}, {"type": "update", "parameters": {"update_allows_fetch_and_merge": False}},
                              {"type": "deletion"}]})
    return out


def _param_diffs(kind: str, want: dict, have: dict) -> list[str]:
    """The wanted parameters of rule `kind` that `have` does not match. GitHub leaves a false
    boolean out of a rule it returns (the tag ruleset's update rule comes back without
    update_allows_fetch_and_merge), so a missing key matches a wanted False."""
    if kind == "required_status_checks":
        contexts = lambda p: sorted(c.get("context") for c in p.get("required_status_checks") or [])  # noqa: E731
        bound = {c.get("context"): c.get("integration_id") for c in have.get("required_status_checks") or []}
        unbound = [c for c in want.get("required_status_checks") or []  # a kept live check must stay bound to its integration
                   if "integration_id" in c and bound.get(c.get("context")) != c["integration_id"]]
        keys = ["required_status_checks"] if contexts(want) != contexts(have) or unbound else []
        if bool(have.get("strict_required_status_checks_policy")) != want["strict_required_status_checks_policy"]:
            keys.append("strict_required_status_checks_policy")
        return keys
    return [k for k, v in want.items() if have.get(k, False if v is False else None) != v]


def ruleset_diffs(want: dict, have: dict) -> tuple[list[str], bool]:
    """(what differs, bypass actors unreadable). A token without admin rights gets a ruleset without its bypass list."""
    diffs = []
    if have.get("target") != want["target"]:
        diffs.append(f"target is {have.get('target')!r}, not {want['target']!r}")
    if have.get("enforcement") != "active":
        diffs.append(f"enforcement is {have.get('enforcement')!r}, not 'active'")
    ref = (have.get("conditions") or {}).get("ref_name") or {}
    want_ref = want["conditions"]["ref_name"]
    if sorted(ref.get("include") or []) != sorted(want_ref["include"]) or ref.get("exclude"):
        diffs.append(f"applies to {ref.get('include') or []} minus {ref.get('exclude') or []}, not {want_ref['include']}")
    have_rules = {r.get("type"): r.get("parameters") or {} for r in have.get("rules") or []}
    for rule in want["rules"]:
        kind = rule["type"]
        if kind not in have_rules:
            diffs.append(f"rule {kind} is missing")
        elif keys := _param_diffs(kind, rule.get("parameters") or {}, have_rules[kind]):
            diffs.append(f"rule {kind} has other parameters: {', '.join(keys)}")
    extra = sorted(set(have_rules) - {r["type"] for r in want["rules"]})
    if extra:
        diffs.append(f"extra rules {', '.join(map(str, extra))}")
    if "bypass_actors" not in have:
        return diffs, True
    key = lambda a: (a.get("actor_type"), a.get("actor_id"), a.get("bypass_mode"))  # noqa: E731
    if sorted(map(key, have["bypass_actors"] or []), key=str) != sorted(map(key, want["bypass_actors"]), key=str):
        diffs.append("bypass actors differ: " + (", ".join(f"{t} {i} ({m})" for t, i, m in map(key, have["bypass_actors"] or []))
                                                 or "none") + " instead of " + (", ".join(
                                                     f"{t} {i} ({m})" for t, i, m in map(key, want["bypass_actors"])) or "none"))
    return diffs, False


def _live_contexts(have: dict) -> list[dict]:
    """The status checks a live ruleset requires, verbatim (the context and, when set, the integration that must report it)."""
    for rule in (have or {}).get("rules") or []:
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
            checks = (rule.get("parameters") or {}).get("required_status_checks") or []
            return [dict(c) for c in checks if isinstance(c, dict) and isinstance(c.get("context"), str)]
    return []


def check_rulesets(ctx: Ctx) -> list[Finding]:
    shared = []
    if not ctx.inherited:
        cfg = ctx.p.get("rulesets")
        shared = ruleset_bodies(cfg) if cfg else []
        if not shared:
            return []

    def one(repo):
        fn, out = repo["full_name"], []
        cfg = ctx.pol(repo).get("rulesets") if ctx.inherited else None
        if ctx.inherited:
            if not (cfg and ruleset_bodies(cfg)):
                return []
        elif not shared:
            return []
        listing = ctx.c.paginate(f"/repos/{fn}/rulesets", {"includes_parents": "false"})
        mine = {r.get("name"): r for r in listing or [] if r.get("source_type", "Repository") == "Repository"}
        live: dict = {}  # live rulesets read before the bodies are built (a failed read is the failure finding, no fix)
        bodies = shared
        if ctx.inherited:
            main = cfg.get("default_branch")
            live_checks = None
            if main is not None and "required_status_checks" not in main and MAIN_RULESET in mine:
                live[MAIN_RULESET] = ctx.c.get(f"/repos/{fn}/rulesets/{mine[MAIN_RULESET]['id']}")
                live_checks = _live_contexts(live[MAIN_RULESET])
            bodies = ruleset_bodies(cfg, live_checks)
        for want in bodies:
            name, cur = want["name"], mine.get(want["name"])
            if cur is None:
                out.append(Finding("rulesets", fn, name, f"ruleset {name} is missing", "fix",
                                   api("POST", f"/repos/{fn}/rulesets", want)))
                continue
            have = live[name] if name in live else ctx.c.get(f"/repos/{fn}/rulesets/{cur['id']}")
            diffs, unknown = ruleset_diffs(want, have or {})
            if diffs:
                out.append(Finding("rulesets", fn, name, f"ruleset {name}: {'; '.join(diffs)}", "fix",
                                   api("PUT", f"/repos/{fn}/rulesets/{cur['id']}", want)))
            elif unknown:
                out.append(Finding("rulesets", fn, f"{name}:bypass", f"ruleset {name}: its bypass actors cannot be read "
                                   "(the token needs admin rights on the repository)", "unavailable"))
        return out

    return per_repo(ctx, "rulesets", one)


def _part(check: str, fn: str, out: list, fn_part) -> None:
    """Run one part of a per-repository check; a failed call becomes a finding and the other parts still run."""
    try:
        out += fn_part()
    except ApiError as exc:
        out.append(failure(check, fn, exc))


def environment_findings(ctx: Ctx, check: str, fn: str, repo: dict, name: str, mode: str = "default_branch",
                         reviewers: list[dict] | None = None, reviewer_label: str = "the owner") -> tuple[list[Finding], bool]:
    """(findings, the environment exists) for an environment whose deployment branches are only the default branch
    (mode default_branch) or the protected branches, and, when `reviewers` is given, exactly those required reviewers
    ([{"type": "User", "id": n}])."""
    env_path = f"/repos/{fn}/environments/{_q(name)}"
    custom = mode == "default_branch"
    want = {"protected_branches": not custom, "custom_branch_policies": custom}
    default = ctx.repo(repo)["default_branch"]
    out = []
    try:
        env = ctx.c.get(env_path)
    except ApiError as exc:
        if exc.status != 404:
            raise
        env = None
    have = (env or {}).get("deployment_branch_policy")
    have_reviewers = sorted((r.get("type"), (r.get("reviewer") or {}).get("id"))
                            for rule in (env or {}).get("protection_rules") or [] if rule.get("type") == "required_reviewers"
                            for r in rule.get("reviewers") or [])
    reviewers_differ = reviewers is not None and have_reviewers != sorted((r["type"], r["id"]) for r in reviewers)
    if env is None or not isinstance(have, dict) or any(bool(have.get(k)) != v for k, v in want.items()) or reviewers_differ:
        if env is None:
            what = "is missing"
        elif not isinstance(have, dict):
            what = "lets every branch deploy"
        elif any(bool(have.get(k)) != v for k, v in want.items()):
            what = "has another deployment branch policy"
        else:
            what = "has other required reviewers (" + (", ".join(f"{t} {i}" for t, i in have_reviewers) or "none") + ")"
        body = {"deployment_branch_policy": want, **({"reviewers": reviewers} if reviewers is not None else {})}
        out.append(Finding(check, fn, f"environment:{name}", f"environment {name} {what}; policy wants "
                           + ("only the default branch" if custom else "protected branches only")
                           + (f" and {reviewer_label} as the one required reviewer" if reviewers is not None else ""), "fix",
                           api("PUT", env_path, body)))
    if custom:
        policies = []
        if isinstance(have, dict) and have.get("custom_branch_policies"):
            policies = ctx.c.paginate(f"{env_path}/deployment-branch-policies", key="branch_policies")
        if not any(p.get("name") == default and p.get("type", "branch") == "branch" for p in policies):
            out.append(Finding(check, fn, f"environment:{name}:branch:{default}", f"environment {name} does "
                               f"not allow the default branch {default}", "fix",
                               api("POST", f"{env_path}/deployment-branch-policies", {"name": default, "type": "branch"})))
        for pol in policies:
            if pol.get("name") == default and pol.get("type", "branch") == "branch":
                continue
            out.append(Finding(check, fn, f"environment:{name}:extra:{pol.get('type', 'branch')}:{pol.get('name')}",
                               f"environment {name} also allows the {pol.get('type', 'branch')} pattern "
                               f"'{pol.get('name')}'; policy wants only {default}", "fix",
                               api("DELETE", f"{env_path}/deployment-branch-policies/{pol['id']}")))
    return out, env is not None


def secret_findings(ctx: Ctx, check: str, fn: str, env_name: str, secret: str, env_exists: bool, needed_by: str) -> list[Finding]:
    """A secret that should live only in an environment: reported when it is a repository or organisation secret too,
    or missing from the environment. Only names are read; a value never is."""
    out = []
    set_it = f"gh secret set {secret} --env {env_name} --repo {fn}"
    for label, where, path in (("repository", "a repository secret", f"/repos/{fn}/actions/secrets"),
                               ("organisation", "an organisation secret shared with the repository",
                                f"/repos/{fn}/actions/organization-secrets")):
        if any(s["name"].upper() == secret for s in ctx.c.paginate(path, key="secrets")):
            out.append(Finding(check, fn, f"secret:{label}", f"{secret} is {where}: every "
                               f"workflow on every branch can read it; it belongs in the environment {env_name}", "warn",
                               manual=f"`{set_it}` (the value is never readable), then delete the other secret"))
    names = set()
    if env_exists:
        names = {s["name"].upper() for s in ctx.c.paginate(f"/repos/{fn}/environments/{_q(env_name)}/secrets", key="secrets")}
    if secret not in names:
        out.append(Finding(check, fn, "secret:environment", f"{secret} is not set in the environment {env_name} "
                           f"({needed_by} needs it)", "info", manual=f"`{set_it}`"))
    return out


def _env_and_secret(ctx: Ctx, check: str, fn: str, repo: dict, out: list, env_name: str, secret: str, needed_by: str,
                    mode: str = "default_branch", reviewers=None, reviewer_label: str = "the owner") -> None:
    exists = [False]

    def env_part():
        found, exists[0] = environment_findings(ctx, check, fn, repo, env_name, mode, reviewers, reviewer_label)
        return found

    _part(check, fn, out, env_part)
    _part(check, fn, out, lambda: secret_findings(ctx, check, fn, env_name, secret, exists[0], needed_by))


def derived_finding(check: str, fn: str, key: str, login: str, source: str) -> Finding:
    """A login that comes from the repository's own profile is repository-controlled: every use of it is named."""
    return Finding(check, fn, f"login:derived:{key}", clean(
        f"{key} {clean(login, 80)} is taken from the repository profile ({source}); the changes below name this account",
        MAX_MESSAGE), "warn", manual=f"check that {clean(login, 80)} is the right account, or set {key} in the organisation policy "
                                   "or the repository's override")


def _why(reasons: list, who: str) -> str:
    """The reasons of derive_logins that concern one login ('agent' or 'reviewer'), for a message."""
    words = ("bot_login",) if who == "agent" else ("owner_login", "codeowners", SAME_LOGIN)
    found = [r for r in reasons if r == "no profile" or any(w in r for w in words)]
    return clean("; ".join(found) or "no value in the repository's profile", 200)


def check_agent(ctx: Ctx) -> list[Finding]:
    if not ctx.p.get("agent") and not ctx.inherited:
        return []

    def role(fn, login):
        try:
            perm = ctx.c.get(f"/repos/{fn}/collaborators/{_q(login)}/permission") or {}
        except ApiError as exc:
            if exc.status != 404:
                raise
            perm = {"role_name": "none"}
        have = perm.get("role_name") or perm.get("permission") or "none"
        if have in ROLE_ABOVE_WRITE:
            return [Finding("agent", fn, f"role:{login}", f"agent account {login} has the {have} role; policy allows write",
                            "fix", api("PUT", f"/repos/{fn}/collaborators/{_q(login)}", {"permission": "push"}))]
        if have in ROLE_BELOW_WRITE:
            return [Finding("agent", fn, f"role:{login}", f"agent account {login} has the {have} role; it needs write to "
                            "push branches and open pull requests", "warn",
                            manual=f"invite {login} with the write role at https://github.com/{fn}/settings/access")]
        return []

    def one(repo):
        cfg = ctx.pol(repo).get("agent")
        if not cfg:
            return []
        mode = cfg.get("branch_policy", "default_branch")
        fn, out = repo["full_name"], []
        if not ctx.inherited:
            login = cfg.get("agent_login")
        else:  # the explicit login, else the one derived from the repository's profile
            lg = ctx.logins(repo)
            login = lg.agent
            if lg.same:  # never change the role of the account that also reviews the release
                login = None
                out.append(Finding("agent", fn, "login:same", clean(
                    f"the reviewer login equals the agent login {clean(lg.agent, 80)}; the agent's role is not checked and "
                    "the release check stands down for this repository", MAX_MESSAGE), "warn",
                    manual="give the agent its own account: set git.bot_login in the repository's profile or agent.agent_login in its override"))
            elif login is None:
                out.append(Finding("agent", fn, "login:agent", clean(
                    f"agent.agent_login is not set and cannot be derived ({_why(lg.reasons, 'agent')})", MAX_MESSAGE), "warn",
                    manual="set git.bot_login in the repository's profile or agent.agent_login in its override"))
        if ctx.inherited and login and lg.agent_derived:
            out.append(derived_finding("agent", fn, "agent.agent_login", login, "git.bot_login"))
        if login:
            _part("agent", fn, out, lambda: role(fn, login))
        _env_and_secret(ctx, "agent", fn, repo, out, AGENT_ENV, AGENT_SECRET, "the land workflow", mode)
        return out

    return per_repo(ctx, "agent", one)


def check_release(ctx: Ctx) -> list[Finding]:
    """The environment the release workflow runs in: only the default branch, the owner as the one required reviewer,
    and TLD_RELEASE_TOKEN as its secret. With the tag ruleset (no workflow bypass) that token is the only way to a tag."""
    if not ctx.p.get("release") and not ctx.inherited:
        return []

    def user_of(login):
        return ctx.memo(("user", login), lambda: ctx.c.get(f"/users/{_q(login)}")["id"])

    if not ctx.inherited:  # one organisation-level lookup, as before
        try:
            user_id = user_of(ctx.p["release"]["reviewer_login"])
        except ApiError as exc:
            return [failure("release", ctx.org, exc)]

    def one(repo):
        cfg = ctx.pol(repo).get("release")
        if not cfg:
            return []
        fn, out = repo["full_name"], []
        if ctx.inherited:
            lg = ctx.logins(repo)
            if lg.reviewer is None:  # comparing reviewers with none would loosen the check: it stands down
                if lg.dropped:
                    return []  # the policy merge dropped it and the policy check says why
                if lg.same:
                    return [Finding("release", fn, "login:same", clean(
                        "the reviewer login equals the agent login; the release check stands down for this repository",
                        MAX_MESSAGE), "warn", manual="give the agent its own account (git.bot_login or agent.agent_login)")]
                return [Finding("release", fn, "login:reviewer", clean(
                    f"release.reviewer_login is not set and cannot be derived ({_why(lg.reasons, 'reviewer')}); the release "
                    "check stands down for this repository", MAX_MESSAGE), "warn",
                    manual="set git.owner_login in the repository's profile or release.reviewer_login in its override")]
            uid = user_of(lg.reviewer)
            if lg.reviewer_derived:
                out.append(derived_finding("release", fn, "release.reviewer_login", lg.reviewer,
                                           "git.owner_login or the one git.codeowners entry"))
        else:
            uid = user_id
        _env_and_secret(ctx, "release", fn, repo, out, cfg.get("environment", RELEASE_ENV), RELEASE_SECRET,
                        "the release workflow", reviewers=[{"type": "User", "id": uid}],
                        reviewer_label=f"{clean(lg.reviewer, 80)} (taken from the repository profile)" if ctx.inherited and lg.reviewer_derived
                        else "the owner")
        return out

    return per_repo(ctx, "release", one)


# --------------------------------------------------------------------------- secrets and variables


def _unused_finding(check, scope, noun, name, path, flag, why):
    msg = f"{noun} {name} is {why}"
    if flag:
        return Finding(check, scope, f"{noun}:{name}", msg, "fix", api("DELETE", path, destructive=True))
    return Finding(check, scope, f"{noun}:{name}", msg, "warn", manual="delete it, or list it under keep (delete_unused: true lets apply delete it)")


def _named(ctx: Ctx, check: str, cfg: dict, noun: str, repo_lists, avail_lists, org_lists, used_index: int) -> list[Finding]:
    """Shared by the secrets and variables checks.

    repo_lists / org_lists: (label, list path, response key, delete path) per API family, with {r},
    {o} and {n} for repository, organisation and name. avail_lists: (list path, key) of every list a
    required name may come from (the repository's own and the ones the organisation shares with it).
    used_index: 0 for secret names, 1 for variable names in Ctx.usage."""
    keep = {k.upper() for k in cfg.get("keep", [])}
    flag = cfg.get("delete_unused", False)

    def one(repo):
        fn, res = repo["full_name"], []
        secrets_used = ctx.usage(repo)
        used, opaque = secrets_used[used_index], secrets_used[2]
        for label, list_path, key, del_path in repo_lists:
            for item in ctx.c.paginate(list_path.format(r=fn), key=key):
                name = item["name"]
                if opaque or name.upper() in keep or name.upper() in used:
                    continue
                res.append(_unused_finding(check, fn, label, name, del_path.format(r=fn, n=_q(name)), flag,
                                           "not referred to by any workflow of this repository"))
        if cfg.get("required"):
            have: set[str] = set()
            for list_path, key in avail_lists:
                have |= {x["name"].upper() for x in ctx.c.paginate(list_path.format(r=fn), key=key)}
            for name in cfg["required"]:
                if name.upper() not in have:
                    res.append(Finding(check, fn, f"missing:{name}", f"required {noun} {name} is not set", "warn",
                                       manual=f"gh {noun} set {name} --repo {fn}  (the script cannot know the value)"))
        return res

    out = per_repo(ctx, check, one)
    if ctx.partial:
        return out + [Finding(check, ctx.org, "org-scan", f"organisation-level {noun}s were not checked: they need every "
                              "repository read, and --repo owner/name limits the run to the ones named", "info")]
    # Organisation level: unused only when no live repository of the organisation refers to the name.
    usages = {}
    for repo in ctx.scan_repos:
        try:
            usages[repo["full_name"]] = ctx.usage(repo)
        except ApiError as exc:
            return out + [failure(check, repo["full_name"], exc)]
    blocked = sorted(r for r, u in usages.items() if u[2])
    used_anywhere = set().union(*(u[used_index] for u in usages.values())) if usages else set()
    complete = ctx.org_complete
    for label, list_path, key, del_path in org_lists:
        for item in ctx.c.paginate(list_path.format(o=ctx.org), key=key):
            name = item["name"]
            if name.upper() in keep or name.upper() in used_anywhere:
                continue
            if blocked or not complete:
                more = " and more" if len(blocked) > 5 else ""
                why = (f"{', '.join(blocked[:5])}{more} hide names (secrets: inherit, a computed name, the whole context or an "
                       "unreadable file)") if blocked else ("the token does not see every repository of the organisation "
                                                           "(it must belong to an owner to be sure)")
                out.append(Finding(check, ctx.org, f"{label}:{name}", f"cannot tell whether {label} {name} is used: {why}", "info"))
                continue
            out.append(_unused_finding(check, ctx.org, label, name, del_path.format(o=ctx.org, n=_q(name)), flag,
                                       "not referred to by any workflow of any repository in the organisation"))
    return out


def check_secrets(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("secrets")
    if cfg is None:
        return []
    kinds = cfg.get("kinds", ["actions", "dependabot"])
    label = {"actions": "secret", "dependabot": "dependabot secret"}
    repo_lists = [(label[k], "/repos/{r}/%s/secrets" % k, "secrets", "/repos/{r}/%s/secrets/{n}" % k) for k in kinds]
    org_lists = [("org " + label[k], "/orgs/{o}/%s/secrets" % k, "secrets", "/orgs/{o}/%s/secrets/{n}" % k) for k in kinds]
    avail = [("/repos/{r}/actions/secrets", "secrets"), ("/repos/{r}/actions/organization-secrets", "secrets")]
    return _named(ctx, "secrets", cfg, "secret", repo_lists, avail, org_lists, 0)


def check_variables(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("variables")
    if cfg is None:
        return []
    repo_lists = [("variable", "/repos/{r}/actions/variables", "variables", "/repos/{r}/actions/variables/{n}")]
    org_lists = [("org variable", "/orgs/{o}/actions/variables", "variables", "/orgs/{o}/actions/variables/{n}")]
    avail = [("/repos/{r}/actions/variables", "variables"), ("/repos/{r}/actions/organization-variables", "variables")]
    return _named(ctx, "variables", cfg, "variable", repo_lists, avail, org_lists, 1)


# --------------------------------------------------------------------------- labels


def _color(value: str | None) -> str:
    return (value or "").lstrip("#").lower()


def label_in_use(ctx: Ctx, fn: str, name: str) -> bool:
    if "," in name:  # the API filter splits on commas: assume the label is in use
        return True
    return bool(ctx.c.get(f"/repos/{fn}/issues", {"labels": name, "state": "all", "per_page": 1}))


def check_labels(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("labels")
    if cfg is None:
        return []
    keep = {k.lower() for k in cfg.get("keep", [])}

    def one(repo):
        fn, out = repo["full_name"], []
        existing = ctx.c.paginate(f"/repos/{fn}/labels")
        by_name = {label["name"].lower(): label for label in existing}
        claimed: set[str] = set()
        for want in cfg.get("sync", []):
            name, color, desc = want["name"], _color(want.get("color")), want.get("description")
            cur = by_name.get(name.lower())
            via = None
            if cur is None:
                via = next((by_name[a.lower()] for a in want.get("aliases", []) if a.lower() in by_name), None)
                cur = via
            if cur is None:
                body = {"name": name, **({"color": color} if color else {}), **({"description": desc} if desc is not None else {})}
                out.append(Finding("labels", fn, f"create:{name}", f"label '{name}' is missing", "fix", api("POST", f"/repos/{fn}/labels", body)))
                continue
            claimed.add(cur["name"].lower())
            body = {}
            if cur["name"] != name:
                body["new_name"] = name
            if color and _color(cur.get("color")) != color:
                body["color"] = color
            if desc is not None and (cur.get("description") or "") != desc:
                body["description"] = desc
            if body:
                verb = f"rename '{cur['name']}' to '{name}'" if via else f"update '{name}' ({', '.join(k for k in body)})"
                out.append(Finding("labels", fn, f"update:{name}", f"label: {verb}", "fix",
                                   api("PATCH", f"/repos/{fn}/labels/{_q(cur['name'])}", body)))
        for label in existing:
            low = label["name"].lower()
            if low in claimed or low in keep:
                continue
            name = label["name"]
            used = label_in_use(ctx, fn, name)
            path = f"/repos/{fn}/labels/{_q(name)}"
            if cfg.get("delete_unlisted") or (cfg.get("delete_unused") and not used):
                out.append(Finding("labels", fn, f"delete:{name}", f"label '{name}' is not in the policy and is "
                                   f"{'used' if used else 'unused'}", "fix", api("DELETE", path, destructive=True)))
            else:
                out.append(Finding("labels", fn, f"unlisted:{name}", f"label '{name}' is not in the policy and is "
                                   f"{'used' if used else 'unused'}", "info" if used else "warn",
                                   manual="" if used else "delete it, or list it under labels.keep"))
        return out

    return per_repo(ctx, "labels", one)


# --------------------------------------------------------------------------- webhooks and deploy keys


def redact_url(url: str | None) -> str:
    """Scheme and host only: the path or query of a delivery URL is often the secret."""
    p = urllib.parse.urlsplit(url or "")
    return f"{p.scheme}://{p.hostname}/…" if p.hostname else "(no url)"


def hook_state(hook: dict) -> str:
    if not hook.get("active", True):
        return "inactive"
    last = hook.get("last_response") or {}
    code, status = last.get("code"), last.get("status")
    if status == "misconfigured" or (code is not None and not 200 <= code < 300):
        return "failing"
    if code is None:
        return "never delivered"
    return "ok"


def _recent_success(ctx: Ctx, list_path: str, hook_id) -> bool | None:
    """Did any of the hook's latest deliveries succeed? None when the deliveries cannot be read."""
    try:
        deliveries = ctx.c.get(f"{list_path}/{hook_id}/deliveries", {"per_page": 30}) or []
    except ApiError:
        return None
    return any(200 <= (d.get("status_code") or 0) < 300 for d in deliveries)


def _hooks(ctx: Ctx, scope: str, list_path: str, cfg: dict) -> list[Finding]:
    out = []
    for hook in ctx.c.paginate(list_path):
        url = (hook.get("config") or {}).get("url") or ""
        if any(url.startswith(prefix) for prefix in cfg.get("keep_urls", [])):
            continue
        state = hook_state(hook)
        if state == "ok":
            continue
        deletable = True
        if state == "failing":
            # One bad delivery is not a dead hook: it is deleted only when none of the latest deliveries succeeded.
            recent = _recent_success(ctx, list_path, hook["id"])
            deletable = recent is False
            if recent:
                state = "flaky (the last delivery failed, an earlier one succeeded)"
        msg = f"webhook {hook['id']} ({redact_url(url)}) is {state}"
        if deletable and state in cfg.get("delete", []):
            out.append(Finding("webhooks", scope, str(hook["id"]), msg, "fix", api("DELETE", f"{list_path}/{hook['id']}", destructive=True)))
        else:
            out.append(Finding("webhooks", scope, str(hook["id"]), msg, "info" if state == "never delivered" else "warn",
                               manual="" if state == "never delivered" else "fix or delete it (webhooks.delete lets apply delete it)"))
    return out


def check_webhooks(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("webhooks")
    if cfg is None:
        return []
    try:
        out = _hooks(ctx, ctx.org, f"/orgs/{ctx.org}/hooks", cfg)
    except ApiError as exc:
        out = [failure("webhooks", ctx.org, exc)]
    return out + per_repo(ctx, "webhooks", lambda r: _hooks(ctx, r["full_name"], f"/repos/{r['full_name']}/hooks", cfg))


def check_keys(ctx: Ctx) -> list[Finding]:
    cfg = ctx.p.get("deploy_keys")
    if not cfg or "max_unused_days" not in cfg:
        return []

    def one(repo):
        fn, out = repo["full_name"], []
        for key in ctx.c.paginate(f"/repos/{fn}/keys"):
            ref = _when(key.get("last_used")) or _when(key.get("created_at"))
            if ref is None or (ctx.now - ref).days <= cfg["max_unused_days"]:
                continue
            days = (ctx.now - ref).days
            msg = f"deploy key '{key.get('title', '?')}' (id {key['id']}, {'read-only' if key.get('read_only') else 'read-write'}): " \
                  f"{'not used for' if key.get('last_used') else 'no recorded use, created'} {days} days"
            if not key.get("last_used"):
                # GitHub does not record a last use for every key: unknown is not unused, so a person decides.
                out.append(Finding("keys", fn, str(key["id"]), msg, "warn", manual="check whether it is still needed, then delete it by hand"))
            elif cfg.get("delete_unused"):
                out.append(Finding("keys", fn, str(key["id"]), msg, "fix", api("DELETE", f"/repos/{fn}/keys/{key['id']}", destructive=True)))
            else:
                out.append(Finding("keys", fn, str(key["id"]), msg, "warn", manual="delete it (deploy_keys.delete_unused: true lets apply do it)"))
        return out

    return per_repo(ctx, "keys", one)


# --------------------------------------------------------------------------- branches

MAX_BRANCH_COMPARES = 500


def last_touched(ctx: Ctx, fn: str, branch: str) -> dt.datetime | None:
    """When the branch last changed (created or pushed to), from the repository activity API; None when unknown.
    The date of the commit it points at says nothing: a branch cut today from an old commit would look old."""
    try:
        acts = ctx.c.get(f"/repos/{fn}/activity", {"ref": f"refs/heads/{branch}", "per_page": 1})
    except ApiError:
        return None
    return _when((acts[0] if acts else {}).get("timestamp"))


def check_branches(ctx: Ctx) -> list[Finding]:
    """Branches whose every commit is already in the default branch, that no open pull request uses as head or
    base and that were last touched more than branches.min_age_days ago (unknown: left alone)."""
    cfg = ctx.p.get("branches")
    if cfg is None:
        return []
    min_age = cfg.get("min_age_days", 14)

    def one(repo):
        fn, default, out = repo["full_name"], ctx.repo(repo)["default_branch"], []
        pulls = ctx.c.paginate(f"/repos/{fn}/pulls", {"state": "open"})
        open_heads = {p["head"]["ref"] for p in pulls if ((p["head"].get("repo") or {}).get("full_name") == fn)}
        open_bases = {(p.get("base") or {}).get("ref") for p in pulls}  # closing a stacked pull request's base closes it
        candidates = [b for b in ctx.c.paginate(f"/repos/{fn}/branches")
                      if b["name"] != default and not b.get("protected") and b["name"] not in open_heads | open_bases
                      and not any(fnmatch.fnmatchcase(b["name"], g) for g in cfg.get("keep", []))]
        for b in candidates[:MAX_BRANCH_COMPARES]:
            name = b["name"]
            cmp = ctx.c.get(f"/repos/{fn}/compare/{urllib.parse.quote(default, safe='/')}...{urllib.parse.quote(name, safe='/')}")
            if cmp.get("ahead_by") != 0 or cmp.get("status") not in ("behind", "identical"):
                continue
            head = last_touched(ctx, fn, name)
            if head is None or (ctx.now - head).days < min_age:
                continue
            msg = f"branch '{name}' is fully merged into {default} (last activity {(ctx.now - head).days} days ago) and has no open pull request"
            if cfg.get("delete_merged"):
                out.append(Finding("branches", fn, name, msg, "fix",
                                   api("DELETE", f"/repos/{fn}/git/refs/heads/{urllib.parse.quote(name, safe='/')}", destructive=True)))
            else:
                out.append(Finding("branches", fn, name, msg, "warn", manual="delete it (branches.delete_merged: true lets apply do it)"))
        if len(candidates) > MAX_BRANCH_COMPARES:
            out.append(Finding("branches", fn, "capped", f"{len(candidates) - MAX_BRANCH_COMPARES} more branches were not examined "
                               f"(limit {MAX_BRANCH_COMPARES} per repository)", "info"))
        return out

    return per_repo(ctx, "branches", one)


# --------------------------------------------------------------------------- files: config directories and workflows


def matches(path: str, pattern: str) -> bool:
    """True when path is the pattern or lies below it. The pattern is matched segment by segment from the
    repository root, so * never crosses a '/'."""
    want, parts = pattern.strip("/").split("/"), path.split("/")
    return len(parts) >= len(want) and all(fnmatch.fnmatchcase(p, g) for p, g in zip(parts, want))


def render_template(text: str, params: dict[str, str]) -> str:
    missing = sorted({m for m in PLACEHOLDER.findall(text)} - {k.upper() for k in params})
    if missing:
        raise ValueError(f"template needs params: {', '.join(m.lower() for m in missing)}")
    return PLACEHOLDER.sub(lambda m: params[m.group(1).lower()] if m.group(1).lower() in params else m.group(0), text)


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip("\n") + "\n"


def workflow_source(policy: dict, wf: dict) -> tuple[str, str, dict]:
    """(template text, default destination, default params) of a policy workflow entry."""
    if "template" in wf:
        name, defaults = BUILTIN_TEMPLATES[wf["template"]]
        return (TEMPLATES / name).read_text(), f".github/workflows/{name}", dict(defaults)
    path = Path(policy.get("_dir", ".")) / wf["path"]
    return path.read_text(), f".github/workflows/{path.name}", {}


def check_files(ctx: Ctx) -> list[Finding]:
    if ctx.p.get("config_dirs") is None and not ctx.p.get("workflows") and not ctx.inherited:
        return []

    def one(repo):
        pol = ctx.pol(repo)
        cfg, workflows = pol.get("config_dirs"), pol.get("workflows")
        if cfg is None and not workflows:
            return []
        forbid = (cfg or {}).get("forbid", [])
        known = set(KNOWN_DOT_DIRS) | set((cfg or {}).get("known", []))
        fn, snap, out = repo["full_name"], ctx.snapshot(repo), []
        if snap.empty:
            return out
        if snap.truncated:
            out.append(Finding("files", fn, "truncated", "the file tree is too large for the API to list in full; file checks "
                               "may miss files", "info"))
        blobs = [e for e in snap.entries if e.get("type") == "blob"]
        present = {e["path"] for e in blobs}
        for needed in (cfg or {}).get("require", []):
            if needed not in present:
                out.append(Finding("files", fn, f"require:{needed}", f"required file {needed} is missing", "warn",
                                   manual=f"add {needed} to the repository (the script cannot know what it should say)"))
        for pattern in forbid:
            hit = sorted(e["path"] for e in blobs if matches(e["path"], pattern))
            if hit:
                changes = [{"op": "delete", "path": p} for p in hit]
                out.append(Finding("files", fn, f"forbid:{pattern}", f"{len(hit)} file(s) under forbidden path '{pattern}' "
                                   f"(first: {hit[0]})", "fix", Action("files", repo=fn, changes=changes)))
        if cfg is not None:
            for e in snap.entries:
                top = e["path"]
                if e.get("type") == "tree" and "/" not in top and top.startswith(".") and top not in known \
                        and not any(matches(top, p) for p in forbid):
                    out.append(Finding("files", fn, f"unknown:{top}", f"top-level directory '{top}' is not in config_dirs.known "
                                       "(unused configuration?)", "info", manual="add it to config_dirs.known or to config_dirs.forbid"))
        for i, wf in enumerate(workflows or []):
            if wf.get("repos") and not any(fnmatch.fnmatchcase(repo["name"], g) for g in wf["repos"]):
                continue
            text, default_dest, defaults = workflow_source(ctx.p, wf)
            if wf.get("template") == "release" and (pol.get("release") or {}).get("environment"):
                defaults["release_environment"] = pol["release"]["environment"]  # the one the release check manages
            dest = wf.get("dest", default_dest)
            entry = next((e for e in blobs if e["path"] == dest), None)
            if wf.get("remove"):
                if entry:
                    out.append(Finding("files", fn, f"workflow:{dest}", f"workflow {dest} should not exist", "fix",
                                       Action("files", repo=fn, changes=[{"op": "delete", "path": dest}])))
                continue
            if ctx.inherited and wf.get("template") == "release" and not {**(wf.get("params") or {}),
                                                                          **((pol.get("workflow_params") or {}).get("release") or {})}:
                out.append(Finding("files", fn, f"workflow:{dest}:standdown", "release workflow: no release parameters for this "
                                   "repository yet; it is not installed or rewritten (the policy check proposes them)", "info"))
                continue
            if ctx.inherited and wf.get("template") == "release":
                prof = repo_admin_profile.repo_profile(ctx, repo)
                if isinstance(prof, dict) and not isinstance(prof.get("release"), dict):
                    out.append(Finding("files", fn, f"workflow:{dest}:standdown", "release workflow: the repository's profile has "
                                       "no release section; it is not installed or rewritten", "info"))
                    continue
            params = {"main_branch": snap.branch, **defaults, **{k.lower(): v for k, v in wf.get("params", {}).items()}}
            # The default branch name comes from the repository, not from the policy: it is put into YAML and shell too.
            bad = [k for k, v in params.items() if not SAFE_PARAM.fullmatch(v) or ".." in v or (k == "main_branch" and not v)]
            if bad:
                out.append(Finding("files", fn, f"workflow:{dest}", f"workflows[{i}]: not rendered, {', '.join(sorted(bad))} "
                                   "has characters other than letters, digits and . _ / -", "error"))
                continue
            try:
                want = _norm(render_template(text, params))
            except ValueError as exc:
                out.append(Finding("files", fn, f"workflow:{dest}", f"workflows[{i}]: {exc}", "error"))
                continue
            if entry is None:
                change = {"op": "put", "path": dest, "content": want, "mode": "100644"}
                out.append(Finding("files", fn, f"workflow:{dest}", f"workflow {dest} is missing", "fix",
                                   Action("files", repo=fn, changes=[change])))
                continue
            have = ctx.c.get_text(f"/repos/{fn}/contents/{urllib.parse.quote(dest, safe='/')}", {"ref": snap.commit})
            if _norm(have) != want:
                change = {"op": "put", "path": dest, "content": want, "mode": entry.get("mode", "100644")}
                out.append(Finding("files", fn, f"workflow:{dest}", f"workflow {dest} differs from its template", "fix",
                                   Action("files", repo=fn, changes=[change])))
        return out

    return per_repo(ctx, "files", one)


SHA = re.compile(r"^[0-9a-f]{40}$")
FIRST_PARTY = ("actions", "github")


def _uses(doc: dict) -> list[str]:
    found = []
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        found.append(job.get("uses"))
        found += [s.get("uses") for s in job.get("steps") or [] if isinstance(s, dict)]
    return [u for u in found if isinstance(u, str)]


def check_lint(ctx: Ctx) -> list[Finding]:
    """Workflow hygiene, read only: actions not pinned to a commit, no top-level permissions, pull_request_target."""
    if not ctx.p.get("workflow_lint") and not ctx.inherited:
        return []

    def one(repo):
        cfg = ctx.pol(repo).get("workflow_lint")
        if not cfg:
            return []
        fn, out = repo["full_name"], []
        files, unreadable = ctx.automation_files(repo)
        if unreadable:
            out.append(Finding("lint", fn, "unreadable", "some workflow files could not be read; the lint may be incomplete", "info"))
        for path, text in files:
            if "/workflows/" not in path:
                continue
            try:
                doc = yaml.safe_load(text)
            except yaml.YAMLError:
                out.append(Finding("lint", fn, f"{path}:yaml", f"{path} is not valid YAML", "warn"))
                continue
            if not isinstance(doc, dict):
                continue
            if cfg.get("require_permissions") and "permissions" not in doc:
                out.append(Finding("lint", fn, f"{path}:permissions", f"{path} has no top-level permissions block (the token gets the "
                                   "repository default)", "warn", manual="add `permissions: contents: read` and widen per job"))
            on = doc.get("on", doc.get(True))  # YAML 1.1 reads the key `on` as true
            events = set(on) if isinstance(on, (list, dict)) else {on}
            if cfg.get("forbid_pull_request_target") and "pull_request_target" in events:
                out.append(Finding("lint", fn, f"{path}:pull_request_target", f"{path} runs on pull_request_target (it has secrets "
                                   "and a write token while it may build code from a fork)", "warn", manual="review it by hand"))
            mode = cfg.get("pin_actions")
            if mode:
                loose = sorted({u for u in _uses(doc) if not u.startswith(("./", "docker://"))
                                and not SHA.match(u.rpartition("@")[2] if "@" in u else "")
                                and not (mode == "third_party" and u.split("/")[0] in FIRST_PARTY)})
                if loose:
                    shown = ", ".join(loose[:5]) + (" and more" if len(loose) > 5 else "")
                    out.append(Finding("lint", fn, f"{path}:pin", f"{path} uses actions that are not pinned to a commit: {shown}", "warn",
                                       manual="replace the tag by the full commit SHA (a tag can be moved)"))
        return out

    return per_repo(ctx, "lint", one)


def _show(value) -> str:
    """A value from a policy or override file, for a message: one line, no control characters, bounded."""
    try:
        text = json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return clean(text, 80)


def _need_release_params(eff: dict, repo_name: str) -> bool:
    """True when the effective workflows list has the release template for this repository and nothing gives it parameters."""
    shared = (eff.get("workflow_params") or {}).get("release") or {}
    return any(isinstance(w, dict) and w.get("template") == "release" and not w.get("remove")
               and (not w.get("repos") or any(fnmatch.fnmatchcase(repo_name, g) for g in w["repos"]))
               and not {**(w.get("params") or {}), **shared} for w in eff.get("workflows") or [])


def _live_main_checks(ctx: Ctx, fn: str) -> list[dict]:
    """The status checks the live tld-main ruleset requires (none when there is no such ruleset)."""
    try:
        listing = ctx.c.paginate(f"/repos/{fn}/rulesets", {"includes_parents": "false"})
        mine = [r for r in listing or [] if r.get("name") == MAIN_RULESET and r.get("source_type", "Repository") == "Repository"]
        return _live_contexts(ctx.c.get(f"/repos/{fn}/rulesets/{mine[0]['id']}")) if mine else []
    except ApiError as exc:
        if exc.status == 404:
            return []
        raise


def _detected(ctx: Ctx, repo: dict, ov: Override, eff: dict) -> tuple[dict, list[str]]:
    """(the override mapping detected from the repository, the lines for the pull request) when something is missing."""
    rs = eff.get("rulesets") if isinstance(eff.get("rulesets"), dict) else {}
    branch = rs.get("default_branch")
    need_checks = isinstance(branch, dict) and "required_status_checks" not in branch
    need_release = _need_release_params(eff, repo["name"])
    kept: list[str] = []
    if need_checks:  # an explicit list replaces the live checks and their app binding: with live checks, propose none
        kept = [c["context"] for c in _live_main_checks(ctx, repo["full_name"])]
        need_checks = not kept
    if not (need_checks or need_release):
        return {}, []
    got = repo_admin_detect.gather(ctx, repo, want_checks=need_checks)
    checks, excluded = repo_admin_detect.status_checks(list(got.samples)) if need_checks else (None, {})
    params, notes, workflows = None, [], None
    if need_release:
        entries = [{k: v for k, v in w.items() if k in ("template", "params", "remove")}
                   for w in eff.get("workflows") or [] if isinstance(w, dict) and isinstance(w.get("template"), str)
                   and (not w.get("repos") or any(fnmatch.fnmatchcase(repo["name"], g) for g in w["repos"]))]
        workflows = repo_admin_detect.own_release_workflow(got.profile_release_workflow, entries)
        if workflows is not None:
            notes.append(f"the profile's release workflow is {got.profile_release_workflow}, not the template's: "
                         "workflows lists no release template")
            notes += [f"the proposed workflows list leaves out the workflow with path {w['path']}: the override stops managing it "
                      "in this repository (a list replaces the organisation's)" for w in eff.get("workflows") or []
                      if isinstance(w, dict) and isinstance(w.get("path"), str) and not isinstance(w.get("template"), str)
                      and (not w.get("repos") or any(fnmatch.fnmatchcase(repo["name"], g) for g in w["repos"]))]
        else:
            params, notes = repo_admin_detect.release_params(list(got.tags), list(got.manifests), got.tag_workflow)
            unsafe = sorted(k for k, v in params.items() if not SAFE_PARAM.fullmatch(v) or ".." in v)
            if unsafe:  # half a set of parameters would render the wrong workflow: none is proposed
                notes += [f"{k} was detected but has characters other than letters, digits and . _ / -; no release parameters "
                          "are proposed" for k in unsafe]
                params = {}
    if kept:
        notes.append(f"required_status_checks are not proposed: {MAIN_RULESET} already requires {len(kept)} "
                     "(kept with their app binding while the key is absent)")
    head = repo_admin_detect.pr_notes(checks, excluded, None, [])
    tail = repo_admin_detect.pr_notes(checks, excluded, params, notes)[len(head):]
    return repo_admin_detect.detected_override(checks, params, workflows), tail + (head if need_checks else [])


def _override_findings(ctx: Ctx, repo: dict, ov: Override, eff: dict) -> list[Finding]:
    """The one finding for the repository's override path: the conversion of a whole old policy, a proposal detected
    from the repository, or both in one put. A proposal never replaces an override with problems."""
    fn, out = repo["full_name"], []
    legacy = ov.legacy and ov.doc is not None
    if ov.problems:
        return out
    existing, detected, lines = ov.doc, {}, []
    if legacy:
        agent, reviewer, _ = repo_admin_policy.derive_logins(repo_admin_profile.repo_profile(ctx, repo))
        if repo_admin_policy._get(ctx.p, "agent.agent_login") is not repo_admin_policy._MISSING:
            agent = None  # the organisation's own value wins, so the override's login is not redundant
        if repo_admin_policy._get(ctx.p, "release.reviewer_login") is not repo_admin_policy._MISSING:
            reviewer = None
        existing = repo_admin_policy.drop_derived(ov.doc, agent, reviewer)
    if ctx.detect:
        try:
            detected, lines = _detected(ctx, repo, ov, eff)
        except ApiError as exc:
            out.append(failure("policy", fn, exc))
    proposal = repo_admin_policy.propose_override(existing, detected)
    if detected:
        errors = validate_policy(proposal, kind="override", where=f"{fn}:{ov.path}")
        if not errors and effective_policy(ctx.p, detected, repo["name"])[1]:
            errors = ["it would loosen a guarded setting of the organisation"]
        if errors:
            out.append(Finding("policy", fn, "override:propose:invalid", clean(
                f"the detected proposal for {ov.path} was dropped: {errors[0]}", MAX_MESSAGE), "warn"))
            proposal, lines = existing or {}, []
    changed = proposal != (existing or {})
    if not legacy and not changed:
        if ov.doc is None and lines and not out:
            out.append(Finding("policy", fn, "override:propose", clean(
                f"nothing could be proposed for {ov.path}: " + "; ".join(lines), MAX_MESSAGE), "info"))
        return out
    change = {"op": "put", "path": ov.path, "content": repo_admin_policy.render_override(proposal), "mode": "100644"}
    action = Action("files", repo=fn, changes=[change], note="\n".join((["; ".join(ov.notes)] if legacy and ov.notes else []) + lines))
    if legacy:
        out.append(Finding("policy", fn, "override:convert", clean(
            f"{ov.path} is a whole policy; with inheritance it holds only the repository's differences", MAX_MESSAGE), "fix", action))
    else:
        out.append(Finding("policy", fn, "override:propose", clean(
            f"{ov.path} proposed from the repository's merged pull requests, tags and manifest", MAX_MESSAGE), "fix", action))
    return out


def check_policy(ctx: Ctx) -> list[Finding]:
    """The inherited policy itself: what the run file loosens, and per repository the problems of its override file,
    the loosenings that were put back, the login notes, a whole old policy to convert, workflow parameters for no template."""
    if not ctx.inherited:
        return []
    out: list[Finding] = []
    for item in ctx.p.get("_run_loosenings") or []:
        key, base_value, value = item
        out.append(Finding("policy", ctx.org, f"loosen:{clean(key, 80)}", clean(
            f"the policy file sets {clean(key, 80)} to {_show(value)}, looser than its base's {_show(base_value)}", MAX_MESSAGE), "warn"))

    def one(repo):
        fn, found = repo["full_name"], []
        ov = ctx.override(repo)
        for n, problem in enumerate(ov.problems, 1):
            found.append(Finding("policy", fn, "override:invalid" if n == 1 else f"override:invalid:{n}",
                                 clean(f"{ov.path}: {problem}", MAX_MESSAGE), "error"))
        for item in ctx.loosenings(repo):
            now = "no valid value" if item.value is None else _show(item.value)
            found.append(Finding("policy", fn, f"loosen:{clean(item.key, 80)}", clean(
                f"the override sets {clean(item.key, 80)} to {now}, looser than the organisation's {_show(item.org_value)}; "
                "the organisation value applies", MAX_MESSAGE), "warn"))
        for subject, message in ctx.pol_warnings(repo):
            found.append(Finding("policy", fn, clean(subject, 80), clean(message, MAX_MESSAGE), "warn"))
        eff = ctx.pol(repo)
        found += _override_findings(ctx, repo, ov, eff)
        listed = {e.get("template") for e in eff.get("workflows") or [] if isinstance(e, dict)}
        for template in sorted(str(t) for t in (eff.get("workflow_params") or {})):
            if template not in listed:
                found.append(Finding("policy", fn, f"workflow_params:{clean(template, 40)}", clean(
                    f"workflow_params.{clean(template, 40)} names a template that is not in this repository's workflows; "
                    "its parameters are not used", MAX_MESSAGE), "warn"))
        return found

    return out + per_repo(ctx, "policy", one)


CHECKS = {
    "org": check_org, "members": check_members, "apps": check_apps, "tokens": check_tokens,
    "repo": check_repo, "security": check_security, "actions": check_actions, "protection": check_protection,
    "rulesets": check_rulesets, "agent": check_agent, "release": check_release,
    "secrets": check_secrets, "variables": check_variables, "labels": check_labels,
    "webhooks": check_webhooks, "keys": check_keys, "branches": check_branches, "files": check_files,
    "lint": check_lint, "profile": check_profile, "git_ops": check_git_ops, "policy": check_policy,
}


def run_checks(ctx: Ctx, names=None) -> list[Finding]:
    findings: list[Finding] = []
    for name in names or CHECKS:
        try:
            findings += CHECKS[name](ctx)
        except ApiError as exc:
            findings.append(failure(name, ctx.org, exc))
    return findings


# --------------------------------------------------------------------------- applying


def _cell(text: str, limit: int = 220) -> str:
    """One table cell. Names come from the repositories, so markdown, HTML and @mentions are defused."""
    text = " ".join(str(text).split())
    text = re.sub(r"([\\|`\[\]<>#&])", r"\\\1", text).replace("@", "@​").replace("#", "#​")
    text = text.replace("://", ":\u200b//")  # a bare URL in a name would be clickable in a pull request
    text = re.sub(r"(?i)\bwww\.", lambda m: m.group(0) + "\u200b", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(org: str, findings: list[Finding], repo_count: int, now: dt.datetime, extends=None) -> str:
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    lines = [f"# Repository admin audit: {org}", "",
             f"{now:%Y-%m-%d %H:%M} UTC, {repo_count} repositories in scope. "
             + ", ".join(f"{counts[s]} {s}" for s in SEVERITIES if counts[s]) + ("." if findings else "Nothing to report."), ""]
    if extends:
        lines[3:3] = ["", f"Extends: {', '.join(extends)}."]
    titles = {"fix": "Out of policy, apply can change it", "warn": "Out of policy, needs a person",
              "info": "For information", "unavailable": "Could not check", "error": "Failed"}
    for sev in SEVERITIES:
        rows = [f for f in findings if f.severity == sev]
        if not rows:
            continue
        lines += [f"## {titles[sev]} ({len(rows)})", "", "| ID | Check | Scope | Finding | Change |", "|---|---|---|---|---|"]
        for f in sorted(rows, key=lambda f: (f.check, f.scope, f.subject)):
            change = ("**deletes** " if f.action and f.action.destructive else "") + (f.action.describe() if f.action else f.manual)
            lines.append(f"| `{f.id}` | {f.check} | {_cell(f.scope, 60)} | {_cell(f.message)} | {_cell(change)} |")
        lines.append("")
    return "\n".join(lines)


def apply_files(client, repo: str, changes: list[dict], default_branch: str, commit: str, tree: str, today: dt.date,
                notes=()) -> str:
    """One commit on a new branch from the default branch's head, and one pull request. Returns the PR URL. `notes` are
    detected values the owner confirms; each is escaped and bounded as a table cell is."""
    merged: dict[str, dict] = {}
    for c in changes:  # one entry per path: the tree API refuses duplicates; an install wins over a removal
        if c["path"] not in merged or c["op"] == "put":
            merged[c["path"]] = c
    changes = sorted(merged.values(), key=lambda c: c["path"])
    entries = []
    for c in changes:
        if c["op"] == "delete":
            entries.append({"path": c["path"], "mode": "100644", "type": "blob", "sha": None})
        else:
            entries.append({"path": c["path"], "mode": c.get("mode", "100644"), "type": "blob", "content": c["content"]})
    new_tree = client.send("POST", f"/repos/{repo}/git/trees", {"base_tree": tree, "tree": entries})
    summary = "\n".join(f"- {'remove' if c['op'] == 'delete' else 'add or update'} `{c['path'].replace(chr(96), chr(39))}`"
                        for c in changes)
    new_commit = client.send("POST", f"/repos/{repo}/git/commits", {
        "message": "chore: apply repository policy\n\n" + summary.replace("`", ""), "tree": new_tree["sha"], "parents": [commit]})
    base = f"chore/repo-admin-{today:%Y%m%d}"
    for n in range(1, 6):
        name = base if n == 1 else f"{base}-{n}"
        try:
            client.send("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{name}", "sha": new_commit["sha"]})
            break
        except ApiError as exc:
            if exc.status != 422:
                raise
    else:
        raise ApiError(422, f"no free branch name from {base}", "POST", f"/repos/{repo}/git/refs")
    detected = "".join(f"{line}\n" for line in ["Detected values (the owner confirms them):", "", *(f"- {_cell(clean(n, 500), 500)}" for n in notes)]) \
        if notes else ""
    pr = client.send("POST", f"/repos/{repo}/pulls", {
        "title": "chore: apply repository policy", "head": name, "base": default_branch,
        "body": f"Changes from the organisation policy (`repo_admin.py apply`):\n\n{summary}\n\n"
                + (detected + "\n" if detected else "")
                + "Review them; this pull request is never merged by the script."})
    return pr.get("html_url", f"{repo}#{pr.get('number', '?')}")


def apply_findings(ctx: Ctx, findings: list[Finding], yes: bool, allow_delete: bool, out=print) -> int:
    """Print or make the changes. Returns the number of failures."""
    todo = [f for f in findings if f.action]
    held = [f for f in todo if f.action.destructive and not allow_delete]
    todo = [f for f in todo if f not in held]
    if not todo and not held:
        out("Nothing to change.")
        return 0
    files: dict[str, list[Finding]] = {}
    for f in todo:
        if f.action.kind == "files":
            files.setdefault(f.action.repo, []).append(f)
    verb = "Would run" if not yes else "Running"
    failures = 0
    for f in todo:
        if f.action.kind != "api":
            continue
        out(f"{verb}: {f.action.describe()}   [{f.id}] {f.message}")
        if yes:
            try:
                ctx.c.send(f.action.method, f.action.path, f.action.body)
            except ApiError as exc:
                failures += 1
                out(f"  FAILED: HTTP {exc.status}: {exc.message}")
    for repo, group in files.items():
        changes = [c for f in group for c in f.action.changes]
        out(f"{verb}: {Action('files', repo=repo, changes=changes).describe()}   [{', '.join(f.id for f in group)}]")
        if yes:
            try:
                full = next(r for r in ctx.all_repos if r["full_name"] == repo)
                snap = ctx.snapshot(full)
                notes = [n for f in group for n in f.action.note.split("\n") if n]
                url = apply_files(ctx.c, repo, changes, snap.branch, snap.commit, snap.tree, ctx.now.date(), notes)
                out(f"  opened {url}")
            except (ApiError, StopIteration) as exc:
                failures += 1
                out(f"  FAILED: {exc.message if isinstance(exc, ApiError) else 'repository not found'}")
    for f in held:
        out(f"Held back (irreversible, needs --allow-delete): {f.action.describe()}   [{f.id}] {f.message}")
    if not yes:
        out("Dry run: nothing was changed. Run again with --yes to make these changes.")
    return failures


# --------------------------------------------------------------------------- command line


def _client() -> Client:
    return Client(find_token(), os.environ.get("GITHUB_API_URL", API))


OWN_FILE = "the repository this file goes into"
ORG_LINE = re.compile(r"(?m)^[\"']?org[\"']?\s*:")


def _flatten(doc, prefix: str = "") -> list[str]:
    """The dotted leaf keys of a document (lists and scalars are leaves)."""
    if isinstance(doc, dict) and doc:
        return [leaf for k, v in doc.items() for leaf in _flatten(v, f"{prefix}.{k}" if prefix else str(k))]
    return [prefix]


def clean(text: object, limit: int = 400) -> str:
    """Text that may come from a fetched file or a server: control characters become '?' and the length is capped,
    so it cannot forge a line or move the cursor of a terminal or log."""
    text = text if isinstance(text, str) else str(text)
    out = "".join(c if c.isprintable() else "?" for c in text)
    return out if len(out) <= limit else out[:max(limit - 3, 0)] + "..."


def _validate_fail(errors: list[str]) -> int:
    for e in errors:
        print(f"policy: {clean(e)}", file=sys.stderr)
    return 1


def cmd_validate(args) -> int:
    from tld.ops import repo_admin_extends
    if args.public and args.kind != "base":
        print("validate-policy: --public needs --kind base", file=sys.stderr)
        return 2
    if bool(args.org_policy) != bool(args.repo_name):
        print("validate-policy: --org-policy needs --repo-name" if args.org_policy else
              "validate-policy: --repo-name needs --org-policy", file=sys.stderr)
        return 2
    explain = args.explain
    resolved = args.resolved or explain
    p = Path(args.policy)
    if not p.is_file():
        print(f"repo_admin: no policy at '{p}'", file=sys.stderr)
        return 1
    try:
        text = p.read_text()
    except (OSError, UnicodeError):
        print(f"policy: '{p}' cannot be read as UTF-8 text", file=sys.stderr)
        return 1
    kind = args.kind
    if kind == "auto":
        kind = "run" if ORG_LINE.search(text) else "override"
    if kind == "run":
        try:
            policy = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            print(f"policy: not valid YAML: {exc}", file=sys.stderr)
            return 1
    else:  # a base or an override comes from somewhere else: the shape check first (credentials, anchors, size)
        policy, errors = repo_admin_extends.shape_errors(text, str(p))
        if policy is None:
            return _validate_fail(errors)
        if args.kind == "auto" and "org" in policy:
            kind = "run"
    where = str(p) if kind != "run" else ""
    errors = validate_policy(policy, p.resolve().parent, kind=kind, where=where,
                             public=OWN_FILE if args.public else None)
    if errors:
        return _validate_fail(errors)
    view, sources = policy, {}
    if kind == "run" and policy.get("extends") and not args.offline:
        try:
            res = repo_admin_extends.resolve(_client(), policy)
        except (ApiError, ValueError) as exc:
            return _validate_fail([f"cannot resolve 'extends': {exc}"])
        if res.errors or res.policy is None:
            return _validate_fail(res.errors)
        view, sources = res.policy, res.sources
    else:
        sources = {k: (kind if kind != "run" else "run") for k in _flatten(policy) if k}
    if resolved and kind == "override" and args.org_policy:
        org_path = Path(args.org_policy)
        if not org_path.is_file():
            print(f"repo_admin: no policy at '{org_path}'", file=sys.stderr)
            return 1
        try:
            org_doc = load_policy(str(org_path)) if not args.offline else yaml.safe_load(org_path.read_text())
        except SystemExit as exc:
            print(clean(exc), file=sys.stderr)
            return 1
        except (ApiError, yaml.YAMLError) as exc:
            return _validate_fail([f"cannot read '{org_path}': {exc}"])
        if not isinstance(org_doc, dict):
            return _validate_fail([f"'{org_path}': the policy must be a YAML mapping"])
        if args.offline:
            if org_doc.get("extends"):
                return _validate_fail([f"'{org_path}' has 'extends'; its bases are not fetched with --offline, "
                                       "so the effective policy cannot be shown"])
            bad = validate_policy(org_doc, org_path.resolve().parent)
            if bad:
                return _validate_fail(bad)
        org_sources = org_doc.get("_sources") or {k: "run" for k in _flatten(org_doc) if k}
        view, _, _ = effective_policy(org_doc, policy, args.repo_name)
        sources = dict(org_sources)
        mine = {k for k in _flatten({k: v for k, v in policy.items() if k != "workflow_params"}) if k}
        mine |= {k for k in _flatten(policy.get("workflow_params") or {}, "workflow_params") if k}
        if policy.get("workflow_params"):
            mine.add("workflows")
        sources.update({k: f"override {args.repo_name}" for k in mine})
    if resolved:
        shown = {k: v for k, v in view.items() if not str(k).startswith("_")}
        if explain:
            leaves = repo_admin_policy.explain_lines(shown, sources)
            print("\n".join(clean(line, 2000) for line in leaves))
        else:
            sys.stdout.write(yaml.safe_dump(shown, sort_keys=False))
    suffix = {"run": "", "override": ", repository override", "base": ", base"}[kind]
    print(f"policy: OK ({p}{suffix})", file=sys.stderr if resolved else sys.stdout)
    return 0


def cmd_latest_pin(args) -> int:
    from tld.ops import repo_admin_extends
    try:
        sha, tag = repo_admin_extends.latest_pin(_client(), args.source)
    except (LookupError, ValueError) as exc:
        print(clean(exc), file=sys.stderr)
        return 1
    except (ApiError, ValueError) as exc:
        print(f"latest-pin: {clean(exc)}", file=sys.stderr)
        return 1
    print(json.dumps({"sha": sha, "tag": tag}))
    return 0


def cmd_whoami(args) -> int:
    client = _client()
    info: dict = {"authenticated": client.token is not None, "login": None, "org": args.org, "role": None}
    try:
        info["login"] = client.get("/user").get("login")
    except ApiError as exc:
        info["note"] = f"GET /user answered {exc.status}"
    if args.org and client.token:
        try:
            info["role"] = client.get(f"/user/memberships/orgs/{args.org}").get("role")
        except ApiError as exc:
            info["note"] = (info.get("note", "") + f" membership lookup answered {exc.status}").strip()
    info["can_administer"] = info["role"] == "admin"
    print(json.dumps(info, indent=2))
    return 0 if (info["can_administer"] or not args.org) and info["authenticated"] else 3


def _run(args) -> tuple[Ctx, list[Finding]]:
    client = _client()
    policy = load_policy(args.policy, client)
    for name in args.repo:
        owner, _, short = name.rpartition("/")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", short) or (owner and owner.lower() != policy["org"].lower()):
            raise SystemExit(f"repo_admin: --repo '{name}': give a repository name or {policy['org']}/name")
    ctx = Ctx(client, policy, args.repo, detect=not getattr(args, "no_detect", False))
    return ctx, run_checks(ctx, args.check or None)


def cmd_audit(args) -> int:
    try:
        ctx, findings = _run(args)
        repo_count = len(ctx.repos)
    except ApiError as exc:
        print(f"repo_admin: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        report = {"org": ctx.org, "generated_at": ctx.now.isoformat(), "repositories": repo_count}
        if ctx.p.get("_extends"):
            report["extends"] = list(ctx.p["_extends"])
        report["findings"] = [f.to_dict() for f in findings]
        text = json.dumps(report, indent=2) + "\n"
    else:
        text = render_markdown(ctx.org, findings, repo_count, ctx.now, ctx.p.get("_extends") or None)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    if any(f.severity == "error" for f in findings):
        return 1  # a check failed: the report is incomplete, so "no differences" cannot be said
    return 3 if any(f.severity in ("fix", "warn") for f in findings) else 0


def cmd_apply(args) -> int:
    try:
        ctx, findings = _run(args)
    except ApiError as exc:
        print(f"repo_admin: {exc}", file=sys.stderr)
        return 1
    if args.only:
        known = {f.id for f in findings}
        unknown = sorted(set(args.only) - known)
        if unknown:
            print(f"repo_admin: unknown finding id(s): {', '.join(unknown)} (run audit again)", file=sys.stderr)
            return 1
        findings = [f for f in findings if f.id in set(args.only)]
    return 1 if apply_findings(ctx, findings, args.yes, args.allow_delete) else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="repo_admin.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate-policy", help="check a policy file (run file, repository override or shared base)")
    v.add_argument("policy")
    v.add_argument("--kind", choices=["auto", "run", "override", "base"], default="auto",
                   help="auto: run when the file has `org`, else override")
    v.add_argument("--public", action="store_true", help="with --kind base: the file goes into a public repository")
    v.add_argument("--resolved", action="store_true", help="print the merged policy (resolves `extends` unless --offline)")
    v.add_argument("--explain", action="store_true", help="print each merged value with its source (implies --resolved)")
    v.add_argument("--offline", action="store_true", help="do not fetch the files `extends` names")
    v.add_argument("--org-policy", metavar="FILE", help="with an override file: show its effective policy over this organisation policy")
    v.add_argument("--repo-name", metavar="NAME", help="the repository the override file belongs to (with --org-policy)")
    lp = sub.add_parser("latest-pin", help="print the commit (and tag) to pin an `extends` entry to")
    lp.add_argument("source", metavar="OWNER/REPO/PATH")
    w = sub.add_parser("whoami", help="show which account the token belongs to and its role in the organisation")
    w.add_argument("--org")
    for name, helptext in (("audit", "read-only: list what differs from the policy"),
                           ("apply", "change what differs (dry run unless --yes)")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--policy", required=True)
        p.add_argument("--repo", action="append", default=[], help="only this repository (name or owner/name); repeatable")
        p.add_argument("--check", action="append", choices=sorted(CHECKS), help="only this check; repeatable")
        p.add_argument("--no-detect", action="store_true", help="do not propose override values from the repositories "
                       "(merged pull requests, tags, workflows)")
        if name == "audit":
            p.add_argument("--format", choices=["md", "json"], default="md")
            p.add_argument("--out", help="write the report to this file")
        else:
            p.add_argument("--only", action="append", default=[], metavar="ID", help="only this finding id (from audit); repeatable")
            p.add_argument("--allow-delete", action="store_true", help="also make the irreversible changes")
            p.add_argument("--yes", action="store_true", help="make the changes (default: print them)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"validate-policy": cmd_validate, "latest-pin": cmd_latest_pin, "whoami": cmd_whoami, "audit": cmd_audit, "apply": cmd_apply}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
