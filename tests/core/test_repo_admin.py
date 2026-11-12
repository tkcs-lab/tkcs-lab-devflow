"""repo_admin.py: policy validation, the API client, every check and the apply step, against a fake GitHub."""
import datetime as dt
import io
import json
import urllib.error

import pytest
import yaml

from conftest import ROOT, TLD, CLAUDE, FORBIDDEN
from conftest import FORBIDDEN

NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.timezone.utc)
STARTER = TLD / "templates" / "admin-policy.yaml"


# --------------------------------------------------------------------------- a fake GitHub


class Fake:
    """Serves canned answers by (method, path). A callable value gets the params. An ApiError is raised.
    Every write (anything but GET) is recorded in .writes as (method, path, body)."""

    def __init__(self, routes):
        self.routes, self.writes, self.reads = dict(routes), [], []

    def _answer(self, method, path, params=None, body=None):
        if (method, path) not in self.routes:
            return ApiErr(404, "Not Found", method, path)
        value = self.routes[(method, path)]
        return value(params or {}) if callable(value) else value

    def _serve(self, method, path, params=None, body=None):
        self.reads.append(path)
        value = self._answer(method, path, params, body)
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, path, params=None):
        return self._serve("GET", path, params)

    get_text = get

    def status(self, path):
        value = self._answer("GET", path)
        if isinstance(value, Exception) and value.status != 404:
            raise value
        return 404 if isinstance(value, Exception) else 204

    def paginate(self, path, params=None, key=None):
        data = self._serve("GET", path, params)
        return data[key] if key else data

    def send(self, method, path, body=None):
        self.writes.append((method, path, body))
        value = self._answer(method, path, None, body)
        if isinstance(value, Exception):
            if (method, path) in self.routes:
                raise value
            return {}
        return value


ApiErr = None  # set by the fixture below, once the module is loaded


@pytest.fixture(autouse=True)
def _bind(ra):
    global ApiErr
    ApiErr = ra.ApiError


def repo(name, **kw):
    return {"name": name, "full_name": f"acme/{name}", "archived": False, "fork": False, "default_branch": "main", **kw}


def add_repo(routes, name, files=None, branch="main", empty=False, truncated=False, **full):
    """Routes for one repository: its settings, its default branch and tree, and the text of every file."""
    fn = f"acme/{name}"
    routes[("GET", f"/repos/{fn}")] = repo(name, default_branch=branch, **full)
    if empty:
        routes[("GET", f"/repos/{fn}/branches/{branch}")] = ApiErr(404, "Branch not found", "GET", "x")
        return
    entries, seen = [], set()
    for path, text in (files or {}).items():
        parts = path.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in seen:
                seen.add(d)
                entries.append({"path": d, "type": "tree", "mode": "040000"})
        entries.append({"path": path, "type": "blob", "mode": "100644"})
        routes[("GET", f"/repos/{fn}/contents/{path}")] = text
    routes[("GET", f"/repos/{fn}/branches/{branch}")] = {"commit": {"sha": f"c-{name}", "commit": {"tree": {"sha": f"t-{name}"}}}}
    routes[("GET", f"/repos/{fn}/git/trees/t-{name}")] = {"tree": entries, "truncated": truncated}


def world(ra, policy, names=("app",), routes=None, only=(), files=None, now=NOW, **full):
    """A Ctx over a fake organisation 'acme' whose repositories are `names`."""
    r = dict(routes or {})
    r[("GET", "/orgs/acme/repos")] = [repo(n) for n in names]
    r.setdefault(("GET", "/orgs/acme"), {"public_repos": len(names), "total_private_repos": 0})
    for n in names:
        if ("GET", f"/repos/acme/{n}") not in r:
            add_repo(r, n, (files or {}).get(n, {}), **full)
    fake = Fake(r)
    return ra.Ctx(fake, {"org": "acme", **policy}, only, now), fake


def by_check(findings, check):
    return [f for f in findings if f.check == check]


def sev(findings):
    return sorted((f.subject, f.severity) for f in findings)


# --------------------------------------------------------------------------- policy


def test_starter_policy_is_valid(ra):
    assert ra.validate_policy(yaml.safe_load(STARTER.read_text()), STARTER.parent) == []


def test_starter_policy_matches_the_schema_it_documents():
    schema = json.loads((TLD / "schema" / "admin-policy.schema.json").read_text())
    starter = yaml.safe_load(STARTER.read_text())
    assert set(starter) <= set(schema["properties"])
    assert set(schema["properties"]) - set(starter) == set(), "every section should appear in the starter"


@pytest.mark.parametrize("policy,needle", [
    ({"orgg": "x"}, "unknown key 'orgg'"),
    ({}, "missing required key 'org'"),
    ({"org": "-bad"}, "does not match"),
    ({"org": "a", "repo_settings": {"allow_squash": True}}, "unknown key 'repo_settings.allow_squash'"),
    ({"org": "a", "org_settings": {"default_repository_permission": "owner"}}, "must be one of"),
    ({"org": "a", "tokens": {"fine_grained": {"max_unused_days": 0}}}, "at least 1"),
    ({"org": "a", "labels": {"sync": [{"name": "x", "color": "red"}]}}, "does not match"),
    ({"org": "a", "webhooks": {"delete": ["old"]}}, "must be one of"),
    ({"org": "a", "workflows": [{"template": "deploy"}]}, "must be one of"),
    ({"org": "a", "workflows": [{"template": "release", "dest": "src/x.yml"}]}, "does not match"),
    ({"org": "a", "workflows": [{"template": "release", "dest": ".github/workflows/../x.yml"}]}, "does not match"),
])
def test_policy_schema_errors(ra, policy, needle):
    errors = ra.validate_policy(policy)
    assert any(needle in e for e in errors), errors
    assert not any("profile-reference" in e for e in errors)


@pytest.mark.parametrize("pattern", ["", "/", ".", "..", "../x", "/abs", "*", "**", ".*", ".git", ".git/hooks", "a/../b"])
def test_dangerous_forbid_patterns_are_refused(ra, pattern):
    errors = ra.validate_policy({"org": "a", "config_dirs": {"forbid": [pattern]}})
    assert any("refusing" in e or "must not be empty" in e for e in errors), errors


@pytest.mark.parametrize("pattern", [".archon", ".archon/", "docs/old", "*.bak", ".cursor/**"])
def test_ordinary_forbid_patterns_are_accepted(ra, pattern):
    assert ra.validate_policy({"org": "a", "config_dirs": {"forbid": [pattern]}}) == []


def test_label_names_and_aliases_must_not_collide(ra):
    labels = [{"name": "bug", "aliases": ["defect"]}, {"name": "defect"}]
    assert any("'defect'" in e for e in ra.validate_policy({"org": "a", "labels": {"sync": labels}}))


def test_workflow_entry_rules(ra, tmp_path):
    ok = {"org": "a", "workflows": [{"path": "w.yml"}]}
    assert any("file not found" in e for e in ra.validate_policy(ok, tmp_path))
    (tmp_path / "w.yml").write_text("name: x\n")
    assert ra.validate_policy(ok, tmp_path) == []
    both = {"org": "a", "workflows": [{"template": "release", "path": "w.yml"}]}
    assert any("exactly one" in e for e in ra.validate_policy(both, tmp_path))
    assert any("exactly one" in e for e in ra.validate_policy({"org": "a", "workflows": [{}]}, tmp_path))
    bad_name = {"org": "a", "workflows": [{"path": "w.tmpl"}]}
    (tmp_path / "w.tmpl").write_text("x")
    assert any("file name must end in .yml" in e for e in ra.validate_policy(bad_name, tmp_path))
    assert ra.validate_policy({"org": "a", "workflows": [{"path": "w.tmpl", "dest": ".github/workflows/w.yml"}]}, tmp_path) == []


@pytest.mark.parametrize("value", ["a b", "x;y", "$(id)", "a\nb", "'q'", "../.."[:2] + "$"])
def test_unsafe_params_are_refused(ra, value):
    errors = ra.validate_policy({"org": "a", "workflows": [{"template": "release", "params": {"tag_prefix": value}}]})
    assert any("letters, digits" in e for e in errors), errors


@pytest.mark.parametrize("params,needle", [
    ({"version_style": "calver"}, "params.version_style': must be one of semver, pep440"),
    ({"create_release": "no"}, "params.create_release': must be one of true, false"),
    ({"check_script": "/etc/check.sh"}, "params.check_script': must be a path inside the repository"),
    ({"check_script": "../check.sh"}, "params.check_script': must be a path inside the repository"),
    ({"check_script": "-x"}, "params.check_script': must be a path inside the repository"),
])
def test_release_params_with_fixed_values_are_checked(ra, params, needle):
    errors = ra.validate_policy({"org": "a", "workflows": [{"template": "release", "params": params}]})
    assert any(needle in e for e in errors), errors


def test_release_params_accept_their_values(ra):
    params = {"version_style": "pep440", "create_release": "false", "check_script": "scripts/tag_release.py"}
    assert ra.validate_policy({"org": "a", "workflows": [{"template": "release", "params": params}]}) == []
    assert ra.validate_policy({"org": "a", "workflows": [{"template": "land", "params": {"version_style": "x"}}]}) == []


def test_every_policy_key_is_documented():
    schema = json.loads((TLD / "schema" / "admin-policy.schema.json").read_text())
    reference = (ROOT / "docs" / "guides" / "admin.md").read_text()

    def walk(node, prefix):
        for key, sub in node.get("properties", {}).items():
            dotted = f"{prefix}{key}"
            if sub.get("type") == "object" and sub.get("properties"):
                walk(sub, dotted + ".")  # a section is documented through its keys
            else:
                assert f"`{dotted}`" in reference, f"{dotted} is not in docs/guides/admin.md"

    walk(schema, "")


def test_every_check_is_documented(ra):
    reference = (ROOT / "docs" / "guides" / "admin.md").read_text()
    for name in ra.CHECKS:
        assert f"| `{name}` |" in reference, name


def test_profile_key_admin_policy(vp, tmp_path):
    profile = {"docs": {"must_read": []}, "git": {"main_branch": "main", "branch_pattern": "x"},
               "verify": {"fast": ["true"], "dod": ["true"]}, "stacks": [], "admin": {"policy": "pol.yaml"}}
    errors, _, resolved = vp.validate(profile, tmp_path)
    assert any("file not found: 'pol.yaml'" in e for e in errors)
    (tmp_path / "pol.yaml").write_text("org: a\n")
    assert vp.validate(profile, tmp_path)[0] == []
    profile["admin"] = {"policies": "x"}
    assert any("unknown key 'admin.policies'" in e for e in vp.validate(profile, None)[0])


def test_no_project_words_in_the_new_files():
    for path in (TLD / "ops" / "repo_admin.py", ROOT / "playbooks" / "repo-admin.md", STARTER,
                 TLD / "schema" / "admin-policy.schema.json"):
        assert FORBIDDEN.search(path.read_text()) is None, path


# --------------------------------------------------------------------------- the client


class Resp:
    def __init__(self, status, body=b"", headers=None):
        self.status, self._body, self.headers = status, body, headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, message="boom", headers=None):
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", headers or {}, io.BytesIO(json.dumps({"message": message}).encode()))


def scripted(*steps):
    """An urlopen that plays the steps in order: a Resp, or an exception to raise. Records requests."""
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req)
        step = steps[len(seen) - 1]
        if isinstance(step, Exception):
            raise step
        return step

    urlopen.seen = seen
    return urlopen


def test_client_follows_link_headers_and_collects_the_key(ra):
    nxt = '<https://api.github.com/orgs/acme/installations?page=2>; rel="next", <https://x/last>; rel="last"'
    op = scripted(Resp(200, json.dumps({"installations": [{"id": 1}]}).encode(), {"Link": nxt}),
                  Resp(200, json.dumps({"installations": [{"id": 2}]}).encode(), {}))
    got = ra.Client("tok", urlopen=op).paginate("/orgs/acme/installations", key="installations")
    assert [i["id"] for i in got] == [1, 2]
    assert op.seen[0].full_url.endswith("/orgs/acme/installations?per_page=100")
    assert op.seen[1].full_url == "https://api.github.com/orgs/acme/installations?page=2"


def test_client_sends_the_token_and_never_shows_it(ra):
    op = scripted(http_error(404, "Not Found"))
    client = ra.Client("sekrit-token", urlopen=op)
    with pytest.raises(ra.ApiError) as e:
        client.get("/repos/o/r")
    assert op.seen[0].get_header("Authorization") == "Bearer sekrit-token"
    assert e.value.status == 404 and e.value.message == "Not Found"
    assert "sekrit-token" not in str(e.value)


def test_client_without_token_sends_no_authorization(ra):
    op = scripted(Resp(200, b"{}"))
    ra.Client(None, urlopen=op).get("/x")
    assert op.seen[0].get_header("Authorization") is None


def test_client_waits_out_a_rate_limit_once(ra):
    slept = []
    op = scripted(http_error(403, "rate", {"Retry-After": "7"}), Resp(200, b'{"ok": true}'))
    assert ra.Client("t", urlopen=op, sleep=slept.append).get("/x") == {"ok": True}
    assert slept == [7]


def test_client_does_not_retry_a_permission_error(ra):
    slept = []
    op = scripted(http_error(403, "Resource not accessible"))
    with pytest.raises(ra.ApiError) as e:
        ra.Client("t", urlopen=op, sleep=slept.append).get("/x")
    assert e.value.status == 403 and slept == [] and len(op.seen) == 1


def test_client_gives_up_after_repeated_rate_limits(ra):
    op = scripted(*[http_error(429, "slow", {"Retry-After": "1"})] * 3)
    with pytest.raises(ra.ApiError) as e:
        ra.Client("t", urlopen=op, sleep=lambda s: None).get("/x")
    assert e.value.status == 429


def test_client_status_distinguishes_a_switch_from_an_error(ra):
    assert ra.Client("t", urlopen=scripted(Resp(204))).status("/x") == 204
    assert ra.Client("t", urlopen=scripted(http_error(404))).status("/x") == 404
    with pytest.raises(ra.ApiError):
        ra.Client("t", urlopen=scripted(http_error(403))).status("/x")


def test_client_network_failure_is_an_api_error(ra):
    with pytest.raises(ra.ApiError) as e:
        ra.Client("t", urlopen=scripted(urllib.error.URLError("no route"))).get("/x")
    assert e.value.status == 0


def test_find_token_order(ra, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "b")
    assert ra.find_token() == "b"
    monkeypatch.setenv("GH_TOKEN", "a")
    assert ra.find_token() == "a"


# --------------------------------------------------------------------------- findings


def test_finding_ids_are_stable_and_distinct(ra):
    a = ra.Finding("labels", "acme/app", "create:bug", "m", "fix")
    assert a.id == ra.Finding("labels", "acme/app", "create:bug", "other text", "warn").id
    assert a.id != ra.Finding("labels", "acme/web", "create:bug", "m", "fix").id
    assert len(a.id) == 10


def test_failure_findings(ra):
    forbidden = ra.failure("tokens", "acme", ra.ApiError(403, "no", "GET", "/orgs/acme/personal-access-tokens"))
    assert forbidden.severity == "unavailable" and "may not do this" in forbidden.message
    assert ra.failure("x", "s", ra.ApiError(500, "down", "GET", "/p")).severity == "error"


# --------------------------------------------------------------------------- organisation checks


def test_org_settings(ra):
    ctx, fake = world(ra, {"org_settings": {"default_repository_permission": "read", "web_commit_signoff_required": True,
                                            "two_factor_requirement_enabled": True, "has_repository_projects": False}},
                      routes={("GET", "/orgs/acme"): {"default_repository_permission": "write", "web_commit_signoff_required": True,
                                                      "two_factor_requirement_enabled": False}})
    found = ra.check_org(ctx)
    assert sev(found) == [("default_repository_permission", "fix"), ("has_repository_projects", "unavailable"),
                          ("two_factor_requirement_enabled", "warn")]
    fix = next(f for f in found if f.severity == "fix")
    assert fix.action.describe() == 'PATCH /orgs/acme {"default_repository_permission": "read"}' and not fix.action.destructive
    assert "settings/security" in next(f for f in found if f.severity == "warn").manual


def test_members(ra):
    members = {("GET", "/orgs/acme/members"): lambda p: (
        [{"login": "eve"}] if p.get("filter") == "2fa_disabled" else [{"login": "a"}, {"login": "b"}, {"login": "c"}] if p.get("role") == "admin" else [])}
    ctx, _ = world(ra, {"members": {"require_two_factor": True, "max_owners": 2}}, routes=members)
    found = ra.check_members(ctx)
    assert sorted(f.message for f in found) == ["3 owners (a, b, c), policy allows 2", "eve has two-factor authentication disabled"]
    assert all(f.severity == "warn" and f.action is None for f in found)
    ctx, _ = world(ra, {"members": {"max_owners": 3}}, routes=members)
    assert ra.check_members(ctx) == []


def test_apps(ra):
    installs = {"installations": [{"id": 1, "app_slug": "Dependabot", "repository_selection": "all"},
                                  {"id": 2, "app_slug": "old-ci", "repository_selection": "all"},
                                  {"id": 3, "app_slug": "codecov", "suspended_at": "2026-01-01T00:00:00Z"}]}
    ctx, _ = world(ra, {"apps": {"allow": ["dependabot", "codecov"]}}, routes={("GET", "/orgs/acme/installations"): installs})
    found = ra.check_apps(ctx)
    assert sev(found) == [("codecov:suspended", "warn"), ("oauth", "info"), ("old-ci", "warn")]
    old = next(f for f in found if f.subject == "old-ci")
    assert old.action is None and "settings/installations/2" in old.manual


def test_tokens(ra):
    def tok(i, **kw):
        return {"id": i, "token_name": f"t{i}", "owner": {"login": "dev"}, "token_expired": False, "token_last_used_at": None,
                "access_granted_at": "2026-11-01T00:00:00Z", **kw}

    tokens = [tok(1, token_expired=True), tok(2, token_last_used_at="2026-05-01T00:00:00Z"), tok(3, token_last_used_at="2026-11-01T00:00:00Z"),
              tok(4, access_granted_at="2026-01-01T00:00:00Z"), tok(5)]
    ctx, _ = world(ra, {"tokens": {"fine_grained": {"max_unused_days": 90}}}, routes={("GET", "/orgs/acme/personal-access-tokens"): tokens})
    found = ra.check_tokens(ctx)
    assert sorted(f.subject for f in found) == ["1", "2", "4"]
    assert "expired" in found[0].message and "not used for 192 days" in next(f for f in found if f.subject == "2").message
    assert "never used, granted 312 days" in next(f for f in found if f.subject == "4").message
    for f in found:
        assert f.severity == "fix" and f.action.destructive
        assert f.action.describe() == f'POST /orgs/acme/personal-access-tokens/{f.subject} {{"action": "revoke"}}'


def test_tokens_expired_only_and_opt_out(ra):
    routes = {("GET", "/orgs/acme/personal-access-tokens"): [{"id": 1, "token_expired": True, "owner": {}}, {"id": 2, "token_expired": False,
              "access_granted_at": "2020-01-01T00:00:00Z", "owner": {}}]}
    ctx, _ = world(ra, {"tokens": {"fine_grained": {}}}, routes=routes)
    assert [f.subject for f in ra.check_tokens(ctx)] == ["1"]
    ctx, _ = world(ra, {"tokens": {"fine_grained": {"revoke_expired": False}}}, routes=routes)
    assert ra.check_tokens(ctx) == []


# --------------------------------------------------------------------------- repository settings


def test_repo_settings(ra):
    ctx, _ = world(ra, {"repo_settings": {"delete_branch_on_merge": True, "has_wiki": False, "allow_auto_merge": True}}, names=("app", "web"),
                   routes={("GET", "/repos/acme/web"): repo("web", delete_branch_on_merge=True, has_wiki=False, allow_auto_merge=True),
                           ("GET", "/repos/acme/app"): repo("app", delete_branch_on_merge=False, has_wiki=False)})
    found = ra.check_repo(ctx)
    assert sev(found) == [("allow_auto_merge", "fix"), ("delete_branch_on_merge", "fix")]
    assert {f.scope for f in found} == {"acme/app"}
    assert sorted(f.action.describe() for f in found) == ['PATCH /repos/acme/app {"allow_auto_merge": true}',
                                                         'PATCH /repos/acme/app {"delete_branch_on_merge": true}']


def test_repo_filters(ra):
    allr = [repo("app"), repo("sandbox-1"), repo("old", archived=True), repo("fork", fork=True), repo("web")]
    policy = {"repos": {"exclude": ["sandbox-*"]}}

    def names(policy, only=()):
        ctx = ra.Ctx(Fake({("GET", "/orgs/acme/repos"): allr}), {"org": "acme", **policy}, only, NOW)
        return [r["name"] for r in ctx.repos]

    assert names(policy) == ["app", "web"]
    assert names({"repos": {"include": ["a*"]}}) == ["app"]
    assert names({"repos": {"skip_archived": False, "skip_forks": False}}) == ["app", "sandbox-1", "old", "fork", "web"]
    assert names(policy, only=("web",)) == ["web"]


def test_owner_slash_name_fetches_just_that_repository(ra):
    fake = Fake({("GET", "/repos/acme/web"): repo("web")})  # no organisation listing is served at all
    ctx = ra.Ctx(fake, {"org": "acme", "repos": {"exclude": ["web"]}}, ("acme/web",), NOW)
    assert ctx.partial and ctx.repos == []  # still subject to exclude
    ctx = ra.Ctx(fake, {"org": "acme"}, ("acme/web",), NOW)
    assert [r["full_name"] for r in ctx.repos] == ["acme/web"]
    mixed = ra.Ctx(Fake({("GET", "/orgs/acme/repos"): [repo("web")]}), {"org": "acme"}, ("web", "acme/app"), NOW)
    assert not mixed.partial


def test_security(ra):
    on = {"security_and_analysis": {"secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "disabled"}}}
    ctx, _ = world(ra, {"security": {"vulnerability_alerts": True, "automated_security_fixes": True, "secret_scanning": True,
                                     "secret_push_protection": True}},
                   routes={("GET", "/repos/acme/app"): repo("app", **on), ("GET", "/repos/acme/app/automated-security-fixes"): {"enabled": False, "paused": False}})
    found = ra.check_security(ctx)
    assert sev(found) == [("automated_security_fixes", "fix"), ("secret_push_protection", "fix"), ("vulnerability_alerts", "fix")]
    desc = {f.subject: f.action.describe() for f in found}
    assert desc["vulnerability_alerts"] == "PUT /repos/acme/app/vulnerability-alerts"
    assert desc["automated_security_fixes"] == "PUT /repos/acme/app/automated-security-fixes"
    assert json.loads(desc["secret_push_protection"].split(" ", 2)[2]) == {"security_and_analysis": {"secret_scanning_push_protection": {"status": "enabled"}}}


def test_security_off_and_unreadable(ra):
    routes = {("GET", "/repos/acme/app"): repo("app"), ("GET", "/repos/acme/app/vulnerability-alerts"): {}}
    ctx, _ = world(ra, {"security": {"vulnerability_alerts": False, "secret_scanning": True}}, routes=routes)
    found = ra.check_security(ctx)
    assert sev(found) == [("secret_scanning", "unavailable"), ("vulnerability_alerts", "fix")]
    assert next(f for f in found if f.subject == "vulnerability_alerts").action.describe() == "DELETE /repos/acme/app/vulnerability-alerts"


def test_actions(ra):
    routes = {("GET", "/repos/acme/app/actions/permissions"): {"enabled": True, "allowed_actions": "all"},
              ("GET", "/repos/acme/app/actions/permissions/workflow"): {"default_workflow_permissions": "write", "can_approve_pull_request_reviews": False}}
    ctx, _ = world(ra, {"actions": {"enabled": True, "default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}}, routes=routes)
    found = ra.check_actions(ctx)
    assert [(f.subject, f.action.describe()) for f in found] == [
        ("default_workflow_permissions", 'PUT /repos/acme/app/actions/permissions/workflow {"default_workflow_permissions": "read"}')]


def test_branch_protection_added_where_missing(ra):
    cfg = {"require_status_checks": ["test"], "strict": True, "approvals": 2}
    ctx, _ = world(ra, {"branch_protection": cfg})
    found = ra.check_protection(ctx)
    assert len(found) == 1 and found[0].severity == "fix" and not found[0].action.destructive
    assert found[0].action.path == "/repos/acme/app/branches/main/protection" and found[0].action.method == "PUT"
    assert found[0].action.body == {
        "required_status_checks": {"strict": True, "contexts": ["test"]}, "enforce_admins": False,
        "required_pull_request_reviews": {"required_approving_review_count": 2}, "restrictions": None,
        "required_linear_history": False, "allow_force_pushes": False, "allow_deletions": False}


def test_branch_protection_never_replaces_an_existing_rule(ra):
    weak = {"required_pull_request_reviews": {"required_approving_review_count": 0}, "enforce_admins": {"enabled": False},
            "required_status_checks": {"contexts": [], "checks": [{"context": "lint"}]}, "allow_force_pushes": {"enabled": True}}
    ctx, _ = world(ra, {"branch_protection": {"require_status_checks": ["test", "lint"], "approvals": 1, "enforce_admins": True}},
                   routes={("GET", "/repos/acme/app/branches/main/protection"): weak})
    found = ra.check_protection(ctx)
    assert found and all(f.severity == "warn" and f.action is None for f in found)
    text = " | ".join(f.message for f in found)
    assert "0 required approvals, policy wants 1" in text and "lack test" in text and "lint" not in text.split("lack")[1]
    assert "enforce_admins" in text and "force pushes are allowed" in text


def test_branch_protection_ruleset_counts_and_empty_repos_are_skipped(ra):
    ctx, _ = world(ra, {"branch_protection": {}}, routes={("GET", "/repos/acme/app/rules/branches/main"): [{"type": "pull_request"}]})
    assert ra.check_protection(ctx) == []
    ctx, _ = world(ra, {"branch_protection": {"branch": "release"}})
    assert ra.check_protection(ctx)[0].subject == "release"
    ctx, _ = world(ra, {"branch_protection": {}}, empty=True)
    assert ra.check_protection(ctx) == []


# --------------------------------------------------------------------------- secrets and variables

WORKFLOW = "jobs:\n  b:\n    steps:\n      - run: deploy\n        env:\n          A: ${{ secrets.NPM_TOKEN }}\n          B: ${{ vars.REGION }}\n          C: ${{ secrets['quoted_one'] }}\n"


def copy_repo_routes(routes, src, dst):
    """The routes of repository `src`, answered for `dst` as well."""
    extra = {(m, p.replace(f"/repos/acme/{src}", f"/repos/acme/{dst}")): v for (m, p), v in routes.items() if f"/repos/acme/{src}" in p}
    return {**routes, **extra}


def secret_routes(repo_secrets=("NPM_TOKEN", "OLD_KEY"), org_secrets=(), org_for_repo=(), dependabot=()):
    items = lambda names: {"secrets": [{"name": n} for n in names]}
    return {("GET", "/repos/acme/app/actions/secrets"): items(repo_secrets),
            ("GET", "/repos/acme/app/dependabot/secrets"): items(dependabot),
            ("GET", "/repos/acme/app/actions/organization-secrets"): items(org_for_repo),
            ("GET", "/orgs/acme/actions/secrets"): items(org_secrets), ("GET", "/orgs/acme/dependabot/secrets"): items(())}


def test_unused_secret_is_reported_and_used_ones_are_not(ra):
    files = {"app": {".github/workflows/ci.yml": WORKFLOW}}
    ctx, _ = world(ra, {"secrets": {}}, routes=secret_routes(("NPM_TOKEN", "OLD_KEY", "QUOTED_ONE")), files=files)
    found = ra.check_secrets(ctx)
    assert [(f.subject, f.severity, f.action) for f in found] == [("secret:OLD_KEY", "warn", None)]
    assert "delete_unused" in found[0].manual


def test_unused_secret_is_deleted_only_when_the_policy_says_so(ra):
    files = {"app": {".github/workflows/ci.yml": WORKFLOW}}
    ctx, _ = world(ra, {"secrets": {"delete_unused": True, "keep": ["old_key"]}}, routes=secret_routes(), files=files)
    assert ra.check_secrets(ctx) == []
    ctx, _ = world(ra, {"secrets": {"delete_unused": True}}, routes=secret_routes(), files=files)
    (f,) = ra.check_secrets(ctx)
    assert f.severity == "fix" and f.action.destructive and f.action.describe() == "DELETE /repos/acme/app/actions/secrets/OLD_KEY"


def test_dependabot_secret_counts_dependabot_yml_as_use(ra):
    files = {"app": {".github/dependabot.yml": "registries:\n  npm:\n    token: ${{secrets.REG_TOKEN}}\n"}}
    ctx, _ = world(ra, {"secrets": {"kinds": ["dependabot"]}}, files=files,
                   routes=secret_routes(repo_secrets=(), dependabot=("REG_TOKEN", "STALE")))
    assert [f.subject for f in ra.check_secrets(ctx)] == ["dependabot secret:STALE"]


@pytest.mark.parametrize("text", ["jobs:\n  x:\n    uses: o/r/.github/workflows/w.yml@v1\n    secrets: inherit\n",
                                  "env:\n  A: ${{ secrets[format('K_{0}', matrix.n)] }}\n"])
def test_hidden_names_stop_the_unused_verdict(ra, text):
    ctx, _ = world(ra, {"secrets": {"delete_unused": True}}, routes=secret_routes(), files={"app": {".github/workflows/ci.yml": text}})
    assert ra.check_secrets(ctx) == []


def test_a_secret_in_a_truncated_tree_is_never_called_unused(ra):
    ctx, _ = world(ra, {"secrets": {}}, routes=secret_routes(), truncated=True)
    assert ra.check_secrets(ctx) == []


def test_required_secrets_may_come_from_the_organisation(ra):
    routes = secret_routes(repo_secrets=("OWN",), org_for_repo=("SHARED",))
    ctx, _ = world(ra, {"secrets": {"required": ["own", "SHARED", "MISSING"], "keep": ["OWN"]}}, routes=routes)
    found = [f for f in ra.check_secrets(ctx) if f.subject.startswith("missing")]
    assert [f.subject for f in found] == ["missing:MISSING"]
    assert found[0].manual == "gh secret set MISSING --repo acme/app  (the script cannot know the value)"


def test_org_secret_used_in_another_repository_is_not_unused(ra):
    files = {"app": {}, "web": {".github/workflows/x.yml": "env: {A: '${{ secrets.SHARED }}'}\n"}}
    routes = secret_routes(repo_secrets=(), org_secrets=("SHARED", "ORPHAN"))
    ctx, _ = world(ra, {"secrets": {"kinds": ["actions"], "delete_unused": True}}, names=("app", "web"), files=files,
                   routes=copy_repo_routes(routes, "app", "web"))
    found = ra.check_secrets(ctx)
    assert [(f.subject, f.action.describe()) for f in found] == [("org secret:ORPHAN", "DELETE /orgs/acme/actions/secrets/ORPHAN")]


def test_org_secret_check_looks_at_excluded_repositories_too(ra):
    files = {"app": {}, "hidden": {".github/workflows/x.yml": "env: {A: '${{ secrets.SHARED }}'}\n"}}
    routes = secret_routes(repo_secrets=(), org_secrets=("SHARED",))
    ctx, _ = world(ra, {"repos": {"exclude": ["hidden"]}, "secrets": {"kinds": ["actions"]}}, names=("app", "hidden"), files=files,
                   routes=copy_repo_routes(routes, "app", "hidden"))
    assert ra.check_secrets(ctx) == []


def test_org_secret_is_not_judged_when_a_repository_hides_names(ra):
    files = {"app": {".github/workflows/x.yml": "jobs:\n  a:\n    secrets: inherit\n"}}
    ctx, _ = world(ra, {"secrets": {"kinds": ["actions"], "delete_unused": True}}, files=files,
                   routes=secret_routes(repo_secrets=(), org_secrets=("MAYBE",)))
    (f,) = ra.check_secrets(ctx)
    assert f.severity == "info" and f.action is None and "acme/app" in f.message


def test_partial_runs_do_not_judge_organisation_secrets(ra):
    r = secret_routes(repo_secrets=(), org_secrets=("X",))
    r[("GET", "/repos/acme/app")] = repo("app")
    ctx, fake = world(ra, {"secrets": {"kinds": ["actions"], "delete_unused": True}}, only=("acme/app",), routes=r)
    assert ctx.partial
    (f,) = ra.check_secrets(ctx)
    assert f.severity == "info" and "were not checked" in f.message
    assert ("GET", "/orgs/acme/repos") not in [(m, p) for m, p, _ in fake.writes]


def test_variables(ra):
    files = {"app": {".github/workflows/ci.yml": WORKFLOW}}
    routes = {("GET", "/repos/acme/app/actions/variables"): {"variables": [{"name": "REGION"}, {"name": "DEAD"}]},
              ("GET", "/repos/acme/app/actions/organization-variables"): {"variables": [{"name": "ORG_V"}]},
              ("GET", "/orgs/acme/actions/variables"): {"variables": [{"name": "ORG_V"}, {"name": "REGION"}]}}
    ctx, _ = world(ra, {"variables": {"delete_unused": True, "required": ["org_v", "NOPE"]}}, routes=routes, files=files)
    found = ra.check_variables(ctx)
    assert sorted((f.subject, f.severity) for f in found) == [("missing:NOPE", "warn"), ("org variable:ORG_V", "fix"), ("variable:DEAD", "fix")]
    assert next(f for f in found if f.subject == "variable:DEAD").action.describe() == "DELETE /repos/acme/app/actions/variables/DEAD"
    assert next(f for f in found if f.subject == "missing:NOPE").manual.startswith("gh variable set NOPE")


# --------------------------------------------------------------------------- labels


def labels_world(ra, policy, existing, used=(), **kw):
    r = {("GET", "/repos/acme/app/labels"): existing,
         ("GET", "/repos/acme/app/issues"): lambda p: [{"number": 1}] if p.get("labels") in used else []}
    return world(ra, {"labels": policy}, routes=r, **kw)


def lab(name, color="ededed", description=None):
    return {"name": name, "color": color, "description": description}


def test_labels_create_update_and_rename(ra):
    sync = [{"name": "bug", "color": "#D73A4A", "description": "Broken"}, {"name": "enhancement", "color": "a2eeef", "aliases": ["feature"]},
            {"name": "docs", "color": "0075ca"}, {"name": "ok", "color": "ededed", "description": ""}]
    ctx, _ = labels_world(ra, {"sync": sync}, [lab("Bug", "d73a4a", "Broken"), lab("feature", "ffffff"), lab("DOCS", "0075ca"), lab("ok")])
    found = ra.check_labels(ctx)
    got = {f.subject: f.action for f in found}
    assert set(got) == {"update:bug", "update:enhancement", "update:docs"}
    assert got["update:bug"].path == "/repos/acme/app/labels/Bug" and got["update:bug"].body == {"new_name": "bug"}
    assert got["update:enhancement"].path == "/repos/acme/app/labels/feature"
    assert got["update:enhancement"].body == {"new_name": "enhancement", "color": "a2eeef"}
    assert got["update:docs"].body == {"new_name": "docs"}
    assert all(f.severity == "fix" and not f.action.destructive for f in found)


def test_labels_create_missing(ra):
    ctx, _ = labels_world(ra, {"sync": [{"name": "bug", "color": "d73a4a", "description": "x"}, {"name": "bare"}]}, [])
    found = ra.check_labels(ctx)
    assert [f.action.body for f in found] == [{"name": "bug", "color": "d73a4a", "description": "x"}, {"name": "bare"}]


def test_labels_unlisted_are_deleted_only_when_unused_and_allowed(ra):
    existing = [lab("bug"), lab("wontfix"), lab("question"), lab("keepme"), lab("a,b")]
    policy = {"sync": [{"name": "bug"}], "keep": ["KeepMe"]}
    ctx, _ = labels_world(ra, policy, existing, used={"question"})
    assert sev(ra.check_labels(ctx)) == [("unlisted:a,b", "info"), ("unlisted:question", "info"), ("unlisted:wontfix", "warn")]
    ctx, _ = labels_world(ra, {**policy, "delete_unused": True}, existing, used={"question"})
    found = ra.check_labels(ctx)
    assert sev(found) == [("delete:wontfix", "fix"), ("unlisted:a,b", "info"), ("unlisted:question", "info")]
    delete = next(f for f in found if f.severity == "fix")
    assert delete.action.destructive and delete.action.describe() == "DELETE /repos/acme/app/labels/wontfix"
    ctx, _ = labels_world(ra, {**policy, "delete_unlisted": True}, existing, used={"question"})
    assert sorted(f.subject for f in ra.check_labels(ctx) if f.severity == "fix") == ["delete:a,b", "delete:question", "delete:wontfix"]


def test_labels_alias_left_behind_is_an_ordinary_unlisted_label(ra):
    ctx, _ = labels_world(ra, {"sync": [{"name": "bug", "aliases": ["defect"]}], "delete_unused": True}, [lab("bug"), lab("defect")])
    assert [(f.subject, f.severity) for f in ra.check_labels(ctx)] == [("delete:defect", "fix")]


def test_label_names_are_url_quoted(ra):
    ctx, _ = labels_world(ra, {"sync": [], "delete_unused": True}, [lab("good first/issue ✓")])
    (f,) = ra.check_labels(ctx)
    assert f.action.path == "/repos/acme/app/labels/good%20first%2Fissue%20%E2%9C%93"


# --------------------------------------------------------------------------- webhooks and deploy keys


def hook(i, url="https://hooks.example.com/services/T0/B0/SECRET?token=abc", active=True, code=200, status="active"):
    return {"id": i, "active": active, "config": {"url": url}, "last_response": {"code": code, "status": status}}


def test_webhook_states_and_url_redaction(ra):
    assert ra.hook_state(hook(1)) == "ok"
    assert ra.hook_state(hook(1, active=False)) == "inactive"
    assert ra.hook_state(hook(1, code=500)) == "failing"
    assert ra.hook_state(hook(1, code=None, status="misconfigured")) == "failing"
    assert ra.hook_state(hook(1, code=None, status="unused")) == "never delivered"
    assert ra.redact_url("https://user:pw@hooks.example.com:8443/services/T0/B0/SECRET?token=abc") == "https://hooks.example.com/…"
    assert ra.redact_url(None) == "(no url)"


def test_webhooks(ra):
    routes = {("GET", "/orgs/acme/hooks"): [hook(1, code=500)],
              ("GET", "/repos/acme/app/hooks"): [hook(2, active=False), hook(3, code=None, status="unused"), hook(4),
                                                  hook(5, url="https://keep.example.com/x", code=500)]}
    ctx, _ = world(ra, {"webhooks": {"delete": ["inactive"], "keep_urls": ["https://keep.example.com/"]}}, routes=routes)
    found = ra.check_webhooks(ctx)
    assert sorted((f.scope, f.subject, f.severity) for f in found) == [("acme", "1", "warn"), ("acme/app", "2", "fix"), ("acme/app", "3", "info")]
    fix = next(f for f in found if f.subject == "2")
    assert fix.action.destructive and fix.action.describe() == "DELETE /repos/acme/app/hooks/2"
    assert all("SECRET" not in f.message and "abc" not in f.message for f in found)
    ctx, _ = world(ra, {"webhooks": {"delete": ["failing", "inactive"]}}, routes=routes)
    assert next(f for f in ra.check_webhooks(ctx) if f.scope == "acme").action is None, "deliveries unreadable: not deleted"
    routes[("GET", "/orgs/acme/hooks/1/deliveries")] = [{"status_code": 500}, {"status_code": 502}]
    ctx, _ = world(ra, {"webhooks": {"delete": ["failing", "inactive"]}}, routes=routes)
    assert next(f for f in ra.check_webhooks(ctx) if f.scope == "acme").action.describe() == "DELETE /orgs/acme/hooks/1"
    routes[("GET", "/orgs/acme/hooks/1/deliveries")] = [{"status_code": 500}, {"status_code": 200}]
    ctx, _ = world(ra, {"webhooks": {"delete": ["failing", "inactive"]}}, routes=routes)
    (flaky,) = [f for f in ra.check_webhooks(ctx) if f.scope == "acme"]
    assert flaky.action is None and "flaky" in flaky.message


def test_webhook_org_failure_does_not_hide_repository_hooks(ra):
    routes = {("GET", "/orgs/acme/hooks"): ApiErr(403, "no", "GET", "/orgs/acme/hooks"), ("GET", "/repos/acme/app/hooks"): [hook(2, active=False)]}
    ctx, _ = world(ra, {"webhooks": {}}, routes=routes)
    assert sev(ra.check_webhooks(ctx)) == [("2", "warn"), ("GET /orgs/acme/hooks", "unavailable")]


def test_deploy_keys(ra):
    keys = [{"id": 1, "title": "ci", "read_only": True, "key": "ssh-ed25519 AAAA", "created_at": "2026-10-01T00:00:00Z", "last_used": None},
            {"id": 2, "title": "old", "read_only": False, "created_at": "2024-01-01T00:00:00Z", "last_used": "2025-01-01T00:00:00Z"},
            {"id": 3, "title": "never", "read_only": True, "created_at": "2025-01-01T00:00:00Z", "last_used": None}]
    ctx, _ = world(ra, {"deploy_keys": {"max_unused_days": 180}}, routes={("GET", "/repos/acme/app/keys"): keys})
    found = ra.check_keys(ctx)
    assert sev(found) == [("2", "warn"), ("3", "warn")] and all(f.action is None for f in found)
    assert all("AAAA" not in f.message for f in found)
    assert "read-write" in found[0].message and "no recorded use, created" in found[1].message
    ctx, _ = world(ra, {"deploy_keys": {"max_unused_days": 180, "delete_unused": True}}, routes={("GET", "/repos/acme/app/keys"): keys})
    found = {f.subject: f for f in ra.check_keys(ctx)}
    assert found["2"].action.destructive, "a key with a recorded old use may be deleted"
    assert found["3"].action is None, "a key GitHub has no last use for is only ever reported"
    ctx, _ = world(ra, {"deploy_keys": {}}, routes={("GET", "/repos/acme/app/keys"): keys})
    assert ra.check_keys(ctx) == []


# --------------------------------------------------------------------------- branches


def cmp_merged(status="behind"):
    return {"ahead_by": 0, "status": status}


# when each branch was last touched (the repository activity API); "no-date" has no answer, the old merge base is a trap
ACTIVITY = {"merged-old": "2026-09-01T00:00:00Z", "merged-new": "2026-11-05T00:00:00Z", "release/1.0": "2026-01-01T00:00:00Z",
            "chore/old-slash": "2026-01-01T00:00:00Z", "forked": "2026-01-01T00:00:00Z", "identical-old": "2026-01-01T00:00:00Z",
            "stacked-base": "2026-01-01T00:00:00Z"}


def branch_routes(extra=None):
    names = ["main", "merged-old", "merged-new", "wip", "unmerged", "release/1.0", "chore/old-slash", "prot", "forked", "identical-old",
             "no-date", "stacked-base"]

    def activity(params):
        when = ACTIVITY.get(params["ref"].removeprefix("refs/heads/"))
        return [{"timestamp": when}] if when else ApiErr(404, "no activity", "GET", "x")

    r = {("GET", "/repos/acme/app/branches"): [{"name": n, "protected": n == "prot"} for n in names],
         ("GET", "/repos/acme/app/pulls"): [{"head": {"ref": "wip", "repo": {"full_name": "acme/app"}}, "base": {"ref": "stacked-base"}},
                                           {"head": {"ref": "forked", "repo": {"full_name": "someone/app"}}, "base": {"ref": "main"}}],
         ("GET", "/repos/acme/app/activity"): activity,
         ("GET", "/repos/acme/app/compare/main...unmerged"): {"ahead_by": 3, "status": "ahead"},
         ("GET", "/repos/acme/app/compare/main...identical-old"): cmp_merged("identical")}
    for n in names:
        r.setdefault(("GET", f"/repos/acme/app/compare/main...{n}"), cmp_merged())
    return {**r, **(extra or {})}


def test_merged_branches_are_reported_by_default(ra):
    ctx, _ = world(ra, {"branches": {"keep": ["release/*"]}}, routes=branch_routes())
    found = ra.check_branches(ctx)
    assert sev(found) == [("chore/old-slash", "warn"), ("forked", "warn"), ("identical-old", "warn"), ("merged-old", "warn")]
    assert all(f.action is None for f in found)
    assert "fully merged into main (last activity 69 days ago)" in next(f for f in found if f.subject == "merged-old").message


def test_what_is_never_called_merged(ra):
    ctx, fake = world(ra, {"branches": {}}, routes=branch_routes())
    subjects = {f.subject for f in ra.check_branches(ctx)}
    assert not subjects & {"main", "wip", "prot", "unmerged", "merged-new", "no-date", "stacked-base"}, subjects
    compared = {p.rsplit("...", 1)[1] for p in fake.reads if "/compare/" in p}
    assert compared == {"merged-old", "merged-new", "unmerged", "release/1.0", "chore/old-slash", "forked", "identical-old", "no-date"}
    assert not compared & {"main", "wip", "prot"}, "the default, an open-PR head or base and a protected branch are never even compared"


def test_a_fork_pull_request_does_not_protect_a_branch_of_the_same_name(ra):
    ctx, _ = world(ra, {"branches": {}}, routes=branch_routes())
    assert "forked" in {f.subject for f in ra.check_branches(ctx)}


def test_min_age_days(ra):
    ctx, _ = world(ra, {"branches": {"min_age_days": 0}}, routes=branch_routes())
    assert "merged-new" in {f.subject for f in ra.check_branches(ctx)}
    ctx, _ = world(ra, {"branches": {"min_age_days": 100}}, routes=branch_routes())
    assert "merged-old" not in {f.subject for f in ra.check_branches(ctx)}


def test_merged_branches_are_deleted_only_when_the_policy_says_so(ra):
    ctx, _ = world(ra, {"branches": {"delete_merged": True}}, routes=branch_routes())
    found = {f.subject: f for f in ra.check_branches(ctx)}
    assert all(f.severity == "fix" and f.action.destructive for f in found.values())
    assert found["merged-old"].action.describe() == "DELETE /repos/acme/app/git/refs/heads/merged-old"
    assert found["chore/old-slash"].action.path == "/repos/acme/app/git/refs/heads/chore/old-slash"


def test_branch_check_is_capped(ra, monkeypatch):
    monkeypatch.setattr(ra, "MAX_BRANCH_COMPARES", 2)
    ctx, fake = world(ra, {"branches": {}}, routes=branch_routes())
    found = ra.check_branches(ctx)
    assert [f for f in found if f.subject == "capped"] and sum(1 for f in found if f.subject != "capped") <= 2


# --------------------------------------------------------------------------- files


@pytest.mark.parametrize("path,pattern,expected", [
    (".archon/a/b.yml", ".archon", True), (".archon", ".archon/", True), (".archonx/a", ".archon", False),
    ("src/.archon/a", ".archon", False), ("docs/old/a.md", "docs/old", True), ("a.bak", "*.bak", True),
    ("x/a.bak", "*.bak", False), ("docs/x/y.md", "docs/*.md", False), ("docs/y.md", "docs/*.md", True), (".cursor/rules/a", ".cursor/**", True), ("README.md", ".archon", False)])
def test_path_matching(ra, path, pattern, expected):
    assert ra.matches(path, pattern) is expected


def test_forbidden_directory_becomes_one_pull_request_change(ra):
    files = {"app": {".archon/a.yml": "x", ".archon/sub/b.yml": "y", "README.md": "z", ".github/workflows/ci.yml": "n: 1\n"}}
    ctx, _ = world(ra, {"config_dirs": {"forbid": [".archon"]}}, files=files)
    (f,) = [f for f in ra.check_files(ctx) if f.severity == "fix"]
    assert f.action.kind == "files" and f.action.repo == "acme/app" and not f.action.destructive
    assert f.action.changes == [{"op": "delete", "path": ".archon/a.yml"}, {"op": "delete", "path": ".archon/sub/b.yml"}]
    assert ra.check_files(world(ra, {"config_dirs": {"forbid": [".archon"]}}, files={"app": {"README.md": "z"}})[0]) == []


def test_unknown_dot_directories_are_reported_not_removed(ra):
    files = {"app": {".github/a.yml": "", ".claude/x": "", ".cursor/rules": "", ".archon/a": "", "src/.hidden/a": ""}}
    ctx, _ = world(ra, {"config_dirs": {"forbid": [".archon"]}}, files=files)
    info = [f for f in ra.check_files(ctx) if f.severity == "info"]
    assert [f.subject for f in info] == ["unknown:.cursor"] and info[0].action is None
    ctx, _ = world(ra, {"config_dirs": {"known": [".cursor"]}}, files=files)
    assert sorted(f.subject for f in ra.check_files(ctx)) == ["unknown:.archon"], "known adds to the built-in list"
    ctx, _ = world(ra, {"workflows": []}, files=files)
    assert ra.check_files(ctx) == [], "without config_dirs nothing is judged"


def release_entry(**kw):
    return {"template": "release", **kw}


def test_workflow_missing_is_added_with_the_branch_filled_in(ra):
    ctx, _ = world(ra, {"workflows": [release_entry(params={"tag_prefix": "rel-"})]}, branch="trunk", files={"app": {"README.md": "x"}})
    (f,) = ra.check_files(ctx)
    (change,) = f.action.changes
    assert change["op"] == "put" and change["path"] == ".github/workflows/tld-release.yml" and change["mode"] == "100644"
    doc = yaml.safe_load(change["content"])
    assert doc["jobs"]["release"]["if"] == "github.ref == 'refs/heads/trunk'"
    assert doc["jobs"]["release"]["steps"][0]["env"]["PREFIX"] == "rel-"
    assert "__" not in change["content"] and change["content"].endswith("\n") and not change["content"].endswith("\n\n")
    steps = {s["name"]: s for s in doc["jobs"]["release"]["steps"]}
    assert steps["Decide the tag"]["env"]["VERSION_STYLE"] == "semver", "the defaults keep the 1.0 behaviour"
    assert steps["Decide the tag"]["env"]["CREATE_RELEASE"] == "true"
    assert steps["Run the project's release check"]["env"]["CHECK_SCRIPT"] == ""


def test_release_params_are_rendered(ra):
    params = {"version_style": "pep440", "create_release": "false", "check_script": "scripts/tag_release.py"}
    ctx, _ = world(ra, {"workflows": [release_entry(params=params)]}, files={"app": {}})
    doc = yaml.safe_load(ra.check_files(ctx)[0].action.changes[0]["content"])
    steps = {s["name"]: s for s in doc["jobs"]["release"]["steps"]}
    assert steps["Decide the tag"]["env"]["VERSION_STYLE"] == "pep440"
    assert steps["Publish the tag and the release"]["env"]["CREATE_RELEASE"] == "false"
    assert steps["Run the project's release check"]["env"]["CHECK_SCRIPT"] == "scripts/tag_release.py"


def test_workflow_up_to_date_is_left_alone_and_a_changed_one_is_updated(ra):
    ctx, _ = world(ra, {"workflows": [release_entry()]}, files={"app": {}})
    want = ra.check_files(ctx)[0].action.changes[0]["content"]
    path = ".github/workflows/tld-release.yml"
    ctx, _ = world(ra, {"workflows": [release_entry()]}, files={"app": {path: want.replace("\n", "\r\n")}})
    assert ra.check_files(ctx) == []
    ctx, _ = world(ra, {"workflows": [release_entry()]}, files={"app": {path: want + "# local edit\n"}})
    (f,) = ra.check_files(ctx)
    assert "differs from its template" in f.message and f.action.changes[0]["content"] == want


def test_workflow_options(ra, tmp_path):
    (tmp_path / "ci.yml").write_text("name: ci\non: [push]\nenv: {BRANCH: __MAIN_BRANCH__, TEAM: __TEAM__}\n")
    policy = {"_dir": str(tmp_path), "workflows": [
        {"path": "ci.yml", "params": {"TEAM": "core"}, "repos": ["a*"]}, {"template": "land", "remove": True},
        {"template": "release", "dest": ".github/workflows/rel.yml", "repos": ["web"]}]}
    ctx, _ = world(ra, policy, names=("app", "web"), files={"app": {".github/workflows/tld-land.yml": "x"}, "web": {}})
    found = ra.check_files(ctx)
    got = sorted((f.scope, f.action.changes[0]["op"], f.action.changes[0]["path"]) for f in found)
    assert got == [("acme/app", "delete", ".github/workflows/tld-land.yml"), ("acme/app", "put", ".github/workflows/ci.yml"),
                   ("acme/web", "put", ".github/workflows/rel.yml")]
    ci = next(f for f in found if f.action.changes[0]["path"].endswith("ci.yml")).action.changes[0]["content"]
    assert "BRANCH: main, TEAM: core" in ci


def test_template_needing_a_missing_param_is_an_error_finding(ra, tmp_path):
    (tmp_path / "w.yml").write_text("a: __WHO__\n")
    ctx, _ = world(ra, {"_dir": str(tmp_path), "workflows": [{"path": "w.yml"}]})
    (f,) = ra.check_files(ctx)
    assert f.severity == "error" and "needs params: who" in f.message and f.action is None


def test_file_checks_skip_empty_repos_and_note_truncated_trees(ra):
    ctx, _ = world(ra, {"config_dirs": {"forbid": [".archon"]}, "workflows": [release_entry()]}, empty=True)
    assert ra.check_files(ctx) == []
    ctx, _ = world(ra, {"config_dirs": {"forbid": [".archon"]}}, truncated=True, files={"app": {".archon/a": "x"}})
    assert sorted(f.severity for f in ra.check_files(ctx)) == ["fix", "info"]


def test_builtin_templates_render_completely(ra):
    for name, (file, defaults) in ra.BUILTIN_TEMPLATES.items():
        text = (TLD / "templates" / file).read_text()
        out = ra.render_template(text, {"main_branch": "main", **defaults})
        assert ra.PLACEHOLDER.search(out) is None, name
        yaml.safe_load(out)


# --------------------------------------------------------------------------- isolation, reports


def test_one_failing_repository_does_not_stop_the_others(ra):
    r = {("GET", "/repos/acme/web"): ApiErr(403, "Resource not accessible", "GET", "/repos/acme/web")}
    r[("GET", "/repos/acme/app")] = repo("app", has_wiki=True)
    ctx, _ = world(ra, {"repo_settings": {"has_wiki": False}}, names=("app", "web"), routes=r)
    found = ra.run_checks(ctx, ["repo"])
    assert sorted((f.scope, f.severity) for f in found) == [("acme/app", "fix"), ("acme/web", "unavailable")]


def test_a_failing_check_does_not_stop_the_others(ra):
    ctx, _ = world(ra, {"org_settings": {"has_repository_projects": False}, "repo_settings": {"has_wiki": False}},
                   routes={("GET", "/orgs/acme"): ApiErr(401, "Bad credentials", "GET", "/orgs/acme"), ("GET", "/repos/acme/app"): repo("app", has_wiki=True)})
    found = ra.run_checks(ctx)
    assert sorted((f.check, f.severity) for f in found) == [("org", "unavailable"), ("repo", "fix")]


def test_markdown_report(ra):
    fs = [ra.Finding("labels", "acme/app", "a", "label 'a|b' is\nunused", "warn", manual="delete it"),
          ra.Finding("repo", "acme/app", "k", "has_wiki is True", "fix", ra.api("PATCH", "/repos/acme/app", {"has_wiki": False})),
          ra.Finding("tokens", "acme", "1", "stale token", "fix", ra.api("POST", "/x", {"action": "revoke"}, True)),
          ra.Finding("keys", "acme/app", "1", "could not", "unavailable")]
    text = ra.render_markdown("acme", fs, 3, NOW)
    assert text.startswith("# Repository admin audit: acme") and "3 repositories in scope" in text
    assert "label 'a\\|b' is unused" in text and "**deletes** POST /x" in text
    assert text.index("## Out of policy, apply can change it") < text.index("## Out of policy, needs a person") < text.index("## Could not check")
    assert ra.render_markdown("acme", [], 1, NOW).strip().endswith("Nothing to report.")


# --------------------------------------------------------------------------- apply


def two_findings(ra):
    return [ra.Finding("repo", "acme/app", "k", "wiki", "fix", ra.api("PATCH", "/repos/acme/app", {"has_wiki": False})),
            ra.Finding("labels", "acme/app", "d", "unused", "fix", ra.api("DELETE", "/repos/acme/app/labels/x", destructive=True))]


def test_apply_dry_run_changes_nothing(ra):
    ctx, fake = world(ra, {})
    out = []
    assert ra.apply_findings(ctx, two_findings(ra), yes=False, allow_delete=True, out=out.append) == 0
    assert fake.writes == []
    text = "\n".join(out)
    assert "Would run: PATCH /repos/acme/app" in text and "Would run: DELETE /repos/acme/app/labels/x" in text and "Dry run" in text


def test_apply_holds_back_irreversible_changes_without_allow_delete(ra):
    ctx, fake = world(ra, {})
    out = []
    assert ra.apply_findings(ctx, two_findings(ra), yes=True, allow_delete=False, out=out.append) == 0
    assert fake.writes == [("PATCH", "/repos/acme/app", {"has_wiki": False})]
    assert any(line.startswith("Held back") and "labels/x" in line for line in out)


def test_apply_with_allow_delete_makes_all_and_counts_failures(ra):
    ctx, fake = world(ra, {}, routes={("DELETE", "/repos/acme/app/labels/x"): ApiErr(422, "nope", "DELETE", "/p")})
    out = []
    assert ra.apply_findings(ctx, two_findings(ra), yes=True, allow_delete=True, out=out.append) == 1
    assert [w[0] for w in fake.writes] == ["PATCH", "DELETE"], "a failure does not stop the next change"
    assert any("FAILED: HTTP 422: nope" in line for line in out)


def test_apply_nothing_to_do(ra):
    ctx, _ = world(ra, {})
    out = []
    assert ra.apply_findings(ctx, [ra.Finding("a", "b", "c", "m", "warn")], True, True, out.append) == 0
    assert out == ["Nothing to change."]


def pr_routes(commit="NEWC", tree="NEWT", refs_taken=0):
    attempts = {"n": 0}

    def ref(_):
        attempts["n"] += 1
        return ApiErr(422, "Reference already exists", "POST", "/git/refs") if attempts["n"] <= refs_taken else {}

    return {("POST", "/repos/acme/app/git/trees"): {"sha": tree}, ("POST", "/repos/acme/app/git/commits"): {"sha": commit},
            ("POST", "/repos/acme/app/git/refs"): ref, ("POST", "/repos/acme/app/pulls"): {"html_url": "https://github.com/acme/app/pull/9", "number": 9}}


class RefFake(Fake):
    """Fake whose callable POST routes may return errors, as send() raises them."""

    def send(self, method, path, body=None):
        self.writes.append((method, path, body))
        value = self.routes.get((method, path), {})
        value = value(body) if callable(value) else value
        if isinstance(value, Exception):
            raise value
        return value


def test_apply_files_makes_one_commit_on_a_new_branch_and_one_pull_request(ra):
    fake = RefFake(pr_routes())
    changes = [{"op": "delete", "path": ".archon/a.yml"}, {"op": "put", "path": ".github/workflows/r.yml", "content": "name: r\n", "mode": "100755"}]
    url = ra.apply_files(fake, "acme/app", changes, "main", "c-app", "t-app", dt.date(2026, 11, 9))
    assert url == "https://github.com/acme/app/pull/9"
    (tree, commit, ref, pull) = fake.writes
    assert tree[2] == {"base_tree": "t-app", "tree": [
        {"path": ".archon/a.yml", "mode": "100644", "type": "blob", "sha": None},
        {"path": ".github/workflows/r.yml", "mode": "100755", "type": "blob", "content": "name: r\n"}]}
    assert commit[2]["parents"] == ["c-app"] and commit[2]["tree"] == "NEWT" and commit[2]["message"].startswith("chore: apply repository policy")
    assert ref[2] == {"ref": "refs/heads/chore/repo-admin-20261109", "sha": "NEWC"}
    assert pull[2]["head"] == "chore/repo-admin-20261109" and pull[2]["base"] == "main"
    assert "never merged" in pull[2]["body"] and "`.archon/a.yml`" in pull[2]["body"]
    assert not any(w[0] in ("PATCH", "PUT", "DELETE") for w in fake.writes), "an existing branch is never touched"


def test_apply_files_picks_a_free_branch_name(ra):
    fake = RefFake(pr_routes(refs_taken=2))
    ra.apply_files(fake, "acme/app", [{"op": "delete", "path": "x"}], "main", "c", "t", dt.date(2026, 11, 9))
    heads = [w[2]["ref"] for w in fake.writes if w[1].endswith("/git/refs")]
    assert heads == ["refs/heads/chore/repo-admin-20261109", "refs/heads/chore/repo-admin-20261109-2", "refs/heads/chore/repo-admin-20261109-3"]


def test_apply_files_gives_up_and_reports_when_no_branch_name_is_free(ra):
    with pytest.raises(ra.ApiError):
        ra.apply_files(RefFake(pr_routes(refs_taken=99)), "acme/app", [{"op": "delete", "path": "x"}], "main", "c", "t", dt.date(2026, 11, 9))


def test_apply_groups_file_findings_into_one_pull_request_per_repository(ra):
    routes = pr_routes()
    files = {"app": {".archon/a": "x"}}
    r = dict(routes)
    ctx, _ = world(ra, {"config_dirs": {"forbid": [".archon", "old.txt"]}, "workflows": [release_entry()]}, files={"app": {".archon/a": "x", "old.txt": "y"}}, routes=r)
    fake = RefFake({**ctx.c.routes, **routes})
    ctx.c = fake
    findings = [f for f in ra.run_checks(ctx, ["files"]) if f.action]
    assert len(findings) == 3
    out = []
    assert ra.apply_findings(ctx, findings, yes=True, allow_delete=False, out=out.append) == 0
    pulls = [w for w in fake.writes if w[1].endswith("/pulls")]
    assert len(pulls) == 1
    tree = next(w for w in fake.writes if w[1].endswith("/git/trees"))[2]["tree"]
    assert sorted(e["path"] for e in tree) == [".archon/a", ".github/workflows/tld-release.yml", "old.txt"]
    assert any("opened https://github.com/acme/app/pull/9" in line for line in out)


def test_apply_files_dry_run_describes_the_pull_request(ra):
    ctx, fake = world(ra, {"config_dirs": {"forbid": [".archon"]}}, files={"app": {".archon/a": "x"}})
    out = []
    ra.apply_findings(ctx, ra.check_files(ctx), yes=False, allow_delete=False, out=out.append)
    assert fake.writes == [] and any("pull request on acme/app: delete .archon/a" in line for line in out)


# --------------------------------------------------------------------------- the command line


@pytest.fixture
def cli(ra, tmp_path, monkeypatch):
    def run(policy, routes, argv, files=None):
        path = tmp_path / "policy.yaml"
        path.write_text(yaml.safe_dump(policy))
        r = {("GET", "/orgs/acme/repos"): [repo("app")]}
        add_repo(r, "app", files or {})
        r.update(routes)
        fake = Fake(r)
        monkeypatch.setattr(ra, "_client", lambda: fake)
        return fake, ra.main([argv[0], "--policy", str(path), *argv[1:]])

    return run


def test_audit_exit_codes_and_json(cli, capsys):
    pol = {"org": "acme", "repo_settings": {"has_wiki": False}}
    fake, code = cli(pol, {("GET", "/repos/acme/app"): repo("app", has_wiki=False)}, ["audit"])
    assert code == 0 and "Nothing to report." in capsys.readouterr().out
    fake, code = cli(pol, {("GET", "/repos/acme/app"): repo("app", has_wiki=True)}, ["audit", "--format", "json"])
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["org"] == "acme" and data["repositories"] == 1
    (f,) = data["findings"]
    assert f["severity"] == "fix" and f["action"] == 'PATCH /repos/acme/app {"has_wiki": false}' and len(f["id"]) == 10
    assert fake.writes == [], "audit never writes"


def test_audit_writes_to_a_file(cli, tmp_path, capsys):
    out = tmp_path / "report.md"
    cli({"org": "acme", "repo_settings": {"has_wiki": False}}, {("GET", "/repos/acme/app"): repo("app", has_wiki=True)}, ["audit", "--out", str(out)])
    assert out.read_text().startswith("# Repository admin audit: acme") and capsys.readouterr().out == ""


def test_audit_exits_1_when_a_check_itself_failed(cli, tmp_path, capsys):
    (tmp_path / "w.yml").write_text("a: __WHO__\n")  # the cli fixture writes policy.yaml into tmp_path too
    pol = {"org": "acme", "workflows": [{"path": "w.yml"}]}
    _, code = cli(pol, {}, ["audit", "--format", "json"], files={"README.md": "x"})
    assert code == 1
    assert [f["severity"] for f in json.loads(capsys.readouterr().out)["findings"]] == ["error"]


def test_audit_check_filter(cli, capsys):
    pol = {"org": "acme", "repo_settings": {"has_wiki": False}, "labels": {"sync": [{"name": "bug"}]}}
    routes = {("GET", "/repos/acme/app"): repo("app", has_wiki=True), ("GET", "/repos/acme/app/labels"): []}
    _, code = cli(pol, routes, ["audit", "--format", "json", "--check", "labels"])
    assert {f["check"] for f in json.loads(capsys.readouterr().out)["findings"]} == {"labels"}


def test_apply_by_id(cli, capsys):
    pol = {"org": "acme", "repo_settings": {"has_wiki": False, "has_projects": False}}
    routes = {("GET", "/repos/acme/app"): repo("app", has_wiki=True, has_projects=True)}
    fake, code = cli(pol, routes, ["audit", "--format", "json"])
    ids = {f["subject" if "subject" in f else "message"]: f["id"] for f in json.loads(capsys.readouterr().out)["findings"]}
    wiki = next(i for m, i in ids.items() if "has_wiki" in m)
    fake, code = cli(pol, routes, ["apply", "--only", wiki])
    assert code == 0 and fake.writes == [] and "Dry run" in capsys.readouterr().out
    fake, code = cli(pol, routes, ["apply", "--only", wiki, "--yes"])
    assert code == 0 and fake.writes == [("PATCH", "/repos/acme/app", {"has_wiki": False})]


def test_apply_rejects_an_unknown_id(cli, capsys):
    fake, code = cli({"org": "acme", "repo_settings": {"has_wiki": False}}, {("GET", "/repos/acme/app"): repo("app", has_wiki=True)},
                     ["apply", "--only", "deadbeef00", "--yes"])
    assert code == 1 and fake.writes == [] and "unknown finding id" in capsys.readouterr().err


def test_apply_exit_code_when_a_change_fails(cli, capsys):
    routes = {("GET", "/repos/acme/app"): repo("app", has_wiki=True), ("PATCH", "/repos/acme/app"): ApiErr(403, "Must have admin rights", "PATCH", "/repos/acme/app")}
    fake, code = cli({"org": "acme", "repo_settings": {"has_wiki": False}}, routes, ["apply", "--yes"])
    assert code == 1 and "FAILED: HTTP 403" in capsys.readouterr().out


def test_invalid_policy_stops_before_any_request(ra, tmp_path, capsys):
    bad = tmp_path / "p.yaml"
    bad.write_text("org: acme\nlabels: {sync: [{name: x, colour: red}]}\n")
    with pytest.raises(SystemExit) as e:
        ra.main(["audit", "--policy", str(bad)])
    assert "unknown key 'labels.sync[0].colour'" in str(e.value)
    assert ra.main(["validate-policy", str(bad)]) == 1
    assert "unknown key" in capsys.readouterr().err


def test_validate_policy_command(ra, capsys):
    assert ra.main(["validate-policy", str(STARTER)]) == 0
    assert "policy: OK" in capsys.readouterr().out
    assert ra.main(["validate-policy", "/nonexistent.yaml"]) == 1


def test_whoami(ra, monkeypatch, capsys):
    def client(token, role):
        r = {("GET", "/user"): {"login": "andras"}, ("GET", "/user/memberships/orgs/acme"): {"role": role}}
        fake = Fake(r)
        fake.token = token
        return fake

    monkeypatch.setattr(ra, "_client", lambda: client("t", "admin"))
    assert ra.main(["whoami", "--org", "acme"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["login"] == "andras" and info["can_administer"] is True
    monkeypatch.setattr(ra, "_client", lambda: client("t", "member"))
    assert ra.main(["whoami", "--org", "acme"]) == 3
    capsys.readouterr()
    monkeypatch.setattr(ra, "_client", lambda: client(None, "admin"))
    assert ra.main(["whoami", "--org", "acme"]) == 3
    assert json.loads(capsys.readouterr().out)["authenticated"] is False


def test_the_token_is_never_printed_by_any_command(ra, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GH_TOKEN", "ghp_SUPERSECRET")
    seen = []
    monkeypatch.setattr(ra._OPENER, "open", lambda req, timeout=None: seen.append(req) or (_ for _ in ()).throw(http_error(401, "Bad credentials")))
    pol = tmp_path / "p.yaml"
    pol.write_text("org: acme\nrepo_settings: {has_wiki: false}\n")
    for argv in (["whoami", "--org", "acme"], ["audit", "--policy", str(pol)], ["apply", "--policy", str(pol), "--yes"]):
        ra.main(argv)
    captured = capsys.readouterr()
    assert "ghp_SUPERSECRET" not in captured.out + captured.err
    assert seen and all(r.get_header("Authorization") == "Bearer ghp_SUPERSECRET" for r in seen)


# --------------------------------------------------------------------------- review fixes and the later additions


def test_token_is_not_sent_to_another_host_on_redirect(ra):
    import urllib.request
    handler = ra._SameHostRedirects()
    req = urllib.request.Request("https://api.github.com/x", headers={"Authorization": "Bearer t"})
    same = handler.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/y")
    other = handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example.com/y")
    assert same.get_header("Authorization") == "Bearer t" and other.get_header("Authorization") is None


@pytest.mark.parametrize("path", ["/etc/passwd", "../x.yml", "sub/../../x.yml"])
def test_workflow_path_must_stay_below_the_policy_directory(ra, tmp_path, path):
    errors = ra.validate_policy({"org": "a", "workflows": [{"path": path, "dest": ".github/workflows/x.yml"}]}, tmp_path)
    assert any("below the policy file's directory" in e for e in errors), errors


def test_workflow_path_symlink_out_of_the_directory_is_refused(ra, tmp_path):
    outside = tmp_path / "outside.yml"
    outside.write_text("name: x\n")
    inside = tmp_path / "pol"
    inside.mkdir()
    (inside / "w.yml").symlink_to(outside)
    assert any("leaves the policy file's directory" in e for e in ra.validate_policy({"org": "a", "workflows": [{"path": "w.yml"}]}, inside))


@pytest.mark.parametrize("pattern", ["**/*", "*/*", "*.*", "?*", "*e*", "a"])
def test_forbid_patterns_need_literal_characters(ra, pattern):
    assert any("refusing" in e for e in ra.validate_policy({"org": "a", "config_dirs": {"forbid": [pattern]}}))


def test_default_branch_name_cannot_break_out_of_the_template(ra):
    ctx, _ = world(ra, {"workflows": [{"template": "release"}]}, files={"app": {}}, branch="a~b")
    (f,) = ra.check_files(ctx)
    assert f.severity == "error" and f.action is None and "main_branch" in f.message


def test_overlapping_changes_make_one_tree_entry_per_path(ra):
    sent = []

    class C:
        def send(self, method, path, body=None):
            sent.append((path, body))
            return {"sha": "s", "html_url": "u", "number": 1}

    ra.apply_files(C(), "acme/app", [{"op": "delete", "path": "a/b"}, {"op": "delete", "path": "a/b"},
                                     {"op": "delete", "path": "w.yml"}, {"op": "put", "path": "w.yml", "content": "x"}],
                   "main", "c", "t", NOW.date())
    tree = next(b for p, b in sent if p.endswith("/git/trees"))["tree"]
    assert [(e["path"], e.get("sha", "x")) for e in tree] == [("a/b", None), ("w.yml", "x")]


def test_names_are_defused_in_the_markdown_report(ra):
    f = ra.Finding("labels", "acme/app", "x", "label '@team <img src=x> [a](b) `c`' is unused", "warn")
    text = ra.render_markdown("acme", [f], 1, NOW)
    import re
    cell = text.split("label '", 1)[1].split("' is unused", 1)[0]
    assert "@team" not in cell and "@\u200bteam" in cell
    assert not re.search(r"(?<!\\)[<>\[\]`]", cell), cell


@pytest.mark.parametrize("repo_arg", ["other/app", "app/../x", "a b", "acme/x/y"])
def test_repo_argument_must_name_a_repository_of_the_organisation(ra, tmp_path, repo_arg):
    pol = tmp_path / "p.yaml"
    pol.write_text("org: acme\nrepo_settings: {has_wiki: false}\n")
    with pytest.raises(SystemExit, match="--repo"):
        ra.main(["audit", "--policy", str(pol), "--repo", repo_arg])


def test_org_secret_is_not_deleted_when_the_token_does_not_see_every_repository(ra):
    routes = secret_routes(repo_secrets=(), org_secrets=("ORPHAN",))
    routes[("GET", "/orgs/acme")] = {"public_repos": 3, "total_private_repos": 2}  # the list below holds one
    ctx, _ = world(ra, {"secrets": {"kinds": ["actions"], "delete_unused": True}}, routes=routes)
    (f,) = ra.check_secrets(ctx)
    assert f.severity == "info" and f.action is None and "every repository" in f.message
    routes[("GET", "/orgs/acme")] = {"public_repos": 1}  # a non-owner does not get the private count
    ctx, _ = world(ra, {"secrets": {"kinds": ["actions"], "delete_unused": True}}, routes=routes)
    assert ra.check_secrets(ctx)[0].action is None


@pytest.mark.parametrize("expr", ["${{ toJSON(secrets) }}", "${{ format('{0}', vars) }}"])
def test_the_whole_context_hides_names(ra, expr):
    files = {"app": {".github/workflows/x.yml": f'env:\n  A: "{expr}"\n'}}
    ctx, _ = world(ra, {"secrets": {"kinds": ["actions"]}}, files=files, routes=secret_routes(repo_secrets=("ANY",)))
    assert ra.check_secrets(ctx) == []


def test_branch_age_is_the_last_activity_not_the_age_of_the_commit(ra):
    routes = branch_routes({("GET", "/repos/acme/app/activity"): lambda p: [{"timestamp": "2026-11-08T00:00:00Z"}]})
    ctx, _ = world(ra, {"branches": {}}, routes=routes)
    assert ra.check_branches(ctx) == [], "every branch was touched yesterday"


def test_the_base_of_an_open_pull_request_is_never_a_candidate(ra):
    ctx, fake = world(ra, {"branches": {}}, routes=branch_routes())
    assert "stacked-base" not in {f.subject for f in ra.check_branches(ctx)}
    assert not any(p.endswith("...stacked-base") for p in fake.reads)


def test_protection_of_a_branch_that_does_not_exist_is_info_not_a_failed_put(ra):
    ctx, fake = world(ra, {"branch_protection": {"branch": "release"}})
    (f,) = ra.check_protection(ctx)
    assert f.severity == "info" and f.action is None and not fake.writes


def test_private_vulnerability_reporting(ra):
    routes = {("GET", "/repos/acme/app/private-vulnerability-reporting"): {"enabled": False}}
    ctx, _ = world(ra, {"security": {"private_vulnerability_reporting": True}}, routes=routes)
    (f,) = ra.check_security(ctx)
    assert f.action.describe() == "PUT /repos/acme/app/private-vulnerability-reporting"
    routes[("GET", "/repos/acme/app/private-vulnerability-reporting")] = {"enabled": True}
    ctx, _ = world(ra, {"security": {"private_vulnerability_reporting": True}}, routes=routes)
    assert ra.check_security(ctx) == []


def test_required_files_are_reported_not_created(ra):
    ctx, _ = world(ra, {"config_dirs": {"require": ["SECURITY.md", "LICENSE"]}}, files={"app": {"LICENSE": "MIT"}})
    (f,) = ra.check_files(ctx)
    assert (f.subject, f.severity, f.action) == ("require:SECURITY.md", "warn", None)


UNPINNED = """name: ci
on: {pull_request_target: {}}
jobs:
  a:
    uses: org/repo/.github/workflows/w.yml@v1
  b:
    steps:
      - uses: actions/checkout@v4
      - uses: third/party@v1
      - uses: pinned/x@0123456789abcdef0123456789abcdef01234567
      - uses: ./local
      - uses: docker://alpine:3
"""


def test_workflow_lint(ra):
    files = {"app": {".github/workflows/ci.yml": UNPINNED, ".github/workflows/ok.yml":
                     "on: push\npermissions: {contents: read}\njobs: {a: {steps: [{uses: 'actions/checkout@0123456789abcdef0123456789abcdef01234567'}]}}\n"}}
    policy = {"workflow_lint": {"pin_actions": "third_party", "require_permissions": True, "forbid_pull_request_target": True}}
    ctx, _ = world(ra, policy, files=files)
    found = ra.check_lint(ctx)
    assert sev(found) == [(".github/workflows/ci.yml:permissions", "warn"), (".github/workflows/ci.yml:pin", "warn"),
                          (".github/workflows/ci.yml:pull_request_target", "warn")]
    pin = next(f for f in found if f.subject.endswith(":pin")).message
    assert "third/party@v1" in pin and "org/repo" in pin and "actions/checkout" not in pin and "local" not in pin and "alpine" not in pin
    assert all(f.action is None for f in found), "the lint never changes anything"
    ctx, _ = world(ra, {"workflow_lint": {"pin_actions": "all"}}, files=files)
    assert "actions/checkout@v4" in next(f for f in ra.check_lint(ctx)).message
    ctx, _ = world(ra, {"workflow_lint": {}}, files=files)
    assert ra.check_lint(ctx) == []
