"""repo_admin_gitops.py: the central git-ops repository, its environment and token, and where secrets are held,
against a fake GitHub (no network). Secret values never appear: the fixtures hold names only."""
import json

import pytest
import yaml

import test_repo_admin as base
from conftest import TLD
from test_repo_admin import by_check, world

POLICY = {"git_ops": {"repo": "acme/git-ops", "workflow": "tld-git-ops.yml", "allowlist": "git-ops-allowlist.json"}}
TEMPLATE = (TLD / "templates" / "tld-git-ops.yml").read_text()
ENV = "/repos/acme/git-ops/environments/git-ops"
LIMITED = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
ANY_BRANCH = {"deployment_branch_policy": None}
MAIN_ONLY = {"branch_policies": [{"id": 1, "name": "main", "type": "branch"}]}


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def routes(names=("app", "git-ops"), *, token=True, env=LIMITED, org_secrets=(), repo_secrets=None, envs=None, extra=None):
    """Every route the check reads. `envs` maps a repository to {environment: (settings, policies, [secret names])}."""
    r = {("GET", "/orgs/acme/actions/secrets"): {"secrets": [{"name": n, "visibility": "all"} for n in org_secrets]}}
    for n in names:
        fn = f"/repos/acme/{n}"
        r[("GET", f"{fn}/actions/secrets")] = {"secrets": [{"name": s} for s in (repo_secrets or {}).get(n, [])]}
        r[("GET", f"{fn}/actions/organization-secrets")] = {"secrets": []}
        listed = (envs or {}).get(n, {})
        r[("GET", f"{fn}/environments")] = {"environments": [{"name": e, **v[0]} for e, v in listed.items()]}
        for e, (_, policies, secrets) in listed.items():
            r[("GET", f"{fn}/environments/{e}/deployment-branch-policies")] = policies
            r[("GET", f"{fn}/environments/{e}/secrets")] = {"secrets": [{"name": s} for s in secrets]}
    if env is not None:
        r[("GET", ENV)] = env
        r[("GET", f"{ENV}/deployment-branch-policies")] = MAIN_ONLY
    r[("GET", f"{ENV}/secrets")] = {"secrets": [{"name": "GIT_OPS_TOKEN"}] if token else []}
    r.update(extra or {})
    return r


def audit(ra, central_files=None, policy=POLICY, names=("app", "git-ops"), **kw):
    ctx, fake = world(ra, policy, names=names, routes=routes(names, **kw), files={"git-ops": central_files or {}})
    return ra.run_checks(ctx, ["git_ops"]), fake, ctx


def complete(app_names=("app", "git-ops")):
    allow = {"owner": "acme", "repos": list(app_names), "protected_branches": ["main"]}
    return {".github/workflows/tld-git-ops.yml": TEMPLATE, "git-ops-allowlist.json": json.dumps(allow)}


def test_central_repository_incomplete(ra):
    found, fake, ctx = audit(ra)
    (wf,) = by_check(found, "git-ops-workflow")
    (allow,) = by_check(found, "git-ops-allowlist")
    for f in (wf, allow):
        assert f.severity == "fix" and f.action.kind == "files" and f.action.repo == "acme/git-ops"
    assert wf.action.changes[0]["path"] == ".github/workflows/tld-git-ops.yml"
    assert wf.action.changes[0]["content"] == TEMPLATE
    data = json.loads(allow.action.changes[0]["content"])
    assert data["owner"] == "acme" and data["repos"] == ["app", "git-ops"] and "main" in data["protected_branches"]
    assert not fake.writes  # an audit only reads
    # apply: one commit, one pull request, never a direct push to the default branch
    fake.routes.update({("POST", "/repos/acme/git-ops/git/trees"): {"sha": "T"}, ("POST", "/repos/acme/git-ops/git/commits"): {"sha": "C"},
                        ("POST", "/repos/acme/git-ops/git/refs"): {}, ("POST", "/repos/acme/git-ops/pulls"): {"html_url": "https://x/pr/1"}})
    lines = []
    assert ra.apply_findings(ctx, [wf, allow], True, False, out=lines.append) == 0
    kinds = [(m, p) for m, p, _ in fake.writes]
    assert kinds == [("POST", "/repos/acme/git-ops/git/trees"), ("POST", "/repos/acme/git-ops/git/commits"),
                     ("POST", "/repos/acme/git-ops/git/refs"), ("POST", "/repos/acme/git-ops/pulls")]
    assert len(fake.writes[0][2]["tree"]) == 2
    assert not any(p.startswith("/repos/acme/git-ops/contents") for _, p, _ in fake.writes)
    # complete: nothing to fix
    assert [f for f in audit(ra, complete())[0] if f.severity == "fix"] == []


def test_allowlist_keeps_entries_and_adds_only_what_is_missing(ra):
    files = complete()
    files["git-ops-allowlist.json"] = json.dumps({"owner": "acme", "repos": ["app-*", "old"], "protected_branches": ["main", "x/*"]})
    found, _, _ = audit(ra, files, names=("app-one", "git-ops", "svc"))
    (one,) = by_check(found, "git-ops-allowlist")
    data = json.loads(one.action.changes[0]["content"])
    assert data == {"owner": "acme", "repos": ["app-*", "old", "git-ops", "svc"], "protected_branches": ["main", "x/*"]}
    files["git-ops-allowlist.json"] = "{not json"
    (bad,) = by_check(audit(ra, files)[0], "git-ops-allowlist")
    assert bad.severity == "fix" and "not a valid allowlist" in bad.message


def test_allowlist_text_from_the_repositories_is_bounded(ra):
    weird = {"name": "x y", "full_name": "acme/x y", "archived": False, "fork": False, "default_branch": "main"}
    ctx, _ = world(ra, POLICY, names=("app", "git-ops"), routes=routes(), files={"git-ops": {}})
    ctx.all_repos.append(weird)
    found = ra.run_checks(ctx, ["git_ops"])
    (one,) = by_check(found, "git-ops-allowlist")
    assert "x y" not in one.action.changes[0]["content"] and "unusual characters" in one.message


def test_allowlist_path_must_be_the_one_the_workflow_reads(ra):
    policy = {"git_ops": {"repo": "acme/git-ops", "allowlist": "allowlist.yml"}}
    (one,) = by_check(audit(ra, complete(), policy=policy)[0], "git-ops-allowlist")
    assert one.severity == "warn" and one.action is None and "git-ops-allowlist.json" in one.manual


def test_shipped_workflow_is_least_privilege():
    doc = yaml.safe_load(TEMPLATE)
    triggers = doc.get(True) or doc.get("on")
    assert set(triggers) == {"workflow_dispatch"}  # never pull_request_target or any other trigger
    assert "pull_request_target" not in TEMPLATE
    assert doc["permissions"] == {"contents": "read"}
    (job,) = doc["jobs"].values()
    assert job["environment"] == "git-ops" and "default_branch" in job["if"]
    assert "permissions" not in job
    for step in job["steps"]:  # actions, if any, must be pinned to a commit
        uses = step.get("uses")
        assert uses is None or uses.rpartition("@")[2].isalnum() and len(uses.rpartition("@")[2]) == 40
    assert "GIT_OPS_TOKEN" in TEMPLATE and "${{ secrets." in TEMPLATE
    assert "ghp_" not in TEMPLATE and "github_pat_" not in TEMPLATE


def test_secret_and_environment(ra):
    found, fake, _ = audit(ra, complete(), token=False, env=None)
    (env,) = [f for f in by_check(found, "git-ops-environment") if f.subject == "environment:git-ops"]
    (tok,) = by_check(found, "git-ops-token")
    for f in (env, tok):
        assert f.severity == "warn" and f.action is None and f.manual
    assert "is missing" in env.message and "git-ops" in env.manual
    assert "GIT_OPS_TOKEN" in tok.message and "--env git-ops" in tok.manual
    assert not fake.writes
    # all set: nothing to report
    assert audit(ra, complete())[0] == []
    # the token is also a repository secret, or the environment lets any branch deploy
    found, _, _ = audit(ra, complete(), repo_secrets={"git-ops": ["GIT_OPS_TOKEN"]}, env=ANY_BRANCH)
    assert any(f.check == "git-ops-token" and "repository secret" in f.message for f in found)
    assert any(f.check == "git-ops-environment" and "lets every branch deploy" in f.message for f in found)
    assert all(f.action is None for f in by_check(found, "git-ops-environment") + by_check(found, "git-ops-token"))


def test_central_repository_missing_or_not_listed(ra):
    (one,) = by_check(audit(ra, names=("app",), extra={})[0], "git-ops-workflow")
    assert one.severity == "warn" and "not among" in one.message


def test_unscoped_secret(ra):
    found, fake, _ = audit(ra, complete(), org_secrets=["ORG_KEY"], repo_secrets={"app": ["DEPLOY_KEY", "OTHER"]})
    scope = by_check(found, "secrets_scope")
    by = {(f.scope, f.subject): f for f in scope}
    assert set(by) == {("acme", "org-secrets"), ("acme/app", "repo-secrets")}
    assert "ORG_KEY" in by[("acme", "org-secrets")].message and "DEPLOY_KEY, OTHER" in by[("acme/app", "repo-secrets")].message
    assert all(f.severity == "warn" and f.action is None and "environment" in f.manual for f in scope)
    assert not fake.writes


def test_env_secret_limited_to_default_branch_not_reported(ra):
    envs = {"app": {"tld-release": (LIMITED, MAIN_ONLY, ["TLD_RELEASE_TOKEN"])}}
    found, _, _ = audit(ra, complete(), envs=envs)
    assert by_check(found, "secrets_scope") == []
    other = {"app": {"tld-release": (LIMITED, {"branch_policies": [{"id": 2, "name": "main", "type": "branch"},
                                                                  {"id": 3, "name": "dev", "type": "branch"}]}, ["TLD_RELEASE_TOKEN"])}}
    assert by_check(audit(ra, complete(), envs=other)[0], "secrets_scope")  # one more branch is not 'only the default'


def test_env_secret_without_branch_policy_reported(ra):
    envs = {"app": {"prod": (ANY_BRANCH, MAIN_ONLY, ["PROD_KEY"]), "empty": (ANY_BRANCH, MAIN_ONLY, [])}}
    found, _, _ = audit(ra, complete(), envs=envs)
    (one,) = by_check(found, "secrets_scope")
    assert one.scope == "acme/app" and one.subject == "env:prod" and "PROD_KEY" in one.message and one.severity == "warn"


def test_secret_names_from_a_repository_are_shown_bounded(ra):
    evil = "X" * 500 + "\n<script>@admin`|"
    found, _, _ = audit(ra, complete(), repo_secrets={"app": [evil]})
    (one,) = by_check(found, "secrets_scope")
    assert "\n" not in one.message and "<script>" not in one.message and "`" not in one.message and "@" not in one.message and len(one.message) < 400


def test_section_absent_means_nothing_is_checked(ra):
    ctx, fake = world(ra, {}, routes={})
    assert ra.run_checks(ctx, ["git_ops"]) == [] and fake.reads == []
    assert "git_ops" in ra.CHECKS
