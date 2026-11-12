"""repo_admin.py: the rulesets, the agent account's role and the tld-agent environment, against a fake GitHub."""
import copy

import pytest
import yaml

import test_repo_admin as base
from conftest import ROOT
from test_repo_admin import world


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


RS = "/repos/acme/app/rulesets"
ENV = "/repos/acme/app/environments/tld-agent"
PERM = "/repos/acme/app/collaborators/bot/permission"
RULESETS = {"default_branch": {"required_status_checks": ["test"]}, "tags": True}
AGENT = {"agent_login": "bot"}


def bodies(ra, cfg=RULESETS):
    return {b["name"]: b for b in ra.ruleset_bodies(cfg)}


def as_served(body, rid):
    """What GET /rulesets/{id} answers for a ruleset made from `body` (GitHub adds ids and defaults)."""
    have = copy.deepcopy(body)
    have.update({"id": rid, "source_type": "Repository", "source": "acme/app"})
    for rule in have["rules"]:
        if rule["type"] == "pull_request":
            rule["parameters"]["allowed_merge_methods"] = ["merge", "squash", "rebase"]
        if rule["type"] == "required_status_checks":
            for c in rule["parameters"]["required_status_checks"]:
                c["integration_id"] = 15368
    return have


def served(ra, cfg=RULESETS, edit=None):
    routes, listing = {}, []
    for rid, (name, body) in enumerate(bodies(ra, cfg).items(), 1):
        have = as_served(body, rid)
        if edit:
            edit(name, have)
        listing.append({"id": rid, "name": name, "source_type": "Repository"})
        routes[("GET", f"{RS}/{rid}")] = have
    routes[("GET", RS)] = listing
    return routes


# --------------------------------------------------------------------------- the bodies


def test_main_ruleset_shape(ra):
    main = bodies(ra)["tld-main"]
    assert main["target"] == "branch" and main["enforcement"] == "active" and main["bypass_actors"] == []
    assert main["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    rules = {r["type"]: r.get("parameters") for r in main["rules"]}
    assert set(rules) == {"pull_request", "required_status_checks", "non_fast_forward", "deletion"}
    pr = rules["pull_request"]
    assert pr["required_approving_review_count"] == 1 and pr["dismiss_stale_reviews_on_push"] is True
    assert pr["require_last_push_approval"] is True
    assert rules["required_status_checks"]["required_status_checks"] == [{"context": "test"}]


def test_main_ruleset_without_checks_and_with_admin_bypass(ra):
    main = bodies(ra, {"default_branch": {"admin_bypass": True}})["tld-main"]
    assert "required_status_checks" not in {r["type"] for r in main["rules"]}
    assert main["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]


def test_this_repository_lets_only_the_admin_role_bypass_main_through_a_pull_request(ra):
    policy_dir = ROOT / ".tld"
    policy = yaml.safe_load((policy_dir / "admin-policy.yaml").read_text())
    assert ra.validate_policy(policy, policy_dir) == []
    main = bodies(ra, policy["rulesets"])["tld-main"]
    assert main["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    checks = {c["context"] for r in main["rules"] if r["type"] == "required_status_checks"
              for c in r["parameters"]["required_status_checks"]}
    assert checks == {"test (3.11)", "test (3.13)"}


def test_tag_ruleset_shape(ra):
    tags = bodies(ra)["tld-tags"]
    assert tags["target"] == "tag" and tags["conditions"]["ref_name"]["include"] == ["~ALL"]
    assert [r["type"] for r in tags["rules"]] == ["creation", "update", "deletion"]
    assert tags["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    assert not any(a["actor_type"] == "Integration" for a in tags["bypass_actors"]), "no workflow token may tag"
    assert set(bodies(ra, {"tags": True})) == {"tld-tags"} and ra.ruleset_bodies({"tags": False}) == []


# --------------------------------------------------------------------------- the rulesets check


def test_missing_rulesets_are_created(ra):
    ctx, fake = world(ra, {"rulesets": RULESETS}, routes={("GET", RS): []})
    found = ra.check_rulesets(ctx)
    assert base.sev(found) == [("tld-main", "fix"), ("tld-tags", "fix")]
    for f in found:
        assert f.action.method == "POST" and f.action.path == RS and not f.action.destructive
        assert f.action.body == bodies(ra)[f.subject]
    assert fake.writes == []


def test_matching_rulesets_are_no_drift(ra):
    ctx, _ = world(ra, {"rulesets": RULESETS}, routes=served(ra))
    assert ra.check_rulesets(ctx) == []


def test_rulesets_of_the_organisation_or_another_name_are_not_ours(ra):
    routes = {("GET", RS): [{"id": 9, "name": "tld-main", "source_type": "Organization"}, {"id": 8, "name": "other"}]}
    ctx, fake = world(ra, {"rulesets": {"tags": True}}, routes=routes)
    assert base.sev(ra.check_rulesets(ctx)) == [("tld-tags", "fix")]
    assert f"{RS}/8" not in fake.reads and f"{RS}/9" not in fake.reads


@pytest.mark.parametrize("edit,needle", [
    (lambda h: h.update(enforcement="evaluate"), "enforcement is 'evaluate'"),
    (lambda h: h["rules"].pop(), "is missing"),
    (lambda h: h["rules"].append({"type": "required_linear_history"}), "extra rules required_linear_history"),
    (lambda h: h["conditions"]["ref_name"].update(include=["refs/heads/dev"]), "applies to"),
    (lambda h: h["bypass_actors"].append({"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}),
     "bypass actors differ"),
])
def test_a_changed_main_ruleset_is_put_back(ra, edit, needle):
    routes = served(ra, edit=lambda name, have: edit(have) if name == "tld-main" else None)
    ctx, _ = world(ra, {"rulesets": RULESETS}, routes=routes)
    found = ra.check_rulesets(ctx)
    assert len(found) == 1 and found[0].subject == "tld-main" and needle in found[0].message, found
    assert found[0].action.method == "PUT" and found[0].action.path == f"{RS}/1"
    assert found[0].action.body == bodies(ra)["tld-main"]


@pytest.mark.parametrize("change", [
    {"required_approving_review_count": 0}, {"dismiss_stale_reviews_on_push": False}, {"require_last_push_approval": False}])
def test_weaker_review_parameters_are_drift(ra, change):
    def edit(name, have):
        if name == "tld-main":
            next(r for r in have["rules"] if r["type"] == "pull_request")["parameters"].update(change)
    ctx, _ = world(ra, {"rulesets": RULESETS}, routes=served(ra, edit=edit))
    assert [f.message for f in ra.check_rulesets(ctx)] == ["ruleset tld-main: rule pull_request has other parameters"]


def test_other_required_checks_are_drift(ra):
    routes = served(ra, {"default_branch": {"required_status_checks": ["lint"]}})
    ctx, _ = world(ra, {"rulesets": {"default_branch": {"required_status_checks": ["lint", "test"]}}}, routes=routes)
    assert [f.message for f in ra.check_rulesets(ctx)] == ["ruleset tld-main: rule required_status_checks has other parameters"]


def test_a_tag_ruleset_that_lets_workflows_tag_is_drift(ra):
    def edit(name, have):
        if name == "tld-tags":
            have["bypass_actors"].append({"actor_id": 15368, "actor_type": "Integration", "bypass_mode": "always"})
    ctx, _ = world(ra, {"rulesets": RULESETS}, routes=served(ra, edit=edit))
    found = ra.check_rulesets(ctx)
    assert [f.subject for f in found] == ["tld-tags"] and "Integration 15368 (always)" in found[0].message
    assert found[0].action.body["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    assert found[0].action.path == f"{RS}/2"


def test_unreadable_bypass_actors_are_unavailable_not_drift(ra):
    ctx, _ = world(ra, {"rulesets": RULESETS}, routes=served(ra, edit=lambda name, have: have.pop("bypass_actors")))
    assert base.sev(ra.check_rulesets(ctx)) == [("tld-main:bypass", "unavailable"), ("tld-tags:bypass", "unavailable")]


def test_rulesets_not_available_on_the_plan_are_reported(ra):
    routes = {("GET", RS): base.ApiErr(403, "Upgrade to GitHub Pro or make this repository public", "GET", RS)}
    ctx, _ = world(ra, {"rulesets": RULESETS}, routes=routes)
    found = ra.check_rulesets(ctx)
    assert len(found) == 1 and found[0].severity == "unavailable" and "Upgrade" in found[0].message


def test_branch_protection_stands_down_for_the_main_ruleset(ra):
    policy = {"rulesets": {"default_branch": {}}, "branch_protection": {"approvals": 1}}
    ctx, _ = world(ra, policy, routes={("GET", RS): []})
    assert ra.check_protection(ctx) == []
    ctx, _ = world(ra, {"rulesets": {"tags": True}, "branch_protection": {"approvals": 1}})
    assert base.sev(ra.check_protection(ctx)) == [("main", "fix")]


def test_rulesets_dry_run_and_apply(ra):
    ctx, fake = world(ra, {"rulesets": RULESETS}, routes={("GET", RS): []})
    found = ra.run_checks(ctx, ["rulesets"])
    lines = []
    assert ra.apply_findings(ctx, found, yes=False, allow_delete=False, out=lines.append) == 0
    assert fake.writes == [] and any(line.startswith("Would run: POST /repos/acme/app/rulesets") for line in lines)
    assert ra.apply_findings(ctx, found, yes=True, allow_delete=False, out=lines.append) == 0
    assert [(m, p, b["name"]) for m, p, b in fake.writes] == [("POST", RS, "tld-main"), ("POST", RS, "tld-tags")]


# --------------------------------------------------------------------------- the agent account and its environment


def agent_routes(role="write", env=None, policies=(), repo_secrets=(), org_secrets=(), env_secrets=("TLD_AGENT_TOKEN",)):
    routes = {("GET", PERM): role if isinstance(role, Exception) else {"permission": "write", "role_name": role},
              ("GET", "/repos/acme/app/actions/secrets"): {"secrets": [{"name": n} for n in repo_secrets]},
              ("GET", "/repos/acme/app/actions/organization-secrets"): {"secrets": [{"name": n} for n in org_secrets]}}
    if env is not None:
        routes[("GET", ENV)] = env
        routes[("GET", f"{ENV}/deployment-branch-policies")] = {"branch_policies": list(policies)}
        routes[("GET", f"{ENV}/secrets")] = {"secrets": [{"name": n} for n in env_secrets]}
    return routes


GOOD_ENV = {"name": "tld-agent", "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
MAIN_ONLY = [{"id": 1, "name": "main", "type": "branch"}]


def test_agent_in_line_is_no_drift(ra):
    ctx, fake = world(ra, {"agent": AGENT}, routes=agent_routes(env=GOOD_ENV, policies=MAIN_ONLY))
    assert ra.check_agent(ctx) == []
    assert fake.writes == []


@pytest.mark.parametrize("role", ["admin", "maintain"])
def test_a_role_above_write_is_lowered(ra, role):
    ctx, _ = world(ra, {"agent": AGENT}, routes=agent_routes(role=role, env=GOOD_ENV, policies=MAIN_ONLY))
    found = ra.check_agent(ctx)
    assert base.sev(found) == [("role:bot", "fix")] and f"has the {role} role" in found[0].message
    assert found[0].action.describe() == 'PUT /repos/acme/app/collaborators/bot {"permission": "push"}'


@pytest.mark.parametrize("role", ["read", "triage", "none"])
def test_a_role_below_write_is_reported_not_raised(ra, role):
    ctx, _ = world(ra, {"agent": AGENT}, routes=agent_routes(role=role, env=GOOD_ENV, policies=MAIN_ONLY))
    found = ra.check_agent(ctx)
    assert base.sev(found) == [("role:bot", "warn")] and found[0].action is None


def test_an_agent_that_is_no_collaborator_is_reported(ra):
    ctx, _ = world(ra, {"agent": AGENT}, routes=agent_routes(role=base.ApiErr(404, "Not Found", "GET", PERM),
                                                             env=GOOD_ENV, policies=MAIN_ONLY))
    assert base.sev(ra.check_agent(ctx)) == [("role:bot", "warn")]


def test_a_missing_environment_is_created_for_the_default_branch_only(ra):
    ctx, _ = world(ra, {"agent": AGENT}, routes=agent_routes())
    found = ra.check_agent(ctx)
    assert base.sev(found) == [("environment:tld-agent", "fix"), ("environment:tld-agent:branch:main", "fix"),
                               ("secret:environment", "info")]
    put, post = found[0].action, found[1].action
    assert (put.method, put.path, put.body) == ("PUT", ENV, {"deployment_branch_policy": {
        "protected_branches": False, "custom_branch_policies": True}})
    assert (post.method, post.path, post.body) == ("POST", f"{ENV}/deployment-branch-policies", {"name": "main", "type": "branch"})


def test_protected_branches_mode(ra):
    ctx, _ = world(ra, {"agent": {**AGENT, "branch_policy": "protected_branches"}}, routes=agent_routes(env=GOOD_ENV))
    found = ra.check_agent(ctx)
    assert base.sev(found) == [("environment:tld-agent", "fix")]
    assert found[0].action.body == {"deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}
    env = {"deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}
    ctx, _ = world(ra, {"agent": {**AGENT, "branch_policy": "protected_branches"}}, routes=agent_routes(env=env))
    assert ra.check_agent(ctx) == []


def test_an_environment_open_to_every_branch_is_drift(ra):
    ctx, fake = world(ra, {"agent": AGENT}, routes=agent_routes(env={"name": "tld-agent", "deployment_branch_policy": None}))
    found = ra.check_agent(ctx)
    assert base.sev(found) == [("environment:tld-agent", "fix"), ("environment:tld-agent:branch:main", "fix")]
    assert "lets every branch deploy" in found[0].message
    assert f"{ENV}/deployment-branch-policies" not in fake.reads


def test_extra_branch_patterns_are_removed_and_the_default_added(ra, ):
    policies = [{"id": 7, "name": "claude/*", "type": "branch"}, {"id": 8, "name": "main", "type": "tag"}]
    ctx, _ = world(ra, {"agent": AGENT}, routes=agent_routes(env=GOOD_ENV, policies=policies))
    found = ra.check_agent(ctx)
    assert [(f.action.method, f.action.path) for f in found] == [
        ("POST", f"{ENV}/deployment-branch-policies"), ("DELETE", f"{ENV}/deployment-branch-policies/7"),
        ("DELETE", f"{ENV}/deployment-branch-policies/8")]
    assert not any(f.action.destructive for f in found), "narrowing who may deploy is not irreversible"


def test_the_agent_token_outside_the_environment_is_reported(ra):
    routes = agent_routes(env=GOOD_ENV, policies=MAIN_ONLY, repo_secrets=["TLD_AGENT_TOKEN"], org_secrets=["tld_agent_token"],
                          env_secrets=())
    ctx, _ = world(ra, {"agent": AGENT}, routes=routes)
    found = ra.check_agent(ctx)
    assert base.sev(found) == [("secret:environment", "info"), ("secret:organisation", "warn"), ("secret:repository", "warn")]
    repo_secret = next(f for f in found if f.subject == "secret:repository")
    assert "gh secret set TLD_AGENT_TOKEN --env tld-agent --repo acme/app" in repo_secret.manual and repo_secret.action is None


def test_one_failing_agent_part_does_not_hide_the_others(ra):
    routes = agent_routes(role="admin")
    routes[("GET", ENV)] = base.ApiErr(500, "down", "GET", ENV)
    ctx, _ = world(ra, {"agent": AGENT}, routes=routes)
    assert base.sev(ra.check_agent(ctx)) == [("GET /repos/acme/app/environments/tld-agent", "error"), ("role:bot", "fix"),
                                             ("secret:environment", "info")]


def test_agent_dry_run_and_apply(ra):
    ctx, fake = world(ra, {"agent": AGENT}, routes=agent_routes(role="admin"))
    found = ra.run_checks(ctx, ["agent"])
    lines = []
    ra.apply_findings(ctx, found, yes=False, allow_delete=False, out=lines.append)
    assert fake.writes == [] and lines[-1].startswith("Dry run")
    assert ra.apply_findings(ctx, found, yes=True, allow_delete=False, out=lines.append) == 0
    assert [(m, p) for m, p, _ in fake.writes] == [("PUT", "/repos/acme/app/collaborators/bot"), ("PUT", ENV),
                                                   ("POST", f"{ENV}/deployment-branch-policies")]


def test_policy_rules_for_the_new_sections(ra):
    assert ra.validate_policy({"org": "a", "rulesets": {"default_branch": {}, "tags": True}, "agent": AGENT}) == []
    assert any("agent.agent_login" in e for e in ra.validate_policy({"org": "a", "agent": {}}))
    assert any("agent.branch_policy" in e for e in ra.validate_policy({"org": "a", "agent": {**AGENT, "branch_policy": "all"}}))
    assert any("rulesets.default_branch.bypass" in e for e in ra.validate_policy({"org": "a", "rulesets": {"default_branch": {"bypass": 1}}}))
    assert any("rulesets.tags" in e for e in ra.validate_policy({"org": "a", "rulesets": {"tags": "yes"}}))


# --------------------------------------------------------------------------- the release environment

RENV = "/repos/acme/app/environments/tld-release"
RELEASE = {"reviewer_login": "owner"}


def release_routes(env=None, policies=MAIN_ONLY, repo_secrets=(), env_secrets=("TLD_RELEASE_TOKEN",)):
    routes = {("GET", "/users/owner"): {"login": "owner", "id": 42},
              ("GET", "/repos/acme/app/actions/secrets"): {"secrets": [{"name": n} for n in repo_secrets]},
              ("GET", "/repos/acme/app/actions/organization-secrets"): {"secrets": []}}
    if env is not None:
        routes[("GET", RENV)] = env
        routes[("GET", f"{RENV}/deployment-branch-policies")] = {"branch_policies": list(policies)}
        routes[("GET", f"{RENV}/secrets")] = {"secrets": [{"name": n} for n in env_secrets]}
    return routes


def release_env(*reviewer_ids):
    rules = [{"type": "branch_policy"}]
    if reviewer_ids:
        rules.append({"type": "required_reviewers", "prevent_self_review": False,
                      "reviewers": [{"type": "User", "reviewer": {"id": i, "login": f"u{i}"}} for i in reviewer_ids]})
    return {"name": "tld-release", "protection_rules": rules,
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}


def test_release_environment_in_line_is_no_drift(ra):
    ctx, fake = world(ra, {"release": RELEASE}, routes=release_routes(env=release_env(42)))
    assert ra.check_release(ctx) == [] and fake.writes == []


def test_a_missing_release_environment_is_created_with_the_owner_as_reviewer(ra):
    ctx, _ = world(ra, {"release": RELEASE}, routes=release_routes())
    found = ra.check_release(ctx)
    assert base.sev(found) == [("environment:tld-release", "fix"), ("environment:tld-release:branch:main", "fix"),
                               ("secret:environment", "info")]
    put = found[0].action
    assert (put.method, put.path) == ("PUT", RENV)
    assert put.body == {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
                        "reviewers": [{"type": "User", "id": 42}]}


@pytest.mark.parametrize("ids", [(), (7,), (42, 7)])
def test_other_release_reviewers_are_drift(ra, ids):
    ctx, _ = world(ra, {"release": RELEASE}, routes=release_routes(env=release_env(*ids)))
    found = ra.check_release(ctx)
    assert base.sev(found) == [("environment:tld-release", "fix")] and "other required reviewers" in found[0].message
    assert found[0].action.body["reviewers"] == [{"type": "User", "id": 42}]


def test_the_release_token_outside_its_environment_is_reported(ra):
    ctx, _ = world(ra, {"release": RELEASE}, routes=release_routes(env=release_env(42), repo_secrets=["TLD_RELEASE_TOKEN"]))
    found = ra.check_release(ctx)
    assert base.sev(found) == [("secret:repository", "warn")]
    assert "gh secret set TLD_RELEASE_TOKEN --env tld-release --repo acme/app" in found[0].manual


def test_an_unknown_reviewer_login_is_one_finding(ra):
    routes = {("GET", "/users/owner"): base.ApiErr(404, "Not Found", "GET", "/users/owner")}
    ctx, _ = world(ra, {"release": RELEASE}, routes=routes)
    assert [f.severity for f in ra.check_release(ctx)] == ["unavailable"]


def test_a_named_release_environment_is_managed_and_rendered(ra):
    policy = {"release": {**RELEASE, "environment": "ship"}, "workflows": [{"template": "release"}]}
    routes = {k: v for k, v in release_routes().items()}
    ctx, _ = world(ra, policy, routes=routes)
    assert {f.action.path for f in ra.check_release(ctx) if f.action} >= {"/repos/acme/app/environments/ship"}
    change = ra.check_files(ctx)[0].action.changes[0]
    assert "environment: ship" in change["content"] and "__RELEASE_ENVIRONMENT__" not in change["content"]


def test_release_dry_run_and_apply(ra):
    ctx, fake = world(ra, {"release": RELEASE}, routes=release_routes())
    found = ra.run_checks(ctx, ["release"])
    ra.apply_findings(ctx, found, yes=False, allow_delete=False, out=lambda line: None)
    assert fake.writes == []
    assert ra.apply_findings(ctx, found, yes=True, allow_delete=False, out=lambda line: None) == 0
    assert [(m, p) for m, p, _ in fake.writes] == [("PUT", RENV), ("POST", f"{RENV}/deployment-branch-policies")]
