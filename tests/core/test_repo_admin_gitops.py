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
    assert bad.severity == "warn" and bad.action is None and "not a valid allowlist" in bad.message


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


def allow_files(**allow):
    files = complete()
    files["git-ops-allowlist.json"] = json.dumps({"owner": "acme", "repos": ["app", "git-ops"], "protected_branches": ["main"], **allow})
    return files


def test_existing_protected_branches_are_kept_verbatim(ra):
    hostile = ["main", "hotfix/[0-9]*", "x" * 150, "--delete", "*"]
    found, _, _ = audit(ra, allow_files(protected_branches=hostile, repos=["app"]))
    (one,) = by_check(found, "git-ops-allowlist")
    assert one.severity == "fix" and json.loads(one.action.changes[0]["content"])["protected_branches"] == hostile


def test_broad_or_outside_repos_entries_are_reported(ra):
    found, _, _ = audit(ra, allow_files(repos=["*", "app"]))
    (broad,) = [f for f in by_check(found, "git-ops-allowlist") if f.subject == "allowlist:broad"]
    assert broad.severity == "warn" and "wildcards" in broad.message
    found, _, _ = audit(ra, allow_files(repos=["?*", "app", "git-ops"]))
    assert any(f.subject == "allowlist:broad" for f in found)
    # a glob that reaches a repository the audit does not cover (here an excluded one)
    policy = {**POLICY, "repos": {"exclude": ["secret"]}}
    found, _, _ = audit(ra, allow_files(repos=["app", "git-ops", "sec*"]), policy=policy, names=("app", "git-ops", "secret"))
    (outside,) = [f for f in by_check(found, "git-ops-allowlist") if f.subject == "allowlist:outside"]
    assert "secret" in outside.message and outside.severity == "warn"


def test_names_starting_with_dash_or_dot_are_never_added(ra):
    found, _, _ = audit(ra, {}, names=("app", "git-ops", ".github", "-x"))
    (one,) = by_check(found, "git-ops-allowlist")
    assert json.loads(one.action.changes[0]["content"])["repos"] == ["app", "git-ops"] and "unusual" in one.message


def test_missing_or_empty_protected_branches_start_from_the_defaults(ra):
    files = allow_files(protected_branches=[], repos=["app"])
    found, _, _ = audit(ra, files)
    assert any(f.subject == "allowlist:protected" and f.severity == "warn" for f in by_check(found, "git-ops-allowlist"))
    (fix,) = [f for f in by_check(found, "git-ops-allowlist") if f.severity == "fix"]
    assert {"main", "release/*"} <= set(json.loads(fix.action.changes[0]["content"])["protected_branches"])
    files["git-ops-allowlist.json"] = json.dumps({"owner": "acme", "repos": ["app", "git-ops"]})
    found, _, _ = audit(ra, files)
    assert any(f.severity == "fix" and "no protected branches" in f.message for f in by_check(found, "git-ops-allowlist"))


def test_deeply_nested_allowlist_does_not_stop_the_audit(ra):
    files = complete()
    files["git-ops-allowlist.json"] = "[" * 100_000
    found, _, _ = audit(ra, files)
    (one,) = by_check(found, "git-ops-allowlist")
    assert one.severity == "warn" and one.action is None and "not a valid allowlist" in one.message
    assert by_check(found, "secrets_scope") == []
    files["git-ops-allowlist.json"] = json.dumps({"owner": "acme", "repos": ["app"], "protected_branches": ["hotfix/*", 7]})
    (kept,) = by_check(audit(ra, files)[0], "git-ops-allowlist")
    assert kept.severity == "warn" and kept.action is None  # the owner's protections are never replaced by defaults


def test_invalid_policy_values_are_not_used_in_paths(ra):
    found, fake, _ = audit(ra, policy={"git_ops": {"repo": "acme/git-ops", "workflow": "../x.yml"}})
    (one,) = by_check(found, "git-ops-workflow")
    assert one.severity == "warn" and "git_ops.workflow" in one.message and not fake.writes


def test_central_environment_text_is_defused(ra):
    env = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
    extra = {("GET", f"{ENV}/deployment-branch-policies"): {"branch_policies": [
        {"id": 1, "name": "main", "type": "branch"}, {"id": 2, "name": "x`@everyone<b>\nz", "type": "branch"}]}}
    found, _, _ = audit(ra, complete(), env=env, extra=extra)
    (one,) = by_check(found, "git-ops-environment")
    assert "@" not in one.message and "<" not in one.message and "`" not in one.message and "\n" not in one.message


def test_default_branch_name_is_shown_safely(ra):
    import urllib.parse
    evil = "main-**[x](http--e)@everyone"
    ctx, fake = world(ra, POLICY, names=("app", "git-ops"), routes=routes(env=None, token=False), files={"git-ops": complete()})
    fake.routes[("GET", "/repos/acme/git-ops")]["default_branch"] = evil
    quoted = urllib.parse.quote(evil, safe="/")
    fake.routes[("GET", f"/repos/acme/git-ops/branches/{quoted}")] = fake.routes[("GET", "/repos/acme/git-ops/branches/main")]
    found = ra.run_checks(ctx, ["git_ops"])
    items = by_check(found, "git-ops-environment") + by_check(found, "git-ops-token")
    assert items
    for f in items:
        assert "@" not in f.manual + f.message and "[" not in f.manual + f.message and "**" not in f.manual + f.message


def test_central_repository_spelled_in_another_case(ra):
    policy = {"git_ops": {"repo": "acme/Git-Ops"}}
    found, _, _ = audit(ra, policy=policy)
    fixes = [f for f in found if f.severity == "fix"]
    assert len(fixes) == 2 and all(f.action.repo == "acme/git-ops" and f.scope == "acme/git-ops" for f in fixes)


UNUSUAL = ["@(*)", "+(?)", "!(zzz)", "zz\n*", "[^x]*", "app\n", "*(x)*", "a\\*", "?(*)", "*([a-z])", "\uff0a",
           "app\u200b", "x" * 101]


@pytest.mark.parametrize("entry", UNUSUAL)
def test_entries_bash_reads_differently_are_reported_and_kept(ra, entry):
    policy = {**POLICY, "repos": {"exclude": ["secret"]}}
    found, _, _ = audit(ra, allow_files(repos=["git-ops", entry]), policy=policy, names=("app", "git-ops", "secret"))
    rows = by_check(found, "git-ops-allowlist")
    (unusual,) = [f for f in rows if f.subject == "allowlist:unusual"]
    assert unusual.severity == "warn" and unusual.manual and "repos[1]" in unusual.message
    (fix,) = [f for f in rows if f.severity == "fix"]  # app is not covered by the entry, so it is added
    assert json.loads(fix.action.changes[0]["content"])["repos"] == ["git-ops", entry, "app"]


@pytest.mark.parametrize("entry", ["S*", "SECRET", "Sec?et"])
def test_globs_are_matched_without_regard_to_case(ra, entry):
    policy = {**POLICY, "repos": {"exclude": ["secret"]}}
    found, _, _ = audit(ra, allow_files(repos=["app", "git-ops", entry]), policy=policy, names=("app", "git-ops", "secret"))
    (outside,) = [f for f in by_check(found, "git-ops-allowlist") if f.subject == "allowlist:outside"]
    assert "secret" in outside.message


@pytest.mark.parametrize("entry", ["@(*)", "*", "!(x)", "?*"])
def test_a_wrong_owner_is_not_fixed_while_a_match_everything_entry_is_there(ra, entry):
    files = complete()
    files["git-ops-allowlist.json"] = json.dumps({"owner": "other", "repos": ["app", "git-ops", entry], "protected_branches": ["main"]})
    found, _, _ = audit(ra, files)
    rows = by_check(found, "git-ops-allowlist")
    assert [f for f in rows if f.action] == [] and any(f.subject == "allowlist:owner" and f.severity == "warn" for f in rows)
    # without such an entry the owner is fixed
    files["git-ops-allowlist.json"] = json.dumps({"owner": "other", "repos": ["app", "git-ops"], "protected_branches": ["main"]})
    (fix,) = [f for f in by_check(audit(ra, files)[0], "git-ops-allowlist") if f.action]
    assert json.loads(fix.action.changes[0]["content"])["owner"] == "acme"


def test_an_update_that_the_audit_would_refuse_is_not_written(ra):
    repos = [f"r{i:04d}" + "x" * 119 for i in range(1990)]
    files = allow_files(repos=repos)
    assert len(files["git-ops-allowlist.json"].encode()) < 256_000
    found, _, _ = audit(ra, files, names=("app", "git-ops", "new-repo"))
    rows = {f.subject: f for f in by_check(found, "git-ops-allowlist")}
    assert set(rows) == {"allowlist:unusual", "allowlist:size"}  # entries over 100 characters are unusual too
    assert rows["allowlist:size"].severity == "warn" and rows["allowlist:size"].action is None


def test_fixed_guidance_is_not_defaced(ra):
    found, _, _ = audit(ra, complete(), token=False, env=None)
    (tok,) = by_check(found, "git-ops-token")
    assert "`gh secret set GIT_OPS_TOKEN --env git-ops --repo acme/git-ops`" in tok.manual
    env = next(f for f in by_check(found, "git-ops-environment") if f.subject == "environment:git-ops")
    assert "https://github.com/acme/git-ops/settings/environments" in env.manual
