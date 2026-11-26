"""repo_admin.py: the two reference policies reproduce as the shared base plus a repository override (plan 93, 3.10)."""
import copy

import pytest
import yaml

import test_repo_admin as base
from conftest import ROOT, TLD
from test_repo_admin import Fake, by_check, world
from test_repo_admin_extends import SHA_A, SHA_B, serve

FIXTURES = ROOT / "tests" / "fixtures" / "admin-policy"
OVERRIDE = ".tld/admin-policy.yaml"
TOOLKIT = ".tld/toolkit.yaml"
BASE_PATH, ORG_PATH = "tld/admin-policy-base.yaml", "tld/admin-policy-org.yaml"
BASE_PIN = f"acme/.github/{BASE_PATH}@{SHA_A}"
ORG_PIN = f"acme/git-ops/{ORG_PATH}@{SHA_B}"

# What the base manages and the old file `a` did not say: the only differences the reproduction may show.
DELTA = {
    "a": {"repo_settings.allow_merge_commit", "repo_settings.allow_squash_merge", "repo_settings.allow_rebase_merge",
          "config_dirs.forbid", "workflow_lint.pin_actions", "workflow_lint.require_permissions",
          "workflow_lint.forbid_pull_request_target"},
    "b": set(),
}
# The findings only the inherited run has: p7 names every login that is taken from the repository's profile.
FINDINGS_DELTA = {("agent", "acme/app", "login:derived:agent.agent_login", "warn"),
                  ("release", "acme/app", "login:derived:release.reviewer_login", "warn")}
LOGINS = {"a": ("bot-a", "owner-a"), "b": ("bot-b", "owner-b")}
PROFILES = {  # what the repository's profile says; the logins of the legacy files come from here
    "a": {"git": {"bot_login": "bot-a", "owner_login": "owner-a"}, "release": {"workflow": "tld-release.yml"}},
    "b": {"git": {"bot_login": "bot-b", "codeowners": ["owner-b"]}, "release": {"workflow": "tld-release.yml"}},
}
LIVE_KEYS = ("repo", "security", "actions", "rulesets", "agent", "release", "files")


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def fixture_text(name):
    return (FIXTURES / name).read_text()


def fixture(name):
    return yaml.safe_load(fixture_text(name))


def run_file(which, **extra):
    """The run file of an organisation with its placeholders replaced by pins, set to the fake organisation `acme`."""
    doc = fixture(f"org-{which}.yaml")
    assert doc["extends"] == ["@BASE_PIN@", "@ORG_PIN@"]
    doc["extends"] = [BASE_PIN, ORG_PIN]
    doc["org"] = "acme"
    doc["repos"] = {"include": ["app"]}
    return {**doc, **extra}


def legacy_file(which):
    doc = fixture(f"legacy-{which}.yaml")
    doc["org"] = "acme"
    doc["repos"] = {**doc["repos"], "include": ["app"]}
    return doc


def pin_routes():
    routes: dict = {}
    serve(routes, "acme/.github", BASE_PATH, SHA_A, fixture_text("shared-base.yaml"), private=False, visibility="public")
    serve(routes, "acme/git-ops", ORG_PATH, SHA_B, "{}\n")
    return routes


def resolve(ra, which, routes=None):
    from tld.ops import repo_admin_extends
    res = repo_admin_extends.resolve(Fake(routes if routes is not None else pin_routes()), run_file(which))
    assert res.errors == [] and res.policy is not None
    return res.policy


@pytest.fixture
def profiles(ra, monkeypatch):
    """Replaces the repository profile reader; `which` says whose profile it is, `calls` the repositories it was asked for."""
    state = {"which": "a", "calls": []}

    def fake_profile(ctx, repo):
        state["calls"].append(repo["full_name"])
        return copy.deepcopy(PROFILES[state["which"]])
    monkeypatch.setattr(ra.repo_admin_profile, "repo_profile", fake_profile)
    return state


def inherited_world(ra, which, override=None, routes=None, **kw):
    r = pin_routes()
    r.update(routes or {})
    files = {"app": {OVERRIDE: override if override is not None else fixture_text(f"override-{which}.yaml")}}
    return world(ra, resolve(ra, which, r), routes=r, files=files, **kw)


def legacy_world(ra, which, routes=None, **kw):
    return world(ra, legacy_file(which), routes=routes, files={"app": {}}, **kw)


def leaves(doc, prefix=""):
    """dotted key -> value for every scalar or list; mappings are walked."""
    out = {}
    for key, value in doc.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out.update(leaves(value, dotted + "."))
        else:
            out[dotted] = value
    return out


def normalised(policy, which):
    """The policy without underscore keys, org, repos, workflow_params and the two logins."""
    out = copy.deepcopy({k: v for k, v in policy.items() if not k.startswith("_") and k not in ("org", "repos", "workflow_params")})
    out.get("agent", {}).pop("agent_login", None)
    out.get("release", {}).pop("reviewer_login", None)
    return leaves(out)


def difference(left, right):
    return {k for k in left.keys() | right.keys() if left.get(k, "<absent>") != right.get(k, "<absent>")}


# --------------------------------------------------------------------------- fixtures


def test_override_fixtures_are_minimal(ra):
    assert fixture("shared-base.yaml") == yaml.safe_load((TLD / "templates" / "admin-policy-base.yaml").read_text())
    for which in "ab":
        assert fixture(f"org-{which}.yaml").keys() == {"org", "extends"}
        assert len(fixture(f"org-{which}.yaml")["extends"]) == 2
    a, b = fixture("override-a.yaml"), fixture("override-b.yaml")
    assert set(leaves(a)) == {"rulesets.default_branch.required_status_checks", "workflows"}
    assert len(a["rulesets"]["default_branch"]["required_status_checks"]) == 2 and a["workflows"] == [{"template": "land"}]
    assert set(leaves(b)) == {"rulesets.default_branch.required_status_checks", "config_dirs.known", "workflow_params.release.tag_prefix",
                              "workflow_params.release.version_style", "workflow_params.release.create_release",
                              "workflow_params.release.check_script"}
    assert len(b["rulesets"]["default_branch"]["required_status_checks"]) == 10 and b["config_dirs"] == {"known": [".claude-plugin"]}
    assert set(b["workflow_params"]) == {"release"}
    for which, doc in (("a", a), ("b", b)):  # both are valid overrides, by the same check the audit applies
        assert ra.validate_policy(doc, kind="override", where=f"override-{which}") == []
        assert ra.validate_policy(legacy_file(which), kind="run") == []
    assert fixture("legacy-a.yaml")["agent"]["agent_login"] == "bot-a" and fixture("legacy-a.yaml")["release"]["reviewer_login"] == "owner-a"
    assert fixture("legacy-b.yaml")["agent"]["agent_login"] == "bot-b" and fixture("legacy-b.yaml")["release"]["reviewer_login"] == "owner-b"
    assert (fixture("legacy-a.yaml")["org"], fixture("legacy-a.yaml")["repos"]["include"]) == ("acme-a", ["app-a"])
    assert (fixture("legacy-b.yaml")["org"], fixture("legacy-b.yaml")["repos"]["include"]) == ("acme-b", ["app-b"])


# --------------------------------------------------------------------------- the effective policy


@pytest.mark.parametrize("which", ["a", "b"])
def test_effective_policy_reproduces_each_legacy_file(ra, profiles, which):
    profiles["which"] = which
    ctx, _ = inherited_world(ra, which)
    repo = ctx.all_repos[0]
    ctx.logins(repo)
    legacy = legacy_file(which)
    assert normalised(ctx.pol(repo), which) and normalised(legacy, which)
    assert difference(normalised(ctx.pol(repo), which), normalised(legacy, which)) == DELTA[which]
    assert by_check(ra.check_policy(ctx), "policy") == []  # the override is accepted as it is


@pytest.mark.parametrize("which", ["a", "b"])
def test_derived_logins_equal_the_legacy_logins(ra, profiles, which):
    profiles["which"] = which
    ctx, _ = inherited_world(ra, which)
    repo = ctx.all_repos[0]
    assert "agent_login" not in (ctx.pol(repo).get("agent") or {}) and "reviewer_login" not in (ctx.pol(repo).get("release") or {})
    got = ctx.logins(repo)
    legacy = legacy_file(which)
    assert (got.agent, got.reviewer) == (legacy["agent"]["agent_login"], legacy["release"]["reviewer_login"]) == LOGINS[which]
    assert got.agent_derived and got.reviewer_derived and not got.same
    assert profiles["calls"] == ["acme/app"]  # the patched reader was used, once (memoised)


# --------------------------------------------------------------------------- the findings


def live_routes(which):
    """A fake organisation whose live state differs from the policy in every shared section and matches the DELTA keys."""
    agent, reviewer = LOGINS[which]
    agent_env = "/repos/acme/app/environments/tld-agent"
    return {
        ("GET", "/repos/acme/app/vulnerability-alerts"): base.ApiErr(404, "Not Found", "GET", "x"),
        ("GET", "/repos/acme/app/automated-security-fixes"): {"enabled": False},
        ("GET", "/repos/acme/app/private-vulnerability-reporting"): {"enabled": False},
        ("GET", "/repos/acme/app/actions/permissions/workflow"): {"default_workflow_permissions": "write",
                                                                 "can_approve_pull_request_reviews": True},
        ("GET", "/repos/acme/app/rulesets"): [],
        ("GET", f"/repos/acme/app/collaborators/{agent}/permission"): {"permission": "write", "role_name": "admin"},
        ("GET", "/repos/acme/app/actions/secrets"): {"secrets": []},
        ("GET", "/repos/acme/app/actions/organization-secrets"): {"secrets": []},
        ("GET", agent_env): {"name": "tld-agent", "deployment_branch_policy": {"protected_branches": True,
                                                                              "custom_branch_policies": False}},
        ("GET", f"{agent_env}/deployment-branch-policies"): {"branch_policies": []},
        ("GET", f"{agent_env}/secrets"): {"secrets": []},
        ("GET", f"/users/{reviewer}"): {"login": reviewer, "id": 42},
    }


LIVE_FULL = dict(allow_auto_merge=False, delete_branch_on_merge=False, allow_update_branch=False, allow_merge_commit=True,
                 allow_squash_merge=False, allow_rebase_merge=False,
                 security_and_analysis={"secret_scanning": {"status": "disabled"},
                                        "secret_scanning_push_protection": {"status": "disabled"}})


def findings_of(ra, ctx):
    found = [f for f in ra.run_checks(ctx) if f.check != "policy"]
    return found, {(f.check, f.scope, f.subject, f.severity) for f in found}


@pytest.mark.parametrize("which", ["a", "b"])
def test_same_findings_as_before(ra, profiles, which):
    profiles["which"] = which
    routes = live_routes(which)
    old_ctx, old_fake = legacy_world(ra, which, routes=dict(routes), **LIVE_FULL)
    new_ctx, new_fake = inherited_world(ra, which, routes=dict(routes), **LIVE_FULL)
    old_found, old = findings_of(ra, old_ctx)
    new_found, new = findings_of(ra, new_ctx)
    assert old and new - old == FINDINGS_DELTA and old - new == set()
    assert {check for check, *_ in new} >= set(LIVE_KEYS)
    assert not [f for f in old_found + new_found if f.severity in ("unavailable", "error")]
    assert f"/repos/acme/app/contents/{OVERRIDE}" in new_fake.reads
    assert not [p for p in old_fake.reads if p.endswith(OVERRIDE)]
    assert "acme/app" in profiles["calls"]


def test_small_policy_resolves_and_validates(ra, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ra, "_client", lambda: Fake(pin_routes()))
    for which in "ab":
        path = tmp_path / f"org-{which}.yaml"
        path.write_text(yaml.safe_dump(run_file(which)))
        assert set(yaml.safe_load(path.read_text())) == {"org", "extends", "repos"}  # the placeholders only set what the test needs
        capsys.readouterr()
        assert ra.main(["validate-policy", str(path)]) == 0
        out, err = capsys.readouterr()
        assert out == f"policy: OK ({path})\n" and err == ""
        assert ra.main(["validate-policy", str(path), "--resolved"]) == 0
        resolved = yaml.safe_load(capsys.readouterr().out)
        assert resolved["security"]["secret_scanning"] is True and resolved["workflows"] == [{"template": "release"}, {"template": "land"}]
        assert "extends" not in resolved and not [k for k in resolved if k.startswith("_")]


@pytest.mark.parametrize("which", ["a", "b"])
def test_override_with_only_the_checks_audits_the_repository_fully(ra, profiles, which):
    profiles["which"] = which
    checks = fixture(f"override-{which}.yaml")["rulesets"]["default_branch"]["required_status_checks"]
    only = yaml.safe_dump({"rulesets": {"default_branch": {"required_status_checks": checks}}})
    routes = live_routes(which)
    old_ctx, _ = legacy_world(ra, which, routes=dict(routes), **LIVE_FULL)
    new_ctx, _ = inherited_world(ra, which, override=only, routes=dict(routes), **LIVE_FULL)
    names = [n for n in LIVE_KEYS if n != "files"]
    old = {(f.check, f.scope, f.subject, f.severity) for f in ra.run_checks(old_ctx, names)}
    new = {(f.check, f.scope, f.subject, f.severity) for f in ra.run_checks(new_ctx, names)}
    assert old and {t for t in new if "login:derived:" not in t[2]} == old
    assert new - old == FINDINGS_DELTA
    assert {check for check, *_ in new} >= set(names)
    # the release workflow has no parameters in this override: it is left alone (an information finding), the rest is the same
    old_files = {(f.subject, f.severity) for f in ra.check_files(old_ctx) if "tld-release.yml" not in f.subject}
    new_files = {(f.subject, f.severity) for f in ra.check_files(new_ctx) if f.severity != "info"}
    assert {s for s in old_files if s[1] != "info"} <= new_files
    standdown = [f for f in ra.check_files(new_ctx) if f.subject.endswith(":standdown")]
    assert [(f.subject, f.severity) for f in standdown] == [("workflow:.github/workflows/tld-release.yml:standdown", "info")]


# --------------------------------------------------------------------------- refusals


def test_base_with_a_token_like_string_is_refused(ra):
    from tld.ops import repo_admin_extends
    token = "gh" + "p_" + "A1b2C3d4E5" * 4  # built at run time: no credential-looking line in this file
    routes: dict = {}
    serve(routes, "acme/.github", BASE_PATH, SHA_A, fixture_text("shared-base.yaml") + f"# {token}\n", private=False, visibility="public")
    serve(routes, "acme/git-ops", ORG_PATH, SHA_B, "{}\n")
    res = repo_admin_extends.resolve(Fake(routes), run_file("a"))
    assert res.policy is None and res.errors
    assert token not in " ".join(res.errors) and token[4:20] not in " ".join(res.errors)


def test_org_level_key_in_an_override_is_rejected(ra, profiles):
    ctx, _ = inherited_world(ra, "a", override=fixture_text("override-a.yaml") + "members:\n  max_owners: 3\n")
    repo = ctx.all_repos[0]
    ov = ctx.override(repo)
    assert ov.doc is None and any("organisation-level" in p and "members" in p for p in ov.problems)
    assert ctx.pol(repo) == ctx.p  # the repository is audited with the organisation policy alone
    found = by_check(ra.check_policy(ctx), "policy")
    assert [f.severity for f in found if "organisation-level" in f.message] == ["error"]
