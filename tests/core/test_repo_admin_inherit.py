"""repo_admin.py: the effective policy of one repository (override file, Ctx.pol), against a fake GitHub."""
import pytest

import test_repo_admin as base
from test_repo_admin import by_check, world

OVERRIDE = ".tld/admin-policy.yaml"
CONTENTS = f"/repos/acme/app/contents/{OVERRIDE}"


@pytest.fixture(autouse=True)
def _bind(ra):
    base.ApiErr = ra.ApiError


def _token():
    return "gh" + "p_" + "A1b2C3d4E5" * 4  # built at run time: no credential-looking line in this file


def inherited(ra, policy, **kw):
    return world(ra, {**policy, "_inherited": True}, **kw)


def reads_of_overrides(fake):
    return [p for p in fake.reads if p.endswith(OVERRIDE)]


def test_override_merged(ra):
    policy = {"repo_settings": {"allow_auto_merge": False, "delete_branch_on_merge": False}}
    files = {"app": {OVERRIDE: "repo_settings:\n  delete_branch_on_merge: true\n"}, "web": {}}
    ctx, fake = inherited(ra, policy, names=("app", "web"), files=files, allow_auto_merge=False, delete_branch_on_merge=False)
    found = ra.check_repo(ctx)
    assert [(f.scope, f.subject, f.action.body) for f in found] == [("acme/app", "delete_branch_on_merge", {"delete_branch_on_merge": True})]
    app, web = ctx.all_repos
    assert ctx.pol(app)["repo_settings"] == {"allow_auto_merge": False, "delete_branch_on_merge": True}
    assert ctx.pol(web)["repo_settings"] == {"allow_auto_merge": False, "delete_branch_on_merge": False}
    assert ctx.p["repo_settings"]["delete_branch_on_merge"] is False  # the organisation policy is never changed


def test_no_override_file(ra):
    ctx, fake = inherited(ra, {"repo_settings": {"allow_auto_merge": True}}, files={"app": {"README.md": "x"}})
    repo = ctx.all_repos[0]
    ov = ctx.override(repo)
    assert (ov.doc, ov.path, ov.legacy, ov.problems, ov.notes) == (None, OVERRIDE, False, [], [])
    assert ctx.pol(repo) == ctx.p
    assert reads_of_overrides(fake) == []


def test_only_the_checks(ra):
    policy = {"repo_settings": {"allow_auto_merge": True}, "security": {"vulnerability_alerts": True},
              "actions": {"default_workflow_permissions": "read"},
              "rulesets": {"default_branch": {"admin_bypass": False}}}
    routes = {("GET", "/repos/acme/app/actions/permissions/workflow"): {"default_workflow_permissions": "write"},
              ("GET", "/repos/acme/app/rulesets"): []}
    files = {"app": {OVERRIDE: "rulesets:\n  default_branch:\n    required_status_checks: [test, lint]\n"}}
    plain, _ = world(ra, dict(policy), routes=routes, files={"app": {}})
    ctx, _ = inherited(ra, policy, routes=routes, files=files)
    for check in (ra.check_repo, ra.check_security, ra.check_actions):
        assert [(f.subject, f.severity, f.message) for f in check(ctx)] == [(f.subject, f.severity, f.message) for f in check(plain)]
        assert check(ctx)
    [fix] = by_check(ra.check_rulesets(ctx), "rulesets")
    rules = {r["type"]: r for r in fix.action.body["rules"]}
    assert [c["context"] for c in rules["required_status_checks"]["parameters"]["required_status_checks"]] == ["test", "lint"]


def test_whole_legacy_file(ra):
    legacy = ("org: acme\nrepo_settings:\n  allow_auto_merge: true\n  delete_branch_on_merge: true\n"
              "labels:\n  delete_unused: true\n")
    ctx, _ = inherited(ra, {"repo_settings": {"allow_auto_merge": True, "delete_branch_on_merge": False}},
                       files={"app": {OVERRIDE: legacy}}, allow_auto_merge=True, delete_branch_on_merge=False)
    ov = ctx.override(ctx.all_repos[0])
    assert ov.legacy is True and ov.problems == []
    assert ov.doc == {"repo_settings": {"delete_branch_on_merge": True}}
    assert any("dropped organisation-level section 'labels'" in n for n in ov.notes)
    assert ctx.p.get("labels") is None and ra.check_labels(ctx) == []
    assert ctx.pol(ctx.all_repos[0])["repo_settings"]["delete_branch_on_merge"] is True


def test_override_with_anchors_or_a_token_is_refused(ra):
    token = _token()
    files = {"app": {OVERRIDE: "repo_settings: &a\n  allow_auto_merge: true\nsecurity: *a\n"},
             "web": {OVERRIDE: f"repo_settings:\n  allow_auto_merge: true  # {token}\n"},
             "old": {OVERRIDE: f"org: acme\nrepo_settings:\n  allow_auto_merge: true\n  note: {token}\n"}}
    policy = {"repo_settings": {"allow_auto_merge": False}}
    routes = {}
    ctx, _ = inherited(ra, policy, names=("app", "web", "old"), files=files, routes=routes)
    texts = []
    for repo in ctx.all_repos:
        ov = ctx.override(repo)
        assert ov.doc is None and ov.problems, repo["name"]
        texts += ov.problems
        assert ctx.pol(repo) == ctx.p
    assert any("uses YAML anchors or aliases" in t for t in texts) and sum("refused: line" in t for t in texts) == 2
    findings = [f for check in (ra.check_repo,) for f in check(ctx)]
    blob = " ".join(texts + [f.message for f in findings] + [str(f.action.body) for f in findings if f.action])
    assert token not in blob and token[4:20] not in blob


def test_legacy_workflow_path_is_refused(ra):
    legacy = "org: acme\nworkflows:\n  - path: wf.yml\n"
    ctx, _ = inherited(ra, {"workflows": [{"template": "land"}]}, files={"app": {OVERRIDE: legacy}})
    ov = ctx.override(ctx.all_repos[0])
    assert ov.doc is None and ov.problems and any("workflows[0]" in p for p in ov.problems)


def test_override_with_problems_is_ignored(ra):
    ctx, _ = inherited(ra, {"repo_settings": {"allow_auto_merge": True}},
                       files={"app": {OVERRIDE: "labels:\n  delete_unused: true\nrepo_settings:\n  allow_auto_merge: false\n"}})
    repo = ctx.all_repos[0]
    ov = ctx.override(repo)
    assert ov.doc is None and ov.problems and any("organisation-level" in p for p in ov.problems)
    assert ctx.pol(repo) == ctx.p


def test_pol_is_the_policy_without_extends(ra):
    ctx, fake = world(ra, {"repo_settings": {"allow_auto_merge": True}}, files={"app": {OVERRIDE: "repo_settings:\n  allow_auto_merge: false\n"}})
    assert ctx.inherited is False
    assert ctx.pol(ctx.all_repos[0]) is ctx.p
    assert ra.check_repo(ctx) and reads_of_overrides(fake) == []


# --------------------------------------------------------------------------- hardening (the override is untrusted data)


def test_organisation_and_run_only_keys_are_never_applied(ra):
    ctx, _ = inherited(ra, {"repo_settings": {"allow_auto_merge": True}})
    repo = ctx.all_repos[0]
    forced = {"labels": {"delete_unused": True}, "repos": {"exclude": ["*"]}, "org": "evil", "extends": ["x/y/z@" + "0" * 40],
              "repo_settings": {"delete_branch_on_merge": True}}
    ctx._cache[("override", repo["full_name"])] = ra.Override(forced, OVERRIDE)  # a caller that forgot to validate
    eff = ctx.pol(repo)
    assert eff["org"] == "acme" and "labels" not in eff and "repos" not in eff and "extends" not in eff
    assert eff["repo_settings"] == {"allow_auto_merge": True, "delete_branch_on_merge": True}


def test_a_blanked_guarded_section_is_restored(ra):
    ctx, _ = inherited(ra, {"security": {"secret_scanning": True}, "actions": {"default_workflow_permissions": "read"},
                        "config_dirs": {"forbid": [".archon"]}})
    repo = ctx.all_repos[0]
    ctx._cache[("override", repo["full_name"])] = ra.Override(
        {"security": None, "actions": {"default_workflow_permissions": 5}, "config_dirs": {"forbid": "none"}}, OVERRIDE)
    eff = ctx.pol(repo)
    assert eff["security"] == {"secret_scanning": True}
    assert eff["actions"]["default_workflow_permissions"] == "read"
    assert eff["config_dirs"]["forbid"] == [".archon"]
    assert {item.key for item in ctx.loosenings(repo)} == {"actions.default_workflow_permissions", "config_dirs.forbid"}  # a non-mapping section is simply not applied


def test_the_reviewer_is_never_the_agent(ra):
    policy = {"agent": {"agent_login": "bot"}, "release": {"reviewer_login": "Owner"}}
    ctx, _ = inherited(ra, policy, files={"app": {OVERRIDE: "agent:\n  agent_login: owner\n"}})
    repo = ctx.all_repos[0]
    eff = ctx.pol(repo)
    assert eff["agent"]["agent_login"] == "bot" and eff["release"]["reviewer_login"] == "Owner"
    subjects = [s for s, _ in ctx.pol_warnings(repo)]
    assert "login:same" in subjects and "login:agent.agent_login" in subjects


def test_an_explicit_login_override_is_reported(ra):
    policy = {"agent": {"agent_login": "bot"}, "release": {"reviewer_login": "owner", "environment": "tld-release"}}
    ctx, _ = inherited(ra, policy, files={"app": {OVERRIDE: "release:\n  reviewer_login: boss\n  environment: other\n"}})
    repo = ctx.all_repos[0]
    assert ctx.pol(repo)["release"] == {"reviewer_login": "boss", "environment": "other"}
    assert {s for s, _ in ctx.pol_warnings(repo)} == {"login:release.reviewer_login", "release:environment"}


def test_messages_from_a_file_are_clean_and_bounded(ra):
    text = "repo_settings: [\x1b[31m" + "x" * 2000 + "\n"
    ctx, _ = inherited(ra, {"repo_settings": {"allow_auto_merge": True}}, files={"app": {OVERRIDE: text}})
    ov = ctx.override(ctx.all_repos[0])
    assert ov.doc is None and ov.problems
    for problem in ov.problems:
        assert len(problem) <= 300 and not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in problem)


def _override(ra, ctx, doc):
    repo = ctx.all_repos[0]
    ctx._cache[("override", repo["full_name"])] = ra.Override(doc, OVERRIDE)
    return repo


def test_equal_logins_with_no_organisation_reviewer_stand_down(ra):
    ctx, _ = inherited(ra, {"agent": {"agent_login": "bot"}, "release": {"environment": "tld-release"}},
                       files={"app": {OVERRIDE: "release:\n  reviewer_login: BOT\n"}})
    repo = ctx.all_repos[0]
    eff = ctx.pol(repo)
    assert eff["agent"]["agent_login"] == "bot" and "reviewer_login" not in eff["release"]
    [msg] = [m for s, m in ctx.pol_warnings(repo) if s == "login:same"]
    assert "release.reviewer_login" in msg and "stands down" in msg and "organisation's logins apply" not in msg
    assert ra.check_release(ctx) == []  # no reviewer: the release check does not run for this repository


def test_equal_logins_with_no_organisation_agent_stand_down(ra):
    ctx, _ = inherited(ra, {"release": {"reviewer_login": "owner"}},
                       files={"app": {OVERRIDE: "agent:\n  agent_login: Owner\n"}})
    repo = ctx.all_repos[0]
    eff = ctx.pol(repo)
    assert eff["release"]["reviewer_login"] == "owner" and "agent_login" not in eff.get("agent", {})
    assert any("agent.agent_login" in m and "stands down" in m for s, m in ctx.pol_warnings(repo) if s == "login:same")
    assert ra.check_agent(ctx) == []  # no agent login and no agent section left: nothing to audit


def test_release_environment_is_never_the_agent_environment(ra):
    ctx, _ = inherited(ra, {"release": {"reviewer_login": "owner", "environment": "tld-release"}})
    repo = _override(ra, ctx, {"release": {"environment": "TLD-Agent"}})
    assert ctx.pol(repo)["release"]["environment"] == "tld-release"
    assert any(s == "release:environment" for s, _ in ctx.pol_warnings(repo))
    ctx2, _ = inherited(ra, {"release": {"reviewer_login": "owner"}})
    repo2 = _override(ra, ctx2, {"release": {"environment": "tld-agent"}})
    assert "environment" not in ctx2.pol(repo2)["release"]  # the default environment applies


def test_a_workflow_entry_keeps_only_template_params_remove(ra):
    ctx, _ = inherited(ra, {"workflows": [{"template": "land"}]})
    repo = _override(ra, ctx, {"workflows": [{"template": "release", "path": "/etc/passwd", "dest": "x", "repos": ["*"],
                                              "params": {"tag_prefix": "v"}}, "junk", {"path": "p"}]})
    assert ctx.pol(repo)["workflows"] == [{"template": "release", "params": {"tag_prefix": "v"}}]
    ctx._cache.pop(("pol", repo["full_name"]))
    repo = _override(ra, ctx, {"workflows": {"template": "land"}, "security": ["x"]})  # wrong shapes are dropped
    assert ctx.pol(repo)["workflows"] == [{"template": "land"}] and "security" not in ctx.pol(repo)


def test_environment_names_are_quoted_in_api_paths(ra):
    ctx, fake = inherited(ra, {"release": {"reviewer_login": "owner", "environment": "a/b c"}},
                          routes={("GET", "/users/owner"): {"id": 1}})
    ra.check_release(ctx)
    assert any("/environments/a%2Fb%20c" in p for p in fake.reads) and not any("a/b c" in p for p in fake.reads)


def test_clean_stays_within_the_bound(ra):
    out = ra.clean("x" * 5000, ra.MAX_MESSAGE)
    assert len(out) == ra.MAX_MESSAGE and out.endswith("...")
    assert ra.clean("short", ra.MAX_MESSAGE) == "short"


def test_the_validate_view_uses_the_same_function(ra):
    org = {"org": "acme", "security": {"secret_scanning": True}}
    over = {"security": {"secret_scanning": False}, "labels": {"delete_unused": True}}
    eff, loose, _ = ra.effective_policy(org, over, "app")
    assert eff["security"]["secret_scanning"] is True and "labels" not in eff and [i.key for i in loose] == ["security.secret_scanning"]


test_login_or_environment_overridden = test_an_explicit_login_override_is_reported


def test_override_problem_messages_name_the_file_once(ra):
    ctx, _ = inherited(ra, {"agent": {"agent_login": "bot"}},
                       files={"app": {OVERRIDE: "org_settings:\n  x: 1\n"}})
    repo = ctx.all_repos[0]
    found = [f for f in ra.check_policy(ctx) if f.subject.startswith("override:invalid")]
    assert found and all(f.message.count(OVERRIDE) == 1 for f in found), [f.message for f in found]
