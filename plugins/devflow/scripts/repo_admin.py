#!/usr/bin/env python3
"""Audit and update GitHub organisation and repository settings from a policy file.

    repo_admin.py validate-policy POLICY
    repo_admin.py whoami [--org ORG]
    repo_admin.py audit --policy POLICY [--repo NAME]... [--check NAME]... [--format md|json] [--out FILE]
    repo_admin.py apply --policy POLICY [--repo NAME]... [--check NAME]... [--only ID]...
                        [--allow-delete] [--yes]

The policy (schema/admin-policy.schema.json, docs/admin.md) says what the organisation and its
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
import dataclasses
import datetime as dt
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
SCHEMA = PLUGIN / "schema" / "admin-policy.schema.json"
TEMPLATES = PLUGIN / "templates"
API = "https://api.github.com"
DOCS_HELP = "see docs/admin.md in the claude-toolkit repo"

# Built-in workflow templates: policy name -> (file, default parameters).
BUILTIN_TEMPLATES = {
    "release": ("devflow-release.yml", {"tag_prefix": "v"}),
    "land": ("devflow-land.yml", {}),
}
KNOWN_DOT_DIRS = (".github", ".claude", ".devcontainer", ".vscode", ".husky", ".config", ".changeset", ".githooks")
SEVERITIES = ("fix", "warn", "info", "unavailable", "error")
SAFE_PARAM = re.compile(r"^[A-Za-z0-9._/-]*$")
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


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """urllib copies every request header to the redirect target. The token must not leave the host it was meant for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_SameHostRedirects)


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
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "devflow-repo-admin"}
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
    spec = importlib.util.spec_from_file_location("validate_profile", HERE / "validate_profile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check, module.HELP


def validate_policy(policy, base_dir: Path | None = None) -> list[str]:
    """Return one message per problem; an empty list means the policy is valid."""
    if not isinstance(policy, dict):
        return ["the policy must be a YAML mapping"]
    check, profile_help = _load_check()
    schema = json.loads(SCHEMA.read_text())
    errors: list[str] = []
    check(policy, schema, schema, "", errors)
    errors = [e.replace(profile_help, DOCS_HELP) for e in errors]
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
        where = f"workflows[{i}]"
        if ("template" in wf) == ("path" in wf):
            errors.append(f"'{where}': give exactly one of 'template' and 'path'")
            continue
        if "path" in wf:
            rel = Path(wf["path"])
            if rel.is_absolute() or ".." in rel.parts:
                errors.append(f"'{where}.path': must be a path below the policy file's directory (no absolute path, no '..')")
                continue
            if base_dir is not None:
                target = (base_dir / rel).resolve()
                if not target.is_relative_to(base_dir.resolve()):
                    errors.append(f"'{where}.path': '{wf['path']}' leaves the policy file's directory (a symbolic link?)")
                    continue
                if not target.is_file():
                    errors.append(f"'{where}.path': file not found: '{wf['path']}' (relative to the policy file)")
        for key, value in wf.get("params", {}).items():
            if not isinstance(value, str) or not SAFE_PARAM.match(value):
                errors.append(f"'{where}.params.{key}': must be a string of letters, digits and . _ / - only")
        if "path" in wf and "dest" not in wf and not re.match(r"^[A-Za-z0-9._-]+\.ya?ml$", Path(wf["path"]).name):
            errors.append(f"'{where}.path': the file name must end in .yml or .yaml, or set 'dest'")
    return errors


def load_policy(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"repo_admin: no policy at '{p}'")
    try:
        policy = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise SystemExit(f"repo_admin: policy is not valid YAML: {exc}")
    errors = validate_policy(policy, p.resolve().parent)
    if errors:
        raise SystemExit("\n".join(f"policy: {e}" for e in errors))
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


class Ctx:
    """The client, the policy and the caches one run shares."""

    def __init__(self, client, policy: dict, only_repos=(), now: dt.datetime | None = None):
        self.c, self.p, self.org = client, policy, policy["org"]
        self.only = set(only_repos)
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self._cache: dict = {}

    def memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

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
    want = ctx.p.get("repo_settings")
    if not want:
        return []

    def one(repo):
        full, fn = ctx.repo(repo), repo["full_name"]
        return [Finding("repo", fn, key, f"{key} is {full.get(key)!r}, policy wants {value!r}", "fix",
                        api("PATCH", f"/repos/{fn}", {key: value}))
                for key, value in want.items() if full.get(key) != value]

    return per_repo(ctx, "repo", one)


SCANNING = {"secret_scanning": "secret_scanning", "secret_push_protection": "secret_scanning_push_protection"}


def check_security(ctx: Ctx) -> list[Finding]:
    want = ctx.p.get("security")
    if not want:
        return []

    def one(repo):
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
    want = ctx.p.get("actions")
    if not want:
        return []

    def one(repo):
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
    cfg = ctx.p.get("config_dirs")
    workflows = ctx.p.get("workflows")
    if cfg is None and not workflows:
        return []
    forbid = (cfg or {}).get("forbid", [])
    known = set(KNOWN_DOT_DIRS) | set((cfg or {}).get("known", []))

    def one(repo):
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
            dest = wf.get("dest", default_dest)
            entry = next((e for e in blobs if e["path"] == dest), None)
            if wf.get("remove"):
                if entry:
                    out.append(Finding("files", fn, f"workflow:{dest}", f"workflow {dest} should not exist", "fix",
                                       Action("files", repo=fn, changes=[{"op": "delete", "path": dest}])))
                continue
            params = {"main_branch": snap.branch, **defaults, **{k.lower(): v for k, v in wf.get("params", {}).items()}}
            # The default branch name comes from the repository, not from the policy: it is put into YAML and shell too.
            bad = [k for k, v in params.items() if not SAFE_PARAM.match(v) or ".." in v or (k == "main_branch" and not v)]
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
    cfg = ctx.p.get("workflow_lint")
    if not cfg:
        return []

    def one(repo):
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


CHECKS = {
    "org": check_org, "members": check_members, "apps": check_apps, "tokens": check_tokens,
    "repo": check_repo, "security": check_security, "actions": check_actions, "protection": check_protection,
    "secrets": check_secrets, "variables": check_variables, "labels": check_labels,
    "webhooks": check_webhooks, "keys": check_keys, "branches": check_branches, "files": check_files,
    "lint": check_lint,
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
    text = re.sub(r"([\\|`\[\]<>])", r"\\\1", text).replace("@", "@​")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_markdown(org: str, findings: list[Finding], repo_count: int, now: dt.datetime) -> str:
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    lines = [f"# Repository admin audit: {org}", "",
             f"{now:%Y-%m-%d %H:%M} UTC, {repo_count} repositories in scope. "
             + ", ".join(f"{counts[s]} {s}" for s in SEVERITIES if counts[s]) + ("." if findings else "Nothing to report."), ""]
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


def apply_files(client, repo: str, changes: list[dict], default_branch: str, commit: str, tree: str, today: dt.date) -> str:
    """One commit on a new branch from the default branch's head, and one pull request. Returns the PR URL."""
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
    pr = client.send("POST", f"/repos/{repo}/pulls", {
        "title": "chore: apply repository policy", "head": name, "base": default_branch,
        "body": f"Changes from the organisation policy (`repo_admin.py apply`):\n\n{summary}\n\n"
                "Review them; this pull request is never merged by the script."})
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
                url = apply_files(ctx.c, repo, changes, snap.branch, snap.commit, snap.tree, ctx.now.date())
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


def cmd_validate(args) -> int:
    p = Path(args.policy)
    if not p.is_file():
        print(f"repo_admin: no policy at '{p}'", file=sys.stderr)
        return 1
    try:
        policy = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        print(f"policy: not valid YAML: {exc}", file=sys.stderr)
        return 1
    errors = validate_policy(policy, p.resolve().parent)
    for e in errors:
        print(f"policy: {e}", file=sys.stderr)
    if not errors:
        print(f"policy: OK ({p})")
    return 1 if errors else 0


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
    policy = load_policy(args.policy)
    for name in args.repo:
        owner, _, short = name.rpartition("/")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", short) or (owner and owner.lower() != policy["org"].lower()):
            raise SystemExit(f"repo_admin: --repo '{name}': give a repository name or {policy['org']}/name")
    ctx = Ctx(_client(), policy, args.repo)
    return ctx, run_checks(ctx, args.check or None)


def cmd_audit(args) -> int:
    try:
        ctx, findings = _run(args)
        repo_count = len(ctx.repos)
    except ApiError as exc:
        print(f"repo_admin: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = json.dumps({"org": ctx.org, "generated_at": ctx.now.isoformat(), "repositories": repo_count,
                           "findings": [f.to_dict() for f in findings]}, indent=2) + "\n"
    else:
        text = render_markdown(ctx.org, findings, repo_count, ctx.now)
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
    v = sub.add_parser("validate-policy", help="check a policy file")
    v.add_argument("policy")
    w = sub.add_parser("whoami", help="show which account the token belongs to and its role in the organisation")
    w.add_argument("--org")
    for name, helptext in (("audit", "read-only: list what differs from the policy"),
                           ("apply", "change what differs (dry run unless --yes)")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--policy", required=True)
        p.add_argument("--repo", action="append", default=[], help="only this repository (name or owner/name); repeatable")
        p.add_argument("--check", action="append", choices=sorted(CHECKS), help="only this check; repeatable")
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
    handlers = {"validate-policy": cmd_validate, "whoami": cmd_whoami, "audit": cmd_audit, "apply": cmd_apply}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
